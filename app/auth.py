"""
Autenticación: emisión y verificación de JWT.

Flujo:
1. Usuario hace click en "Login with Google" en el companion (o web).
2. El companion abre http://localhost:8000/auth/google → redirige a Google.
3. Google llama a /auth/google/callback con un code.
4. Backend intercambia code por user info, crea/actualiza User, emite tokens.
5. Tokens (access + refresh) van al companion vía URL custom (jarvis://callback?token=...)
   o como query string a la página de éxito.
6. Companion guarda tokens, los usa en Authorization: Bearer <access_token>.
"""

import datetime as dt
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from .settings import settings
from .db import get_db
from .models import User, Subscription


# ---------------- JWT ----------------
def create_access_token(user_id: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)).timestamp()),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> str:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {e}")
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=401, detail=f"Token de tipo incorrecto: esperaba {expected_type}")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token sin sub")
    return user_id


# ---------------- Dependency para endpoints protegidos ----------------
_bearer = HTTPBearer(auto_error=False)


async def current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status_code=401, detail="No autenticado")
    user_id = decode_token(creds.credentials, "access")
    # Eager-load la subscription para evitar lazy-load fuera de sesión async
    res = await db.execute(
        select(User)
        .options(selectinload(User.subscription))
        .where(User.id == user_id)
    )
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    return user


# ---------------- OAuth: Google ----------------
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def google_auth_url(state: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def google_exchange_code(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        r.raise_for_status()
        tokens = r.json()
        u = await client.get(GOOGLE_USERINFO_URL, headers={
            "Authorization": f"Bearer {tokens['access_token']}"
        })
        u.raise_for_status()
        return u.json()  # { id, email, name, picture, ... }


# ---------------- OAuth: GitHub ----------------
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def github_auth_url(state: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_REDIRECT_URI,
        "scope": "read:user user:email",
        "state": state,
    }
    return f"{GITHUB_AUTH_URL}?{urlencode(params)}"


async def github_exchange_code(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(GITHUB_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "redirect_uri": settings.GITHUB_REDIRECT_URI,
        }, headers={"Accept": "application/json"})
        r.raise_for_status()
        tokens = r.json()
        access_token = tokens["access_token"]
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        u = await client.get(GITHUB_USER_URL, headers=headers)
        u.raise_for_status()
        info = u.json()  # { id, name, login, avatar_url, email puede ser null }
        if not info.get("email"):
            er = await client.get(GITHUB_EMAILS_URL, headers=headers)
            er.raise_for_status()
            emails = er.json()
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
            if primary:
                info["email"] = primary["email"]
        return info


# ---------------- Crear/actualizar User a partir de OAuth ----------------
async def upsert_user_from_oauth(
    db: AsyncSession,
    provider: str,
    provider_id: str,
    email: str,
    name: str = "",
    picture_url: str = "",
) -> User:
    """Busca usuario por provider+provider_id o por email; crea si no existe."""
    res = await db.execute(
        select(User).where(User.provider == provider, User.provider_id == provider_id)
    )
    user = res.scalar_one_or_none()

    if not user and email:
        # Buscar por email (en caso de que el mismo email haya entrado por otro provider)
        res = await db.execute(select(User).where(User.email == email))
        user = res.scalar_one_or_none()

    now = dt.datetime.now(dt.timezone.utc)
    if user:
        user.name = name or user.name
        user.picture_url = picture_url or user.picture_url
        user.last_login_at = now
        user.provider = provider
        user.provider_id = provider_id
    else:
        user = User(
            email=email,
            name=name,
            picture_url=picture_url,
            provider=provider,
            provider_id=provider_id,
        )
        db.add(user)
        await db.flush()
        # Crear suscripción inicial (trial gratis 14 días)
        sub = Subscription(
            user_id=user.id,
            plan="pro",  # trial te da Pro features
            status="trialing",
            trial_ends_at=now + dt.timedelta(days=14),
        )
        db.add(sub)

    await db.commit()
    # Refrescar con la subscription cargada para evitar lazy-load posterior
    await db.refresh(user, attribute_names=["subscription"])
    return user
