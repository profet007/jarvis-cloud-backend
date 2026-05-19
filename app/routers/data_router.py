"""Endpoints REST para memoria, tareas e historial del usuario."""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_user
from ..db import get_db
from ..models import User, Memory, Task, ChatTurn, BriefingConfig

router = APIRouter(tags=["data"])


# =============================================================
#  MEMORIA
# =============================================================
class MemoryItem(BaseModel):
    id: int
    category: str
    text: str
    created_at: str


class MemoryCreate(BaseModel):
    text: str
    category: str = "general"


@router.get("/api/memory", response_model=list[MemoryItem])
async def list_memory(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    res = await db.execute(
        select(Memory).where(Memory.user_id == user.id).order_by(desc(Memory.created_at))
    )
    return [
        MemoryItem(id=m.id, category=m.category, text=m.text,
                   created_at=m.created_at.isoformat() if m.created_at else "")
        for m in res.scalars().all()
    ]


@router.post("/api/memory", response_model=MemoryItem)
async def add_memory(
    req: MemoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    if not req.text.strip():
        raise HTTPException(400, "Texto vacío")
    m = Memory(user_id=user.id, category=req.category.strip() or "general", text=req.text.strip())
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return MemoryItem(id=m.id, category=m.category, text=m.text,
                      created_at=m.created_at.isoformat() if m.created_at else "")


@router.delete("/api/memory/{memory_id}")
async def delete_memory(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    await db.execute(
        delete(Memory).where(Memory.id == memory_id, Memory.user_id == user.id)
    )
    await db.commit()
    return {"ok": True}


# =============================================================
#  TAREAS
# =============================================================
class TaskItem(BaseModel):
    id: int
    text: str
    priority: str
    done: bool
    created_at: str
    completed_at: Optional[str] = None


class TaskCreate(BaseModel):
    text: str
    priority: str = "normal"


@router.get("/api/tasks", response_model=list[TaskItem])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
    include_done: bool = False,
):
    q = select(Task).where(Task.user_id == user.id)
    if not include_done:
        q = q.where(Task.done == False)  # noqa
    q = q.order_by(desc(Task.created_at))
    res = await db.execute(q)
    return [
        TaskItem(
            id=t.id, text=t.text, priority=t.priority, done=t.done,
            created_at=t.created_at.isoformat() if t.created_at else "",
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
        )
        for t in res.scalars().all()
    ]


@router.post("/api/tasks", response_model=TaskItem)
async def add_task(
    req: TaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    if not req.text.strip():
        raise HTTPException(400, "Texto vacío")
    t = Task(user_id=user.id, text=req.text.strip(), priority=req.priority.lower())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return TaskItem(
        id=t.id, text=t.text, priority=t.priority, done=t.done,
        created_at=t.created_at.isoformat() if t.created_at else "",
        completed_at=None,
    )


@router.post("/api/tasks/{task_id}/complete", response_model=TaskItem)
async def complete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    res = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user.id)
    )
    t = res.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Tarea no encontrada")
    t.done = True
    t.completed_at = dt.datetime.now(dt.timezone.utc)
    await db.commit()
    await db.refresh(t)
    return TaskItem(
        id=t.id, text=t.text, priority=t.priority, done=t.done,
        created_at=t.created_at.isoformat() if t.created_at else "",
        completed_at=t.completed_at.isoformat() if t.completed_at else None,
    )


@router.delete("/api/tasks/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    await db.execute(
        delete(Task).where(Task.id == task_id, Task.user_id == user.id)
    )
    await db.commit()
    return {"ok": True}


# =============================================================
#  HISTORIAL
# =============================================================
class HistoryItem(BaseModel):
    id: int
    user_text: str
    jarvis_text: str
    tools_used: list
    created_at: str


@router.get("/api/history", response_model=list[HistoryItem])
async def list_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
    limit: int = Query(50, ge=1, le=200),
):
    res = await db.execute(
        select(ChatTurn).where(ChatTurn.user_id == user.id)
        .order_by(desc(ChatTurn.created_at)).limit(limit)
    )
    return [
        HistoryItem(
            id=t.id, user_text=t.user_text, jarvis_text=t.jarvis_text,
            tools_used=t.tools_used or [],
            created_at=t.created_at.isoformat() if t.created_at else "",
        )
        for t in res.scalars().all()
    ]


@router.delete("/api/history")
async def clear_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    await db.execute(delete(ChatTurn).where(ChatTurn.user_id == user.id))
    await db.commit()
    return {"ok": True}


# =============================================================
#  BRIEFING CONFIG
# =============================================================
class BriefingOut(BaseModel):
    enabled: bool
    time: str
    timezone: str


class BriefingUpdate(BaseModel):
    enabled: bool
    time: str = "08:00"
    timezone: str = "America/Mexico_City"


@router.get("/api/briefing", response_model=BriefingOut)
async def get_briefing(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    res = await db.execute(
        select(BriefingConfig).where(BriefingConfig.user_id == user.id)
    )
    b = res.scalar_one_or_none()
    if not b:
        return BriefingOut(enabled=False, time="08:00", timezone="America/Mexico_City")
    return BriefingOut(enabled=b.enabled, time=b.time, timezone=b.timezone)


@router.put("/api/briefing", response_model=BriefingOut)
async def set_briefing(
    req: BriefingUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    res = await db.execute(
        select(BriefingConfig).where(BriefingConfig.user_id == user.id)
    )
    b = res.scalar_one_or_none()
    if not b:
        b = BriefingConfig(user_id=user.id)
        db.add(b)
    b.enabled = req.enabled
    b.time = req.time
    b.timezone = req.timezone
    await db.commit()
    return BriefingOut(enabled=b.enabled, time=b.time, timezone=b.timezone)
