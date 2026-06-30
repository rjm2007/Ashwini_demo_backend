"""Voice-to-English-text endpoint for the defect intake form.

Accepts a short audio clip in ANY spoken language, base64-encoded inside a
JSON body, and returns the English translation as plain text using OpenAI's
audio translations endpoint (Whisper).

NOTE: This is deliberately a JSON body, not multipart/form-data. The NestJS
caller sends it this way to avoid a Node.js fetch()+FormData+Blob
compatibility issue that caused outgoing multipart uploads to fail silently
before ever reaching this service. Do not change this endpoint back to
UploadFile/File(...) without first confirming the Node-side issue is
actually resolved.
"""

import base64
import logging
import os
import tempfile

from fastapi import APIRouter, HTTPException
from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger("voice_routes")
router = APIRouter()

_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # 15MB — generous for a short defect description


class VoiceTranslateRequest(BaseModel):
    audioBase64: str
    filename: str = "audio.webm"
    mimeType: str = "audio/webm"


@router.post("/voice/translate")
async def translate_voice_to_english(payload: VoiceTranslateRequest):
    """Translate a spoken defect description (any language) into English text."""
    try:
        audio_bytes = base64.b64decode(payload.audioBase64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 audio data")

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="Audio file too large (max 15MB)")

    suffix = os.path.splitext(payload.filename or "")[1] or ".webm"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            result = _client.audio.translations.create(
                model="whisper-1",
                file=audio_file,
            )
        text = (result.text or "").strip()
        logger.info("voice/translate ok chars=%d", len(text))
        return {"text": text}
    except Exception as exc:
        logger.error("voice/translate failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Could not transcribe/translate audio. Please try again.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
