# Demo access and retention

Only synthetic document data belongs in this demo. `/health/live`, the login
screen, static UI assets, synthetic samples, and API schema are intentionally public.
All claim/document/job/result/review operations and readiness require authentication.

The operator bearer token owns the `api` workspace, including legacy claims. It
cannot access browser workspaces. A successful password login creates a new,
isolated workspace identified by a random server-generated actor ID. Browser
sessions use random opaque HttpOnly/SameSite=Strict cookies; only SHA-256 hashes
are persisted. Sessions expire after eight hours by default. Signing out revokes
that session immediately. A fresh login starts a fresh workspace; this demo does
not offer accounts or workspace recovery. This boundary suits guided synthetic
review sessions, not a multi-user production identity system.

Set DEMO_PASSWORD server-side and PUBLIC_ORIGIN to the browser's exact origin.
Mutations require that Origin and the X-CSRF-Token obtained from /auth/session.
API_AUTH_TOKEN is for operator scripts only; frontend assets contain neither this
token nor provider keys. Set SESSION_SECURE=false only for local loopback HTTP;
HTTPS must use secure cookies. Login permits ten attempts per client/minute per
API process; it does not trust forwarded client headers. Other JSON requests are
bounded to 64 KiB; file uploads retain their independent limit. CORS uses only
explicit configured origins. Denied preflights cannot enable cross-origin reads;
browser mutations additionally require the exact public origin and CSRF token.

Request logs use server-generated request IDs, route templates, status and elapsed
time; worker logs use job IDs, attempts and safe failure codes. Never log request
bodies, authorization headers, document fields, raw exception strings, or query
strings. Run uvicorn with --no-access-log to avoid its unfiltered URL logger.

Synthetic files and claims persist until the operator purges them. A local demo
can be reset by stopping the compose project and explicitly removing its named
volumes; this is destructive and should only be done after retaining any desired
synthetic audit evidence. Expired session rows are pruned on login; ownership
records remain until retention cleanup. Upload reconciliation is documented in
[uploads.md](uploads.md).

Migration b61ceaf00211 backfills existing claims to the operator workspace and
adds browser sessions. Before downgrade, stop API/worker and preserve a backup;
downgrading removes ownership isolation and invalidates browser sessions. Do not
serve the old binary on a public network after this downgrade.
