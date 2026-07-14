"""百炼 OpenAI 兼容客户端."""

from __future__ import annotations

from openai import OpenAI

from src.config import settings_manager


def get_client() -> OpenAI:
    cfg = settings_manager.data
    return OpenAI(api_key=cfg.dashscope_api_key, base_url=cfg.dashscope_base_url)


def chat_complete(
    model: str,
    system: str,
    user: str,
    *,
    stream: bool = False,
    on_token=None,
) -> str:
    client = get_client()
    if stream and on_token:
        parts: list[str] = []
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
            temperature=0.5,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                parts.append(delta)
                on_token(delta)
        return "".join(parts).strip()

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.5,
    )
    return (resp.choices[0].message.content or "").strip()
