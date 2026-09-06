import ipaddress
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

API_BASE = "https://api.cloudflare.com/client/v4"
REQUEST_TIMEOUT = 30


def read_ip_list(source: str, session: requests.Session) -> list[str]:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        response = session.get(source, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        text = response.text
    else:
        text = Path(source).read_text(encoding="utf-8")

    ips = set()
    for line in text.splitlines():
        value = line.strip()
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version == 4:
            ips.add(str(address))

    return sorted(ips, key=ipaddress.IPv4Address)


def cloudflare_request(
    session: requests.Session,
    method: str,
    path: str,
    **kwargs,
) -> dict:
    response = session.request(
        method,
        f"{API_BASE}{path}",
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        errors = "; ".join(
            f"{item.get('code')}: {item.get('message')}"
            for item in payload.get("errors", [])
        )
        raise RuntimeError(errors or "Cloudflare API request failed")
    return payload


def get_zone(session: requests.Session, zone_name: str) -> dict:
    payload = cloudflare_request(
        session,
        "GET",
        "/zones",
        params={"name": zone_name, "status": "active", "per_page": 50},
    )
    matches = [
        zone
        for zone in payload.get("result", [])
        if zone.get("name", "").rstrip(".").lower() == zone_name
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one active zone named {zone_name!r}, found {len(matches)}"
        )
    return matches[0]


def list_a_records(
    session: requests.Session,
    zone_id: str,
    record_name: str,
) -> list[dict]:
    records = []
    page = 1
    while True:
        payload = cloudflare_request(
            session,
            "GET",
            f"/zones/{zone_id}/dns_records",
            params={
                "type": "A",
                "name": record_name,
                "page": page,
                "per_page": 100,
            },
        )
        records.extend(payload.get("result", []))
        info = payload.get("result_info", {})
        if page >= info.get("total_pages", 1):
            return records
        page += 1


def create_a_record(
    session: requests.Session,
    zone_id: str,
    record_name: str,
    ip: str,
) -> None:
    cloudflare_request(
        session,
        "POST",
        f"/zones/{zone_id}/dns_records",
        json={
            "type": "A",
            "name": record_name,
            "content": ip,
            "ttl": 1,
            "proxied": False,
        },
    )
    print(f"Add {record_name}: {ip}")


def update_a_record(
    session: requests.Session,
    zone_id: str,
    record: dict,
    record_name: str,
    ip: str,
) -> None:
    cloudflare_request(
        session,
        "PUT",
        f"/zones/{zone_id}/dns_records/{record['id']}",
        json={
            "type": "A",
            "name": record_name,
            "content": ip,
            "ttl": 1,
            "proxied": False,
        },
    )
    print(f"Keep {record_name}: {ip}")


def delete_record(session: requests.Session, zone_id: str, record: dict) -> None:
    cloudflare_request(
        session,
        "DELETE",
        f"/zones/{zone_id}/dns_records/{record['id']}",
    )
    print(f"Del {record['name']}: {record['id']}")


def sync_dns(
    session: requests.Session,
    zone_id: str,
    record_name: str,
    ip_list: list[str],
) -> None:
    if not ip_list:
        raise RuntimeError("No valid IPv4 addresses were collected; DNS was not changed")

    existing = list_a_records(session, zone_id, record_name)
    desired = set(ip_list)
    existing_by_ip: dict[str, list[dict]] = {}
    for record in existing:
        existing_by_ip.setdefault(record["content"], []).append(record)

    for ip in ip_list:
        records = existing_by_ip.get(ip, [])
        if records:
            update_a_record(session, zone_id, records.pop(0), record_name, ip)
        else:
            create_a_record(session, zone_id, record_name, ip)

    for record in existing:
        if record["content"] not in desired:
            delete_record(session, zone_id, record)

    print(f"Synced {record_name}: {len(ip_list)} IPv4 record(s)")


def main() -> None:
    api_token = os.getenv("CF_API_TOKEN")
    if not api_token:
        raise RuntimeError("CF_API_TOKEN is not set")

    zone_name = os.getenv("CF_ZONE_NAME", "855660.xyz").strip().rstrip(".").lower()
    record_name = os.getenv("CF_RECORD_NAME", f"best.{zone_name}").strip().rstrip(".").lower()
    source = os.getenv("CF_IP_SOURCE", "ip.txt").strip()

    if record_name != zone_name and not record_name.endswith(f".{zone_name}"):
        raise RuntimeError(f"CF_RECORD_NAME must be inside zone {zone_name!r}")

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
    )

    zone = get_zone(session, zone_name)
    ip_list = read_ip_list(source, session)
    print(f"Using zone {zone['name']} ({zone['id']})")
    print(f"Loaded {len(ip_list)} valid IPv4 address(es) from {source}")
    sync_dns(session, zone["id"], record_name, ip_list)


if __name__ == "__main__":
    try:
        main()
    except (OSError, requests.RequestException, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
