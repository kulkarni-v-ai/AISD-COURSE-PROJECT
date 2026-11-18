from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class UserLogin(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str = "student"  # student, faculty, technician, admin


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
