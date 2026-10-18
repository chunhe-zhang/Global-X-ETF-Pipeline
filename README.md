# Global X ETF Look-through

An Azure Data Engineer interview project that catalogs publicly listed Global X products and calculates look-through exposure when source holdings are available.

## Public product catalog

The website catalog snapshot was captured on **2026-10-18** from public regional catalog files saved in the user-authorized project folder. It includes **224 listings**:

| Region | Listings | Current catalog detail |
|---|---:|---|
| United States | 116 | Ticker and official product URL |
| Australia | 53 | Product names and public fund facts |
| Brazil | 38 | Product names and public fund facts |
| Colombia | 2 | Product facts; top holdings were captured separately |
| Hong Kong | 9 | Partial visible product list |
| Canada | 6 | PowerStock funds already landed by ADF |

This is a broad public snapshot, not a complete Global X master list. Canada’s full catalog page returned HTTP 403 to the earlier permitted retrieval attempt; Europe showed no catalog rows, Singapore exposed no product-level listing, and Japan was excluded after the official site notice restricted reproduction. The U.S. file has ticker-only entries. Each website entry links to an official regional catalog or fund page where known.

## Holdings coverage and look-through method

The Azure pipeline currently ingests raw HTML for AAPP, AMZP, GOOP, NVDP, SPCP, and TSLP into the private `bronze` container. The new Function collector supports the official full-holdings download or public holdings table and has a two-pass ADF template for all 224 catalog entries. Official product-page routes are mapped for US (116), Australia (53), Brazil (38), Colombia (2), Hong Kong (9), and Canada (6); AU and Brazil use the official funds-page URL pattern and Hong Kong uses links from its official fund list. **The Function and refresh template remain code only until deployed and run in Azure.** Some public pages may lack downloadable full holdings or may not parse; those rows remain unavailable rather than fabricated.

Holdings are normalized as rows with a security ticker and weight percentage of parent NAV. For a nested ETF, exposure is multiplied down the path; repeated underlying securities are aggregated. Weights above 100% remain intact (for example, 133.54% is represented as 1.3354×). Cycles and unavailable fund holdings are reported as unresolved instead of guessed.

## Azure architecture (no Databricks)

```text
Global X public holdings pages
        | HTTPS
        v
Azure Data Factory Copy activity (deployed)
        | timestamped raw HTML
        v
Azure Blob Storage / private bronze container
        | future Function parser + recursive calculation
        v
logical silver normalized holdings -> gold look-through JSON
        | public read-only API
        v
GitHub Pages website
```

The existing ADF pipeline is `pl_globalx_ingest`; its system-assigned managed identity is scoped to the `bronze` container. The multi-region pipeline template is `adf/pipeline_globalx_refresh.json`; deployment guidance is in `adf/PUBLIC_HOLDINGS_REFRESH.md`. These require a Function App deployment, narrowly scoped Function managed identity access to bronze, and ADF secure key wiring before live results are served.

## Website

The standalone experience is in `globalx-lookthrough/` in the personal website repository and has a different visual design from the portfolio. Set `window.GLOBALX_API_BASE` to the deployed Function API base ending in `/api` to enable live processed results.

## Run locally

```powershell
python -m pip install -r requirements.txt
python src/fetch_raw.py
```

Do not commit secrets or raw downloaded pages. Keep source URL, catalog snapshot date, holdings as-of date, and ingestion time separate. This project is educational and not investment advice.
