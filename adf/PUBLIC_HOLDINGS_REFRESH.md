> Deployment status (2026-10-18): this Function-based refresh is a template. The deployed Canadian flow is `pl_globalx_canada_snapshot_sync`; see [CANADA_EXPANSION.md](CANADA_EXPANSION.md). Its source is a captured public snapshot, and Python analysis has been run in Azure Cloud Shell.

# Public holdings refresh template

This template is designed to run from Azure Data Factory after the Function App
has been deployed. It processes the catalog entries that have a mapped official
product URL in `src/catalog_data.json` (397 catalog entries with mapped official regional product pages).

## Flow

1. The first ForEach calls `POST /api/refresh/{region}/{ticker}`. The Function
   requests the mapped Global X product page with the public full-holdings CSV
   option, follows an official CSV link when present, or parses the public
   holdings table. It stores the untouched source response under
   `raw/holdings/{region}/{ticker}/` and normalized rows under
   `silver/holdings/{region}/{ticker}.json`.
2. Only after acquisition completes, the second ForEach calls
   `POST /api/calculate/{region}/{ticker}`. This two-pass design ensures
   nested ETFs can see all successfully acquired child snapshots. Gold output
   is written under `gold/lookthrough/{region}/{ticker}.json`.
3. Both stages use the Function key passed as an ADF SecureString parameter.
   Store the key in Key Vault and configure the ADF parameter as a secure
   Key Vault reference before publishing. Do not commit the key.

## Deploy and configure

- Deploy the Function App from the repository root with Python v2 programming
  model and set `BLOB_ACCOUNT_URL`, `DATA_CONTAINER=bronze`, and the allowed
  website origin as app settings.
- Enable the Function App system-assigned managed identity and grant it
  Storage Blob Data Contributor only on the `bronze` container. All raw,
  silver, and gold paths in this initial project share that container.
- Import the JSON template into ADF, provide the Function base URL and secure
  Function key reference, then publish and trigger a manual run first.
- The Function App identity, RBAC role, ADF import/publish, and successful
  full run must be confirmed in Azure before the website can show live results.

## Coverage limits

The catalog now maps all 224 entries to official product pages: US 116, AU 53,
BR 38, CO 2, HK 9, and CA 6. AU and Brazil URLs follow the official funds-page
route pattern and are marked as such in catalog metadata; Hong Kong URLs were
copied from its official product listing. A route can still return 404 or omit
full holdings. The collector records a per-fund error and never writes
fabricated holdings. A successful Function run is required to establish which
sources actually parse.

ETF holdings disclose snapshots as of a source date. Leveraged products can
have cash, swaps, options, or futures; portfolio weights may exceed 100%.
The calculation multiplies published parent weights through nested ETF
holdings, but cannot infer delta-adjusted derivative exposure unless the
source explicitly publishes it.
