const question = document.getElementById("q");
const pasted = document.getElementById("pasted");
const askFields = document.getElementById("ask-fields");
const pasteFields = document.getElementById("paste-fields");
const modeAsk = document.getElementById("mode-ask");
const modePaste = document.getElementById("mode-paste");
const button = document.getElementById("go");
const micButton = document.getElementById("mic");
const speakButton = document.getElementById("speak");
const status = document.getElementById("status");
const answer = document.getElementById("answer");
const asked = document.getElementById("asked");
const modelLine = document.getElementById("model-line");
const policyLine = document.getElementById("policy-line");
const finalWrap = document.getElementById("final-wrap");
const finalAnswer = document.getElementById("final-answer");
const correctedWrap = document.getElementById("corrected-wrap");
const corrected = document.getElementById("corrected");
const checksTitle = document.getElementById("checks-title");
const overall = document.getElementById("overall");
const claims = document.getElementById("claims");

let mode = "ask";
let spokenText = "";
let mediaRecorder = null;
let mediaStream = null;
let audioChunks = [];
let audioPlayer = null;

modeAsk.addEventListener("click", () => setMode("ask"));
modePaste.addEventListener("click", () => setMode("paste"));
button.addEventListener("click", run);
speakButton.addEventListener("click", speakCurrentAnswer);
micButton.addEventListener("pointerdown", startRecording);
micButton.addEventListener("pointerup", stopRecording);
micButton.addEventListener("pointerleave", stopRecording);
micButton.addEventListener("pointercancel", stopRecording);

function setMode(next) {
  mode = next;
  const asking = next === "ask";
  modeAsk.classList.toggle("active", asking);
  modePaste.classList.toggle("active", !asking);
  askFields.hidden = !asking;
  pasteFields.hidden = asking;
  button.textContent = asking ? "Ask through Bifrost" : "Check with Tavily";
  micButton.hidden = !asking;
}

function setBusy(busy) {
  button.disabled = busy;
  micButton.disabled = busy;
  if (busy) speakButton.disabled = true;
}

function clearResult() {
  answer.textContent = "";
  asked.textContent = "";
  modelLine.textContent = "";
  policyLine.textContent = "";
  finalAnswer.textContent = "";
  finalWrap.hidden = true;
  corrected.textContent = "";
  correctedWrap.hidden = true;
  overall.textContent = "";
  overall.className = "overall";
  claims.replaceChildren();
  checksTitle.textContent = "Claim checks";
  spokenText = "";
  speakButton.hidden = true;
  stopAudio();
}

async function run() {
  const asking = mode === "ask";
  const text = (asking ? question.value : pasted.value).trim();
  if (!text) {
    status.textContent = asking ? "Enter a question first." : "Paste an answer first.";
    return;
  }

  setBusy(true);
  status.textContent = asking ? "Asking Bifrost, then checking claims…" : "Checking claims with Tavily…";
  clearResult();
  answer.textContent = status.textContent;

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
    answer.textContent = data.answer || text;
    asked.textContent = asking ? `You asked: ${text}` : "Checked the answer you pasted.";
    const groundingNote =
      data.grounding === "google_search"
        ? " · grounded with Google Search"
        : data.grounding === "openai_web_search"
          ? " · live search with OpenAI web_search"
          : data.grounding === "memory_quota"
            ? " · no live search (provider search quota exceeded)"
            : data.grounding === "memory"
              ? " · no live search (memory only)"
              : "";
    modelLine.textContent = data.model ? `Model: ${data.model}${groundingNote}` : "";
    showPolicy(report);
    showCorrection(report.corrected_answer);
    showFinal(report);
    renderOverall(report);
    renderClaims(report.claims || []);
    spokenText = pickSpokenText(data.answer || text, report);
    speakButton.hidden = !spokenText;
    speakButton.disabled = !spokenText;
    const model = data.model ? `Answered by ${data.model}. ` : "";
    const headerScore = response.headers.get("X-Freshgate-Score");
    const headerAction = response.headers.get("X-Freshgate-Action");
    status.textContent = `${model}${headerScore ? `Score ${headerScore}. ` : ""}${headerAction ? `Action ${headerAction}.` : ""}`.trim();
  } catch (error) {
    showError(error.message || "Request failed");
  } finally {
    setBusy(false);
  }
}

function pickSpokenText(rawAnswer, report) {
  if (report.action === "correct" && report.final_answer) return report.final_answer;
  if (report.corrected_answer) return report.corrected_answer;
  return rawAnswer || "";
}

async function startRecording(event) {
  event.preventDefault();
  if (mediaRecorder || micButton.disabled || mode !== "ask") return;
  if (!navigator.mediaDevices?.getUserMedia) {
    status.textContent = "This browser cannot use the microphone.";
    return;
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
    mediaRecorder = new MediaRecorder(mediaStream, mime ? { mimeType: mime } : undefined);
    mediaRecorder.ondataavailable = (part) => {
      if (part.data.size) audioChunks.push(part.data);
    };
    mediaRecorder.onstop = () => {
      finishRecording();
    };
    mediaRecorder.start();
    micButton.classList.add("recording");
    micButton.textContent = "Listening…";
    status.textContent = "Listening. Release to send your question.";
  } catch (error) {
    status.textContent = error.message || "Microphone permission denied.";
    cleanupMic();
  }
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") return;
  mediaRecorder.stop();
}

async function finishRecording() {
  const blob = new Blob(audioChunks, { type: mediaRecorder?.mimeType || "audio/webm" });
  cleanupMic();
  if (!blob.size) {
    status.textContent = "No audio captured. Hold the mic and speak again.";
    return;
  }
  setBusy(true);
  status.textContent = "Transcribing with OpenAI Whisper…";
  try {
    const form = new FormData();
    form.append("file", blob, "speech.webm");
    const response = await fetch("/api/transcribe", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) {
      status.textContent = readError(data);
      return;
    }
    question.value = data.text || "";
    status.textContent = data.text ? "Transcribed. Asking Bifrost…" : "No speech detected.";
    if (data.text) await run();
  } catch (error) {
    status.textContent = error.message || "Transcription failed.";
  } finally {
    setBusy(false);
  }
}

function cleanupMic() {
  if (mediaStream) {
    for (const track of mediaStream.getTracks()) track.stop();
  }
  mediaStream = null;
  mediaRecorder = null;
  audioChunks = [];
  micButton.classList.remove("recording");
  micButton.textContent = "Hold to talk";
}

async function speakCurrentAnswer() {
  const text = spokenText.trim();
  if (!text) return;
  speakButton.disabled = true;
  status.textContent = "Generating speech with OpenAI…";
  try {
    const response = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      status.textContent = readError(data);
      return;
    }
    const blob = await response.blob();
    stopAudio();
    audioPlayer = new Audio(URL.createObjectURL(blob));
    await audioPlayer.play();
    status.textContent = "Playing answer.";
  } catch (error) {
    status.textContent = error.message || "Speech failed.";
  } finally {
    speakButton.disabled = false;
  }
}

function stopAudio() {
  if (!audioPlayer) return;
  audioPlayer.pause();
  if (audioPlayer.src) URL.revokeObjectURL(audioPlayer.src);
  audioPlayer = null;
}

function showPolicy(report) {
  if (!report.action) {
    policyLine.textContent = "";
    return;
  }
  const held = report.held ? " Answer held from clients." : "";
  policyLine.textContent = `Gateway policy ${report.policy} · cutoff ${report.threshold} · action ${report.action}.${held}`;
}

function showFinal(report) {
  if (report.action === "correct" && report.final_answer) {
    finalAnswer.textContent = report.final_answer;
    finalWrap.hidden = false;
    return;
  }
  if (report.action === "hold") {
    finalAnswer.textContent = "Held. Clients do not receive this answer until an operator releases it.";
    finalWrap.hidden = false;
    return;
  }
  finalWrap.hidden = true;
  finalAnswer.textContent = "";
}

function showCorrection(text) {
  if (!text) {
    correctedWrap.hidden = true;
    corrected.textContent = "";
    return;
  }
  corrected.textContent = text;
  correctedWrap.hidden = false;
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
    score.textContent = `${item.freshness}/100 · ${verdictLabel(item)}`;
    card.append(score);

    card.append(kicker("Model sentence"));
    const text = document.createElement("p");
    text.className = "claim";
    text.textContent = item.claim;
    card.append(text);

    if (item.quote) {
      card.append(kicker("Live fact"));
      const quote = document.createElement("p");
      quote.className = "quote";
      quote.textContent = item.quote;
      card.append(quote);
    }

    if (item.correction) {
      card.append(kicker("Correction"));
      const fix = document.createElement("p");
      fix.className = "claim";
      fix.textContent = item.correction;
      card.append(fix);
    }

    const reason = document.createElement("p");
    reason.className = "reason";
    reason.textContent = item.reason || "";
    card.append(reason);

    const sources = (item.sources || []).filter((source) => source?.url).slice(0, 5);
    for (const source of sources) {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.className = "source-link";
      const trust = source.trust != null ? ` · trust ${source.trust}` : "";
      const when = source.published ? ` · ${source.published}` : "";
      link.textContent = `${source.title || source.url}${trust}${when}`;
      card.append(link);
    }

    claims.append(card);
  }
}

function kicker(text) {
  const label = document.createElement("p");
  label.className = "kicker";
  label.textContent = text;
  return label;
}

function verdictLabel(item) {
  if (item.verdict === "agrees") return "supported";
  if (item.verdict === "disagrees") return "disagrees";
  if (item.verdict === "outdated") return "source too old";
  if (item.likely_stale) return "not confirmed";
  return "looks fresh";
}

function showError(message) {
  status.textContent = "";
  clearResult();
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
