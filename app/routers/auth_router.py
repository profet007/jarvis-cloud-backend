"""Endpoints de autenticación con OAuth."""

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (
    google_auth_url, google_exchange_code,
    github_auth_url, github_exchange_code,
    upsert_user_from_oauth,
    create_access_token, create_refresh_token, decode_token,
    current_user,
)
from ..db import get_db
from ..models import User
from ..settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])

# Memoria simple para validar el state CSRF (en producción usar Redis)
_state_store: set[str] = set()


def _new_state(callback_url: str | None = None) -> str:
    """Crea un state CSRF. Si companion mandó un callback_url, lo embebimos."""
    state = secrets.token_urlsafe(24)
    if callback_url:
        state = f"{state}|{callback_url}"
    _state_store.add(state)
    return state


def _consume_state(state: str) -> str | None:
    """Verifica que state esté en el store y devuelve el callback_url si había."""
    if state not in _state_store:
        return None
    _state_store.discard(state)
    if "|" in state:
        return state.split("|", 1)[1]
    return None


# ---------------- GOOGLE ----------------
@router.get("/google")
async def login_google(callback_url: str | None = None):
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Google OAuth no configurado")
    state = _new_state(callback_url)
    return RedirectResponse(url=google_auth_url(state))


@router.get("/google/callback")
async def google_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    callback_url = _consume_state(state)
    if state and state not in _state_store and "|" in state:
        # consumido OK, callback_url ya extraído
        pass
    try:
        info = await google_exchange_code(code)
    except Exception as e:
        raise HTTPException(400, f"Error con Google: {e}")
    user = await upsert_user_from_oauth(
        db,
        provider="google",
        provider_id=info["id"],
        email=info.get("email", ""),
        name=info.get("name", ""),
        picture_url=info.get("picture", ""),
    )
    return await _emit_tokens_response(user, callback_url)


# ---------------- GITHUB ----------------
@router.get("/github")
async def login_github(callback_url: str | None = None):
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(500, "GitHub OAuth no configurado")
    state = _new_state(callback_url)
    return RedirectResponse(url=github_auth_url(state))


@router.get("/github/callback")
async def github_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    callback_url = _consume_state(state)
    try:
        info = await github_exchange_code(code)
    except Exception as e:
        raise HTTPException(400, f"Error con GitHub: {e}")
    if not info.get("email"):
        raise HTTPException(400, "Tu cuenta de GitHub no tiene email verificado público")
    user = await upsert_user_from_oauth(
        db,
        provider="github",
        provider_id=str(info["id"]),
        email=info.get("email", ""),
        name=info.get("name") or info.get("login", ""),
        picture_url=info.get("avatar_url", ""),
    )
    return await _emit_tokens_response(user, callback_url)


# ---------------- Emisión de tokens ----------------
async def _emit_tokens_response(user: User, callback_url: str | None):
    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    # Si el companion mandó un callback_url (probablemente http://localhost:PUERTO/oauth-done),
    # redirigimos ahí con los tokens en query string.
    if callback_url:
        sep = "&" if "?" in callback_url else "?"
        return RedirectResponse(url=f"{callback_url}{sep}access_token={access}&refresh_token={refresh}")
    # Si no hay callback (login desde web), mostrar una página de éxito.
    return HTMLResponse(content=f"""
    <html><head><title>JARVIS · Login</title>
    <style>body{{font-family:system-ui;background:#050a10;color:#e8f4ff;display:flex;
    align-items:center;justify-content:center;height:100vh;text-align:center}}
    .ok{{color:#4dd4ff;font-size:24px;letter-spacing:0.2em}}
    code{{background:#0f1d2e;padding:4px 8px;border-radius:4px;color:#4dd4ff}}
    </style></head><body><div>
    <div class="ok">✓ AUTENTICADO</div>
    <p>Hola <strong>{user.name or user.email}</strong>.</p>
    <p>Puedes cerrar esta ventana y volver a JARVIS.</p>
    <details style="margin-top:30px"><summary>Tokens (debug)</summary>
    <p>Access: <code style="word-break:break-all">{access}</code></p>
    <p>Refresh: <code style="word-break:break-all">{refresh}</code></p>
    </details></div></body></html>""")


# ---------------- /auth/me + refresh ----------------
@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture_url": user.picture_url,
        "provider": user.provider,
        "subscription": {
            "plan": user.subscription.plan if user.subscription else "free",
            "status": user.subscription.status if user.subscription else "active",
            "trial_ends_at": user.subscription.trial_ends_at.isoformat() if user.subscription and user.subscription.trial_ends_at else None,
        } if user.subscription else None,
    }


class RefreshRequest:
    pass


@router.post("/refresh")
async def refresh_token(payload: dict, db: AsyncSession = Depends(get_db)):
    token = payload.get("refresh_token")
    if not token:
        raise HTTPException(400, "Falta refresh_token")
    user_id = decode_token(token, "refresh")
    from sqlalchemy import select
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "Usuario no encontrado")
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
    }
