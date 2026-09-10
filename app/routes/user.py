from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.user import UserOut, UserUpdate, ChangePassword
from app.services.security import hash_password, verify_password

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    return user


@router.put("/me", response_model=UserOut)
async def update_me(data: UserUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if data.name is not None:
        user.name = data.name.strip()
    if data.email is not None and data.email != user.email:
        result = await db.execute(select(User).where(User.email == data.email.lower()))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email já cadastrado")
        user.email = data.email.lower()
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/change-password")
async def change_password(data: ChangePassword, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")
    user.password_hash = hash_password(data.new_password)
    await db.commit()
    return {"message": "Senha alterada com sucesso."}