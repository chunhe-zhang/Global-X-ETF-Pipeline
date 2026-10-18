"""Download timestamped raw snapshots of Global X PowerStock product pages."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRONZE_DIR = PROJECT_ROOT / "data" / "bronze"
MANIFEST_PATH = PROJECT_ROOT / "data" / "manifests" / "fetch_manifest.jsonl"
USER_AGENT = "GlobalXHoldingsInterviewProject/0.1 (educational data pipeline)"
SOURCES = {
    "AAPP": "https://www.globalx.ca/product/aapp",
    "AMZP": "https://www.globalx.ca/product/amzp",
    "GOOP": "https://www.globalx.ca/product/goop",
    "NVDP": "https://www.globalx.ca/product/nvdp",
    "SPCP": "https://www.globalx.ca/product/spcp",
    "TSLP": "https://www.globalx.ca/product/tslp",
}

def fetch_snapshot(ticker: str, url: str, fetched_at: datetime) -> dict[str, str | int]:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(10, 30))
    response.raise_for_status()
    content = response.content
    stamp = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    destination = BRONZE_DIR / ticker / f"{ticker.lower()}_{stamp}.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {"ticker": ticker, "source_url": url, "fetched_at_utc": fetched_at.isoformat(),
            "raw_path": destination.relative_to(PROJECT_ROOT).as_posix(),
            "http_status": response.status_code, "content_type": response.headers.get("Content-Type", ""),
            "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}

def main() -> None:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0)
    records = []
    for ticker, url in SOURCES.items():
        record = fetch_snapshot(ticker, url, fetched_at)
        records.append(record)
        print(f"Fetched {ticker}: {record['bytes']} bytes -> {record['raw_path']}")
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("a", encoding="utf-8", newline="\\n") as manifest:
        for record in records:
            manifest.write(json.dumps(record, ensure_ascii=False) + "\\n")
    print(f"Appended {len(records)} records to {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")

if __name__ == "__main__":
    main()
