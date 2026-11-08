import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

from tavily import TavilyClient

from app.config import settings
from app.services.bifrost import BifrostError, ask

TRUSTED_HOST_SUFFIXES = (
    ".gov",
    ".gov.uk",
    ".europa.eu",
    "usa.gov",
    "whitehouse.gov",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "nytimes.com",
    "wsj.com",
    "bloomberg.com",
    "ft.com",
    "theguardian.com",
    "npr.org",
    "wikipedia.org",
    "openai.com",
    "microsoft.com",
    "apple.com",
    "google.com",
    "alphabet.com",
)
LOW_TRUST_HOSTS = (
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "quora.com",
    "www.quora.com",
    "medium.com",
    "www.medium.com",
    "blogspot.com",
    "wordpress.com",
    "tumblr.com",
    "pinterest.com",
    "tiktok.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
)
EXCLUDE_DOMAINS = (
    "reddit.com",
    "quora.com",
    "medium.com",
    "pinterest.com",
    "tiktok.com",
)

STALE_HINT = re.compile(
    r"\b(ceo|cto|founder|president|price|pricing|costs?|\$\d|version|v\d|api|law|act|regulation|acquired|hired|launch|released|as of|currently|today|stepped down)\b",
    re.I,
)
LEADERSHIP = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z.'-]+){0,3})\s+is the current (CEO|president|prime minister) of\s+([A-Z0-9][A-Za-z0-9&.\- ]{1,40})",
    re.I,
)
ROLE_WORD = re.compile(r"\b(CEO|president|prime minister)\b", re.I)
PRICE_AMOUNT = re.compile(r"\$\s?(\d+(?:\.\d+)?)")
PER_TOKEN = re.compile(r"per\s+token\b", re.I)
PER_MILLION = re.compile(r"per\s+million|/\s*1\s*m|per\s+1m|per\s+1,000,000", re.I)
LAW_NEGATIVE = re.compile(
    r"\b(only a proposal|still only|has not been adopted|not been passed|not yet law|still a draft|has not entered)\b",
    re.I,
)
LAW_POSITIVE = re.compile(
    r"\b(entered into force|in force|was adopted|has been adopted|enacted|became law|regulation)\b",
    re.I,
)
FORMER = re.compile(
    r"\b(former|previously|no longer|stepped down|used to be|was the|ex-)\b",
    re.I,
)
CURRENT = re.compile(r"\b(current|currently|is the|serves as)\b", re.I)
EXTRACT_SYSTEM = (
    "Extract factual claims that can go stale: who holds a role, prices, "
    "product or API versions, laws, and dated company facts. "
    "Copy each claim as one sentence from the answer. "
    'Return JSON only, no markdown: {"claims": ["sentence", "sentence"]}. '
    'At most 4 claims. If none, return {"claims": []}.'
)


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def extract_claims(answer: str) -> list[str]:
    claims = []
    for chunk in re.split(r"(?<=[.!?])\s+|\n+", answer):
        text = chunk.strip(" -\t")
        if len(text) < 20:
            continue
        if STALE_HINT.search(text):
            claims.append(text)
    return claims[:4]


def parse_claims(raw: str) -> list[str]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}|\[.*\]", text, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    values = data if isinstance(data, list) else data.get("claims") or []
    claims = []
    for value in values:
        if not isinstance(value, str):
            continue
        sentence = value.strip()
        if len(sentence) >= 20:
            claims.append(sentence)
    return claims[:4]


def claims_for(answer: str, model: str | None = None) -> tuple[list[str], str]:
    quick = extract_claims(answer)
    if quick:
        return quick, "rules"
    sentences = [sentence for sentence in split_sentences(answer) if len(sentence) >= 20][:3]
    if sentences:
        return sentences, "rules"
    try:
        raw = ask(EXTRACT_SYSTEM, answer, model=model, max_tokens=200, timeout=8)
        found = parse_claims(raw)
    except BifrostError:
        found = []
    if found:
        return found, "bifrost"
    return [], "rules"


def source_age_days(published: str | None) -> int | None:
    if not published:
        return None
    text = published.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
        for fmt in ("%Y-%m-%d", "%d %b %Y", "%b %d, %Y"):
            try:
                parsed = datetime.strptime(text[:20].strip(), fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - parsed).days)


def leadership_target(claim: str) -> tuple[str, str] | None:
    match = LEADERSHIP.search(claim)
    if not match:
        return None
    return match.group(1).strip(), f"{match.group(2)} of {match.group(3).strip(' .')}"


HOLDER_AFTER = re.compile(
    r"\b(?:current\s+)?(?:CEO|president|prime minister)\s+of\s+(?:the\s+)?[A-Z0-9][^.]{0,60}?\bis\s+([A-Z][a-z]+(?:\s+[A-Z][a-z.'-]+){0,3})",
    re.I,
)
HOLDER_BEFORE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z.'-]+){0,3})\s+is the\b[^.]{0,40}?\b(?:CEO|president|prime minister)\b",
    re.I,
)
CURRENT_ROLE_NAME = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z.'-]+){0,2})\b[^.]{0,50}?\bcurrent\s+(?:CEO|president|prime minister)\b",
    re.I,
)


def named_holder(text: str) -> str | None:
    match = HOLDER_AFTER.search(text) or HOLDER_BEFORE.search(text) or CURRENT_ROLE_NAME.search(text)
    if not match:
        return None
    return match.group(1).strip(" .")


def search_query(claim: str) -> str:
    target = leadership_target(claim)
    if target:
        return f"current {target[1]}"
    office = re.search(
        r"\bcurrent (CEO|president|prime minister) of ((?:the )?[A-Z0-9][A-Za-z0-9&.\- ]*?)(?=\s+is\b|[.?!]|$)",
        claim,
        re.I,
    )
    if office:
        return f"current {office.group(1)} of {office.group(2).strip(' .')}"
    if re.search(r"GPT-4", claim) and re.search(r"\$\s?\d", claim):
        return "current OpenAI GPT-4 API input price per million tokens"
    if re.search(r"\bAI Act\b", claim):
        return "EU AI Act status entered into force"
    return claim


def host_of(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def source_trust(url: str | None) -> int:
    host = host_of(url)
    if not host:
        return 40
    if any(host == bad or host.endswith("." + bad) for bad in LOW_TRUST_HOSTS):
        return 10
    if host.endswith(".gov") or host.endswith(".gov.uk") or host.endswith(".europa.eu"):
        return 100
    for suffix in TRUSTED_HOST_SUFFIXES:
        clean = suffix.lstrip(".")
        if host == clean or host.endswith("." + clean) or host.endswith(suffix):
            return 90
    return 45


def rank_sources(sources: list[dict]) -> list[dict]:
    ranked = []
    for source in sources:
        item = dict(source)
        item["trust"] = source_trust(item.get("url"))
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["trust"], item.get("age_days") is None, item.get("age_days") or 10_000))
    return ranked


def evidence_text(live_answer: str, sources: list[dict]) -> str:
    trusted = [source for source in sources if source.get("trust", 0) >= 80]
    preferred = trusted or [source for source in sources if source.get("trust", 0) >= 40] or sources
    snippets = " ".join(source.get("snippet") or "" for source in preferred[:3]).strip()
    answer = (live_answer or "").strip()
    parts = [part for part in (answer, snippets) if part]
    return "\n".join(parts)


def quote_from(text: str, pattern: re.Pattern | None = None) -> str:
    lines = split_sentences(text)
    if pattern:
        for line in lines:
            if pattern.search(line):
                return line[:400]
    if lines:
        return lines[0][:400]
    return text.strip()[:400]


def predecessor_pattern(person: str) -> re.Pattern:
    name = re.escape(person)
    return re.compile(
        rf"(?:succeeding|succeeded|replaced|replacing|after|following)\s+{name}"
        rf"|{name}.{{0,40}}(?:was succeeded|stepped down|former)",
        re.I,
    )


def classify_person(person: str, evidence: str) -> tuple[str, str]:
    lines = split_sentences(evidence)
    person_lines = [line for line in lines if person.lower() in line.lower()]
    predecessor = predecessor_pattern(person)
    handed_over = [line for line in person_lines if predecessor.search(line)]
    still_about_person = [line for line in person_lines if line not in handed_over]
    current_lines = [
        line for line in still_about_person if CURRENT.search(line) and not FORMER.search(line)
    ]
    if current_lines:
        return "agrees", current_lines[0][:400]
    former_lines = [line for line in person_lines if FORMER.search(line) or line in handed_over]
    if former_lines:
        return "disagrees", former_lines[0][:400]
    for line in lines:
        if person.lower() not in line.lower() and ROLE_WORD.search(line) and not FORMER.search(line):
            return "disagrees", line[:400]
    if still_about_person:
        return "agrees", still_about_person[0][:400]
    return "disagrees", quote_from(evidence)


def classify_price(claim: str, evidence: str) -> tuple[str, str] | None:
    claim_amounts = {round(float(value), 2) for value in PRICE_AMOUNT.findall(claim)}
    if not claim_amounts:
        return None
    quote = quote_from(evidence, re.compile(r"\$"))
    evidence_amounts = {round(float(value), 2) for value in PRICE_AMOUNT.findall(evidence)}
    claim_per_token = bool(PER_TOKEN.search(claim)) and not PER_MILLION.search(claim)
    evidence_per_million = bool(PER_MILLION.search(evidence))
    if claim_per_token and evidence_per_million:
        return "disagrees", quote
    if evidence_amounts and claim_amounts.isdisjoint(evidence_amounts):
        return "disagrees", quote
    if evidence_amounts:
        return "agrees", quote
    return "unknown", quote


def classify_law(claim: str, evidence: str) -> tuple[str, str] | None:
    if not re.search(r"\b(act|law|regulation|directive)\b", claim, re.I):
        return None
    positive = LAW_POSITIVE.search(evidence)
    quote = quote_from(evidence, LAW_POSITIVE if positive else None)
    if LAW_NEGATIVE.search(claim) and positive:
        return "disagrees", quote
    if LAW_NEGATIVE.search(claim) and LAW_NEGATIVE.search(evidence):
        return "agrees", quote
    if positive and not LAW_NEGATIVE.search(claim):
        return "agrees", quote
    return None


def classify_overlap(claim: str, evidence: str) -> tuple[str, str]:
    quote = quote_from(evidence)
    words = {word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", claim)}
    evidence_lower = evidence.lower()
    overlap = (sum(1 for word in words if word in evidence_lower) / len(words)) if words else 0
    if re.search(r"\b(current|currently|still)\b", claim, re.I) and FORMER.search(evidence):
        return "disagrees", quote_from(evidence, FORMER)
    if overlap >= 0.45:
        return "agrees", quote
    if overlap < 0.25:
        return "unknown", quote
    return "unknown", quote


def judge_claim(claim: str, live_answer: str, sources: list[dict]) -> dict:
    evidence = evidence_text(live_answer, sources)
    if not evidence:
        return {
            "freshness": 12,
            "verdict": "unknown",
            "reason": "No live source found for this claim.",
            "quote": "",
        }

    claimed_holder = named_holder(claim)
    live_holder = named_holder(evidence)
    target = leadership_target(claim)
    if claimed_holder and live_holder and claimed_holder.lower() != live_holder.lower():
        verdict, quote = "disagrees", quote_from(evidence, re.compile(re.escape(live_holder), re.I))
    elif target:
        verdict, quote = classify_person(target[0], evidence)
    else:
        priced = classify_price(claim, evidence)
        law = classify_law(claim, evidence)
        if priced is not None and priced[0] != "unknown":
            verdict, quote = priced
        elif law is not None:
            verdict, quote = law
        elif priced is not None:
            verdict, quote = priced
        else:
            verdict, quote = classify_overlap(claim, evidence)

    score = {"agrees": 88, "disagrees": 22, "unknown": 55}[verdict]
    ages = [source["age_days"] for source in sources if source.get("age_days") is not None]
    age_note = ""
    if ages:
        newest = min(ages)
        age_note = f" The newest dated source is {newest} days old."
        if verdict == "unknown" and newest > 365:
            verdict = "outdated"
            score = 34
        elif verdict == "agrees" and newest <= 30:
            score = 95

    trusted = [source for source in sources if source.get("trust", 0) >= 80]
    trust_note = ""
    if trusted:
        trust_note = f" Preferred source: {host_of(trusted[0].get('url'))}."
        if verdict == "agrees":
            score = min(100, score + 5)
    elif sources and max(source.get("trust", 0) for source in sources) <= 10:
        trust_note = " Only low-trust sources were found."
        if verdict == "agrees":
            score = max(0, score - 20)
            if score < 60:
                verdict = "unknown"

    reasons = {
        "agrees": "The live source supports this claim.",
        "disagrees": "The live source disagrees.",
        "outdated": "The only dated sources are too old to treat this as current.",
        "unknown": "The live pages mention this topic but do not confirm the claim.",
    }
    quoted = f' "{quote}"' if quote else ""
    return {
        "freshness": score,
        "verdict": verdict,
        "reason": f"{reasons[verdict]}{quoted}{age_note}{trust_note}",
        "quote": quote,
    }


def short_fact(text: str) -> str:
    fact = re.sub(r"\s+", " ", " ".join(split_sentences(text)[:2])).strip()
    return fact[:400]


def locate_claim(answer: str, claim: str) -> str:
    if claim in answer:
        return claim
    claim_words = set(re.findall(r"[a-z0-9]+", claim.lower()))
    best = ""
    best_score = 0.0
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
        words = set(re.findall(r"[a-z0-9]+", sentence.lower()))
        if not claim_words or not words:
            continue
        score = len(claim_words & words) / len(claim_words)
        if score > best_score:
            best_score = score
            best = sentence.strip()
    if best_score >= 0.6:
        return best
    return ""


def rewrite_answer(answer: str, checked: list[dict]) -> str | None:
    pieces = []
    changed = False
    for item in checked:
        correction = item.get("correction")
        if item.get("likely_stale") and correction:
            pieces.append(correction)
            changed = True
        elif item.get("claim"):
            pieces.append(item["claim"])
    if not changed:
        return None
    return " ".join(pieces)


def tavily_key() -> str:
    return settings.tavily_api_key or os.environ.get("TAVILY_API_KEY", "")


def verify_claim(claim: str) -> dict:
    key = tavily_key()
    if not key:
        return failed_claim(claim, "Set TAVILY_API_KEY in .env.")

    query = search_query(claim)
    current_office = bool(re.search(r"\bcurrent (CEO|president|prime minister)\b", query, re.I))
    try:
        found = TavilyClient(api_key=key).search(
            query=query,
            max_results=5,
            search_depth="fast",
            include_answer=True,
            topic="news" if current_office else "general",
            time_range="year" if current_office else None,
            exclude_domains=list(EXCLUDE_DOMAINS),
            timeout=20,
        )
    except Exception as exc:
        message = str(exc)
        if key and key in message:
            message = "request rejected"
        return failed_claim(claim, f"Live search failed: {message}")

    results = found.get("results") or []
    sources = []
    for item in results:
        published = item.get("published_date")
        sources.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "published": published,
                "age_days": source_age_days(published),
                "snippet": (item.get("content") or "")[:400],
            }
        )
    sources = rank_sources(sources)
    live_answer = (found.get("answer") or "").strip()
    judged = judge_claim(claim, live_answer, sources)
    threshold = settings.freshgate_threshold
    score = judged["freshness"]
    correction = None
    if score < threshold:
        trusted_quote = next(
            (source.get("snippet") for source in sources if source.get("trust", 0) >= 80 and source.get("snippet")),
            "",
        )
        correction = short_fact(judged["quote"] or trusted_quote or live_answer) or None
        if correction and correction.strip() == claim.strip():
            correction = None
    return {
        "claim": claim,
        "freshness": score,
        "likely_stale": score < threshold,
        "verdict": judged["verdict"],
        "reason": judged["reason"],
        "quote": judged["quote"],
        "live_answer": live_answer,
        "correction": correction,
        "sources": sources,
    }


def failed_claim(claim: str, reason: str) -> dict:
    return {
        "claim": claim,
        "freshness": 0,
        "likely_stale": True,
        "verdict": "unknown",
        "reason": reason,
        "quote": "",
        "live_answer": "",
        "correction": None,
        "sources": [],
        "trust": 0,
    }


def check_claims(claims: list[str]) -> list[dict]:
    if not claims:
        return []
    workers = min(4, len(claims))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(verify_claim, claims))


def policy_action(score: int | None, flagged: int, corrected: str | None) -> dict:
    threshold = settings.freshgate_threshold
    policy = settings.freshgate_policy
    if policy not in {"warn", "correct", "hold"}:
        policy = "correct"
    if score is None or score >= threshold or flagged == 0:
        action = "pass"
    elif policy == "warn":
        action = "warn"
    elif policy == "hold":
        action = "hold"
    else:
        action = "correct" if corrected else "warn"
    return {
        "policy": policy,
        "threshold": threshold,
        "action": action,
        "held": action == "hold",
        "final_answer": corrected if action == "correct" and corrected else None,
    }


def check_answer(answer: str, model: str | None = None) -> dict:
    claims, claim_source = claims_for(answer, model)
    checked = check_claims(claims)
    scores = [item["freshness"] for item in checked]
    corrected = rewrite_answer(answer, checked)
    flagged = sum(1 for item in checked if item["likely_stale"])
    overall = min(scores) if scores else None
    policy = policy_action(overall, flagged, corrected)
    return {
        "claims": checked,
        "checked_count": len(checked),
        "flagged_count": flagged,
        "overall_freshness": overall,
        "corrected_answer": corrected,
        "claim_source": claim_source,
        **policy,
    }
