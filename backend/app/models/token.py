from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.validators import OncoLinkEmail


class LoginRequest(BaseModel):
    email: OncoLinkEmail
    password: str


class TwoFactorVerifyRequest(BaseModel):
    temp_token: str
    code: str | None = None
    recovery_code: str | None = None


class TwoFactorSetupResponse(BaseModel):
    provisioning_uri: str
    secret: str


class TwoFactorVerifySetupRequest(BaseModel):
    secret: str
    code: str


class TwoFactorVerifySetupResponse(BaseModel):
    enrolled: bool
    recovery_codes: list[str]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    role: str
    requires_2fa: bool = False
    temp_token: str | None = None
    totp_enrolled: bool = True


class TokenPayload(BaseModel):
    sub: str
    role: str
    jti: str
    iat: int
    exp: int
    type: str = "access"
    scope: str = "access"


class RefreshTokenInDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token_hash: str
    family_id: str
    user_id: str
    expires_at: datetime
    created_at: datetime
    revoked: bool = False
    revoked_at: datetime | None = None
