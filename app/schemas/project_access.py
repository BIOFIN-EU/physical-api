from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

LevelIn = Literal["viewer", "editor", "manager"]


class AddMemberRequest(BaseModel):
    email: EmailStr
    level: LevelIn = "viewer"
    # Workflow roles (codes from the project's workflow); a member with roles
    # is at least an editor.
    roles: list[str] = Field(default_factory=list, max_length=20)


class ChangeMemberRequest(BaseModel):
    """Either or both; a field left out is unchanged."""
    level: Optional[LevelIn] = None
    roles: Optional[list[str]] = Field(default=None, max_length=20)


class TransferOwnershipRequest(BaseModel):
    user_id: UUID
