# Normalization, validation, and processing outcomes

The graph now executes OCR, structured extraction, normalization, deterministic
validation, optional semantic validation, and a data-quality gate. It returns
`READY` or `REVIEW_REQUIRED`. Provider/parse failures raise typed exceptions;
those are not reviewable extraction results. The durable worker in ticket #9
will translate them into persisted retry/failure states.

`READY` requires confidence at or above the configured threshold, no validation
issues, `is_valid=true`, and `semantic_status=completed`. Warnings and informational
issues require review as well as critical issues. Skipped, failed, malformed, or
low-confidence semantic checks cannot silently produce READY. Neither outcome
makes a coverage or payment decision. Legacy ClaimData status values remain for
compatibility; they are not processing outcomes and the pipeline leaves them at DRAFT.

## Canonical values and evidence

Names are trimmed. Dates support ISO, US month/day/year, and day/month/year when
the US format cannot parse; ambiguous slash dates are interpreted as US dates.
Invalid dates become null with an explicit invalid-field issue. Missing patient
name, service date, and amount are critical. Missing provider/DOB produce warnings.
A future service date or DOB on/after service date is critical; dates over two
years old produce a warning. Validation can inject a fixed `today` for reproducible
fixtures; live validation uses the server's calendar date.

M1 supports USD only. Amount parsing accepts finite numeric values, plain decimal
strings, `$`/`USD` prefixes, and correctly grouped commas. Unsupported currency or
invalid formatting becomes null for review. Zero and negative amounts produce a
critical invalid-amount issue; zero is not treated as absent. Numeric LLM JSON
amounts parse directly into Decimal instead of binary floats. Canonical JSON stores
amounts as decimal strings and dates as ISO strings, including exact zero values.

The processing output retains raw extracted fields, normalized ClaimData,
validation issues/recommendations/status, confidence/reasoning, and provenance.
Provenance records provider/model, Azure model/evidence, prompt/schema versions,
and the confidence threshold. Persistence supplies actual claim/document/job IDs.
Original OCR evidence and raw invalid fields remain protected result data, not logs.

## Transaction boundary

`run_extraction_pipeline(path, settings=..., graph=...)` performs provider work
without a database session. Inject a graph or use `build_extraction_graph` with
fake OCR, extraction, and validation clients for deterministic tests.

`persist_processing_result(db, job_id, lease_owner, output)` requires a transaction
owned by the caller. It locks the job, document, and claim, checks active lease
ownership against PostgreSQL time, and verifies processing states and gates.
Result, validation, provenance, document state, claim state/version, and job
completion flush together. The caller commits or rolls everything back. Expired,
foreign, or completed leases cannot publish a result. No provider runs while
these locks are held. No schema migration is needed.

The enqueue endpoint, polling API, lease acquisition/recovery, and worker heartbeat
are still ticket #9; extraction remains unavailable over HTTP until that integration.
This PR provides the processing/persistence functions rather than an in-request
background task. Review APIs and corrected-field validation remain later tickets.
