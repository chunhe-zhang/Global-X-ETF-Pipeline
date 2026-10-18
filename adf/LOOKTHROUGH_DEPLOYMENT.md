# Look-through deployment notes

Existing ADF Copy pipeline remains the raw landing step. The multi-region catalog snapshot is metadata; holding availability is tracked independently.

## Logical lake layout (inside existing private bronze container)
- `holdings/<ticker>/ingest_date=YYYY-MM-DD/*.html`: raw Canadian source snapshots (existing ADF pipeline)
- `silver/holdings/CA/<ticker>.json`: parsed source rows with ticker, name, weight_pct, is_fund, as_of, and source_url
- `gold/lookthrough/CA/<ticker>.json`: recursively multiplied exposure served by the API

The HTML parser is best-effort and must be checked against source table layouts. It rejects pages where it cannot find a recognizable holdings/weight table; it does not fabricate results.

## Azure Function
Deploy the Python Function App on a supported plan and set `BLOB_ACCOUNT_URL`, `DATA_CONTAINER=bronze`, and `ALLOWED_ORIGIN=https://chunhe-zhang.github.io`. Enable a system-assigned identity and grant **Storage Blob Data Contributor** only on the existing `bronze` container. This Function identity has not yet been created or granted access.

API routes:
- `GET /api/catalog`: returns the 224-entry public regional catalog and per-product gold-snapshot availability
- `GET /api/lookthrough/{region}/{ticker}`: returns one processed snapshot
- `POST /api/refresh/{ticker}`: key-protected Canadian raw-to-silver-to-gold processing

Public GET returns only public product/holdings data. Keep POST protected with a Function key or Entra authentication. Set CORS to the GitHub Pages origin. Avoid including account keys in GitHub.

## ADF orchestration
Keep the deployed raw ingestion pipeline. Publish `pipeline_globalx_refresh.json` after deploying the Function and store its Function key as a secure pipeline parameter or Key Vault reference. The template runs sequentially over the six currently ingested Canadian products. Existing ADF managed identity has access only to bronze.

## Coverage and cost
Catalog capture date is 2026-10-18. The catalog includes US (116 ticker-only), Australia (53), Brazil (38), Colombia (2), Hong Kong (9 partial visible listings), and Canada (6 ADF products). It is not a claim that holdings are available for all products. Japan is omitted per the official site's reproduction restriction; Canada full catalog retrieval was blocked; Europe and Singapore had no product-level rows in the captured public pages.

No Function App has been provisioned yet. Function hosting and logging may incur charges; check the subscription's pricing and plan availability before deployment. Weights over 100% are valid and should not be normalized to 100%.
