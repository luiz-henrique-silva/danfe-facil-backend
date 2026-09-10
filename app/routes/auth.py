from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.subscription import Subscription, SubStatus, PlanType
from app.models.user import User
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    RefreshRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.services.security import hash_password, verify_password, create_token, decode_token
from app.services.email_service import send_password_reset_email, send_welcome_email

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    from app.models.subscription import Subscription
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email já cadastrado")

    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        name=data.name.strip(),
    )
    db.add(user)
    await db.flush()

    sub = Subscription(
        user_id=user.id,
        status=SubStatus.free.value,
        plan=PlanType.free.value,
    )
    db.add(sub)

    await db.commit()

    access_token = create_token(user.id, "access", timedelta(minutes=30))
    refresh_token = create_token(user.id, "refresh", timedelta(days=7))

    try:
        await send_welcome_email(user.email, user.name or "")
    except Exception:
        pass

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Conta desativada")

    access_token = create_token(user.id, "access", timedelta(minutes=30))
    refresh_token = create_token(user.id, "refresh", timedelta(days=7))

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    user_id = decode_token(data.refresh_token, expected_type="refresh")
    if not user_id:
        raise HTTPException(status_code=401, detail="Refresh token inválido")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Usuário inválido")

    access_token = create_token(user.id, "access", timedelta(minutes=30))
    refresh_token = create_token(user.id, "refresh", timedelta(days=7))

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    user = result.scalar_one_or_none()

    # Sempre responde 200 para não vazar quais emails existem
    if user:
        reset_token = create_token(user.id, "reset", timedelta(minutes=30))
        try:
            await send_password_reset_email(user.email, reset_token)
        except Exception:
            pass

    return {"message": "Se o email existir, você receberá um link de redefinição."}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    user_id = decode_token(data.token, expected_type="reset")
    if not user_id:
        raise HTTPException(status_code=401, detail="Link inválido ou expirado")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    user.password_hash = hash_password(data.new_password)
    await db.commit()

    return {"message": "Senha redefinida com sucesso."}