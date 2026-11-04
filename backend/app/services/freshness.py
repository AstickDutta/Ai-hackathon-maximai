import os
import re
from datetime import datetime, timezone

from tavily import TavilyClient

from app.config import settings

STALE_HINT = re.compile(
    r"\b(ceo|cto|founder|president|price|pricing|costs?|\$\d|version|v\d|api|law|act|regulation|acquired|hired|launch|released|as of|currently|today|stepped down)\b",
    re.I,
)


def extract_claims(answer: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", answer)
    claims = []
    for chunk in chunks:
        text = chunk.strip(" -\t")
        if len(text) < 20:
            continue
        if STALE_HINT.search(text):
            claims.append(text)
    return claims[:3]


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


def search_query(claim: str) -> str:
    match = re.search(r"\bCEO of ([A-Z][A-Za-z0-9&.\- ]{1,40})", claim)
    if match:
        return f"current CEO of {match.group(1).strip(' .')}"
    if re.search(r"GPT-4", claim) and re.search(r"\$\s?\d", claim):
        return "current GPT-4 API input price"
    return claim


def verify_claim(client: TavilyClient, claim: str) -> dict:
    found = client.search(
        query=search_query(claim),
        max_results=3,
        search_depth="basic",
        include_answer=True,
        topic="general",
    )
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
    score, reason = score_claim(claim, found.get("answer") or "", sources)
    return {
        "claim": claim,
        "freshness": score,
        "likely_stale": score < 60,
        "reason": reason,
        "live_answer": found.get("answer"),
        "sources": sources,
    }


def score_claim(claim: str, live_answer: str, sources: list[dict]) -> tuple[int, str]:
    if not sources and not live_answer:
        return 15, "No live source found for this claim."

    score = 40
    reasons = []
    evidence = live_answer.lower() if live_answer else ""
    if not evidence:
        evidence = " ".join(
            f"{source.get('title', '')} {source.get('snippet', '')}" for source in sources
        ).lower()
        reasons.append("No direct live answer, so the pages were compared instead.")
        score -= 10
    else:
        reasons.append("Compared with Tavily's current answer.")

    claim_words = {word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", claim)}
    overlap = (sum(1 for word in claim_words if word in evidence) / len(claim_words)) if claim_words else 0
    if overlap < 0.35:
        score -= 20
        reasons.append("Most of the claim does not appear in that answer.")
    else:
        score += 25

    names = re.findall(r"\b[A-Z][A-Za-z0-9.+-]{2,}\b", claim)
    missing = [name for name in names if name.lower() not in evidence]
    if names and missing:
        score -= 35
        reasons.append(f"The live answer does not mention {', '.join(missing[:3])}.")

    claim_lower = claim.lower()
    if re.search(r"\b(current|currently|still)\b", claim_lower) and re.search(
        r"\b(former|interim|previously|no longer|stepped down|not the)\b", evidence
    ):
        score -= 25
        reasons.append("The live answer describes this as past, not current.")

    ages = [source["age_days"] for source in sources if source.get("age_days") is not None]
    if ages:
        newest = min(ages)
        if newest <= 30:
            score += 20
            reasons.append(f"A source was published {newest} days ago.")
        elif newest > 365:
            score -= 25
            reasons.append(f"The newest dated source is {newest} days old.")
        else:
            reasons.append(f"The newest dated source is {newest} days old.")

    return max(0, min(100, score)), " ".join(reasons)


def check_answer(answer: str) -> dict:
    api_key = settings.tavily_api_key or os.environ.get("TAVILY_API_KEY", "")
    client = TavilyClient(api_key=api_key)
    claims = extract_claims(answer)
    checked = [verify_claim(client, claim) for claim in claims]
    scores = [item["freshness"] for item in checked]
    return {
        "claims": checked,
        "checked_count": len(checked),
        "flagged_count": sum(1 for item in checked if item["likely_stale"]),
        "overall_freshness": min(scores) if scores else None,
    }
