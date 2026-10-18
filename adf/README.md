# Azure Data Factory artifacts

Import `pipeline_globalx_ingest.json` into the `adf` Git folder of the Data Factory. Create a linked service named `ls_globalx_function` of type **Azure Function**, pointing to the Function App and its key. Keep the key in Key Vault or the linked-service secure value; never commit it here.

The pipeline is a single orchestration step: ADF invokes the HTTP-triggered Function, which fetches the six official pages and writes immutable HTML snapshots and a JSONL manifest to the bronze container. Add a daily schedule trigger after validating the first manual run. Data is partitioned by ingestion date.
