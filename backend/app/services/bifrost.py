import httpx

from app.config import settings


class BifrostError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def provider_of(model: str) -> str:
    return model.split("/", 1)[0].lower() if "/" in model else ""


def ask(
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 400,
    timeout: float = 90,
) -> str:
    if not settings.bifrost_vk:
        raise BifrostError(500, "Set BIFROST_VK in .env to your Bifrost virtual key.")

    payload = {
        "model": model or settings.bifrost_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "reasoning": {"effort": "minimal"},
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            upstream = client.post(
                f"{settings.bifrost_url}/v1/chat/completions",
                json=payload,
                headers={"x-bf-vk": settings.bifrost_vk},
            )
    except httpx.HTTPError as exc:
        raise BifrostError(502, f"Bifrost unreachable: {exc}") from exc

    if upstream.status_code >= 400:
        raise BifrostError(upstream.status_code, upstream.text)

    data = upstream.json()
    return data["choices"][0]["message"]["content"]


def openai_web_search(user: str, model: str, timeout: float = 60) -> str:
    if not settings.bifrost_vk:
        raise BifrostError(500, "Set BIFROST_VK in .env to your Bifrost virtual key.")

    body = {
        "model": model,
        "input": user,
        "instructions": (
            "Answer in English only, even if the question is in another language. "
            "Use at most 4 short sentences. Use current live facts. No preamble."
        ),
        "tools": [{"type": "web_search"}],
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            upstream = client.post(
                f"{settings.bifrost_url}/v1/responses",
                json=body,
                headers={"x-bf-vk": settings.bifrost_vk},
            )
    except httpx.HTTPError as exc:
        raise BifrostError(502, f"Bifrost unreachable: {exc}") from exc

    if upstream.status_code >= 400:
        raise BifrostError(upstream.status_code, upstream.text[:400])

    data = upstream.json()
    texts = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") in (None, "output_text") and part.get("text"):
                texts.append(part["text"].strip())
    answer = "\n".join(text for text in texts if text).strip()
    if not answer:
        raise BifrostError(502, "OpenAI web search returned no text.")
    return answer


def gemini_grounded_answer(user: str, model: str, timeout: float = 45) -> str:
    if not settings.bifrost_vk:
        raise BifrostError(500, "Set BIFROST_VK in .env to your Bifrost virtual key.")

    model_id = model.split("/", 1)[-1]
    url = f"{settings.bifrost_url}/genai/v1beta/models/{model_id}:generateContent"
    body = {
        "systemInstruction": {
            "parts": [{
                "text": (
                    "Answer in English only, even if the question is in another language. "
                    "Use at most 4 short sentences. Use current facts. No preamble."
                )
            }]
        },
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"maxOutputTokens": 400},
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            upstream = client.post(url, json=body, headers={"x-bf-vk": settings.bifrost_vk})
    except httpx.HTTPError as exc:
        raise BifrostError(502, f"Bifrost unreachable: {exc}") from exc

    if upstream.status_code >= 400:
        raise BifrostError(upstream.status_code, upstream.text[:300])

    data = upstream.json()
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    texts = [part.get("text", "").strip() for part in parts if part.get("text") and not part.get("thought")]
    answer = "\n".join(text for text in texts if text).strip()
    if not answer:
        raise BifrostError(502, "Gemini returned no grounded text.")
    return answer


def transcribe_audio(audio_bytes: bytes, filename: str = "speech.webm", content_type: str = "audio/webm") -> str:
    if not settings.bifrost_vk:
        raise BifrostError(500, "Set BIFROST_VK in .env to your Bifrost virtual key.")
    files = {"file": (filename, audio_bytes, content_type or "application/octet-stream")}
    data = {"model": settings.openai_stt_model, "language": "en"}
    try:
        with httpx.Client(timeout=90) as client:
            upstream = client.post(
                f"{settings.bifrost_url}/v1/audio/transcriptions",
                data=data,
                files=files,
                headers={"x-bf-vk": settings.bifrost_vk},
            )
    except httpx.HTTPError as exc:
        raise BifrostError(502, f"Bifrost unreachable: {exc}") from exc
    if upstream.status_code >= 400:
        raise BifrostError(upstream.status_code, upstream.text[:400])
    payload = upstream.json()
    text = (payload.get("text") or "").strip()
    if not text:
        raise BifrostError(502, "No speech text returned.")
    return text


def speak_text(text: str) -> bytes:
    if not settings.bifrost_vk:
        raise BifrostError(500, "Set BIFROST_VK in .env to your Bifrost virtual key.")
    clean = " ".join(text.split())
    if len(clean) > 3500:
        clean = clean[:3500]
    body = {
        "model": settings.openai_tts_model,
        "input": clean,
        "voice": settings.openai_tts_voice,
        "response_format": "mp3",
    }
    try:
        with httpx.Client(timeout=90) as client:
            upstream = client.post(
                f"{settings.bifrost_url}/v1/audio/speech",
                json=body,
                headers={"x-bf-vk": settings.bifrost_vk},
            )
    except httpx.HTTPError as exc:
        raise BifrostError(502, f"Bifrost unreachable: {exc}") from exc
    if upstream.status_code >= 400:
        raise BifrostError(upstream.status_code, upstream.text[:400])
    if not upstream.content:
        raise BifrostError(502, "No audio returned.")
    return upstream.content


def complete_chat(message: str, model: str | None = None) -> tuple[str, str, str]:
    chosen_model = model or settings.bifrost_model
    provider = provider_of(chosen_model)

    try:
        if provider == "openai":
            return openai_web_search(message, chosen_model), chosen_model, "openai_web_search"
        if provider == "gemini":
            return gemini_grounded_answer(message, chosen_model), chosen_model, "google_search"
    except BifrostError as exc:
        detail = str(exc.detail).lower()
        mode = (
            "memory_quota"
            if ("429" in detail or "quota" in detail or "resource_exhausted" in detail)
            else "memory"
        )
    else:
        mode = "memory"

    answer = ask(
        (
            "Answer in English only, even if the question is in another language. "
            "Use at most 4 short sentences. Use current facts. No preamble."
        ),
        message,
        model=chosen_model,
        max_tokens=400,
        timeout=35,
    )
    return answer, chosen_model, mode
