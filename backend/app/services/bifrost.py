import httpx

from app.config import settings


class BifrostError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def complete_chat(message: str, model: str | None = None) -> tuple[str, str]:
    if not settings.bifrost_vk:
        raise BifrostError(500, "Set BIFROST_VK in .env to your Bifrost virtual key.")

    chosen_model = model or settings.bifrost_model
    payload = {
        "model": chosen_model,
        "messages": [
            {
                "role": "system",
                "content": "Answer in at most 4 short sentences. No preamble.",
            },
            {"role": "user", "content": message},
        ],
        "max_tokens": 250,
        "reasoning": {"effort": "minimal", "max_tokens": 0},
    }
    try:
        with httpx.Client(timeout=240) as client:
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
    answer = data["choices"][0]["message"]["content"]
    return answer, chosen_model
