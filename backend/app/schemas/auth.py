from datetime import datetime

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    password: str
    invite_token: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthStatus(BaseModel):
    logged_in: bool
    username: str | None = None
    is_admin: bool = False
    registration_open: bool = True
    has_users: bool = False


class InviteResponse(BaseModel):
    id: int
    token: str
    created_at: datetime
    expires_at: datetime
    used: bool

    model_config = {"from_attributes": True}
