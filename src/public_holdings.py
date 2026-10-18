"""Acquire one Global X product's latest public holdings snapshot.
The collector prefers Global X's official full-holdings download, then parses
the official product page's public holdings table. It never synthesizes rows.
"""
from __future__ import annotations
import csv
import io
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "GlobalXLookthroughResearch/1.0 (public ETF holdings project)"}
WEIGHT_KEYS = ("net assets", "weight", "% of nav", "% of net assets", "exposure", "portfolio weight")
TICKER_KEYS = ("ticker", "symbol", "holding ticker", "security ticker")
NAME_KEYS = ("name", "security", "holding", "company")

def _download_url(product_url: str) -> str:
    parts = urlsplit(product_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("download_full_holdings", "true")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

def _weight_column(headers):
    for i, header in enumerate(headers):
        normalized = re.sub(r"[^a-z% ]", " ", header.lower()).strip()
        if any(key in normalized for key in WEIGHT_KEYS) or normalized in ("weight %", "net assets %"):
            return i
    return None

def _ticker_column(headers):
    for i, header in enumerate(headers):
        normalized = re.sub(r"[^a-z ]", " ", header.lower()).strip()
        if any(key in normalized for key in TICKER_KEYS):
            return i
    return None

def _name_column(headers, ticker_idx):
    for i, header in enumerate(headers):
        normalized = re.sub(r"[^a-z ]", " ", header.lower()).strip()
        if i != ticker_idx and any(key in normalized for key in NAME_KEYS):
            return i
    return None

def _pct(value: str):
    text = (value or "").strip().replace(",", "").replace("%", "")
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text)
    return float(match.group()) if match else None

def _parse_csv(text: str, known_funds):
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        records = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error:
        records = list(csv.reader(io.StringIO(text)))
    header_idx = None
    indexes = None
    for i, row in enumerate(records[:40]):
        headers = [cell.strip() for cell in row]
        ticker_idx, weight_idx = _ticker_column(headers), _weight_column(headers)
        if ticker_idx is not None and weight_idx is not None:
            header_idx = i
            indexes = (ticker_idx, weight_idx, _name_column(headers, ticker_idx))
            break
    if header_idx is None:
        return []
    ticker_idx, weight_idx, name_idx = indexes
    output = []
    for row in records[header_idx + 1:]:
        if max(ticker_idx, weight_idx) >= len(row):
            continue
        ticker = row[ticker_idx].strip().upper()
        weight = _pct(row[weight_idx])
        name = row[name_idx].strip() if name_idx is not None and name_idx < len(row) else ticker
        if ticker and weight is not None:
            output.append({"ticker": ticker, "name": name or ticker, "weight_pct": weight,
                           "is_fund": ticker in known_funds})
    return output

def _parse_html(text: str, known_funds):
    soup = BeautifulSoup(text, "html.parser")
    output = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for header_idx, header_row in enumerate(rows[:3]):
            headers = [cell.get_text(" ", strip=True) for cell in header_row.find_all(["th", "td"])]
            ticker_idx, weight_idx = _ticker_column(headers), _weight_column(headers)
            if ticker_idx is None or weight_idx is None:
                continue
            name_idx = _name_column(headers, ticker_idx)
            for row in rows[header_idx + 1:]:
                cells = row.find_all(["td", "th"])
                if max(ticker_idx, weight_idx) >= len(cells):
                    continue
                ticker = cells[ticker_idx].get_text(" ", strip=True).upper()
                weight = _pct(cells[weight_idx].get_text(" ", strip=True))
                name = cells[name_idx].get_text(" ", strip=True) if name_idx is not None and name_idx < len(cells) else ticker
                if ticker and weight is not None:
                    output.append({"ticker": ticker, "name": name or ticker, "weight_pct": weight,
                                   "is_fund": ticker in known_funds})
            if output:
                return output
    return output

def _source_date(text: str):
    match = re.search(r"(?:as of|holdings as at|data as at)\s*[:\-]?\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", text, re.I)
    return match.group(1) if match else None

def fetch_public_holdings(product: dict, known_funds: set[str]):
    """Return parsed holdings, source metadata and exact raw response bytes."""
    source_url = product.get("product_url")
    if not source_url:
        raise ValueError("No public product URL is mapped for this catalog entry")
    session = requests.Session()
    response = session.get(_download_url(source_url), headers=HEADERS, timeout=(10, 45))
    response.raise_for_status()
    raw = response.content
    content_type = response.headers.get("Content-Type", "").lower()
    text = response.text
    holdings = _parse_csv(text, known_funds) if ("csv" in content_type or "text/plain" in content_type) else []
    final_url = response.url
    if not holdings:
        soup = BeautifulSoup(text, "html.parser")
        csv_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            label = link.get_text(" ", strip=True).lower()
            if ".csv" in href.lower() or ("full" in label and "hold" in label and "csv" in label):
                csv_links.append(requests.compat.urljoin(response.url, href))
        for url in csv_links[:3]:
            candidate = session.get(url, headers=HEADERS, timeout=(10, 45))
            candidate.raise_for_status()
            parsed = _parse_csv(candidate.text, known_funds)
            if parsed:
                holdings, raw, text, final_url = parsed, candidate.content, candidate.text, candidate.url
                content_type = candidate.headers.get("Content-Type", "").lower()
                break
    if not holdings:
        holdings = _parse_html(text, known_funds)
    if not holdings:
        raise ValueError("Official page returned no recognizable full holdings table or CSV")
    return {
        "holdings": holdings,
        "source_url": final_url,
        "as_of": _source_date(text),
        "raw": raw,
        "media_type": "text/csv" if final_url.lower().endswith(".csv") or "csv" in content_type else content_type or "text/html",
    }
