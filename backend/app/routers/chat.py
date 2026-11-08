from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from app.schemas import ChatIn, SpeakIn, VerifyIn
from app.services.bifrost import BifrostError, complete_chat, speak_text, transcribe_audio
from app.services.freshness import check_answer

router = APIRouter()


def with_freshness_headers(body: dict) -> JSONResponse:
    report = body.get("freshness") or body
    score = report.get("overall_freshness")
    action = report.get("action") or "pass"
    return JSONResponse(
        body,
        headers={
            "X-Freshgate-Score": "none" if score is None else str(score),
            "X-Freshgate-Flagged": str(report.get("flagged_count", 0)),
            "X-Freshgate-Action": str(action),
        },
    )


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.post("/verify")
def verify(body: VerifyIn):
    return with_freshness_headers(check_answer(body.answer))


@router.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty audio upload.")
    try:
        text = transcribe_audio(
            audio,
            filename=file.filename or "speech.webm",
            content_type=file.content_type or "audio/webm",
        )
    except BifrostError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return {"text": text}


@router.post("/api/speak")
def speak(body: SpeakIn):
    try:
        audio = speak_text(body.text)
    except BifrostError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/v1/chat")
def chat(body: ChatIn):
    try:
        answer, model, grounding = complete_chat(body.message, body.model)
    except BifrostError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    report = check_answer(answer, model)
    return with_freshness_headers(
        {
            "answer": answer,
            "model": model,
            "grounding": grounding,
            "freshness": report,
        }
    )
