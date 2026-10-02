# OCR and extraction adapters

The pinned Azure Document Intelligence SDK is 1.0.2, using API `2024-11-30`.
The adapter uploads binary content through `begin_analyze_document(model_id,
body=stream, content_type="application/octet-stream")`. The configurable default
is `prebuilt-layout` with the `keyValuePairs` feature; other configured models do
not automatically receive this layout-specific feature. Account/model availability
requires a live check. See Microsoft's [SDK examples](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-documentintelligence-readme?view=azure-python)
and [model features](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept/add-on-capabilities?view=doc-intel-4.0.0).

Inject an Azure client with `extract_document_from_azure(path, settings=..., client=...)`
or an LLM client with `ExtractionAgent(settings=..., client=...)`. Injected clients
belong to the caller. The OCR adapter closes its own client; graph nodes close
owned LLM clients through `agent.close()`. Construction/imports do not require keys.

OCR returns raw text, convenient key-value/table projections, and the full SDK
`as_dict()` evidence, including available word/field confidence, spans, and
locations. It supplies no invented overall OCR confidence. Evidence may contain
synthetic document text and must remain protected alongside extracted results.
LLM confidence is self-reported, finite, numeric, and bounded to [0,1]; it is not
calibrated accuracy. Low confidence is valid extraction data for later review.

The LLM contract requires every field explicitly, using null for unknown values,
a bounded nonempty reasoning string, and complete JSON. It rejects malformed or
truncated JSON, duplicate/unknown fields, missing fields, and invalid confidence.
The adapter preserves raw date/amount values; the [processing pipeline](processing.md) then normalizes them. Numeric JSON amounts parse as Decimal and serialize as decimal strings. Text input is
bounded to 200,000 characters; output is bounded to 32,768 characters and 2,048
provider output tokens. Larger inputs fail safely rather than silently truncate.
Text content blocks are supported; reasoning blocks are excluded from JSON parsing.

## Failures and retry ownership

Adapters raise `ProviderFailure`, never a fallback success dictionary. Its safe
fields are `stage`, `code`, `retryable`, and optional `retry_after`; provider error
messages, response bodies, credentials, and document text are not included or
chained into the outward traceback. The graph propagates these failures instead
of routing them into approval or review. The [durable worker](jobs.md) persists retry/failure outcomes.

Timeouts, connection failures, 429, and selected 5xx failures are retryable.
Authentication/request rejection, missing configuration, empty OCR/input, and
invalid structured output are permanent. Numeric Retry-After seconds are capped
at 60; invalid/nonfinite values are ignored. Adapters attempt each call once;
SDK retries are disabled. The durable worker owns the persisted attempt budget
and backoff, avoiding multiplied retries across libraries.

`PROVIDER_TIMEOUT_SECONDS` configures LLM request timeouts and an Azure polling
deadline. Poll sleeps, including Retry-After, stop at that deadline; each status
request gets connection/read timeouts from the remaining budget. The adapter waits
for its polling thread to finish rather than leaving a default indefinite poller
behind. HTTP timeouts are transport connection/read inactivity limits: a slow
streaming response can exceed elapsed time, so this is not an OS-enforced wall-clock
kill. A hard process deadline is outside this adapter's guarantee.

## Explicit synthetic live smoke

Ordinary tests block network access and use deterministic clients. A real pinned
Azure SDK/fake transport contract test verifies the serialized HTTP request and
polling. Google request construction verifies timeout and zero retry settings.
Mocked tests establish boundaries, not provider availability or extraction accuracy.

Set Azure credentials and `AZURE_DOCUMENT_MODEL` in your local environment. For
LLM checks also set `LLM_PROVIDER`, an account-supported `LLM_MODEL`, and its key.
Then explicitly opt into potentially billable calls:

```bash
uv run --locked python -m scripts.smoke_providers --live
uv run --locked python -m scripts.smoke_providers --live --with-llm
```

The script creates a valid PDF containing only fixed synthetic claim details,
removes it afterward, and prints SDK versions, configured model IDs, API version,
and pass/failure codes. It suppresses SDK logs and prints neither credentials nor
OCR/extracted content. It accepts no user document path and performs no database
writes. Success establishes provider access and response contract compatibility;
it does not evaluate accuracy. Live smoke has not been run as part of this PR.
