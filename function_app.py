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
KNOWN_FUNDS_BY_REGION = {region: {p["ticker"].upper() for p in PRODUCTS if p["region_code"] == region} for region in {p["region_code"] for p in PRODUCTS}}

def _container():
    svc = BlobServiceClient(ACCOUNT_URL, credential=DefaultAzureCredential())
    return svc.get_container_client(CONTAINER)

def _json_response(data, status=200):
    return func.HttpResponse(json.dumps(data), status_code=status, mimetype="application/json",
        headers={"Access-Control-Allow-Origin": os.getenv("ALLOWED_ORIGIN", "https://chunhe-zhang.github.io"),
                 "Cache-Control": "public, max-age=300"})

def _coverage_name(region, ticker):
    return f"gold/status/{region}/{ticker}.json"

def _save_coverage(container, region, ticker, status, reason, **details):
    payload = {"region": region, "ticker": ticker, "coverage_status": status,
               "coverage_reason": reason, "updated_at": datetime.now(timezone.utc).isoformat()}
    payload.update(details)
    container.get_blob_client(_coverage_name(region, ticker)).upload_blob(
        json.dumps(payload), overwrite=True)
    return payload

def _read_coverage(container, region, ticker):
    try:
        blob = container.get_blob_client(_coverage_name(region, ticker))
        return json.loads(blob.download_blob().readall())
    except Exception:
        return {}

def _fallback_coverage(product):
    status = product.get("holdings_status", "not_loaded")
    if status == "raw_html_only":
        return ("raw_only", "Azure Data Factory saved this product page as raw HTML in bronze, but it has not yet been parsed into normalized holdings.")
    if status == "top_holdings_captured":
        return ("limited_source_data", "Only limited top-holdings metadata is recorded; a full normalized holdings snapshot is not available.")
    return ("not_attempted", "The official product page is mapped, but no successful holdings fetch or normalized snapshot has been recorded yet.")


@app.route(route="catalog", methods=["GET", "OPTIONS"])
def catalog(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers={"Access-Control-Allow-Origin": os.getenv("ALLOWED_ORIGIN", "https://chunhe-zhang.github.io"),
            "Access-Control-Allow-Methods": "GET,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
    try:
        container = _container()
        ready = {blob.name.removeprefix("gold/lookthrough/").removesuffix(".json")
                 for blob in container.list_blobs(name_starts_with="gold/lookthrough/")}
        statuses = {}
        for blob in container.list_blobs(name_starts_with="gold/status/"):
            if blob.name.endswith(".json"):
                key = blob.name.removeprefix("gold/status/").removesuffix(".json")
                try:
                    statuses[key] = json.loads(container.get_blob_client(blob.name).download_blob().readall())
                except Exception:
                    logging.warning("Skipping unreadable coverage status %s", blob.name)
        result = []
        for product in PRODUCTS:
            item = dict(product)
            key = f"{item['region_code']}/{item['ticker']}"
            item["data_ready"] = key in ready
            coverage = statuses.get(key) or {}
            fallback_status, fallback_reason = _fallback_coverage(item)
            item["coverage_status"] = coverage.get("coverage_status") or ("processed" if key in ready else fallback_status)
            item["coverage_reason"] = coverage.get("coverage_reason") or (None if key in ready else fallback_reason)
            item["coverage_updated_at"] = coverage.get("updated_at")
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
        coverage = _read_coverage(_container(), region, ticker)
        product = next(p for p in PRODUCTS if p["region_code"] == region and p["ticker"].upper() == ticker)
        fallback_status, fallback_reason = _fallback_coverage(product)
        reason = coverage.get("coverage_reason") or fallback_reason
        status = coverage.get("coverage_status") or fallback_status
        return _json_response({"error":"holdings_unavailable","region":region,"ticker":ticker,
            "coverage_status":status,"coverage_reason":reason,"message":reason}, 404)

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
        acquired = fetch_public_holdings(product, KNOWN_FUNDS_BY_REGION.get(region, set()))
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
        _save_coverage(container, region, ticker, "normalized",
                       "Public holdings were fetched and normalized from the official source.",
                       source_url=acquired["source_url"], as_of=acquired["as_of"],
                       holdings_count=len(acquired["holdings"]))
        return _json_response({"ticker":ticker,"region":region,"silver":silver_name,
                               "source_blob":raw_name,"holdings_count":len(acquired["holdings"]),
                               "as_of":acquired["as_of"]},202)
    except requests.exceptions.HTTPError as exc:
        logging.warning("Public source returned HTTP error for %s/%s: %s", region, ticker, exc)
        reason = "The official product page returned an HTTP error; no holdings were accepted."
        try:
            _save_coverage(_container(), region, ticker, "source_http_error", reason,
                           http_status=getattr(exc.response, "status_code", None))
        except Exception:
            logging.exception("Could not persist coverage status for %s/%s", region, ticker)
        return _json_response({"error":"source_http_error","coverage_status":"source_http_error",
                               "coverage_reason":reason,"region":region,"ticker":ticker,
                               "message":reason},502)
    except ValueError as exc:
        logging.info("No recognizable public holdings for %s/%s: %s", region, ticker, exc)
        reason = "The official page was reachable, but no recognizable ticker-and-weight table or holdings CSV was found."
        try:
            _save_coverage(_container(), region, ticker, "parser_no_holdings", reason)
        except Exception:
            logging.exception("Could not persist coverage status for %s/%s", region, ticker)
        return _json_response({"error":"parser_no_holdings","coverage_status":"parser_no_holdings",
                               "coverage_reason":reason,"region":region,"ticker":ticker,
                               "message":reason},422)
    except Exception:
        logging.exception("Public holdings acquisition failed for %s/%s",region,ticker)
        reason = "The public holdings source could not be fetched or decoded; no exposure was fabricated."
        try:
            _save_coverage(_container(), region, ticker, "public_source_unavailable", reason)
        except Exception:
            logging.exception("Could not persist coverage status for %s/%s", region, ticker)
        return _json_response({"error":"public_source_unavailable","coverage_status":"public_source_unavailable",
                               "coverage_reason":reason,"region":region,"ticker":ticker,
                               "message":reason},422)

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
            coverage = _read_coverage(container, region, ticker)
            reason = coverage.get("coverage_reason") or "No normalized holdings snapshot exists for this fund."
            return _json_response({"error":"silver_snapshot_missing",
                                   "coverage_status":coverage.get("coverage_status","not_attempted"),
                                   "coverage_reason":reason,"region":region,"ticker":ticker,
                                   "message":reason},404)
        result = calculate_lookthrough(ticker, graph)
        product = next(p for p in PRODUCTS if p["region_code"]==region and p["ticker"].upper()==ticker)
        silver = json.loads(container.get_blob_client(f"silver/holdings/{region}/{ticker}.json").download_blob().readall())
        result.update({"region":region,"as_of":silver.get("as_of"),"source_url":silver.get("source_url"),
                       "processed_at":datetime.now(timezone.utc).isoformat(),
                       "method":"recursive_weight_multiplication"})
        target=container.get_blob_client(f"gold/lookthrough/{region}/{ticker}.json")
        target.upload_blob(json.dumps(result),overwrite=True)
        unresolved = result.get("unresolved", [])
        coverage_status = "partial" if unresolved else "processed"
        reason = (f"Exposure is calculated, but {len(unresolved)} nested positions remain unresolved because child holdings are unavailable, cyclic, or beyond the depth limit."
                  if unresolved else "Public holdings were recursively multiplied through all available nested ETF layers.")
        _save_coverage(container, region, ticker, coverage_status, reason,
                       as_of=silver.get("as_of"), unresolved_count=len(unresolved),
                       source_url=silver.get("source_url"))
        return _json_response({"ticker":ticker,"region":region,"gold":target.blob_name,
                               "lookthrough_count":len(result.get("holdings",[])),
                               "unresolved_count":len(unresolved)},202)
    except Exception:
        logging.exception("Look-through calculation failed for %s/%s",region,ticker)
        reason = "The source was acquired, but Azure could not finish the exposure calculation."
        try:
            _save_coverage(container, region, ticker, "calculation_failed", reason)
        except Exception:
            logging.exception("Could not persist coverage status for %s/%s", region, ticker)
        return _json_response({"error":"calculation_failed","coverage_status":"calculation_failed",
                               "coverage_reason":reason,"region":region,"ticker":ticker,
                               "message":reason},500)
