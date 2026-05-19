"""Endpoints de conversación con JARVIS + inbox móvil→PC."""

import asyncio
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_user, decode_token
from ..db import get_db, AsyncSessionLocal
from ..models import User, InboxItem, ChatTurn
from ..llm import chat_complete
from ..ws_manager import manager

router = APIRouter(tags=["chat"])


# =============================================================
#  Chat síncrono — el companion (o web) manda texto y recibe respuesta
# =============================================================
class ChatRequest(BaseModel):
    text: str
    for_voice: bool = False  # si True, JARVIS evita markdown/emojis


class ChatResponse(BaseModel):
    reply: str
    turn_id: int


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Texto vacío")
    if len(text) > 4000:
        raise HTTPException(400, "Texto demasiado largo (max 4000)")

    try:
        reply = await chat_complete(db, user, text, for_voice=req.for_voice)
    except Exception as e:
        raise HTTPException(500, f"Error del LLM: {e}")

    # Guardar en el historial
    turn = ChatTurn(user_id=user.id, user_text=text, jarvis_text=reply, tools_used=[])
    db.add(turn)
    await db.commit()
    await db.refresh(turn)
    return ChatResponse(reply=reply, turn_id=turn.id)


# =============================================================
#  INBOX — móvil/web mandan tareas asíncronas, companion las recibe
# =============================================================
class InboxQueueRequest(BaseModel):
    prompt: str
    source: str = "mobile_web"   # de dónde viene


class InboxItemOut(BaseModel):
    id: int
    title: str
    prompt: str
    response: str
    status: str
    source: str
    error: str
    created_at: str
    completed_at: Optional[str] = None
    read_at: Optional[str] = None


def _to_out(item: InboxItem) -> InboxItemOut:
    return InboxItemOut(
        id=item.id,
        title=item.title,
        prompt=item.prompt,
        response=item.response,
        status=item.status,
        source=item.source,
        error=item.error,
        created_at=item.created_at.isoformat() if item.created_at else "",
        completed_at=item.completed_at.isoformat() if item.completed_at else None,
        read_at=item.read_at.isoformat() if item.read_at else None,
    )


async def _process_inbox_item_bg(item_id: int, user_id: str):
    """Procesa un item del inbox EN BACKGROUND con su propia sesión de DB."""
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(InboxItem).where(InboxItem.id == item_id))
        item = res.scalar_one_or_none()
        if not item:
            return
        item.status = "processing"
        await db.commit()

        # Cargar usuario
        res = await db.execute(select(User).where(User.id == user_id))
        user = res.scalar_one_or_none()
        if not user:
            item.status = "failed"
            item.error = "Usuario no encontrado"
            await db.commit()
            return

        try:
            reply = await chat_complete(db, user, item.prompt, for_voice=False, max_tokens=1200)
            item.response = reply
            item.status = "ready"
            item.completed_at = dt.datetime.now(dt.timezone.utc)
        except Exception as e:
            item.status = "failed"
            item.error = str(e)[:500]

        await db.commit()
        # Notificar a los companions del usuario que tienen WS abierto
        await manager.send_to_user(user_id, {
            "type": "inbox_item_ready",
            "item_id": item.id,
            "title": item.title,
            "status": item.status,
        })


@router.post("/api/inbox", response_model=InboxItemOut)
async def queue_inbox_item(
    req: InboxQueueRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Encola una tarea para que JARVIS la procese. Devuelve enseguida.
    El usuario puede pedir el resultado después con GET /api/inbox/{id}."""
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt vacío")
    if len(prompt) > 4000:
        raise HTTPException(400, "Prompt demasiado largo")

    # Título auto: primeros 80 chars del prompt
    title = prompt[:80].rstrip() + ("..." if len(prompt) > 80 else "")

    item = InboxItem(
        user_id=user.id,
        prompt=prompt,
        title=title,
        source=req.source[:20],
        status="pending",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    # Lanzar procesamiento en background
    asyncio.create_task(_process_inbox_item_bg(item.id, user.id))

    # Notificar inmediatamente al companion que llegó algo nuevo (en pending)
    asyncio.create_task(manager.send_to_user(user.id, {
        "type": "inbox_item_queued",
        "item_id": item.id,
        "title": item.title,
    }))

    return _to_out(item)


@router.get("/api/inbox", response_model=list[InboxItemOut])
async def list_inbox(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
    only_unread: bool = False,
    limit: int = 50,
):
    """Lista los items del inbox del usuario, más recientes primero."""
    q = select(InboxItem).where(InboxItem.user_id == user.id)
    if only_unread:
        q = q.where(InboxItem.read_at.is_(None))
    q = q.order_by(desc(InboxItem.created_at)).limit(min(limit, 200))
    res = await db.execute(q)
    items = res.scalars().all()
    return [_to_out(i) for i in items]


@router.get("/api/inbox/{item_id}", response_model=InboxItemOut)
async def get_inbox_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    res = await db.execute(
        select(InboxItem).where(InboxItem.id == item_id, InboxItem.user_id == user.id)
    )
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item no encontrado")
    return _to_out(item)


@router.post("/api/inbox/{item_id}/read", response_model=InboxItemOut)
async def mark_inbox_read(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    res = await db.execute(
        select(InboxItem).where(InboxItem.id == item_id, InboxItem.user_id == user.id)
    )
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item no encontrado")
    item.read_at = dt.datetime.now(dt.timezone.utc)
    await db.commit()
    await db.refresh(item)
    return _to_out(item)


@router.delete("/api/inbox/{item_id}")
async def delete_inbox(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    await db.execute(
        delete(InboxItem).where(InboxItem.id == item_id, InboxItem.user_id == user.id)
    )
    await db.commit()
    return {"ok": True}


# =============================================================
#  WebSocket — companion mantiene conexión abierta para recibir pushes
# =============================================================
@router.websocket("/ws/companion")
async def ws_companion(websocket: WebSocket, token: str):
    """El companion se conecta con su access_token como query param.
    Mantiene la conexión abierta para recibir notificaciones de inbox."""
    try:
        user_id = decode_token(token, "access")
    except HTTPException:
        await websocket.close(code=1008)
        return

    await manager.connect(user_id, websocket)
    # Avisar al companion que está conectado
    await websocket.send_json({"type": "connected", "user_id": user_id})

    try:
        while True:
            # Mantener vivo el socket. El companion puede mandar pings
            # o el cliente puede simplemente escuchar.
            msg = await websocket.receive_text()
            # Echo para keepalive opcional
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
    except Exception:
        manager.disconnect(user_id, websocket)
