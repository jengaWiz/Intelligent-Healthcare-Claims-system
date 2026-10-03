# Explainable risk triage contract

Status: policy, schemas and persistence implemented; worker integration and HTTP
routes are delivered by later tickets. See the [implementation plan](risk-triage-plan.md).

Risk is priority for human investigation, not fraud probability, coverage,
medical necessity or payment approval. It is independent of document status:
READY can be HIGH. Document approval never acknowledges or waives risk.

## Versioned policy: risk-v1

Require nonblank patient and provider names, valid service date, positive finite
USD amount, no critical validation issues, and verified extraction evidence.
Without human verification, confidence must meet the configured extraction gate
and semantic validation must have completed. Human review resolves those two
uncertainties only; missing/invalid data and substantive signals still apply.

| Input | Result / stable reason code |
| --- | --- |
| Missing patient/provider/date/amount | INSUFFICIENT_DATA / missing_patient_name, missing_provider_name, missing_service_date, missing_amount |
| Nonpositive amount or critical validation issue | INSUFFICIENT_DATA / invalid_data |
| Missing or below-gate confidence, without human verification | INSUFFICIENT_DATA / unverified_extraction |
| Semantic check unavailable, without human verification | INSUFFICIENT_DATA / unverified_semantics |
| Currency other than USD | INSUFFICIENT_DATA / unsupported_currency; no USD amount rule applied |
| USD amount > 10,000 and <= 100,000 | MEDIUM / amount_medium |
| USD amount > 100,000 | HIGH / amount_high |
| Eligible exact-document peer | HIGH / possible_duplicate_document |
| Complete evidence with no triggered rule | LOW under this limited policy |

These thresholds are illustrative portfolio rules, not calibrated against real
claim outcomes. Use Decimal; exactly 10,000 triggers no amount rule and exactly
100,000 triggers MEDIUM. Missing-data reasons take precedence over a level,
but preserve other known signals. Reasons have deterministic code ordering and
bounded, static messages and evidence paths; never include patient values.

An exact duplicate is another active, non-rejected claim with matching document
SHA-256 and the same persisted owner_id. It is a possible repeated document, not
proof of duplicate billing. Workers must explicitly scope peer queries even when
their database session is unscoped. Exclude self; expose no peer identity.
Duplicate context is a committed snapshot, not a continuously updated guarantee.
Concurrent completions may see different snapshots. Refresh captures new context;
earlier assessments are never silently overwritten.

## Identity and lifecycle

An assessment records claim/extraction IDs, source claim version, policy version,
input/context fingerprints, level, reasons, assessment time and context time.
Use UTC timezone-aware timestamps. Fingerprints are internal deterministic hashes;
never hash low-entropy patient data for public display or log it. Public evidence
contains field paths and static explanations, not raw input snapshots.

Source claim version identifies the corrected data; context fingerprint identifies
eligible peer context. A refresh does not increment document claim version.
Identical current claim version, extraction, policy and input/context identity
reuses the current assessment, including its original timestamps; changed context
creates a new one. Returning to a historical context also creates a new revision,
so an old acknowledgment never becomes current again merely through deduplication.
Policy updates require a new version. Store history append-only. Original data
and old acknowledgments remain intact after correction. Acknowledgment targets one
current assessment; it does not change the level and does not transfer to a new
assessment. Rejected/inactive claims retain history but leave active risk queues.

Historical claims have `risk: null` until explicitly assessed. In-flight/failed
extraction without a result is also null, not LOW or INSUFFICIENT_DATA. The latter
means evaluation ran and found insufficient evidence. Legacy upgrade performs no
automatic LOW backfill. Assessment publication is atomic with successful extraction
or data review; stale workers cannot publish assessments.

## Planned HTTP API

These routes are contracts for RT07, not currently registered endpoints.

| Route | Request / response |
| --- | --- |
| GET /claims/{id}/results | Add nullable current `risk` and current `risk_acknowledgment`; retain existing data/state semantics. |
| GET /claims/{id}/risk | RiskHistoryResponse; newest first, stable ID tie; limit 1–100 (default 20), offset >= 0. |
| POST /claims/{id}/risk/refresh | RiskRefreshCreate -> current RiskAssessmentResponse; expected_version required. |
| POST /claims/{id}/risk/acknowledgments | RiskAcknowledgmentCreate -> RiskAcknowledgmentResponse; trimmed reason 1–2000 chars, current assessment ID and expected_version required. |
| GET /risk/queue | Scoped, paginated active latest assessments; level and acknowledged filters; HIGH, MEDIUM, INSUFFICIENT_DATA, LOW ordering. |

All routes require existing cookie or operator authentication and ownership; return
404 `claim_not_found` for another workspace. Cookie mutations require exact Origin
and CSRF. Reject client-supplied risk level, policy, evidence or actor (422).
No-risk-source refresh returns 409 `risk_source_unavailable`; mismatched version
returns 409 `stale_risk`; obsolete acknowledgment ID returns 409 `stale_assessment`.
Rejected/inactive mutation returns 409 `risk_inactive`. Serializing refresh/ack
against claim locking prevents committing an acknowledgment to an obsolete
assessment. Repeat acknowledgment for the same assessment/actor/reason reuses it;
different reason returns 409 `risk_already_acknowledged` rather than rewriting it.
Existing request/body limits and safe error logging apply. History is paginated,
not embedded unbounded in results. See [access boundaries](access.md).

## Storage and migration

Migration `a1fb3ff0cf40` adds assessments/acknowledgments and composite source
constraints without rewriting M1 claims. An assessment's claim, document and
extraction must refer to the same source. Claim locking assigns monotonically
increasing revisions; unique (claim_id, revision) enforces their identity.
PostgreSQL triggers reject updates to both history tables. Deleting a source claim
still cascades to its history for explicit retention/reset; immutability does not
mean unlimited retention. Public service reads enforce ownership and paginate.

Downgrading drops risk history and acknowledgments but retains M1 claims/documents.
Use paired backup and a compatible binary for rollback; it is not a lossless risk
rollback. No historical assessment is backfilled. The SQL immutability triggers
are PostgreSQL features; SQLite test metadata is not a deployment substitute.
