# Azure Data Factory artifacts

This version uses native ADF Copy activity; it does not require a Function App or Databricks workspace. The pipeline, both datasets, and both linked services have been published to `adf-globalx-etf-dev-01`.

1. The factory contains `ls_http_globalx`, `ls_adls_globalx_bronze`, `ds_http_globalx_binary`, `ds_adls_globalx_binary`, and `pl_globalx_ingest`.
2. The HTTP linked service is anonymous and reads the official Global X Canada product pages.
3. The ADLS Gen2 linked service targets `stglobalxetfdev01`. The private `bronze` container exists. The Data Factory system-assigned managed identity is `adf-globalx-etf-dev-01`; grant it **Storage Blob Data Contributor** scoped to the `bronze` container before testing the sink.
4. The pipeline uses a sequential ForEach over the six tickers. A successful run writes each source HTML page under `bronze/holdings/<ticker>/ingest_date=YYYY-MM-DD/` with a UTC timestamped filename. The sequential setting avoids parallel bursts to the public source site.
5. The pipeline validates successfully. Run it manually after the container-scoped role assignment and inspect the bronze files first. Add a daily schedule only after confirming the source pages and storage output.

The source pages are point-in-time product pages. A later milestone can parse the holdings section into a Silver table and add row-count, source-date, and percentage-range checks.

