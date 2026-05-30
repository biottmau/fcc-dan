"""Historial de conversaciones por número de teléfono (SQLite/PostgreSQL)."""

import os
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from dotenv import load_dotenv
load_dotenv(override=False)

DATABASE_URL = os.getenv("WA_DATABASE_URL", "sqlite+aiosqlite:///./faccma_wa.db")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Mensaje(Base):
    __tablename__ = "wa_mensajes"

    id:        Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono:  Mapped[str]      = mapped_column(String(50), index=True)
    role:      Mapped[str]      = mapped_column(String(20))
    content:   Mapped[str]      = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def inicializar_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def guardar_mensaje(telefono: str, role: str, content: str) -> None:
    async with async_session() as session:
        session.add(Mensaje(telefono=telefono, role=role, content=content, timestamp=datetime.utcnow()))
        await session.commit()


async def obtener_historial(telefono: str, limite: int = 20) -> list[dict]:
    async with async_session() as session:
        q = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(limite)
        )
        resultado = await session.execute(q)
        mensajes = resultado.scalars().all()
        mensajes.reverse()
        return [{"role": m.role, "content": m.content} for m in mensajes]


async def limpiar_historial(telefono: str) -> None:
    async with async_session() as session:
        await session.execute(sql_delete(Mensaje).where(Mensaje.telefono == telefono))
        await session.commit()


async def es_nueva_sesion_hoy(telefono: str) -> bool:
    async with async_session() as session:
        hoy = datetime.utcnow().date()
        inicio = datetime(hoy.year, hoy.month, hoy.day)
        q = select(Mensaje.id).where(Mensaje.telefono == telefono).where(Mensaje.timestamp >= inicio).limit(1)
        resultado = await session.execute(q)
        return resultado.scalar() is None
