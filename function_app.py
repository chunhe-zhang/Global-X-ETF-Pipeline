import json, logging, os
from datetime import datetime, timezone
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from src.catalog import PRODUCTS
from src.lookthrough import calculate_lookthrough
from src.parse_holdings import parse_holdings_html

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
CONTAINER = os.getenv("DATA_CONTAINER", "bronze")
ACCOUNT_URL = os.environ["BLOB_ACCOUNT_URL"]
KNOWN_FUNDS = {p["ticker"] for p in PRODUCTS}

def _container():
    svc = BlobServiceClient(ACCOUNT_URL, credential=DefaultAzureCredential())
    return svc.get_container_client(CONTAINER)

def _json_response(data, status=200):
    return func.HttpResponse(json.dumps(data), status_code=status, mimetype="application/json",
        headers={"Access-Control-Allow-Origin": os.getenv("ALLOWED_ORIGIN", "https://chunhe-zhang.github.io"),
                 "Cache-Control": "public, max-age=300"})

def _read_graph(container):
    graph = {}
    for blob in container.list_blobs(name_starts_with="silver/holdings/CA/"):
        if not blob.name.endswith(".json"):
            continue
        ticker = blob.name.rsplit("/", 1)[-1].removesuffix(".json").upper()
        try:
            graph[ticker] = json.loads(container.get_blob_client(blob.name).download_blob().readall())
        except Exception:
            logging.warning("Skipping unreadable normalized holdings blob %s", blob.name)
    return graph

@app.route(route="catalog", methods=["GET", "OPTIONS"])
def catalog(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers={"Access-Control-Allow-Origin": os.getenv("ALLOWED_ORIGIN", "https://chunhe-zhang.github.io"),
            "Access-Control-Allow-Methods": "GET,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
    try:
        client = _container()
        result = []
        for product in PRODUCTS:
            item = dict(product)
            try:
                blob = client.get_blob_client(f"gold/lookthrough/CA/{item['ticker']}.json")
                item["as_of"] = json.loads(blob.download_blob().readall()).get("as_of")
                item["data_ready"] = True
            except Exception:
                item["data_ready"] = False
            result.append(item)
        return _json_response({"products": result})
    except Exception:
        logging.exception("Catalog request failed")
        return _json_response({"error": "catalog_unavailable"}, 500)

@app.route(route="lookthrough/{ticker}", methods=["GET", "OPTIONS"])
def lookthrough(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers={"Access-Control-Allow-Origin": os.getenv("ALLOWED_ORIGIN", "https://chunhe-zhang.github.io"),
            "Access-Control-Allow-Methods": "GET,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
    ticker = (req.route_params.get("ticker") or "").upper()
    try:
        blob = _container().get_blob_client(f"gold/lookthrough/CA/{ticker}.json")
        return _json_response(json.loads(blob.download_blob().readall()))
    except Exception:
        return _json_response({"error":"holdings_unavailable", "ticker":ticker,
            "message":"No processed snapshot is available yet."}, 404)

@app.route(route="refresh/{ticker}", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def refresh(req: func.HttpRequest) -> func.HttpResponse:
    """Parse the latest ADF-landed HTML page, persist silver, then recompute gold."""
    ticker = (req.route_params.get("ticker") or "").upper()
    if ticker not in KNOWN_FUNDS:
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
        source_as_of = None
        # The page may contain its data timestamp as visible text; retain it only when confidently found.
        import re
        date_match = re.search(r"(?:as of|holdings as at|data as at)\s*[:\-]?\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", html, re.I)
        if date_match:
            source_as_of = date_match.group(1)
        normalized = {"ticker":ticker,"region":"CA","as_of":source_as_of,
                      "ingested_at":datetime.now(timezone.utc).isoformat(),
                      "source_url":next(p["url"] for p in PRODUCTS if p["ticker"]==ticker),
                      "source_blob":latest.name,"holdings":rows}
        silver_name=f"silver/holdings/CA/{ticker}.json"
        container.get_blob_client(silver_name).upload_blob(json.dumps(normalized), overwrite=True)
        graph_docs=_read_graph(container)
        graph={key:doc.get("holdings",[]) for key,doc in graph_docs.items()}
        graph[ticker]=rows
        result=calculate_lookthrough(ticker, graph)
        result.update({"as_of":source_as_of,"source_url":normalized["source_url"],
                       "source_blob":latest.name,"processed_at":normalized["ingested_at"],
                       "method":"recursive_weight_multiplication"})
        target=container.get_blob_client(f"gold/lookthrough/CA/{ticker}.json")
        target.upload_blob(json.dumps(result),overwrite=True)
        return _json_response({"ticker":ticker,"silver":silver_name,"gold":target.blob_name,
                                "holdings_count":len(rows),"lookthrough_count":len(result["holdings"])},202)
    except Exception:
        logging.exception("Refresh failed for %s",ticker)
        return _json_response({"error":"refresh_failed","ticker":ticker,
                               "message":"Source parsing or storage write failed; inspect Function logs."},400)
