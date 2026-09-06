import ipaddress
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )
}
URLS = [
    "https://ip.164746.xyz/ipTop10.html",
    "https://cf.090227.xyz",
    "https://api.uouin.com/cloudflare.html",
    "https://www.wetest.vip/page/cloudflare/address_v4.html",
    "https://stock.hostmonit.com/CloudFlareYes",
]
IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def valid_ipv4(value: str) -> str | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    return str(address) if address.version == 4 else None


def extract_ips(text: str) -> set[str]:
    ips = set()
    for value in IP_PATTERN.findall(text):
        ip = valid_ipv4(value)
        if ip:
            ips.add(ip)
    return ips


def fetch_ips(session: requests.Session, url: str) -> set[str]:
    response = session.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()

    if url == "https://stock.hostmonit.com/CloudFlareYes":
        return extract_ips(response.text)

    soup = BeautifulSoup(response.text, "html.parser")
    if url in {
        "https://ip.164746.xyz/ipTop10.html",
        "https://cf.090227.xyz",
    }:
        elements = soup.find_all("tr")
    elif url == "https://api.uouin.com/cloudflare.html":
        elements = soup.find_all("div", class_="ip")
    elif url == "https://www.wetest.vip/page/cloudflare/address_v4.html":
        elements = soup.find_all("p")
    else:
        elements = soup.find_all("li")

    selected_text = "\n".join(element.get_text(" ") for element in elements)
    selected_ips = extract_ips(selected_text)
    return selected_ips or extract_ips(response.text)


def main() -> None:
    all_ips = set()
    session = requests.Session()

    for url in URLS:
        try:
            print(f"正在处理: {url}")
            ips = fetch_ips(session, url)
            all_ips.update(ips)
            print(f"  找到 {len(ips)} 个有效 IPv4")
        except requests.RequestException as error:
            print(f"  请求失败，跳过: {error}")
        except Exception as error:
            print(f"  解析失败，跳过: {error}")
        time.sleep(1)

    if not all_ips:
        raise RuntimeError("未找到有效 IPv4，保留现有 ip.txt")

    output = "\n".join(sorted(all_ips, key=ipaddress.IPv4Address)) + "\n"
    Path("ip.txt").write_text(output, encoding="utf-8")
    print(f"总共找到 {len(all_ips)} 个唯一 IPv4，已保存到 ip.txt")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(f"Error: {error}")
        raise SystemExit(1) from error
