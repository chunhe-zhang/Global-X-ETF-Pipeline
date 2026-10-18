import json, logging, os, re
from datetime import datetime, timezone
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from src.catalog import PRODUCTS, CATALOG_AS_OF
from src.lookthrough import calculate_lookthrough
from src.parse_holdings import parse_holdings_html

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
CONTAINER = os.getenv("DATA_CONTAINER", "bronze")
ACCOUNT_URL = os.environ["BLOB_ACCOUNT_URL"]
KNOWN_FUNDS = {p["ticker"].upper() for p in PRODUCTS}
CANADIAN_FUNDS = {p["ticker"].upper() for p in PRODUCTS if p["region_code"] == "CA"}

def _container():
    svc = BlobServiceClient(ACCOUNT_URL, credential=DefaultAzureCredential())
    return svc.get_container_client(CONTAINER)

def _json_response(data, status=200):
    return func.HttpResponse(json.dumps(data), status_code=status, mimetype="application/json",
        headers={"Access-Control-Allow-Origin": os.getenv("ALLOWED_ORIGIN", "https://chunhe-zhang.github.io"),
                 "Cache-Control": "public, max-age=300"})

@app.route(route="catalog", methods=["GET", "OPTIONS"])
def catalog(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers={"Access-Control-Allow-Origin": os.getenv("ALLOWED_ORIGIN", "https://chunhe-zhang.github.io"),
            "Access-Control-Allow-Methods": "GET,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
    try:
        container = _container()
        ready = {blob.name.removeprefix("gold/lookthrough/").removesuffix(".json")
                 for blob in container.list_blobs(name_starts_with="gold/lookthrough/")}
        result = []
        for product in PRODUCTS:
            item = dict(product)
            item["data_ready"] = f"{item['region_code']}/{item['ticker']}" in ready
            result.append(item)
        return _json_response({"catalog_as_of": CATALOG_AS_OF, "products": result})
    except Exception:
        logging.exception("Catalog request failed")
        return _json_response({"error": "catalog_unavailable"}, 500)

@app.route(route="lookthrough/{region}/{ticker}", methods=["GET", "OPTIONS"])
def lookthrough(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers={"Access-Control-Allow-Origin": os.getenv("ALLOWED_ORIGIN", "https://chunhe-zhang.github.io"),
            "Access-Control-Allow-Methods": "GET,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
    region = (req.route_params.get("region") or "").upper()
    ticker = (req.route_params.get("ticker") or "").upper()
    if not any(p["region_code"] == region and p["ticker"].upper() == ticker for p in PRODUCTS):
        return _json_response({"error":"unknown_fund","region":region,"ticker":ticker}, 404)
    try:
        blob = _container().get_blob_client(f"gold/lookthrough/{region}/{ticker}.json")
        return _json_response(json.loads(blob.download_blob().readall()))
    except Exception:
        return _json_response({"error":"holdings_unavailable","region":region,"ticker":ticker,
            "message":"Catalog entry exists, but no processed holdings snapshot is available yet."}, 404)

@app.route(route="refresh/{ticker}", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def refresh(req: func.HttpRequest) -> func.HttpResponse:
    """Parse the latest ADF-landed Canadian HTML snapshot, persist silver, then recompute gold."""
    ticker = (req.route_params.get("ticker") or "").upper()
    if ticker not in CANADIAN_FUNDS:
        return _json_response({"error":"unknown_fund","ticker":ticker}, 404)
    try:
        container = _container()
        prefix = f"holdings/{ticker}/"
        candidates = [b for b in container.list_blobs(name_starts_with=prefix) if b.name.lower().endswith(".html")]
        if not candidates:
            return _json_response({"error":"raw_snapshot_missing","ticker":ticker}, 404)
        latest = max(candidates, key=lambda b: b.last_modified or datetime.min.replace(tzinfo=timezone.utc))
        html = container.get_blob_client(latest.name).download_blob().readall().decode("utf-8", errors="replace")
        rows = parse_holdings_html(html, KNOWN_FUNDS)
        date_match = re.search(r"(?:as of|holdings as at|data as at)\s*[:\-]?\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", html, re.I)
        source_as_of = date_match.group(1) if date_match else None
        product = next(p for p in PRODUCTS if p["region_code"]=="CA" and p["ticker"].upper()==ticker)
        ingested_at = datetime.now(timezone.utc).isoformat()
        normalized = {"ticker":ticker,"region":"CA","as_of":source_as_of,"ingested_at":ingested_at,
                      "source_url":product["product_url"],"source_blob":latest.name,"holdings":rows}
        silver_name=f"silver/holdings/CA/{ticker}.json"
        container.get_blob_client(silver_name).upload_blob(json.dumps(normalized), overwrite=True)
        graph = {}
        for blob in container.list_blobs(name_starts_with="silver/holdings/CA/"):
            if blob.name.endswith(".json"):
                key = blob.name.rsplit("/",1)[-1].removesuffix(".json").upper()
                try:
                    graph[key] = json.loads(container.get_blob_client(blob.name).download_blob().readall()).get("holdings",[])
                except Exception:
                    logging.warning("Skipping unreadable normalized snapshot %s", blob.name)
        graph[ticker] = rows
        result = calculate_lookthrough(ticker, graph)
        result.update({"region":"CA","as_of":source_as_of,"source_url":product["product_url"],
                       "source_blob":latest.name,"processed_at":ingested_at,"method":"recursive_weight_multiplication"})
        target=container.get_blob_client(f"gold/lookthrough/CA/{ticker}.json")
        target.upload_blob(json.dumps(result),overwrite=True)
        return _json_response({"ticker":ticker,"silver":silver_name,"gold":target.blob_name,
                                "holdings_count":len(rows),"lookthrough_count":len(result["holdings"])},202)
    except Exception:
        logging.exception("Refresh failed for %s",ticker)
        return _json_response({"error":"refresh_failed","ticker":ticker,
                               "message":"Source parsing or storage write failed; inspect Function logs."},400)
