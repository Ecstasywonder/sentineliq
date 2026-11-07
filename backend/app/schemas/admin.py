"""
Admin schemas — Gate 19.

Pydantic models for user/role administration endpoints.
Requires admin:users permission.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.models.user import VALID_ROLES

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    roles: list[str] = Field(default_factory=list)

    model_config = {"str_strip_whitespace": True}


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=255)
    is_active: bool | None = None

    model_config = {"str_strip_whitespace": True}


class RoleAssignRequest(BaseModel):
    role: str = Field(..., description=f"One of: {', '.join(VALID_ROLES)}")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UserRoleSummary(BaseModel):
    role: str
    granted_by: str | None


class UserDetailResponse(BaseModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    is_verified: bool
    roles: list[UserRoleSummary]
    created_at: str


class UserListItem(BaseModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    roles: list[str]
    created_at: str


class UserListResponse(BaseModel):
    items: list[UserListItem]
    total: int
    page: int
    page_size: int
    pages: int


class RoleDescription(BaseModel):
    name: str
    description: str
    permissions: list[str]


class RolesResponse(BaseModel):
    roles: list[RoleDescription]
