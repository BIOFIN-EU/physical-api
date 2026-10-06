"""
A member's access level on a project, stored as the four permission flags
of case_user_access:

    viewer   read the project (and its member list)
    editor   + edit its steps (those without roles, and their roles' steps)
    manager  + delete it, manage its members and their roles, and record a
               step on a role's behalf

The owner is a manager who can't be removed or changed, and can hand the
project over to another member.
"""
from __future__ import annotations

from typing import Literal

from app.models.case_data import CaseUserAccess

Level = Literal["viewer", "editor", "manager"]
LEVELS: tuple[Level, ...] = ("viewer", "editor", "manager")
PERMISSION_FLAGS = ("can_view", "can_update", "can_delete", "can_assign_users")

_FLAGS: dict[str, tuple[bool, bool, bool, bool]] = {
    "viewer": (True, False, False, False),
    "editor": (True, True, False, False),
    "manager": (True, True, True, True),
}

LEVEL_LABELS = {
    "owner": "Owner",
    "manager": "Manager",
    "editor": "Editor",
    "viewer": "Viewer",
}
LEVEL_DESCRIPTIONS = {
    "owner": "Everything a manager can do; can hand the project over to another member. Can't be removed.",
    "manager": "Edits the project, manages its members and their roles, can delete it, and can record a step on a role's behalf.",
    "editor": "Edits the project's steps: those without roles, and the steps of the roles they hold.",
    "viewer": "Reads the project and its member list.",
}


def level_of(access: CaseUserAccess) -> str:
    """owner, manager, editor or viewer (the highest the flags allow)."""
    if access.is_owner:
        return "owner"
    if access.can_assign_users:
        return "manager"
    if access.can_update:
        return "editor"
    return "viewer"


def apply_level(access: CaseUserAccess, level: Level) -> None:
    for flag, value in zip(PERMISSION_FLAGS, _FLAGS[level]):
        setattr(access, flag, value)


def at_least_editor(level: str) -> str:
    """Members with workflow roles must be able to edit (to do their steps)."""
    return "editor" if level == "viewer" else level


def levels_for_display() -> list[dict[str, str]]:
    return [
        {"code": code, "label": LEVEL_LABELS[code], "description": LEVEL_DESCRIPTIONS[code]}
        for code in ("owner", *reversed(LEVELS))
    ]
