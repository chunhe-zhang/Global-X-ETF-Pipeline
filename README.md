# Global X ETF Holdings Pipeline

An interview project for an Azure Data Engineer role. The first milestone collects the published holdings pages for Global X Canada's six PowerStock ETFs and stores timestamped raw HTML snapshots for lineage and replay.

## Initial scope

- AAPP, AMZP, GOOP, NVDP, SPCP, TSLP
- Source: each fund's official Global X Canada product page
- First layer: raw HTML snapshots (bronze); parsing and validation come next
- Holdings are point-in-time data. Keep the source as-of date separate from the fetch timestamp.

## Source fields observed

Each product page exposes a `Top Holdings` section with a source date, security name, and weight. The PowerStock funds are leveraged single-stock ETFs, so weights can exceed 100%; do not normalize them to 100% or treat them as conventional diversified ETF portfolios.

## Run locally

```powershell
python -m pip install -r requirements.txt
python src/fetch_raw.py
```

Raw snapshots are written under `data/bronze/<ticker>/` with a UTC timestamp in the filename. The manifest records source URL, fetch time, and SHA-256 checksum.

## Azure architecture (without Databricks)

```text
Global X product pages
        | HTTPS
        v
Azure Data Factory Copy activity
        | HTTP GET (six product pages, sequential ForEach)
        v
ADLS Gen2 / Blob Storage
bronze HTML snapshots partitioned by ticker and ingest date
```

The ADF artifacts are in `adf/`. A sequential `ForEach` executes an HTTP Binary Copy for each official product page and writes the raw HTML under `bronze/holdings/<ticker>/ingest_date=YYYY-MM-DD/` using a UTC timestamped filename. This keeps the source payload unchanged for replay. In Azure, grant the Data Factory system-assigned managed identity **Storage Blob Data Contributor** on the storage account. The local Python script remains a simple way to reproduce the same raw capture locally.

This architecture demonstrates ingestion, orchestration, partitioned data-lake storage, managed identity, retries, and lineage without Databricks or a custom compute host. Azure rejected Databricks Trial SKU for this subscription and also does not support Functions Flex Consumption on this Free Trial subscription, so the pipeline uses ADF's native HTTP Copy activity.

## GitHub and Azure deployment

Keep source in a private GitHub repository. Connect ADF authoring to that repository and the `adf` folder. Do not commit secrets or downloaded source snapshots. Keep subscription-specific values in deployment parameters, not source code.

## Data use

This project is for educational and interview demonstration purposes. Source pages state that holdings are subject to change. Every output should retain its source URL and source as-of date and should not be presented as investment advice.
