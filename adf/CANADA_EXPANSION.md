# Canada expansion — 2026-10-18

179 Canadian listing tickers / share classes from https://www.globalx.ca/products replace the earlier six-product subset. Some funds have multiple currency listings; 179 is not a count of distinct portfolios. The combined global catalogue has 397 listing records.

The structured public-page capture contains 1,238 direct holdings rows. The analysis emits 2,283 resolved security rows across the Canadian listings and preserves 57 unresolved ETF-position rows. Coverage is partial; weights are never rescaled to 100%. Bonds, preferred securities, cash and derivatives retain their instrument type. A security name is displayed where no verified exchange ticker is available.

Nested ETF weights are multiplied along each path; multiple paths into one security are summed and retained as contributions. Official same-date underlying tables are preferred where available. Other mixed-date paths are flagged in each product. The source dates are retained; capture date is not holdings date.

## Actual Azure execution
canada_analysis.py has been run in Azure Cloud Shell against the pinned source and original global catalogue. It generated 179 silver files, 179 gold files, the structured raw source, the combined gold catalogue and run-summary.json (361 files), uploaded to stglobalxetfdev01 / bronze.

The ADF pipeline pl_globalx_canada_snapshot_sync copies four versioned GitHub snapshot bundles into raw / silver / gold paths in the same bronze container, using the factory managed identity. Its revision parameter can pin an immutable commit. It does not scrape fresh issuer pages or execute Python. The analysis engine currently runs explicitly in Azure Cloud Shell; the separate Function-based refresh remains a deployment template, not an operating service.

## Reproduce analysis
python canada_analysis.py --source canada-source.json --base-catalog base-catalog.json --out-dir generated

Use the 224-record base catalogue from commit a70fc22f0c7aac62d64d177f3e175c2c14cfeb41. The engine replaces its Canadian subset with the captured 179 records.

## Deploy ADF
python deploy_canada_adf.py --bundle canada_adf_bundle.json

Requires an already signed-in Azure CLI with existing factory management permission. No new role assignment, secret or account key is included in this bundle. The existing factory managed identity must have Blob Data Contributor on bronze only.
