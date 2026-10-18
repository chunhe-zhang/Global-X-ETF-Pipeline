"""Best-effort parser for public Global X HTML holdings tables.
Keeps source values verbatim as percentages; rejects pages without a recognizable table.
"""
import re
from bs4 import BeautifulSoup

def parse_holdings_html(html, known_funds):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th","td"])]
        weight_col = next((i for i,h in enumerate(headers) if "weight" in h or "%" in h), None)
        name_col = next((i for i,h in enumerate(headers) if any(k in h for k in ("holding","security","company","name","ticker"))), None)
        if weight_col is not None and name_col is not None:
            candidates.append((rows, headers, name_col, weight_col))
    if not candidates:
        raise ValueError("No holdings table with recognizable name and weight columns was found")
    rows, _, name_col, weight_col = max(candidates, key=lambda x: len(x[0]))
    output = []
    for row in rows[1:]:
        cells = row.find_all(["td","th"])
        if max(name_col, weight_col) >= len(cells):
            continue
        label = cells[name_col].get_text(" ", strip=True)
        weight_text = cells[weight_col].get_text(" ", strip=True).replace(",", "")
        match = re.search(r"[-+]?\d+(?:\.\d+)?", weight_text)
        if not label or not match:
            continue
        ticker = ""
        link = cells[name_col].find("a", href=True)
        if link:
            ticker_match = re.search(r"/([A-Z]{1,6})(?:/|$|\?)", link["href"].upper())
            if ticker_match:
                ticker = ticker_match.group(1)
        if not ticker:
            token = re.search(r"\b[A-Z][A-Z0-9.]{0,5}\b", label.upper())
            ticker = token.group(0) if token else ""
        if not ticker:
            continue
        ticker = ticker.upper()
        output.append({"ticker":ticker,"name":label,"weight_pct":float(match.group()),
                       "is_fund":ticker in known_funds})
    if not output:
        raise ValueError("Holdings table was found but no parseable rows were extracted")
    return output
