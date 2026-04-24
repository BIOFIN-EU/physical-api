from uuid import UUID

from pydantic import BaseModel, Field, EmailStr

class AssignCaseUserRequest(BaseModel):
    email: EmailStr
    case_role: str = Field(pattern="^(borrower|funder|intermediary)$")

    can_view: bool = True
    can_update: bool = False
    can_delete: bool = False
    can_assign_users: bool = False


class UpdateCaseUserAccessRequest(BaseModel):
    case_role: str | None = Field(default=None, pattern="^(borrower|funder|intermediary)$")

    can_view: bool | None = None
    can_update: bool | None = None
    can_delete: bool | None = None
    can_assign_users: bool | None = None