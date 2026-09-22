from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.support import ContactMessage
from app.schemas.support import ContactMessageCreate

router = APIRouter()


@router.post("/contact", status_code=201)
async def submit_contact_message(
    payload: ContactMessageCreate,
    db: AsyncSession = Depends(get_db),
):
    message = ContactMessage(
        name=payload.name,
        email=payload.email,
        reason=payload.reason,
        comment=payload.comment,
    )
    db.add(message)
    await db.commit()

    return {"message": "Your message has been received."}
