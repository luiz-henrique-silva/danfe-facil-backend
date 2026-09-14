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
from app.services.email_validation import is_disposable_email
from app.services.email_service import send_password_reset_email, send_welcome_email
import httpx
from urllib.parse import urlencode
from app.config import get_settings

settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/google", status_code=status.HTTP_200_OK)
async def google_login():
    """Returns the Google consent screen URL."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Login Google não configurado")

    redirect_uri = f"{settings.APP_URL}/api/auth/google/callback"
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
    }
    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"}


@router.get("/google/callback", status_code=status.HTTP_200_OK)
async def google_callback(code: str, state: str | None = None, db: AsyncSession = Depends(get_db)):
    """Exchanges the Google code for tokens, then logs in or creates the user."""
    redirect_uri = f"{settings.APP_URL}/api/auth/google/callback"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            token_res = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_res.status_code != 200:
                raise HTTPException(status_code=400, detail="Falha ao obter token do Google")

            tokens = token_res.json()

            info_res = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            if info_res.status_code != 200:
                raise HTTPException(status_code=400, detail="Falha ao obter dados do usuário")

            info = info_res.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Erro ao comunicar com o Google")

    email = (info.get("email") or "").lower()

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        user = User(email=email, name=info.get("name"), google_id=info.get("id"))
        db.add(user)
        await db.flush()

        sub = Subscription(
            user_id=user.id,
            status=SubStatus.free.value,
            plan=PlanType.free.value,
        )
        db.add(sub)
        await db.commit()
    else:
        if user.google_id != info.get("id"):
            user.google_id = info.get("id")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Conta desativada")
        if not user.name:
            user.name = info.get("name")
        await db.commit()

    access_token = create_token(user.id, "access", timedelta(minutes=30))
    refresh_token = create_token(user.id, "refresh", timedelta(days=7))

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    from app.models.subscription import Subscription
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email já cadastrado")

    if is_disposable_email(data.email):
        raise HTTPException(
            status_code=400,
            detail="Use um email permanente (endereços temporários não são aceitos).",
        )

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

    if not user or not user.password_hash or not verify_password(data.password, user.password_hash):
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