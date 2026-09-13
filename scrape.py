from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OUT = Path("docs/feed.json")
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
HEADERS = {"User-Agent": "ContadoresHoyRadarBridge/1.0 (+https://contadoreshoy.com)"}


def canonical(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, "")).rstrip("/")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def date_from(text: str) -> str | None:
    month_re = "|".join(MONTHS)
    m = re.search(rf"(\d{{1,2}})\s+(?:de\s+)?({month_re})\s+(?:de\s+)?(20\d{{2}})", text, re.I)
    if m:
        return f"{int(m.group(3)):04d}-{MONTHS.index(m.group(2).lower())+1:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def fetch(url: str, verify: bool = True) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=45, verify=verify)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return BeautifulSoup(response.text, "html.parser")


def item(source: str, title: str, url: str, context: str = "") -> dict:
    url = canonical(url)
    return {
        "id": hashlib.sha256(url.encode()).hexdigest(),
        "source": source,
        "title": clean(title),
        "date": date_from(f"{title} {context}"),
        "url": url,
        "summary": clean(context)[:500],
    }


def scrape_dapre(now: datetime) -> list[dict]:
    month = MONTHS[now.month - 1]
    page = f"https://dapre.presidencia.gov.co/normativa/decretos-{now.year}/decretos-{month}-{now.year}"
    soup = fetch(page, verify=False)
    out = []
    for a in soup.select("a[href]"):
        title = clean(a.get_text(" ", strip=True))
        if re.match(r"^DECRETO\s+(?:No\.?\s*)?\d+", title, re.I):
            out.append(item("Presidencia – DAPRE", title, urljoin(page, a["href"]), clean(a.parent.get_text(" ", strip=True))))
    return out


def scrape_ctcp(now: datetime) -> list[dict]:
    page = f"https://www.ctcp.gov.co/conceptos/{now.year}"
    soup = fetch(page, verify=False)
    out = []
    for a in soup.select("a[href]"):
        title = clean(a.get_text(" ", strip=True))
        href = urljoin(page, a["href"])
        combined = f"{title} {href}"
        if re.search(r"concepto[^0-9]{0,20}\d+", combined, re.I):
            if not title or title.lower() in {"ver", "descargar", "ver concepto"}:
                title = clean(a.parent.get_text(" ", strip=True))
            if re.search(r"concepto[^0-9]{0,20}\d+", title, re.I):
                out.append(item("CTCP", title, href, clean(a.parent.get_text(" ", strip=True))))
    return out


def scrape_dian(now: datetime) -> list[dict]:
    pages = [
        "https://www.dian.gov.co/normatividad/Paginas/Resoluciones.aspx",
        "https://www.dian.gov.co/normatividad/Paginas/Circulares.aspx",
    ]
    out = []
    for page in pages:
        soup = fetch(page, verify=False)
        for a in soup.select("a[href]"):
            title = clean(a.get_text(" ", strip=True))
            href = urljoin(page, a["href"])
            if re.match(r"^(RESOLUCI[ÓO]N|CIRCULAR)\s+(?:No\.?\s*)?\d+", title, re.I):
                out.append(item("DIAN", title, href, clean(a.parent.get_text(" ", strip=True))))
    return out


def main() -> None:
    now = datetime.now(timezone.utc)
    records: list[dict] = []
    errors: list[dict] = []
    for name, scraper in [("DIAN", scrape_dian), ("CTCP", scrape_ctcp), ("Presidencia – DAPRE", scrape_dapre)]:
        try:
            records.extend(scraper(now))
        except Exception as exc:
            errors.append({"source": name, "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(1)

    unique = {r["id"]: r for r in records}
    records = sorted(unique.values(), key=lambda r: (r["date"] or "", r["title"]), reverse=True)
    payload = {
        "generated_at": now.isoformat(),
        "count": len(records),
        "items": records,
        "errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

