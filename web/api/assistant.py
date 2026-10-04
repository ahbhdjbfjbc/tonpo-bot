"""AI Assistant API — guidance only. Never calls TradeExecutor or Gateway."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.models import User
from services.ai_assistant import answer, quick_actions
from web.deps import get_current_user, get_db

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    language: Optional[str] = Field(None, pattern="^(ar|en)$")


class ChatOut(BaseModel):
    reply: str
    language: str
    intent: str
    provider: str
    context: dict
    configured: bool


@router.get("/status")
def assistant_status(user: User = Depends(get_current_user)):
    import os
    configured = bool(os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY"))
    return {
        "available": True,
        "mode": "knowledge_base",
        "configured": configured,
        "message": None if configured else "AI Assistant is not configured for external LLM; using built-in knowledge base.",
        "can_execute_trades": False,
    }


@router.get("/quick-actions")
def get_quick_actions(
    language: str = "ar",
    user: User = Depends(get_current_user),
):
    lang = language if language in ("ar", "en") else "ar"
    return {"language": lang, "actions": quick_actions(lang)}


@router.post("/chat", response_model=ChatOut)
def chat(
    body: ChatIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = answer(body.message, lang=body.language, db=db, user=user)
    return ChatOut(**result)
