# Explainable claim risk triage — implementation plan

Status: RT01–RT11 implemented and verified. RT12 release handoff is in progress;
final integration, local deployment and publication are recorded in tracker #47.
This extends the local synthetic demo independently of outstanding M1 live-provider
evaluation. No hosting, provider spending, new agents, or predictive model is required.

GitHub tracker: [#47](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/47).

## Product contract

Risk means **priority for human investigation**, not fraud probability, coverage,
medical necessity, or payment approval. Existing document states remain unchanged;
a READY claim can have HIGH risk. Human data approval does not clear risk flags.

Return LOW, MEDIUM, HIGH, or INSUFFICIENT_DATA with stable reason codes, evidence
field paths, policy version, claim version, assessment time and context time.
Do not display a numeric probability or imply thresholds are clinically validated.

Implemented versioned demo policy `risk-v1`:

| Signal | Behavior |
| --- | --- |
| Missing/unreliable name, provider, service date, amount, or insufficient extraction confidence without human verification | INSUFFICIENT_DATA; list available signals, never default LOW. |
| Billed USD amount > 10,000 and <= 100,000 | MEDIUM; illustrative review threshold. |
| Billed USD amount > 100,000 | HIGH; aligns with the existing high-amount validation flag. |
| Exact document SHA-256 matches another active, non-rejected claim in the same workspace | HIGH; possible duplicate document, not proven duplicate billing. |
| Complete supported data, no triggered rules | LOW under this limited policy; no claim of safety or absence of fraud. |

Non-USD amounts are INSUFFICIENT_DATA until a currency-specific policy exists.
Use Decimal comparisons and a versioned checked-in policy; validate configuration
and never let browsers supply weights, levels or thresholds. Missing-data status
takes precedence over a level, but known signals remain visible. Human verification
can resolve extraction uncertainty; it cannot waive duplicate/high-amount signals.
Exclude fuzzy identity matches, protected demographic features, payer data,
clinical judgments, and population-based amount anomalies from this release.

Duplicate context is a snapshot of eligible committed peers at assessment time.
Do not claim both simultaneous uploads are automatically classified identically.
Expose context time and explicit refresh; earlier assessments are not silently
rewritten when a later claim arrives. Scope every peer query by persisted owner_id,
including unscoped worker sessions. Do not expose peer identities to other owners.

## Milestones and PR sequence

One implementation ticket maps to one focused PR, using multiple small commits
when needed. Branch names below identify the implementation slices. Actual merged PRs are
linked in [the release notes](releases/risk-v1.md). Every PR includes its own relevant tests.

| Milestone | Tickets / proposed PRs | Exit gate | Planning effort |
| --- | --- | --- | --- |
| M2 — Risk contracts and assessment foundation | RT01 policy, RT02 engine, RT03 persistence | Versioned deterministic rules and migrated assessment storage verified | 1–2 days |
| M3 — Processing, correction and duplicate integration | RT04 worker, RT05 reassessment, RT06 duplicates | Atomic/stale-safe assessments on extraction and review, scoped duplicate signals | 2–3 days |
| M4 — Risk API and reviewer experience | RT07 API/acknowledgment, RT08 results UI, RT09 queue | Reviewers can explain, refresh, prioritize and acknowledge assessments | 1–2 days |
| M5 — Verification and local release | RT10 scenarios, RT11 Docker verification, RT12 release | End-to-end regression, persistence/restore and accurate handoff | 1–2 days |

Total planning range: **5–9 focused engineering days**, including review and
integration. Faster implementation may be possible, but the earlier one-day
estimate did not adequately allow for concurrent duplicate context, immutable
reassessment and a separate risk-review workflow. No fixed delivery date is promised.

Sequence: RT01 -> RT02/RT03 -> RT04 -> RT05/RT06 -> RT07 -> RT08/RT09 -> RT10 -> RT11 -> RT12.
Merge dependency PRs before dependent ones; RT02/RT03 and RT08/RT09 are independent
implementation tracks, not instructions to spawn parallel agents.

## Ticket specifications

### RT01 — Specify risk policy and public contracts

Milestone: M2. Proposed PR: `risk/policy-contracts`. Dependencies: none.

- [x] Add `docs/risk.md` and strict `schema/risk.py` contracts for assessments, signals and acknowledgments.
- [x] Freeze policy precedence, exact threshold boundaries, supported inputs and semantics above; define data-version versus context-version behavior.
- [x] Specify API shapes, limits, stable error codes, authorization, lifecycle and compatibility with existing results.
- [x] Document old claims as not assessed (null), not LOW; completed evaluation with inadequate evidence is INSUFFICIENT_DATA.
- [x] Add schema/example checks for all levels, signal evidence, unknown levels and forbidden client-supplied risk fields.

Acceptance: policy is unambiguous, versioned and executable; examples make no fraud
accuracy claims. Existing document review and risk acknowledgment are distinct.

### RT02 — Implement deterministic assessment engine

Milestone: M2. Proposed PR: `risk/rule-engine`. Dependencies: RT01.

- [x] Implement a pure assessment service using normalized ClaimData, validation, confidence/human-verification metadata and explicit context inputs.
- [x] Add validated checked-in `risk-v1` configuration, stable reason codes, deterministic ordering and injectable assessment clock.
- [x] Implement exact Decimal boundaries, insufficiency precedence and visible signals even when classification is incomplete.
- [x] Test threshold equality, missing/invalid data, low confidence, human verification, non-USD, multiple signals and deterministic repeat evaluation.

Acceptance: no database, LLM or network calls inside the engine; repeat inputs and
policy yield identical substantive output; LOW is never an uncomputed fallback.

### RT03 — Add immutable assessment and acknowledgment persistence

Milestone: M2. Proposed PR: `risk/assessment-storage`. Dependencies: RT01.

- [x] Add Alembic migration/models for append-only assessments and reviewer acknowledgments with claim/extraction references, source claim version, policy, input/context fingerprint and timestamps.
- [x] Define unique assessment identity to deduplicate repeated work while allowing explicit refresh when context changes.
- [x] Index latest assessment and queue queries; add ownership-aware service projections without raw patient information in operational logs.
- [x] Test migration upgrade/schema check, valid constraints, transaction rollback, repeated inserts and supported downgrade/data-loss limitations.

Acceptance: assessments survive restart and preserve previous evaluations; an
acknowledgment targets one assessment and never edits its level or evidence.

### RT04 — Integrate assessment with successful worker completion

Milestone: M3. Proposed PR: `risk/worker-integration`. Dependencies: RT02, RT03.

- [x] Identify the successful result-persistence transaction and calculate/persist assessment together with extraction/validation results.
- [x] Preserve lease ownership and stale-worker guards; failed/cancelled work cannot publish risk, and retry does not duplicate assessments.
- [x] Preserve existing READY/REVIEW_REQUIRED state rules; risk is an independent result.
- [x] Cover both synthetic and live processor paths without invoking live providers in tests; add real PostgreSQL atomicity/retry/stale-completion tests.

Acceptance: committed new extraction results have a matching risk assessment;
transaction failure commits neither; all durable-job regression checks still pass.

### RT05 — Reassess corrected data and preserve review history

Milestone: M3. Proposed PR: `risk/review-reassessment`. Dependencies: RT04.

- [x] Extend version-locked review decisions so corrected/accepted data produces a new assessment in the same transaction.
- [x] Preserve extraction and previous risk snapshots; human verification only clears evidence uncertainty, not substantive risk signals.
- [x] Define rejected-claim behavior explicitly: keep assessment history, exclude claim from active risk queue and eligible duplicate peers.
- [x] Add service for explicit refresh using expected claim version, idempotent assessment identity and current policy/context.
- [x] Test stale/conflicting decisions, concurrent refresh/correction, rollback, approval retaining HIGH and correction changing a level.

Acceptance: current data and current assessment versions agree; old acknowledgment
does not acknowledge a new assessment; historical data remains retrievable.

### RT06 — Add workspace-scoped exact duplicate context

Milestone: M3. Proposed PR: `risk/duplicate-context`. Dependencies: RT04, RT05.

- [x] Match exact document SHA-256 across eligible committed peer claims, excluding self, inactive and rejected peers; no fuzzy patient matching.
- [x] Enforce explicit owner predicate for worker and HTTP calls; add query indexes and bounded evidence/projection.
- [x] Persist context fingerprint/time and expose possible duplicate reason without claiming fraud or duplicate billing.
- [x] Document snapshot semantics and refresh after later arrivals/peer rejection; avoid locking patterns that conflict with existing job/review lock order.
- [x] Test same/different owner, rejected/inactive/self peers, concurrent upload/completion, refresh and query-plan/index behavior.

Acceptance: no cross-workspace signal or identity leakage, deterministic snapshot
assessment, and no deadlock in concurrent processing/review tests.

### RT07 — Expose protected risk endpoints and acknowledgments

Milestone: M4. Proposed PR: `risk/api-contracts`. Dependencies: RT05, RT06.

- [x] Extend results with nullable current assessment and bounded history; implement paginated protected assessment history.
- [x] Add CSRF-protected refresh endpoint with expected claim version and bounded request validation.
- [x] Add separate acknowledge endpoint targeting current assessment ID with actor/reason, expected version and replay/stale handling; do not reuse the document approval endpoint.
- [x] Support READY claims with risk flags without enabling arbitrary data edits or automatic payment decisions.
- [x] Test cookie/bearer ownership, 404 isolation, CSRF, stale 409, null legacy results, pagination and safe logs/OpenAPI examples.

Acceptance: users can inspect/refresh/acknowledge risk independently of document
status; clients cannot set levels; acknowledgment leaves computed evidence intact.

### RT08 — Display assessment reasons and review actions

Milestone: M4. Proposed PR: `risk/results-interface`. Dependencies: RT07.

- [x] Add accessible level badge, textual explanation, policy/data/context timestamps and explicit not-assessed/insufficient-data states.
- [x] Display signals via safe DOM operations; clarify illustrative rules and absence of fraud probability.
- [x] Add refresh and reason-required acknowledgment with busy controls, conflict recovery and current-assessment targeting.
- [x] Preserve upload/polling/correction/logout behavior; use text and icons as well as color for levels.
- [x] Add browser checks for LOW/HIGH/INSUFFICIENT_DATA, stale response and version changes after correction.

Acceptance: a reviewer can explain why a claim was flagged and record investigation
without confusing the badge with approval or silently clearing risk.

### RT09 — Add risk queue filtering and prioritization

Milestone: M4. Proposed PR: `risk/reviewer-queue`. Dependencies: RT07.

- [x] Add a separate scoped risk queue rather than changing the existing data-quality review queue.
- [x] Filter by level and current-assessment acknowledgment; exclude rejected/inactive claims and distinguish unassessed legacy rows.
- [x] Use explicit priority HIGH, MEDIUM, INSUFFICIENT_DATA, LOW, then stable timestamp/ID ties; paginate in SQL.
- [x] Show priority/reason summary in the UI and link to results; do not make old acknowledgment hide a new assessment.
- [x] Test stable pagination, owner isolation, filters, new assessment reappearance and READY/HIGH records.

Acceptance: pagination/order is deterministic for an unchanged dataset, SQL queries
are bounded/indexed, and no claim vanishes from ordinary document listings.

### RT10 — Add synthetic risk corpus and end-to-end verification

Milestone: M5. Proposed PR: `risk/scenarios-and-regressions`. Dependencies: RT08, RT09.

- [x] Extend versioned fixture PDFs/manifest with complete LOW, MEDIUM, HIGH, insufficient data and exact duplicate scenarios; retain fixture provenance.
- [x] Add expected rule outputs and source hashes; make date-sensitive scenarios use a controlled clock or documented stable dates.
- [x] Exercise upload -> assessment -> correction/refresh -> acknowledgment -> queue/history in real Chromium/PostgreSQL.
- [x] Add adversarial boundaries, multiple rules, concurrent processing and cross-owner isolation scenarios; preserve all original flows.
- [x] Record scenario correctness as rule conformance, not predictive fraud accuracy; require zero live-provider calls.

Acceptance: every policy branch and integration lifecycle has evidence; malformed
or unsupported inputs cannot silently become LOW; original CI remains green.

### RT11 — Verify Docker migration, restart, backup and restore

Milestone: M5. Proposed PR: `risk/container-verification`. Dependencies: RT10.

- [x] Extend disposable compose verification to migrate existing M1 data and preserve null historical assessment behavior.
- [x] Verify risk/historical acknowledgments persist through API/worker restart and paired DB/upload restore.
- [x] Check interrupted processing/retry leaves no partial or duplicate assessments; document compatible-image and schema rollback limits.
- [x] Publish synthetic verification JSON with exact checks and zero provider calls; remove only test-owned resources.

Acceptance: existing demo data survives upgrade, new risk history survives restore,
and local Docker remains the deployment target with no infrastructure purchases.

### RT12 — Review, integrate and publish the local risk release

Milestone: M5. Proposed PR: `risk/release-handoff`. Dependencies: RT11.

- [x] Review each implementation PR and merge only after relevant checks pass; retain focused commits rather than one large squash.
- [x] Update README/screenshots, API/policy/operator docs and migration/rollback instructions with actual delivered behavior.
- [ ] Run final default-branch CI and deploy locally; publish a versioned local prerelease with synthetic evidence and merged PR links.
- [ ] Close implementation tickets only against satisfied acceptance criteria; update trackers and explicitly retain M1 live-provider evaluation as outstanding.
- [ ] Report final release URL, local launch instructions, verification and limitations; do not claim trained fraud detection or public hosting.

Acceptance: no planned behavior is described as implemented until verified;
reviewer can reproduce all risk scenarios without cloud accounts or fees.

## GitHub execution checklist

### [M2 — Risk contracts and assessment foundation](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/milestone/2)

- [x] [#35 — RT01: Specify risk policy and public contracts](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/35)
- [x] [#36 — RT02: Implement deterministic assessment engine](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/36)
- [x] [#37 — RT03: Add immutable assessment and acknowledgment persistence](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/37)

### [M3 — Processing, correction and duplicate integration](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/milestone/3)

- [x] [#38 — RT04: Integrate assessment with successful worker completion](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/38)
- [x] [#39 — RT05: Reassess corrected data and preserve review history](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/39)
- [x] [#40 — RT06: Add workspace-scoped exact duplicate context](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/40)

### [M4 — Risk API and reviewer experience](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/milestone/4)

- [x] [#41 — RT07: Expose protected risk endpoints and acknowledgments](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/41)
- [x] [#42 — RT08: Display assessment reasons and review actions](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/42)
- [x] [#43 — RT09: Add risk queue filtering and prioritization](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/43)

### [M5 — Risk verification and local release](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/milestone/5)

- [x] [#44 — RT10: Add synthetic risk corpus and end-to-end verification](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/44)
- [x] [#45 — RT11: Verify Docker migration, restart, backup and restore](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/45)
- [ ] [#46 — RT12: Review, integrate and publish the local risk release](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/46)

