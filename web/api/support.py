"""User support tickets — own tickets only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.models import SupportMessage, SupportTicket, User
from web.deps import get_current_user, get_db

router = APIRouter(prefix="/api/support", tags=["support"])


class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=3, max_length=160)
    message: str = Field(..., min_length=3, max_length=4000)


@router.get("/tickets")
def list_tickets(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(SupportTicket)
        .filter(SupportTicket.user_id == user.id)
        .order_by(SupportTicket.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "items": [
            {
                "id": t.id,
                "subject": t.subject,
                "status": t.status,
                "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
            }
            for t in rows
        ]
    }


@router.post("/tickets", status_code=201)
def create_ticket(
    body: TicketCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ticket = SupportTicket(
        user_id=user.id,
        telegram_id=user.telegram_id,
        subject=body.subject.strip(),
        status="open",
    )
    db.add(ticket)
    db.flush()
    msg = SupportMessage(
        ticket_id=ticket.id,
        sender_telegram_id=user.telegram_id,
        sender_role="user",
        message=body.message.strip(),
    )
    db.add(msg)
    db.commit()
    db.refresh(ticket)
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat() + "Z" if ticket.created_at else None,
    }


@router.get("/tickets/{ticket_id}")
def get_ticket(
    ticket_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ticket = (
        db.query(SupportTicket)
        .filter(SupportTicket.id == ticket_id, SupportTicket.user_id == user.id)
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    messages = (
        db.query(SupportMessage)
        .filter(SupportMessage.ticket_id == ticket.id)
        .order_by(SupportMessage.created_at.asc())
        .all()
    )
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "status": ticket.status,
        "messages": [
            {
                "id": m.id,
                "sender_role": m.sender_role,
                "message": m.message,
                "created_at": m.created_at.isoformat() + "Z" if m.created_at else None,
            }
            for m in messages
        ],
    }
