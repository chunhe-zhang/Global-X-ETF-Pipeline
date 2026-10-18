"""Azure Functions entry point for the Global X raw holdings ingestion."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import azure.functions as func
import requests
from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

SOURCES = {
    "AAPP": "https://www.globalx.ca/product/aapp",
    "AMZP": "https://www.globalx.ca/product/amzp",
    "GOOP": "https://www.globalx.ca/product/goop",
    "NVDP": "https://www.globalx.ca/product/nvdp",
    "SPCP": "https://www.globalx.ca/product/spcp",
    "TSLP": "https://www.globalx.ca/product/tslp",
}
USER_AGENT = "GlobalXHoldingsInterviewProject/0.1 (educational data pipeline)"


def _blob_service() -> BlobServiceClient:
    account_url = os.environ["BLOB_ACCOUNT_URL"]
    return BlobServiceClient(account_url, credential=DefaultAzureCredential())


@app.route(route="ingest", methods=["POST"])
def ingest(req: func.HttpRequest) -> func.HttpResponse:
    """Fetch each official product page and persist immutable bronze snapshots."""
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    container = os.getenv("BRONZE_CONTAINER", "bronze")
    service = _blob_service()
    try:
        service.get_container_client(container).create_container()
    except ResourceExistsError:
        pass
    records: list[dict[str, object]] = []

    try:
        for ticker, url in SOURCES.items():
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=(10, 30),
            )
            response.raise_for_status()
            content = response.content
            blob_path = f"holdings/{ticker.lower()}/ingest_date={fetched_at:%Y-%m-%d}/{ticker.lower()}_{stamp}.html"
            service.get_blob_client(container=container, blob=blob_path).upload_blob(
                content, overwrite=False, metadata={"ticker": ticker, "source_url": url}
            )
            records.append({
                "ticker": ticker,
                "source_url": url,
                "fetched_at_utc": fetched_at.isoformat(),
                "raw_path": f"{container}/{blob_path}",
                "http_status": response.status_code,
                "content_type": response.headers.get("Content-Type", ""),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            })

        manifest = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records)
        manifest_path = f"manifests/ingest_date={fetched_at:%Y-%m-%d}/manifest_{stamp}.jsonl"
        service.get_blob_client(container=container, blob=manifest_path).upload_blob(
            manifest.encode("utf-8"), overwrite=False
        )
        return func.HttpResponse(
            json.dumps({"status": "succeeded", "fetched_at_utc": fetched_at.isoformat(),
                        "records": records, "manifest": f"{container}/{manifest_path}"}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as exc:  # surfaced to ADF as a failed activity
        logging.exception("Global X ingestion failed")
        return func.HttpResponse(
            json.dumps({"status": "failed", "error": str(exc), "records_written": len(records)}),
            mimetype="application/json",
            status_code=500,
        )
