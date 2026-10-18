# Look-through pipeline deployment notes

This is a template, not yet deployed. Existing ADF Copy pipeline remains the raw landing step.

## Logical lake layout (inside existing private bronze container)
- `holdings/<ticker>/ingest_date=YYYY-MM-DD/*.html`: unchanged official source snapshot (existing ADF output)
- `silver/holdings/CA/<ticker>.json`: source-adapter normalized rows, each with ticker, name, weight_pct, is_fund, as_of, source_url
- `gold/lookthrough/CA/<ticker>.json`: recursively multiplied exposure used by the website

The API expects ADF or a parser job to write normalized JSON to silver before refresh. This PR supplies the recursive calculator and API skeleton; a source-specific parser is the next engineering milestone. Never infer missing positions from product names.

## Azure Function
Deploy this Python Function App on a supported Linux Functions plan in the same region as Storage. Set `BLOB_ACCOUNT_URL`, `DATA_CONTAINER=bronze`, and `ALLOWED_ORIGIN=https://chunhe-zhang.github.io`. Enable a system-assigned identity and grant it **Storage Blob Data Contributor** scoped to the existing `bronze` container. This is a new identity and assignment; it has not been granted yet.

The API routes are `GET /api/catalog`, `GET /api/lookthrough/{ticker}`, and `POST /api/refresh`. Protect POST with Entra authentication or a Function key stored as an ADF secure parameter/Key Vault reference. Public GET routes return only public derived holdings. Do not use anonymous POST in production.

## ADF orchestration
Keep the deployed raw ingestion pipeline. After source parsing writes silver, call the refresh route per ticker using a Web activity. The JSON in `pipeline_globalx_refresh.json` is a starter template and needs a Function linked service / secure parameter wiring before publish. Existing Data Factory identity currently only has access to bronze.

## Cost and coverage
No new Azure service has been provisioned. Function hosting, logging, and outbound calls may incur cost. The first catalog slice is the six Canadian PowerStock products already ingested by ADF; expand from official region catalogs only when accessible. Each output must retain source date, URL, and unresolved ETF edges. Holdings over 100% are allowed and must not be normalized to 100%.
