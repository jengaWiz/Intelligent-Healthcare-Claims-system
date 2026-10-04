# Browser demo

**Risk queue** is separate from the document-quality Review queue. Its default
view shows assessments needing acknowledgment; filter by level or select all /
acknowledged assessments. HIGH appears before MEDIUM, INSUFFICIENT_DATA and LOW.
Rejected, inactive and unassessed claims are excluded, but ordinary My documents
remains available. Open a row to investigate its evidence and history.

Results include **Risk review priority** independently of document status. Read
the level, static reasons and policy/data/context timestamps. Not assessed does
not mean LOW; INSUFFICIENT_DATA means evaluation needs more evidence. HIGH is a
rule-based investigation priority, not a fraud probability.

Use **Refresh risk assessment** to capture changed peer context, or enter a reason
and **Record risk acknowledgment** to document investigation. This does not clear
computed risk or approve document data. A new assessment requires its own
acknowledgment. **Show assessment history** loads 20 records per page. Stale
mutation conflicts refresh the current result before displaying the error.

Open `/demo` at the exact PUBLIC_ORIGIN and sign in with the server-configured
DEMO_PASSWORD. The browser receives an opaque session and CSRF token, never
operator/provider credentials. Keep that session to revisit **My documents**.
A fresh login creates a new private workspace; signing out revokes access.

1. Select **Try** beside a labeled sample in synthetic mode, or download a sample
   and use the file picker. One-click samples are hidden in live mode.
2. The API creates the claim/document and enqueues the same processing workflow.
3. Follow status polling. Polling stops on success, review-required, rejection,
   failure, sign-out, navigation away, or a request error.
4. Inspect extracted fields, model-reported confidence, quality issues, and reasoning.
5. For review-required records, accept, correct and accept, or reject document data.
   Supply a reason. A correction reruns deterministic rules; version conflicts
   require reopening the current record. Original evidence remains unchanged.
6. Open review history to inspect the actor, timestamps, versions, and before/after
   snapshots. A failed job offers an explicit fresh retry.

Fixture mode (`SYNTHETIC_MODE=true`) accepts only byte-identical versioned samples
from `samples/manifest.json`. It does not call Azure or an LLM. Complete, missing
amount/low-confidence, and permanent provider-failure scenarios are labeled.
Live mode (`false`, default outside compose) uses the configured providers; its
actual behavior is not claimed by fixture checks. Synthetic date validation uses the manifest reference date recorded in provenance;
live processing uses the actual date.

The interface uses plain HTML/CSS/JavaScript served by FastAPI, bounded forms,
keyboard-accessible controls, visible loading/failed states, and textContent for
untrusted output. CSP permits only same-origin assets and forbids framing.

## Review workspace layout

The document summary shows processing state and links directly to the data review
when a decision is needed. Desktop results use a case-file layout: stored filename,
patient, provider, amount, dates, validation and audit evidence on the left; the
data decision and independent risk investigation on the right. Mobile stacks those sections and keeps all four navigation choices visible.
File details come from the existing protected document metadata API; filenames
are rendered as text and stale responses cannot replace another selected case.
Amounts use currency formatting for display; stored values and review inputs retain
exact decimal semantics. Policy timestamps and acknowledgment actor details remain
available under **Policy & assessment details**. Raw before/after audit snapshots
use a bounded scroll area so opening evidence does not overwhelm the workspace.

Keyboard focus is visible, active navigation uses `aria-current`, busy submissions
use `aria-busy`, and signed-out workspace controls are disabled. Screenshots are
captured at a consistent 1440px desktop width with the page at the top.

## Browser verification

With a dedicated migrated TEST_DATABASE_URL:

```bash
npm ci --prefix tests/browser
npm exec --prefix tests/browser -- playwright install chromium
uv run --locked python -m scripts.check_browser
```

The launcher starts separate API and worker processes on loopback port 8047 and
runs five Chromium workflows covering login, upload, complete results,
correction/audit, rejection, failure/retry, scoped duplicates, risk investigation,
and logout. The mobile workflow checks one-click samples, real file metadata,
investigation/acknowledgment, data approval,
queue navigation, and horizontal overflow at 390px. Its dedicated test DB must
not contain real/user data. A separate scenario delays a metadata response while
switching cases and verifies the selected filename/amount remain correct.
The launcher removes demo smoke records and session rows after completion.
Screenshots show this actual fixture flow, not a proposed interface:

![Results](screenshots/results.png)
![Review audit](screenshots/review.png)

The [UI design notes](ui-design.md) record the reference products and visual decisions.
