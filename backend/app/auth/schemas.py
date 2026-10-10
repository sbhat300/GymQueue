from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    netid: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    netid: str
    password: str


class UserPublic(BaseModel):
    id: str
    netid: str
    display_name: str | None
    onboarding_complete: bool
    face_enrolled: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
