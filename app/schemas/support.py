from pydantic import BaseModel, EmailStr, Field


class ContactMessageCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    reason: str = Field(..., min_length=1, max_length=100)
    comment: str = Field(..., min_length=1, max_length=5000)
