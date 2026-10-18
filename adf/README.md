# Azure Data Factory artifacts

This version uses native ADF Copy activity; it does not require a Function App or Databricks workspace. The pipeline, both datasets, and both linked services are published to `adf-globalx-etf-dev-01`.

1. The factory contains `ls_http_globalx`, `ls_adls_globalx_bronze`, `ds_http_globalx_binary`, `ds_adls_globalx_binary`, and `pl_globalx_ingest`.
2. The HTTP linked service is anonymous and reads the official Global X Canada product pages.
3. The ADLS Gen2 linked service targets `stglobalxetfdev01`. The private `bronze` container exists. The Data Factory system-assigned managed identity `adf-globalx-etf-dev-01` has **Storage Blob Data Contributor** scoped only to the `bronze` container.
4. The pipeline uses a sequential ForEach over six tickers. A successful run writes each source HTML page under `bronze/holdings/<ticker>/ingest_date=YYYY-MM-DD/` with a UTC timestamped filename. The sequential setting avoids parallel bursts to the public source site.
5. The pipeline was validated and published, and its Debug run succeeded for all six Copy activity iterations. The resulting `holdings` hierarchy and a 259.33 KiB AAPP HTML blob were verified in the bronze container. ADF's linked-service Test Connection reported a forbidden error because its probe attempted a `testconnection` container; the actual pipeline proved access to the authorized `bronze` container without widening the role scope.

The source pages are point-in-time product pages. The next milestone is to parse the holdings section into a Silver table and add row-count, source-date, and percentage-range checks.
