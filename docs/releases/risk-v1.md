# Risk v1 local synthetic release

## Delivered behavior

Successful extractions receive explainable LOW, MEDIUM, HIGH, or
INSUFFICIENT_DATA review-priority assessments. Reviewers can inspect rule reasons
and assessment history, refresh duplicate context, filter a prioritized queue,
and acknowledge the current assessment with a reason. Corrections publish a new
assessment atomically with the review. Original extraction and risk evidence remain
intact, and an old acknowledgment does not acknowledge a new assessment.

Risk is independent of document readiness: READY/HIGH is valid. The policy uses
illustrative USD thresholds and exact-document duplicate signals within one owner
workspace. It does not estimate fraud probability or authorize coverage/payment.
LOW is limited to this policy; insufficient evidence never silently becomes LOW.

The deployment remains **local Docker only, with no hosting cost**. Synthetic mode
requires no Azure/LLM account and makes zero provider calls. No public HTTPS target
or paid infrastructure is provisioned.

## Integrated changes

| PR | Behavior |
| --- | --- |
| [#49](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/49) | Versioned policy semantics and strict public contracts. |
| [#50](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/50) | Pure deterministic assessment engine and boundary checks. |
| [#51](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/51) | Immutable assessment/acknowledgment storage and serialized revisions. |
| [#52](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/52) | Atomic worker publication and final lease-deadline protection. |
| [#53](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/53) | Correction reassessment, explicit refresh, preserved history. |
| [#54](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/54) | Owner-scoped duplicate snapshots and supporting index. |
| [#55](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/55) | Protected risk APIs, independent acknowledgment, queue service. |
| [#56](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/56) | Accessible explanations, refresh, acknowledgment, conflict recovery. |
| [#57](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/57) | Filtered risk queue with SQL priority/pagination. |
| [#58](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/58) | Versioned synthetic scenarios, reproducible date validation, browser regressions. |
| [#59](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/59) | Populated M1 upgrade, Docker restart/restore evidence, actual backup schema metadata. |
| [#60](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/pull/60) | Version 0.2.0, recruiter README/screenshots, and release handoff. |

Each focused PR retains small commits and must pass CI before integration.
[Tracker #47](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/47)
records the completed milestones and final publication/deployment status.

## Configuration and migration

Application version: **0.2.0**. Policy: **risk-v1**. Corpus: **risk-corpus-1**,
with synthetic reference date **2026-10-03** recorded in provenance. Live processing
continues to validate against the actual date. Policy thresholds are versioned in
[config/risk-v1.json](../../config/risk-v1.json); clients cannot supply levels or rules.

Required migration head: **968da3f6918e**, after risk-table revision
**a1fb3ff0cf40** and M1 baseline **b61ceaf00211**. Compose defaults to the local
`claims-demo:risk-v1` image and gates API/worker startup on migration and upload
reconciliation. Existing private credentials and persistent volumes are retained.

There is no automatic risk backfill. Existing eligible M1 results remain unassessed
until explicitly refreshed. New successful processing and review decisions create
assessments transactionally. Duplicate context reflects committed peers at the
recorded time; later arrivals require refresh to change an earlier snapshot.

## Verification

- **303 Python tests passed** against isolated PostgreSQL, including stale leases,
  atomic rollback, concurrency, owner isolation, immutable history, acknowledgment
  replay/conflicts, rule boundaries, and a populated M1 migration.
- **Three Chromium workflows passed**: original document/review/retry behavior,
  all risk scenarios with duplicate refresh/queue priority, and HIGH acknowledgment,
  history, correction, and stale-conflict recovery. Screenshots use synthetic data.
- [Docker evidence](../verification/compose.json): **11 checks** cover controlled
  startup, populated M1 upgrade, processing/review/retry, queued work recovery,
  persisted risk/acknowledgment, seven upload byte hashes, six assessment rows,
  paired backup/restore, and retained compatible-image redeployment.
- [Rule conformance](../verification/risk.json): all six declared scenarios match
  expected behavior, including failed processing with no assessment. Duplicate
  fixture context is declared; real database context is tested separately.
- Hosted CI checks lint/docs/unit tests, PostgreSQL migrations/integration,
  Chromium, containers, and secret scanning. Final results are linked in the release.

These checks are software/rule verification, not predictive accuracy or a provider
latency benchmark. The [live configuration report](../verification/live-providers.json)
records sample size zero; no live Azure/LLM evaluation was performed.

## Operation and rollback

Use the [deployment runbook](../deployment.md) for local startup, private credentials,
paired backups, fresh-project restore, and compatible-image redeployment. Record
immutable image IDs and the integrated source SHA in the GitHub release.
Keep the pre-upgrade database and upload archive together outside the repository.
Backup manifests record the actual schema revision.

Downgrading the risk migration removes assessment/acknowledgment history. A rollback
across that boundary requires the matching pre-upgrade backup and application.
The Docker image rehearsal redeploys a retained image of the same compatible
release; it does not prove that pre-risk binaries maintain risk audit semantics.

## Remaining scope

Rules are illustrative and require domain validation before real claims use.
No trained model, fuzzy identity matching, payer integration, medical judgment,
public hosting, or production compliance is included. Existing M1 live-provider
verification tickets [#15](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/15)
and [#16](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/16)
remain open separately; this release does not waive them.
