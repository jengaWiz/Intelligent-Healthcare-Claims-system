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
let listRequestId = 0;
let riskAssessmentId = null,
  riskClaimId = null,
  riskHistoryOffset = 0;
let documentMetadata = null;
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
    const error = new Error(
      `${data.message || "Request failed"} (${data.code || response.status})`,
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
function stopPolling() {
  clearTimeout(timer);
  timer = null;
}
function signedOut() {
  listRequestId += 1;
  stopPolling();
  csrf = null;
  claimId = null;
  documentId = null;
  documentMetadata = null;
  riskAssessmentId = null;
  riskClaimId = null;
  $("login-panel").hidden = false;
  $("workspace").hidden = true;
  $("logout").hidden = true;
  for (const name of ["upload", "queue", "recent", "risk"])
    $(`nav-${name}`).disabled = true;
}
function signedIn() {
  $("login-panel").hidden = true;
  $("workspace").hidden = false;
  $("logout").hidden = false;
  for (const name of ["upload", "queue", "recent", "risk"])
    $(`nav-${name}`).disabled = false;
  show("upload");
}
function show(panel) {
  const changedPanel = $(`${panel}-panel`).hidden;
  $("page-title").textContent =
    panel === "results"
      ? "Claim review"
      : panel === "list"
        ? {
            recent: "My documents",
            queue: "Data review queue",
            risk: "Risk investigation",
          }[listMode]
        : "New claim";
  for (const name of ["upload", "list", "results"])
    $(`${name}-panel`).hidden = name !== panel;
  for (const name of ["upload", "queue", "recent", "risk"]) {
    const active =
      name === panel ||
      (panel === "list" && name === listMode) ||
      (panel === "results" && name === "recent");
    $(`nav-${name}`).classList.toggle("active", active);
    if (active) $(`nav-${name}`).setAttribute("aria-current", "page");
    else $(`nav-${name}`).removeAttribute("aria-current");
  }
  if (changedPanel) window.scrollTo({ top: 0, behavior: "instant" });
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
  button.setAttribute("aria-busy", "true");
  button.disabled = true;
  $("logout").disabled = true;
  const mutations = document.querySelectorAll(
    "#risk-refresh, #risk-ack-form button, #review-form button, #upload-form button, #retry, .sample-start",
  );
  for (const control of mutations) control.disabled = true;
  message("");
  try {
    await operation();
  } catch (error) {
    stopPolling();
    message(error.message, true);
  } finally {
    busy = false;
    button.removeAttribute("aria-busy");
    button.disabled = false;
    $("logout").disabled = false;
    for (const control of mutations) control.disabled = false;
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
  claimId = null;
  documentId = null;
  stopPolling();
  message("");
  show("upload");
});
for (const name of ["queue", "recent", "risk"])
  $(`nav-${name}`).addEventListener("click", () => {
    listMode = name;
    listOffset = 0;
    loadList().catch((e) => message(e.message, true));
  });
async function loadList() {
  const requestId = ++listRequestId;
  const mode = listMode;
  const offset = listOffset;
  claimId = null;
  documentId = null;
  stopPolling();
  show("list");
  $("list-title").textContent =
    mode === "risk"
      ? "Risk investigation queue"
      : mode === "queue"
        ? "Documents needing your review"
        : "Your documents";
  $("risk-filters").hidden = mode !== "risk";
  const params = new URLSearchParams({ limit: "20", offset: String(offset) });
  if (mode === "risk") {
    if ($("risk-filter-level").value)
      params.set("level", $("risk-filter-level").value);
    params.set("acknowledged", $("risk-filter-ack").value);
  }
  const response = await api(
    `${mode === "risk" ? "/risk/queue" : mode === "queue" ? "/reviews" : "/claims"}?${params}`,
  );
  if (requestId !== listRequestId || claimId !== null || !csrf) return;
  const entries =
    mode === "risk" ? response.items : response.map((claim) => ({ claim }));
  $("claim-list").replaceChildren();
  for (const entry of entries) {
    const claim = entry.claim;
    const row = node("div", "", "claim-row");
    const text = node(
      "div",
      `${claim.state.replaceAll("_", " ")} · ${new Date(claim.created_at).toLocaleString()}`,
    );
    text.append(node("p", claim.claim_id, "muted"));
    if (entry.risk) {
      const badge = node(
        "span",
        entry.risk.level.replaceAll("_", " "),
        "badge",
      );
      badge.dataset.level = entry.risk.level;
      text.append(
        badge,
        node(
          "p",
          entry.acknowledgment ? "Acknowledged" : "Needs acknowledgment",
          "muted",
        ),
      );
      if (entry.risk.signals.length)
        text.append(
          node(
            "p",
            entry.risk.signals
              .map((signal) => signal.message)
              .join(" ")
              .slice(0, 200),
            "muted",
          ),
        );
    }
    const button = node("button", "Open →", "quiet");
    button.onclick = () => {
      claimId = claim.claim_id;
      refresh().catch((e) => message(e.message, true));
    };
    row.append(text, button);
    $("claim-list").append(row);
  }
  if (!entries.length)
    $("claim-list").append(node("p", "No documents here yet."));
  $("list-prev").disabled = listOffset === 0;
  $("list-next").disabled = entries.length < 20;
}
for (const id of ["risk-filter-level", "risk-filter-ack"])
  $(id).onchange = () => {
    listOffset = 0;
    loadList().catch((error) => message(error.message, true));
  };
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
  action(event.submitter, () => processFile($("file").files[0]));
});
async function processFile(file) {
  stopPolling();
  const claim = await api("/claims", {
    method: "POST",
    body: JSON.stringify({ source_system: "synthetic-demo-ui" }),
  });
  claimId = claim.claim_id;
  const form = new FormData();
  form.append("file", file);
  const document = await api(`/claims/${claimId}/documents`, {
    method: "POST",
    body: form,
  });
  documentId = document.document_id;
  documentMetadata = document;
  await enqueue();
}
for (const button of document.querySelectorAll(".sample-start")) {
  button.onclick = () =>
    action(button, async () => {
      const name = button.dataset.sample;
      const response = await fetch(`/samples/${name}.pdf`, {
        credentials: "same-origin",
      });
      if (!response.ok)
        throw new Error("The sample could not be loaded. Please try again.");
      await processFile(
        new File([await response.blob()], `${name}.pdf`, {
          type: "application/pdf",
        }),
      );
    });
}
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
  renderRisk(result);
  $("state").textContent = state.replaceAll("_", " ");
  $("state").dataset.state = state;
  $("claim-reference").textContent = `Claim ${claimId} · version ${version}`;
  $("claim-reference").title = `Claim ${claimId} · version ${version}`;
  $("result-title").textContent =
    state === "PROCESSING"
      ? "Processing document"
      : state === "FAILED"
        ? "Processing needs another attempt"
        : state === "REVIEW_REQUIRED"
          ? "Data review required"
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
  $("review-shortcut").hidden = state !== "REVIEW_REQUIRED";
  $("field-details").replaceChildren();
  $("issues").replaceChildren();
  $("quality-count").textContent = result.current
    ? `${result.current.validation.issues.length} ${result.current.validation.issues.length === 1 ? "issue" : "issues"}`
    : "PENDING";
  if (result.current) {
    const data = result.current.data;
    $("record-patient").textContent =
      data.patient.full_name || "Patient not identified";
    $("record-provider").textContent = data.provider.name
      ? `Provider: ${data.provider.name}`
      : "Provider not identified";
    $("record-currency").textContent =
      `Billed amount (${data.billing.currency})`;
    $("record-total").textContent =
      formatAmount(data.billing.total_amount, data.billing.currency) ||
      "Not extracted";
    const values = [
      ["Date of birth", data.patient.date_of_birth],
      ["Service date", data.service.service_date],
    ];
    for (const [label, value] of values) {
      const row = node("div", "");
      row.append(
        node("dt", label),
        node("dd", value === null ? "Missing" : String(value)),
      );
      $("field-details").append(row);
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
      $("issues").append(
        node(
          "p",
          "All data checks passed. No validation issues found.",
          "validation-clear",
        ),
      );
    $("patient-name").value = data.patient.full_name || "";
    $("patient-dob").value = data.patient.date_of_birth || "";
    $("provider-name").value = data.provider.name || "";
    $("service-date").value = data.service.service_date || "";
    $("total-amount").value = data.billing.total_amount || "";
  } else {
    $("record-patient").textContent = "Awaiting extraction";
    $("record-provider").textContent = "";
    $("record-total").textContent = "—";
    $("record-currency").textContent = "Billed amount";
    $("field-details").append(
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
  await renderDocumentMetadata(selected, documentId);
  if (selected !== claimId || !csrf) return;
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
async function renderDocumentMetadata(selectedClaim, selectedDocument) {
  if (documentMetadata?.document_id !== selectedDocument) {
    $("source-file").textContent = "Stored document";
    $("source-meta").textContent = "";
    if (!selectedDocument) return;
    try {
      const metadata = await api(`/documents/${selectedDocument}`);
      if (selectedClaim !== claimId || selectedDocument !== documentId || !csrf)
        return;
      documentMetadata = metadata;
    } catch {
      if (selectedClaim === claimId && selectedDocument === documentId)
        $("source-meta").textContent = "File details unavailable";
      return;
    }
  }
  if (documentMetadata) {
    $("source-file").textContent = documentMetadata.file_name;
    $("source-meta").textContent =
      `${documentMetadata.mime_type.replace("application/", "").replace("image/", "").toUpperCase()} · ${(documentMetadata.byte_size / 1024).toFixed(1)} KB`;
  }
}
function formatAmount(amount, currency) {
  if (amount === null) return null;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Number(amount));
  } catch {
    return String(amount);
  }
}
function renderRisk(result) {
  const risk = result.risk;
  const newId = risk?.assessment_id || null;
  if (riskClaimId !== result.claim.claim_id || riskAssessmentId !== newId) {
    $("risk-reason").value = "";
    $("risk-history").replaceChildren();
    $("risk-history-navigation").hidden = true;
    riskHistoryOffset = 0;
  }
  riskClaimId = result.claim.claim_id;
  riskAssessmentId = newId;
  $("risk-level").textContent = risk
    ? risk.level.replaceAll("_", " ")
    : "Not assessed";
  $("risk-level").dataset.level = risk?.level || "";
  $("risk-panel").dataset.level = risk?.level || "";
  $("risk-summary").textContent = risk
    ? {
        LOW: "No review signals triggered under this limited policy.",
        MEDIUM: "Review recommended · inspect the signals below.",
        HIGH: "Investigation recommended · inspect the signals below.",
        INSUFFICIENT_DATA:
          "More evidence is needed before risk can be classified.",
      }[risk.level]
    : "Not assessed yet. This does not mean low risk.";
  $("risk-meta").textContent = risk
    ? `${risk.policy_version} · data version ${risk.claim_version} · assessed ${new Date(risk.assessed_at).toLocaleString()} · context captured ${new Date(risk.context_at).toLocaleString()}`
    : "No assessment exists for the current data. This does not mean low risk.";
  $("risk-signals").replaceChildren();
  for (const signal of risk?.signals || []) {
    const row = node("div", "", "issue");
    row.append(
      node(
        "strong",
        signal.code
          .replaceAll("_", " ")
          .replace(/^./, (letter) => letter.toUpperCase()),
      ),
      node("p", signal.message),
      node("p", `Evidence: ${signal.evidence_fields.join(", ")}`, "muted"),
    );
    $("risk-signals").append(row);
  }
  const acknowledgment = result.risk_acknowledgment;
  $("risk-acknowledgment").textContent = acknowledgment
    ? `Investigation acknowledged: ${acknowledgment.reason}. Computed risk is unchanged.`
    : risk
      ? "This assessment has no risk acknowledgment."
      : "No assessment is available to acknowledge.";
  $("risk-ack-meta").hidden = !acknowledgment;
  $("risk-ack-meta").textContent = acknowledgment
    ? `Acknowledged by ${acknowledgment.actor_id} at ${new Date(acknowledgment.created_at).toLocaleString()}`
    : "";
  const editable = ["READY", "REVIEW_REQUIRED"].includes(result.claim.state);
  $("risk-refresh").hidden = !editable || !result.current;
  $("risk-ack-form").hidden = !editable || !risk || !!acknowledgment;
}

async function mutateRisk(suffix, payload, success) {
  const selected = claimId;
  if (riskClaimId !== selected)
    throw new Error("Wait for this document to finish loading.");
  try {
    await api(`/claims/${selected}/risk/${suffix}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (selected !== claimId) return;
    await refresh();
    if (selected === claimId) message(success);
  } catch (error) {
    if (selected !== claimId) return;
    if (error.status === 409 && selected === claimId) await refresh();
    throw error;
  }
}
$("risk-refresh").onclick = () =>
  action($("risk-refresh"), () =>
    mutateRisk(
      "refresh",
      { expected_version: version },
      "Risk refreshed. Previous assessments are retained.",
    ),
  );
$("risk-ack-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.submitter, () =>
    mutateRisk(
      "acknowledgments",
      {
        expected_version: version,
        assessment_id: riskAssessmentId,
        reason: $("risk-reason").value,
      },
      "Risk acknowledgment recorded. Document status and computed risk are unchanged.",
    ),
  );
});
async function loadRiskHistory() {
  const selected = claimId;
  const offset = riskHistoryOffset;
  const assessment = riskAssessmentId;
  const page = await api(`/claims/${selected}/risk?limit=20&offset=${offset}`);
  if (
    selected !== claimId ||
    offset !== riskHistoryOffset ||
    assessment !== riskAssessmentId
  )
    return;
  $("risk-history").replaceChildren();
  for (const item of page.items) {
    const row = node("details", "", "audit");
    row.append(
      node(
        "summary",
        `${item.level.replaceAll("_", " ")} · data version ${item.claim_version} · ${new Date(item.assessed_at).toLocaleString()}`,
      ),
      node("p", `Policy: ${item.policy_version}`),
    );
    for (const signal of item.signals) row.append(node("p", signal.message));
    $("risk-history").append(row);
  }
  if (!page.items.length)
    $("risk-history").append(node("p", "No assessments on this page."));
  $("risk-history-navigation").hidden = false;
  $("risk-history-prev").disabled = riskHistoryOffset === 0;
  $("risk-history-next").disabled = page.items.length < 20;
}
$("risk-history-load").onclick = () =>
  action($("risk-history-load"), loadRiskHistory);
$("risk-history-prev").onclick = () => {
  riskHistoryOffset = Math.max(0, riskHistoryOffset - 20);
  loadRiskHistory().catch((error) => message(error.message, true));
};
$("risk-history-next").onclick = () => {
  riskHistoryOffset += 20;
  loadRiskHistory().catch((error) => message(error.message, true));
};
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
      ? "Synthetic mode. Only the versioned samples are supported; no OCR or LLM calls are made."
      : "Live mode: processing uses the server’s configured OCR and language model.";
    for (const button of document.querySelectorAll(".sample-start"))
      button.hidden = !config.synthetic_mode;
    const session = await api("/auth/session");
    csrf = session.csrf_token;
    signedIn();
  } catch {
    signedOut();
  }
})();
