---
type: llm
---

The brief was written from this context only:

Context from this session: the nightly invoice export job started timing out on Tuesday. It runs as a Cloud Run job with a 10 minute limit. One customer has 40,000 invoices, and the export loads them all into memory before it writes the CSV. I added pagination (5,000 rows per page) and the job passed last night in 4 minutes. Separately, someone raised the job's memory from 512 MiB to 2 GiB on Monday, and nobody knows why. Options: ship pagination as is; also revert the memory change; or rewrite the export to stream rows, which is about two days of work. Finance needs the export reliable by month end, in 9 days. I have not checked whether other jobs share the same loader.

PASS if every factual claim in the brief is supported by that context, and the brief does not claim to know whether other jobs share the loader or why the memory was raised. Calling those two unknown, or leaving them out, both pass. Judgements that read as the writer's view, such as a recommendation or 'streaming is not needed to meet month end', are allowed.
FAIL if the brief states as fact something the context does not support, states that other jobs do or do not share the loader, or states why the memory was raised.
