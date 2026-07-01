"""Call-summary endpoint for the Call Logs feature.

Accepts a completed Vapi call transcript from the NestJS backend (after the
backend receives Vapi's `end-of-call-report` webhook) and returns the
structured fields the Call Logs UI displays. JSON body — mirrors the
voice_routes.py backend-to-ai-service pattern already used for voice
translation, not multipart.
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.call_summarizer import summarize_call

logger = logging.getLogger("call_routes")
router = APIRouter()


class CallSummarizeRequest(BaseModel):
    transcript: str = ""
    agentKey: str = ""
    agentName: str = ""


@router.post("/call/summarize")
async def call_summarize(payload: CallSummarizeRequest):
    result = summarize_call(payload.transcript, payload.agentKey, payload.agentName)
    logger.info("call/summarize ok agentKey=%s summary_chars=%d", payload.agentKey, len(result["summary"]))
    return result
