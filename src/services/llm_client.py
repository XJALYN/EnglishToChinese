"""OpenAI 兼容大模型客户端（多厂商）."""

from __future__ import annotations

from openai import OpenAI

from src.config import LLM_PROVIDERS, settings_manager


def get_client() -> OpenAI:
    cfg = settings_manager.data
    api_key = cfg.active_api_key()
    base_url = cfg.active_base_url()
    if not api_key:
        provider = cfg.llm_provider
        label = LLM_PROVIDERS.get(provider, {}).get("label", provider)
        env_key = LLM_PROVIDERS.get(provider, {}).get("env_key", "LLM_API_KEY")
        raise RuntimeError(f"请设置 {label} API Key（{env_key}）")
    if not base_url:
        raise RuntimeError("请设置大模型 Base URL")
    return OpenAI(api_key=api_key, base_url=base_url)


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
