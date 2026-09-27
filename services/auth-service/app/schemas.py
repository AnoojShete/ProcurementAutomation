from datetime import datetime
from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, EmailStr, ConfigDict, Field


class DataResponse(BaseModel):
    data: Any
    meta: Optional[Dict[str, Any]] = None


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


# Field max_length stops oversized bodies before any hashing happens; the
# user-facing password rules are in app/security.check_password_policy.
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=1024)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=1024)


class EmailOnlyRequest(BaseModel):
    email: EmailStr


class TokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    new_password: str = Field(max_length=1024)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


Role = Literal["requester", "approver", "finance", "admin"]


class UserUpdateRequest(BaseModel):
    role: Optional[Role] = None
    is_active: Optional[bool] = None


class TokenResponse(BaseModel):
    # The refresh token is set as an httpOnly cookie, not returned here.
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserResponse(BaseModel):
    # Deliberately no password hash, token_version or other internals.
    id: str
    email: str
    role: str
    model_config = ConfigDict(from_attributes=True)


class AdminUserResponse(UserResponse):
    is_active: bool
    email_verified_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
