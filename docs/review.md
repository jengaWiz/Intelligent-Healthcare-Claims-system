# Human document-data review

`GET /claims/{id}/results` returns a typed claim/job projection, immutable original
extraction/provenance, current document fields/validation, and ordered review history.
Pending and failed claims have `extraction: null` until extraction succeeds.
`GET /reviews?limit=50&offset=0` lists review-required claims; `GET /claims/{id}/reviews`
returns their revisions. These routes require authentication.

`POST /claims/{id}/reviews` accepts `expected_version`, `decision` (`approve`,
`correct`, or `reject`), and a nonempty `reason`. A correction requires a complete
bounded correction object with patient name, optional DOB/provider, service date,
and a positive USD amount of at most two decimal places. Other decisions prohibit
corrections. Use the version returned by the current results response.

The claim row is locked, its version is checked, and the audit revision and final
state commit together. Stale/repeated decisions return 409. Only REVIEW_REQUIRED
claims accept decisions. Approval/correction reruns deterministic required-field,
date, and amount rules; critical findings return 422. No provider is called during
review. Human acceptance explicitly resolves semantic availability and confidence
concerns; warnings remain visible in the audit snapshot. Rejection resolves to
REJECTED. Accepted document data resolves to READY; neither state authorizes
insurance coverage or payment.

Original extraction and validation rows are never overwritten. Every successful
decision retains actor, time, reason, original/current snapshots, and consecutive
versions. Corrections do not trigger re-extraction. No schema migration is needed
for this ticket. Reverting its routes leaves persisted audit data intact.
