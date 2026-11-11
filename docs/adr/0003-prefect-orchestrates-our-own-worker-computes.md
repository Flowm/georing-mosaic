---
status: accepted
---

# Prefect orchestrates, our own worker computes

Flows run in a worker we operate, inside our own Docker image, against a process
work pool. Self-hosted, the Prefect server sits beside it in one compose file;
on Prefect Cloud only the API URL and key change. We rejected Prefect's managed
compute because it caps a run at 4 vCPU and 16 GB, runs only Prefect's official
images (the satellite stack would be installed on every run) and bills by the
minute.

## Consequences

- Prefect Cloud needs a paid plan: the free tier has no work pools on our own
  infrastructure (Starter, USD 100 per month, as of November 2026).
- Nothing may depend on features that exist only on Cloud: incoming webhooks,
  SLAs, managed and push work pools, email and incident actions.
- Prefect's run history is not the record of which Slots are done. Self-hosted
  it grows without limit unless pruned, and Cloud deletes it after days. The
  catalogue beside the products is the record.
