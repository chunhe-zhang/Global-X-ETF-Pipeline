# Azure Data Factory artifacts

This version uses ADF Copy activity directly; it does not require a Function App or Databricks workspace.

1. Import both linked services, both binary datasets, then `pipeline_globalx_ingest.json` into the Data Factory.
2. The HTTP linked service is anonymous and reads the official Global X Canada product pages.
3. The ADLS Gen2 linked service targets `stglobalxetfdev01`. Enable the Data Factory system-assigned managed identity and grant it **Storage Blob Data Contributor** on the storage account before testing the sink.
4. The pipeline uses a sequential ForEach over the six tickers. A successful run writes each source HTML page under `bronze/holdings/<ticker>/ingest_date=YYYY-MM-DD/` with a UTC timestamped filename. The sequential setting avoids parallel bursts to the public source site.
5. Run it manually and inspect the bronze files first. Add a daily schedule only after confirming the source pages and storage output.

The source pages are point-in-time product pages. A later milestone can parse the holdings section into a Silver table and add row-count, source-date, and percentage-range checks.
