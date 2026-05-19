"""
JARVIS Cloud Backend
====================

Punto de entrada de la API.
"""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from .settings import settings
from .db import init_db
from .routers import auth_router, chat_router, data_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"\n  JARVIS Cloud arrancando en modo {settings.ENV}")
    print(f"  Base de datos: {settings.DATABASE_URL[:50]}...")
    await init_db()
    print(f"  ✓ DB lista")
    print(f"  ✓ API disponible en {settings.BASE_URL}/docs\n")
    yield
    print("Cerrando JARVIS Cloud...")


app = FastAPI(
    title="JARVIS Cloud API",
    version="0.1.0",
    description="Backend para el asistente personal JARVIS.",
    lifespan=lifespan,
)

# CORS — acepta cualquier deploy de Vercel del proyecto + localhost
# Usamos regex porque el usuario puede tener múltiples deploys (production, preview)
# todos válidos a la vez.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://([a-zA-Z0-9-]+\.)?(vercel\.app|jarvisai\.com)|http://localhost(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Routers
app.include_router(auth_router.router)
app.include_router(chat_router.router)
app.include_router(data_router.router)


@app.get("/")
async def root():
    return {
        "service": "JARVIS Cloud",
        "version": "0.1.0",
        "env": settings.ENV,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
