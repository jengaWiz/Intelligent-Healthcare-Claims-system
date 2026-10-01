# Implementation and integration

Work from the [M1 ticket checklist](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/16).
Use a short branch such as `feat/5-claim-api`, `fix/7-provider-errors`, or
`docs/2-workflow-contracts`. Each PR links its ticket, explains resulting behavior,
and reports real checks and migration/configuration/rollback implications.

The default integration branch is `ayaan`. Never push implementation directly to
it. Stack dependent PRs on their prerequisite branches to keep diffs focused;
merge prerequisites first, then rebase/retarget later PRs to `ayaan` and rerun CI.
Squash merges require rebasing stacked branches to avoid replaying prerequisite
commits. Do not merge a dependent PR into a temporary feature branch as a shortcut.

## Required verification

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python scripts/check_docs.py
uv run --locked pytest -m 'not integration' -q
```

CI `setup` verifies locked installation and config boundaries; `quality` checks
formatting, lint, docs, and unit tests; `postgres` upgrades an empty database,
checks metadata drift, runs persistence tests, and rehearses downgrade/re-upgrade.
Provider secrets are never supplied to ordinary CI. Unit tests clear configuration
credentials and block Python socket connections. PostgreSQL tests use a dedicated
service database and synthetic records. For local DB commands, see
[the database guide](docs/database.md).

Live provider checks are separate, explicit opt-in work in ticket #7/#15. Until
that harness is implemented, ordinary CI cannot validate provider-account model
availability or OCR/LLM accuracy. Do not mistake mocked checks for live verification.

## Review and merge

Require `setup`, `quality`, and `postgres` to pass and one approving reviewer.
Dismiss stale approvals after code changes; resolve review discussions. Verify
branch protection in repository settings rather than assuming a documented policy
is enforced. Repository administrators may bypass protection if enforcement for
admins is disabled; they should still follow this review process. A single owner
cannot provide the independent approval on their own PR; use an invited reviewer.
If repository-plan permissions prevent protection, document that limitation in the
tracking issue and perform the same checks/review manually.

Close tickets when their PR merges and acceptance criteria are met, not merely
when a branch is pushed. Deployment is a separate reviewed release step with
synthetic smoke verification, secret handling, backup and rollback evidence.

### Activate protection after CI integration

The repository initially had no protection on `ayaan`. Do not require workflow
checks before their implementation is merged: earlier stacked PRs do not contain
those jobs. Review and integrate the foundation PRs first, verify `setup`,
`quality`, and `postgres` run on `ayaan`, then an authorized administrator applies
[the protection policy](.github/branch-protection.json):

```bash
gh api repos/jengaWiz/Intelligent-Healthcare-Claims-system/branches/ayaan/protection \
  --method PUT --input .github/branch-protection.json
```

Verify the resulting settings and record the outcome in issue #13. That ticket
remains open until the protection step and hosted CI verification are complete.
