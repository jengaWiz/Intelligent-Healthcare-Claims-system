"use strict";
const $ = (id) => document.getElementById(id);
let csrf = null,
  claimId = null,
  documentId = null,
  version = null,
  timer = null,
  busy = false;
let listMode = "recent",
  listOffset = 0;
const terminal = new Set(["READY", "REVIEW_REQUIRED", "FAILED", "REJECTED"]);
function message(text, error = false) {
  $("message").textContent = text;
  $("message").className = error ? "error" : "";
  $("message").hidden = !text;
}
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (options.method && options.method !== "GET" && csrf)
    headers.set("X-CSRF-Token", csrf);
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) signedOut();
    throw new Error(
      `${data.message || "Request failed"} (${data.code || response.status})`,
    );
  }
  return data;
}
function stopPolling() {
  clearTimeout(timer);
  timer = null;
}
function signedOut() {
  stopPolling();
  csrf = null;
  claimId = null;
  documentId = null;
  $("login-panel").hidden = false;
  $("workspace").hidden = true;
  $("logout").hidden = true;
}
function signedIn() {
  $("login-panel").hidden = true;
  $("workspace").hidden = false;
  $("logout").hidden = false;
  show("upload");
}
function show(panel) {
  for (const name of ["upload", "list", "results"])
    $(`${name}-panel`).hidden = name !== panel;
  for (const name of ["upload", "queue", "recent"])
    $(`nav-${name}`).classList.toggle(
      "active",
      name === panel || (panel === "list" && name === listMode),
    );
}
function node(tag, text, className) {
  const el = document.createElement(tag);
  el.textContent = text;
  if (className) el.className = className;
  return el;
}
async function action(button, operation) {
  if (busy) return;
  busy = true;
  button.disabled = true;
  message("");
  try {
    await operation();
  } catch (error) {
    stopPolling();
    message(error.message, true);
  } finally {
    busy = false;
    button.disabled = false;
  }
}
$("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.submitter, async () => {
    const session = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ password: $("password").value }),
    });
    csrf = session.csrf_token;
    $("password").value = "";
    signedIn();
  });
});
$("logout").addEventListener("click", () =>
  action($("logout"), async () => {
    await api("/auth/logout", { method: "POST" });
    signedOut();
  }),
);
$("nav-upload").addEventListener("click", () => {
  stopPolling();
  message("");
  show("upload");
});
for (const name of ["queue", "recent"])
  $(`nav-${name}`).addEventListener("click", () => {
    listMode = name;
    listOffset = 0;
    loadList().catch((e) => message(e.message, true));
  });
async function loadList() {
  stopPolling();
  show("list");
  $("list-title").textContent =
    listMode === "queue" ? "Documents needing your review" : "Your documents";
  const records = await api(
    `${listMode === "queue" ? "/reviews" : "/claims"}?limit=20&offset=${listOffset}`,
  );
  $("claim-list").replaceChildren();
  for (const claim of records) {
    const row = node("div", "", "claim-row");
    const text = node(
      "div",
      `${claim.state.replaceAll("_", " ")} · ${new Date(claim.created_at).toLocaleString()}`,
    );
    text.append(node("p", claim.claim_id, "muted"));
    const button = node("button", "Open →", "quiet");
    button.onclick = () => {
      claimId = claim.claim_id;
      refresh().catch((e) => message(e.message, true));
    };
    row.append(text, button);
    $("claim-list").append(row);
  }
  if (!records.length)
    $("claim-list").append(node("p", "No documents here yet."));
  $("list-prev").disabled = listOffset === 0;
  $("list-next").disabled = records.length < 20;
}
$("list-prev").onclick = () => {
  listOffset = Math.max(0, listOffset - 20);
  loadList().catch((e) => message(e.message, true));
};
$("list-next").onclick = () => {
  listOffset += 20;
  loadList().catch((e) => message(e.message, true));
};
$("upload-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.submitter, async () => {
    stopPolling();
    const claim = await api("/claims", {
      method: "POST",
      body: JSON.stringify({ source_system: "synthetic-demo-ui" }),
    });
    claimId = claim.claim_id;
    const form = new FormData();
    form.append("file", $("file").files[0]);
    const document = await api(`/claims/${claimId}/documents`, {
      method: "POST",
      body: form,
    });
    documentId = document.document_id;
    await enqueue();
  });
});
async function enqueue() {
  await api(`/documents/${documentId}/extract`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
  await refresh();
}
$("retry").onclick = () => action($("retry"), enqueue);
async function refresh() {
  stopPolling();
  const selected = claimId;
  const result = await api(`/claims/${selected}/results`);
  if (selected !== claimId) return;
  show("results");
  version = result.claim.version;
  documentId = result.job ? result.job.document_id : null;
  const state = result.claim.state;
  $("state").textContent = state.replaceAll("_", " ");
  $("state").dataset.state = state;
  $("claim-reference").textContent = `Claim ${claimId} · version ${version}`;
  $("result-title").textContent =
    state === "PROCESSING"
      ? "Extraction in progress"
      : state === "FAILED"
        ? "Processing needs another attempt"
        : state === "REVIEW_REQUIRED"
          ? "A few things need your review"
          : state === "READY"
            ? "Document data is ready"
            : state === "REJECTED"
              ? "Document data was rejected"
              : "Document awaiting upload";
  $("confidence").textContent = result.extraction
    ? `${Math.round(result.extraction.confidence * 100)}% CONFIDENCE`
    : "PENDING";
  $("reasoning").textContent = result.extraction
    ? result.extraction.reasoning
    : result.job
      ? `Attempt ${result.job.attempts} of ${result.job.max_attempts} · ${result.job.state.replaceAll("_", " ")}`
      : "Upload and process a document to see extracted fields.";
  $("retry").hidden = state !== "FAILED" || !documentId;
  $("review-panel").hidden = state !== "REVIEW_REQUIRED";
  $("fields").replaceChildren();
  $("issues").replaceChildren();
  if (result.current) {
    const data = result.current.data;
    const values = [
      ["Patient", data.patient.full_name],
      ["Date of birth", data.patient.date_of_birth],
      ["Provider", data.provider.name],
      ["Service date", data.service.service_date],
      ["Billed amount (USD)", data.billing.total_amount],
    ];
    for (const [label, value] of values) {
      const row = node("div", "");
      row.append(
        node("dt", label),
        node("dd", value === null ? "Missing" : String(value)),
      );
      $("fields").append(row);
    }
    for (const issue of result.current.validation.issues) {
      const item = node("div", "", `issue ${issue.severity}`);
      item.append(
        node("strong", `${issue.severity.toUpperCase()} · ${issue.field}`),
        node("p", issue.description),
      );
      if (issue.suggested_fix) item.append(node("p", issue.suggested_fix));
      $("issues").append(item);
    }
    if (!result.current.validation.issues.length)
      $("issues").append(node("p", "No validation issues found."));
    $("patient-name").value = data.patient.full_name || "";
    $("patient-dob").value = data.patient.date_of_birth || "";
    $("provider-name").value = data.provider.name || "";
    $("service-date").value = data.service.service_date || "";
    $("total-amount").value = data.billing.total_amount || "";
  } else {
    $("fields").append(
      node("p", "Fields will appear after extraction completes."),
    );
    $("issues").append(
      node("p", result.job?.error?.message || "Waiting for quality checks."),
    );
  }
  $("history").replaceChildren();
  for (const review of result.reviews) {
    const item = node("details", "", "audit");
    item.append(
      node(
        "summary",
        `${review.decision.toUpperCase()} · version ${review.previous_version} → ${review.new_version} · ${new Date(review.created_at).toLocaleString()}`,
      ),
      node("p", review.reason),
      node("p", `Actor: ${review.actor_id}`, "muted"),
      node(
        "pre",
        JSON.stringify(
          { before: review.before_data, after: review.after_data },
          null,
          2,
        ),
      ),
    );
    $("history").append(item);
  }
  if (!result.reviews.length)
    $("history").append(node("p", "No human review decisions yet.", "muted"));
  if (!terminal.has(state) && result.job)
    timer = setTimeout(
      () =>
        refresh().catch((e) => {
          stopPolling();
          message(e.message, true);
        }),
      2000,
    );
}
$("decision").onchange = () => {
  const correction = $("decision").value === "correct";
  $("corrections").hidden = !correction;
  for (const id of ["patient-name", "service-date", "total-amount"])
    $(id).required = correction;
};
$("review-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.submitter, async () => {
    const payload = {
      expected_version: version,
      decision: $("decision").value,
      reason: $("reason").value,
    };
    if (payload.decision === "correct")
      payload.corrections = {
        patient_name: $("patient-name").value,
        patient_dob: $("patient-dob").value || null,
        provider_name: $("provider-name").value || null,
        service_date: $("service-date").value,
        total_amount: $("total-amount").value,
      };
    await api(`/claims/${claimId}/reviews`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    $("reason").value = "";
    await refresh();
    message("Review saved. Original extraction evidence is retained.");
  });
});
window.addEventListener("pagehide", stopPolling);
(async () => {
  try {
    const config = await api("/demo/config");
    $("upload-limit").textContent =
      `${Math.round(config.max_upload_bytes / 1048576)} MiB`;
    $("processing-mode").textContent = config.synthetic_mode
      ? "Fixture mode: labeled samples use deterministic synthetic results. Azure/LLM accuracy is not evaluated in this mode."
      : "Live mode: processing uses the server’s configured OCR and language model.";
    const session = await api("/auth/session");
    csrf = session.csrf_token;
    signedIn();
  } catch {
    signedOut();
  }
})();
