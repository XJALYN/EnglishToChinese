"""大模型流式翻译 (OpenAI 兼容 API)."""

from __future__ import annotations

from typing import Callable

from src.config import settings_manager
from src.services.llm_client import get_client

SYSTEM_PROMPT = (
    "你是专业同声传译员。将用户给出的英文口语片段翻译成自然流畅的中文。"
    "只输出译文，不要解释，不要加引号或前缀。"
)


class TranslateWorker:
    def __init__(
        self,
        on_token: Callable[[str], None],
        on_complete: Callable[[str], None],
        on_tts_feed: Callable[[str], None] | None = None,
    ):
        self.on_token = on_token
        self.on_complete = on_complete
        self.on_tts_feed = on_tts_feed

    def translate(self, english: str) -> str:
        client = get_client()

        full: list[str] = []
        stream = client.chat.completions.create(
            model=settings_manager.data.translate_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": english},
            ],
            stream=True,
            temperature=0.3,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                full.append(delta)
                self.on_token(delta)
                if self.on_tts_feed:
                    self.on_tts_feed(delta)

        result = "".join(full).strip()
        self.on_complete(result)
        return result
