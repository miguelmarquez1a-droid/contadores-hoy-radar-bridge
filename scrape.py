from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import requests
import urllib3
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OUT = Path("docs/feed.json")
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.7",
}


def canonical(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, "")).rstrip("/")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def link_text(a, href: str) -> tuple[str, str]:
    """Return the best human title and nearby row/card text for a link."""
    own = clean(a.get_text(" ", strip=True))
    nearby_node = a.find_parent(["tr", "li", "article", "div", "p"]) or a.parent
    nearby = clean(nearby_node.get_text(" ", strip=True)) if nearby_node else own
    filename = clean(unquote(urlsplit(href).path.rsplit("/", 1)[-1]).rsplit(".", 1)[0])
    generic = {"", "ver", "descargar", "ver concepto", "ver decreto", "pdf"}
    title = nearby if own.lower() in generic else own
    if title.lower() in generic:
        title = filename
    return title, nearby


def date_from(text: str) -> str | None:
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})", text)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    month_re = "|".join(MONTHS)
    m = re.search(rf"(\d{{1,2}})\s+(?:de\s+)?({month_re})\s+(?:de\s+)?(20\d{{2}})", text, re.I)
    if m:
        return f"{int(m.group(3)):04d}-{MONTHS.index(m.group(2).lower())+1:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def fetch(url: str, verify: bool = True) -> BeautifulSoup:
    # These government portals populate their lists with JavaScript. A real
    # browser is therefore required; plain requests often returns an empty shell.
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="es-CO",
            ignore_https_errors=not verify,
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        html = page.content()
        browser.close()
    return BeautifulSoup(html, "html.parser")


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
        href = urljoin(page, a["href"])
        title, nearby = link_text(a, href)
        combined = f"{title} {nearby} {unquote(href)}"
        is_document = re.search(r"\.(?:pdf|docx?)(?:$|[?#])", href, re.I)
        if is_document and re.search(rf"\bDECRETO\b[^0-9]{{0,30}}\d+.*\b{now.year}\b", combined, re.I):
            out.append(item("Presidencia – DAPRE", title, href, nearby))
    if not out:
        sample = [
            f"{clean(a.get_text(' ', strip=True))[:80]} -> {a.get('href', '')[:160]}"
            for a in soup.select("a[href]")[:25]
        ]
        raise RuntimeError("Enlaces observados: " + " | ".join(sample))
    return out


def scrape_ctcp(now: datetime) -> list[dict]:
    page = f"https://www.ctcp.gov.co/conceptos/{now.year}"
    soup = fetch(page, verify=False)
    out = []
    for a in soup.select("a[href]"):
        href = urljoin(page, a["href"])
        title, nearby = link_text(a, href)
        combined = f"{title} {nearby} {unquote(href)}"
        is_document = re.search(r"\.(?:pdf|docx?)(?:$|[?#])", href, re.I)
        is_detail = re.search(rf"/conceptos/{now.year}/[^/?#]+", urlsplit(href).path, re.I)
        is_download = re.search(r"getfile|download|attachment|document|media", href, re.I)
        has_concept_code = re.search(rf"\b(?:{now.year}[-/]\d+|\d{{3,4}}[-/]{now.year})\b", combined, re.I)
        if is_detail or (
            str(now.year) in combined
            and (is_document or is_download)
            and (has_concept_code or re.search(r"concepto|consulta|radicad", combined, re.I))
        ):
            out.append(item("CTCP", title, href, nearby))
    if not out:
        anchors = soup.select("a[href]")
        likely = [a for a in anchors if str(now.year) in f"{a.get_text(' ', strip=True)} {a.get('href', '')}"]
        observed = (likely[:50] or anchors[-40:])
        sample = [
            f"{clean(a.get_text(' ', strip=True))[:80]} -> {a.get('href', '')[:160]}"
            for a in observed
        ]
        raise RuntimeError("Enlaces observados: " + " | ".join(sample))
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
            href = urljoin(page, a["href"])
            title, nearby = link_text(a, href)
            combined = f"{title} {nearby} {unquote(href)}"
            if str(now.year) in combined and re.search(r"\b(RESOLUCI[ÓO]N|CIRCULAR)\b[^0-9]{0,30}\d+", combined, re.I):
                out.append(item("DIAN", title, href, nearby))
    return out


def main() -> None:
    now = datetime.now(timezone.utc)
    records: list[dict] = []
    errors: list[dict] = []
    for name, scraper in [("DIAN", scrape_dian), ("CTCP", scrape_ctcp), ("Presidencia – DAPRE", scrape_dapre)]:
        try:
            found = scraper(now)
            records.extend(found)
            if not found:
                errors.append({"source": name, "error": "La página respondió, pero no entregó enlaces reconocibles"})
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
