"""Rebuild Canadian look-through artifacts from captured official public rows.

Input includes source dates and normalized security/fund identifiers. A ticker is
never invented when the issuer publishes only a security name. No partial table
is rescaled to 100%. Bond, preferred, cash and derivative positions retain type.
"""
import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path


def normalized_name(value):
    value = re.sub(r"GLOBAL X|HORIZONS", "", str(value).upper())
    value = re.sub(r"\([^)]*\)", "", value)
    return re.sub(r"[^A-Z0-9]", "", value)


def analyze(source, max_depth=8):
    graph = {}
    for product in source["products"]:
        graph["CA|" + product["ticker"]] = dict(
            product, rows=(product["issuer_underlying"] if product["use_issuer_underlying"]
                           else product["holdings"]))
    for product in source.get("us_snapshots", []):
        if not product.get("holdings"):
            continue
        rows = [dict(h, weight_pct=h["exposure_pct"],
                     asset_type=h.get("asset_type", "equity")) for h in product["holdings"]]
        rows += [dict(h, weight_pct=h["exposure_pct"], asset_type="fund", is_fund=True)
                 for h in product.get("unresolved", [])]
        graph["US|" + product["ticker"]] = dict(product, rows=rows)
    results = []
    for root in source["products"]:
        positions = {}
        unresolved = []
        dates = set()
        methods = set()

        def emit(row, exposure, path):
            key = row.get("asset_type", "security") + "|" + normalized_name(row.get("name") or row["ticker"])
            if key not in positions:
                positions[key] = {
                    "ticker": row["ticker"], "name": row.get("name", row["ticker"]),
                    "asset_type": row.get("asset_type", "security"), "exposure_pct": 0,
                    "paths": path, "contributions": []}
            positions[key]["exposure_pct"] += exposure
            positions[key]["contributions"].append({"path": path, "exposure_pct": exposure})

        def walk(key, multiplier, path, ancestors, depth):
            node = graph[key]
            if node.get("as_of"):
                dates.add(node["as_of"])
            issuer = node.get("use_issuer_underlying", False)
            methods.add("issuer_published_underlying" if issuer else "recursive_weight_multiplication")
            prefix = path
            if issuer:
                funds = [h for h in node["holdings"] if h.get("is_fund")]
                layer = ((funds[0].get("fund_key") or funds[0]["ticker"]).replace("|", ":")
                         if len(funds) == 1 else "Issuer look-through")
                prefix = path + [layer]
            for row in node["rows"]:
                exposure = multiplier * float(row["weight_pct"])
                if exposure == 0:
                    continue
                next_path = prefix + [row["ticker"]]
                if row.get("is_fund"):
                    child = row.get("fund_key")
                    if child in graph and child not in ancestors and depth < max_depth:
                        label = row["ticker"] if child.startswith("CA|") else child.replace("|", ":")
                        walk(child, exposure / 100, prefix + [label], ancestors | {child}, depth + 1)
                    else:
                        reason = ("cycle_detected" if child in ancestors else
                                  "depth_limit" if depth >= max_depth else
                                  "External or nested ETF holdings snapshot was not captured; no single-stock exposure is inferred.")
                        unresolved.append({
                            "ticker": row["ticker"], "name": row.get("name", row["ticker"]),
                            "asset_type": "fund", "exposure_pct": exposure,
                            "paths": next_path, "reason": reason})
                else:
                    emit(row, exposure, next_path)

        key = "CA|" + root["ticker"]
        walk(key, 1.0, [root["ticker"]], {key}, 0)
        holdings = sorted(positions.values(), key=lambda row: abs(row["exposure_pct"]), reverse=True)
        for row in holdings:
            row["exposure_pct"] = round(row["exposure_pct"], 8)
            for contribution in row["contributions"]:
                contribution["exposure_pct"] = round(contribution["exposure_pct"], 8)
            if len(row["contributions"]) == 1:
                del row["contributions"]
            if row["name"] == row["ticker"]:
                del row["name"]
            if len(row["paths"]) == 2:
                del row["paths"]
        product = dict(root["profile"], holdings=holdings, unresolved=unresolved,
                       source_dates=sorted(dates), calculation_methods=sorted(methods),
                       mixed_source_dates=len(dates) > 1)
        results.append(product)
    return results


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--base-catalog", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8-sig"))
    base = json.loads(args.base_catalog.read_text(encoding="utf-8-sig"))
    tickers = [p["ticker"] for p in source["products"]]
    if len(tickers) != len(set(tickers)) or len(tickers) != source["reported_listing_count"]:
        raise ValueError("Captured listing count or uniqueness does not match official catalog")
    products = analyze(source)
    root = args.out_dir
    write_json(root / "raw/catalog/CA/canada-source.json", source)
    for product, record in zip(products, source["products"]):
        ticker = product["ticker"]
        write_json(root / f"silver/holdings/CA/{ticker}.json", {
            "ticker": ticker, "region": "CA", "as_of": record["as_of"],
            "source_url": record["source_url"], "holdings": record["holdings"],
            "issuer_underlying": record["issuer_underlying"],
            "use_issuer_underlying": record["use_issuer_underlying"]})
        write_json(root / f"gold/lookthrough/CA/{ticker}.json", dict(
            product, region="CA", as_of=product["exposure_as_of"],
            method="typed_recursive_public_snapshot"))
    base["products"] = [p for p in base["products"] if p["region_code"] != "CA"] + products
    base["canada_listing_count"] = len(products)
    base["catalog_as_of"] = source["captured_at"][:10]
    write_json(root / "gold/catalog.json", base)
    summary = {
        "canadian_listings": len(products),
        "direct_source_rows": sum(len(p["holdings"]) for p in source["products"]),
        "lookthrough_security_rows": sum(len(p["holdings"]) for p in products),
        "unresolved_fund_rows": sum(len(p["unresolved"]) for p in products),
        "total_catalog_products": len(base["products"]),
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "catalog_sha256": hashlib.sha256((root / "gold/catalog.json").read_bytes()).hexdigest()}
    write_json(root / "run-summary.json", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
