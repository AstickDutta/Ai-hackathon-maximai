const question = document.getElementById("q");
const pasted = document.getElementById("pasted");
const askFields = document.getElementById("ask-fields");
const pasteFields = document.getElementById("paste-fields");
const modeAsk = document.getElementById("mode-ask");
const modePaste = document.getElementById("mode-paste");
const button = document.getElementById("go");
const status = document.getElementById("status");
const answer = document.getElementById("answer");
const overall = document.getElementById("overall");
const claims = document.getElementById("claims");

let mode = "ask";

modeAsk.addEventListener("click", () => setMode("ask"));
modePaste.addEventListener("click", () => setMode("paste"));
button.addEventListener("click", run);

function setMode(next) {
  mode = next;
  const asking = next === "ask";
  modeAsk.classList.toggle("active", asking);
  modePaste.classList.toggle("active", !asking);
  askFields.hidden = !asking;
  pasteFields.hidden = asking;
  button.textContent = asking ? "Ask through Bifrost" : "Check with Tavily";
}

async function run() {
  const asking = mode === "ask";
  const text = (asking ? question.value : pasted.value).trim();
  if (!text) {
    status.textContent = asking ? "Enter a question first." : "Paste an answer first.";
    return;
  }

  button.disabled = true;
  status.textContent = asking ? "Asking Bifrost, then checking claims…" : "Checking claims with Tavily…";
  answer.textContent = "";
  overall.textContent = "";
  claims.replaceChildren();

  try {
    const response = await fetch(asking ? "/v1/chat" : "/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(asking ? { message: text } : { answer: text }),
    });
    const data = await response.json();
    if (!response.ok) {
      showError(readError(data));
      return;
    }
    const report = data.freshness || data;
    answer.textContent = data.answer || (asking ? "" : text);
    renderOverall(report);
    renderClaims(report.claims || []);
    const model = data.model ? `Answered by ${data.model}. ` : "";
    const headerScore = response.headers.get("X-Freshgate-Score");
    status.textContent = headerScore ? `${model}Gateway score header: ${headerScore}` : model;
  } catch (error) {
    showError(error.message || "Request failed");
  } finally {
    button.disabled = false;
  }
}

function renderOverall(report) {
  if (report.overall_freshness == null) {
    overall.textContent = "";
    return;
  }
  const stale = report.flagged_count > 0;
  overall.className = `overall ${stale ? "bad" : "ok"}`;
  overall.textContent = `Lowest claim score ${report.overall_freshness}/100 · ${report.flagged_count} flagged`;
}

function renderClaims(items) {
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No time-sensitive claims were found in this answer.";
    claims.append(empty);
    return;
  }

  for (const item of items) {
    const card = document.createElement("article");
    card.className = "card";

    const score = document.createElement("p");
    score.className = `score ${item.likely_stale ? "bad" : "ok"}`;
    const mark = item.likely_stale ? "likely stale" : "looks fresh";
    score.textContent = `${item.freshness}/100 · ${mark}`;

    const text = document.createElement("p");
    text.className = "claim";
    text.textContent = item.claim;

    const reason = document.createElement("p");
    reason.className = "reason";
    reason.textContent = item.reason || "";

    card.append(score, text, reason);

    const source = item.sources?.[0];
    if (source?.url) {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = source.title || source.url;
      card.append(link);
    }

    claims.append(card);
  }
}

function showError(message) {
  status.textContent = "";
  answer.textContent = "";
  overall.textContent = "";
  const error = document.createElement("p");
  error.className = "error";
  error.textContent = message;
  claims.replaceChildren(error);
}

function readError(data) {
  if (typeof data.detail === "string") return data.detail;
  if (data.detail) return JSON.stringify(data.detail);
  return "Request failed";
}
