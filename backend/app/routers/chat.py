from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.schemas import ChatIn, VerifyIn
from app.services.bifrost import BifrostError, complete_chat
from app.services.freshness import check_answer

router = APIRouter()


def with_freshness_headers(body: dict) -> JSONResponse:
    report = body.get("freshness") or body
    score = report.get("overall_freshness")
    return JSONResponse(
        body,
        headers={
            "X-Freshgate-Score": "none" if score is None else str(score),
            "X-Freshgate-Flagged": str(report.get("flagged_count", 0)),
        },
    )


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.post("/verify")
def verify(body: VerifyIn):
    return with_freshness_headers(check_answer(body.answer))


@router.post("/v1/chat")
def chat(body: ChatIn):
    try:
        answer, model = complete_chat(body.message, body.model)
    except BifrostError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    report = check_answer(answer)
    return with_freshness_headers({"answer": answer, "model": model, "freshness": report})
