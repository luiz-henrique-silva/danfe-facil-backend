import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: EmailStr
    name: str | None
    role: str
    created_at: datetime


class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None


class ChangePassword(BaseModel):
    current_password: str
    new_password: str