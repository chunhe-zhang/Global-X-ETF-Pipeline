# Public holdings refresh template

This template is designed to run from Azure Data Factory after the Function App
has been deployed. It processes the catalog entries that have a mapped official
product URL in `src/catalog_data.json` (currently 124 of 224 entries).

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

The current catalog has 224 product entries, but only 124 have an explicit
product page URL in the catalog: US 116, Canada 6, Colombia 2. Australia (53),
Brazil (38), and Hong Kong (9) lack product-level URLs in this snapshot, so
they are not silently assigned guessed endpoints. Public-site responses can
still fail or change format; failed acquisitions return a per-fund error and
write no fabricated holdings. The UI should treat these as unavailable until
an official source URL and parser are verified.

ETF holdings disclose snapshots as of a source date. Leveraged products can
have cash, swaps, options, or futures; portfolio weights may exceed 100%.
The calculation multiplies published parent weights through nested ETF
holdings, but cannot infer delta-adjusted derivative exposure unless the
source explicitly publishes it.
