"""Conexión a la base de datos."""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from .settings import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """Dependency de FastAPI para obtener una sesión de DB."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Crea las tablas si no existen (solo dev — en prod usar Alembic)."""
    # Importar todos los modelos para que se registren
    from . import models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
