import json, logging, os, re
import requests
from datetime import datetime, timezone
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from src.catalog import PRODUCTS, CATALOG_AS_OF
from src.lookthrough import calculate_lookthrough
from src.public_holdings import fetch_public_holdings

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
@app.route(route="refresh/{region}/{ticker}", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def refresh(req: func.HttpRequest) -> func.HttpResponse:
    """Fetch official public holdings, persist raw and silver snapshots."""
    region = (req.route_params.get("region") or "CA").upper()
    ticker = (req.route_params.get("ticker") or "").upper()
    product = next((p for p in PRODUCTS if p["region_code"] == region and p["ticker"].upper() == ticker), None)
    if not product:
        return _json_response({"error":"unknown_fund","region":region,"ticker":ticker}, 404)
    try:
        acquired = fetch_public_holdings(product, KNOWN_FUNDS)
        container = _container()
        ingested_at = datetime.now(timezone.utc).isoformat()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ext = "csv" if "csv" in acquired["media_type"] else "html"
        raw_name = f"raw/holdings/{region}/{ticker}/{stamp}.{ext}"
        container.get_blob_client(raw_name).upload_blob(acquired["raw"], overwrite=True)
        normalized = {
            "ticker":ticker,"region":region,"as_of":acquired["as_of"],
            "ingested_at":ingested_at,"source_url":acquired["source_url"],
            "source_blob":raw_name,"holdings":acquired["holdings"],
            "coverage_status":"parsed_public_source"
        }
        silver_name=f"silver/holdings/{region}/{ticker}.json"
        container.get_blob_client(silver_name).upload_blob(json.dumps(normalized),overwrite=True)
        return _json_response({"ticker":ticker,"region":region,"silver":silver_name,
                               "source_blob":raw_name,"holdings_count":len(acquired["holdings"]),
                               "as_of":acquired["as_of"]},202)
    except requests.exceptions.HTTPError as exc:
        logging.warning("Public source returned HTTP error for %s/%s: %s", region, ticker, exc)
        return _json_response({"error":"public_source_http_error","region":region,"ticker":ticker,
                               "message":"Official public source could not be fetched."},502)
    except Exception:
        logging.exception("Public holdings acquisition failed for %s/%s",region,ticker)
        return _json_response({"error":"public_source_unavailable","region":region,"ticker":ticker,
                               "message":"No parseable public holdings were found; no exposure was fabricated."},422)

@app.route(route="calculate/{region}/{ticker}", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def calculate(req: func.HttpRequest) -> func.HttpResponse:
    """Recalculate after acquisition finishes so nested ETF children are available."""
    region = (req.route_params.get("region") or "").upper()
    ticker = (req.route_params.get("ticker") or "").upper()
    if not any(p["region_code"] == region and p["ticker"].upper() == ticker for p in PRODUCTS):
        return _json_response({"error":"unknown_fund","region":region,"ticker":ticker},404)
    try:
        container = _container()
        graph = {}
        for blob in container.list_blobs(name_starts_with=f"silver/holdings/{region}/"):
            if blob.name.endswith(".json"):
                key = blob.name.rsplit("/",1)[-1].removesuffix(".json").upper()
                try:
                    graph[key] = json.loads(container.get_blob_client(blob.name).download_blob().readall()).get("holdings",[])
                except Exception:
                    logging.warning("Skipping unreadable normalized snapshot %s",blob.name)
        if ticker not in graph:
            return _json_response({"error":"silver_snapshot_missing","region":region,"ticker":ticker},404)
        result = calculate_lookthrough(ticker, graph)
        product = next(p for p in PRODUCTS if p["region_code"]==region and p["ticker"].upper()==ticker)
        silver = json.loads(container.get_blob_client(f"silver/holdings/{region}/{ticker}.json").download_blob().readall())
        result.update({"region":region,"as_of":silver.get("as_of"),"source_url":silver.get("source_url"),
                       "processed_at":datetime.now(timezone.utc).isoformat(),
                       "method":"recursive_weight_multiplication"})
        target=container.get_blob_client(f"gold/lookthrough/{region}/{ticker}.json")
        target.upload_blob(json.dumps(result),overwrite=True)
        return _json_response({"ticker":ticker,"region":region,"gold":target.blob_name,
                               "lookthrough_count":len(result.get("holdings",[])),
                               "unresolved_count":len(result.get("unresolved",[]))},202)
    except Exception:
        logging.exception("Look-through calculation failed for %s/%s",region,ticker)
        return _json_response({"error":"calculation_failed","region":region,"ticker":ticker},500)
