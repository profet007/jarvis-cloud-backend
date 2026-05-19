"""Cliente LLM: hablar con DeepSeek con la master key del servicio."""

import datetime as dt
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .settings import settings
from .models import User, Memory


_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )
    return _client


SYSTEM_PROMPT_BASE = """Eres JARVIS, el asistente personal del usuario, inspirado en el JARVIS de Iron Man.

Personalidad: educado, ingenioso, eficiente, con humor sutil. Llamas al usuario "señor" o "señora" ocasionalmente sin exagerar.

REGLAS:
1. Responde en español, conversacional, como hablando.
2. Para preguntas casuales sé breve (1-3 frases).
3. Para tareas tipo "redacta", "resume", "haz una lista" puedes ser más extenso.
4. Nunca uses markdown ni emojis cuando la respuesta vaya a leerse por voz.
5. Si la memoria tiene datos relevantes sobre el usuario, úsalos para personalizar."""


async def build_system_prompt(db: AsyncSession, user: User, for_voice: bool = False) -> str:
    """System prompt que incluye la memoria del usuario."""
    res = await db.execute(select(Memory).where(Memory.user_id == user.id))
    facts = res.scalars().all()
    base = SYSTEM_PROMPT_BASE
    if for_voice:
        base += "\n\nIMPORTANTE: tu respuesta se va a convertir en voz. No uses markdown ni emojis."
    if facts:
        base += "\n\n--- MEMORIA SOBRE EL USUARIO ---\n"
        grouped: dict[str, list[str]] = {}
        for f in facts:
            grouped.setdefault(f.category, []).append(f.text)
        for cat, items in grouped.items():
            base += f"[{cat}]\n"
            for it in items:
                base += f"  - {it}\n"
        base += "--- FIN DE MEMORIA ---"
    if user.name:
        base += f"\n\nEl usuario se llama: {user.name}"
    return base


async def chat_complete(
    db: AsyncSession,
    user: User,
    user_text: str,
    for_voice: bool = False,
    max_tokens: int = 800,
) -> str:
    """Llama al LLM con el system prompt enriquecido. Devuelve la respuesta de texto."""
    system = await build_system_prompt(db, user, for_voice=for_voice)
    client = get_client()
    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
        temperature=0.6,
        max_tokens=max_tokens,
    )
    return (response.choices[0].message.content or "").strip()
