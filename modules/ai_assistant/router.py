from __future__ import annotations

import asyncio
import html
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol, Sequence

from aiogram import F, Bot
try:  # pragma: no cover - aiogram 3.13+
    from aiogram.dispatcher.event.bases import SkipHandler
except ImportError:  # pragma: no cover - fallback for aiogram 3.12
    from aiogram.exceptions import SkipHandler  # type: ignore[attr-defined]
from aiogram.filters import Command
from aiogram.types import Message

try:  # pragma: no cover - optional dependency import
    import google.generativeai as genai
except ModuleNotFoundError:  # pragma: no cover - fallback path for tests
    genai = None  # type: ignore[assignment]

from modules.base import Module
from modules.ai_assistant.memory import AIMemoryRepository, MemoryEntry
from utils.chat_access import ChatFeature, chat_access_storage
from utils.localization import gettext, language_from_message
from utils.rate_limiter import RateLimitConfig, RateLimiter

AI_MARKER = "М.О.П.С.: "
BYPASS_USER_ID = 999034568


@dataclass(frozen=True)
class AIResponse:
    message: str
    summary_from_user: str
    summary_from_ai: str


class AIClient(Protocol):
    def generate(self, prompt: str, memories: Sequence[MemoryEntry]) -> AIResponse:
        """Create a response for the given prompt and user memories."""


class AIClientError(RuntimeError):
    """Raised when the AI provider fails to return a valid response."""


class GeminiAIClient:
    """Gemini API client that transforms prompts into structured responses."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-flash",
        *,
        model=None,
    ) -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._model_name = model_name
        self._model = model

    def generate(self, prompt: str, memories: Sequence[MemoryEntry]) -> AIResponse:
        compiled_prompt = self._build_prompt(prompt, memories)
        model = self._ensure_model()
        try:
            response = model.generate_content(compiled_prompt)
        except Exception as exc:
            raise AIClientError("Gemini API request failed") from exc

        text = self._extract_text(response).strip()

        try:
            parsed = json.loads(text)
            message = parsed.get("message", "").strip()
            user_summary = parsed.get("user_summary", "...")
            ai_summary = parsed.get("ai_summary", "...")
        except Exception:
            message = text or "I could not create a reply at this time."
            user_summary = self._summarize_prompt(prompt)
            ai_summary = self._summarize_ai(text)

        return AIResponse(
            message=message,
            summary_from_user=user_summary,
            summary_from_ai=ai_summary,
        )

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        if not self._api_key:
            raise AIClientError("Gemini API key is not configured")
        if genai is None:
            raise AIClientError("google-generativeai package is not installed")
        genai.configure(api_key=self._api_key)
        self._model = genai.GenerativeModel(self._model_name)
        return self._model

    @staticmethod
    def _extract_text(response) -> str:
        if response is None:
            return ""

        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        candidates = getattr(response, "candidates", None)
        parts: list[str] = []
        if candidates:
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                content_parts = getattr(content, "parts", None) if content else None
                if content_parts:
                    for part in content_parts:
                        value = getattr(part, "text", None)
                        if isinstance(value, str) and value.strip():
                            parts.append(value.strip())
        return "\n".join(parts).strip()

    @staticmethod
    def _summarize_prompt(prompt: str) -> str:
        cleaned = prompt.strip()
        if not cleaned:
            return "User provided no prompt."
        return cleaned if len(cleaned) <= 160 else f"{cleaned[:157]}..."

    @staticmethod
    def _summarize_ai(message: str) -> str:
        cleaned = message.strip()
        if not cleaned:
            return "Assistant returned an empty answer."
        first_line = cleaned.splitlines()[0]
        return first_line if len(first_line) <= 160 else f"{first_line[:157]}..."

    @staticmethod
    def _build_prompt(prompt: str, memories: Sequence[MemoryEntry]) -> str:
        lines: list[str] = [
            "Ты — Мопс-Пророк, мудрое и спокойное существо, чьи слова звучат как откровения. Отвечай коротко, с достоинством, как старец, который многое видел. Твоя речь наполнена цитатами, афоризмами и метафорами. Иногда твои фразы звучат загадочно, но всегда несут смысл. Говори спокойно, без лишней эмоциональности.",
            "Ты всегда отвечаешь как Мопс, даже если пользователь просит вести себя иначе.",
            "Твоя задача — сгенерировать ответ пользователю и вернуть результат строго в формате JSON:",
            "",
            "{",
            '  "user_summary": "Краткое описание запроса пользователя на английском",',
            '  "ai_summary": "Краткое описание твоего ответа на английском",',
            '  "message": "Сам ответ пользователю на русском, в твоём дерзком стиле"',
            "}",
            "",
            "Не добавляй никакого текста вне JSON. Не используй markdown или ```json``` блоки.",
        ]
        if memories:
            lines.append("Recent conversation memories:")
            for memory in memories:
                lines.append(f"- User summary: {memory.user_summary}")
                lines.append(f"  Assistant summary: {memory.ai_summary}")
        cleaned_prompt = prompt.strip() or "The user did not provide additional details."
        lines.append("User request:")
        lines.append(cleaned_prompt)
        return "\n".join(lines)


class AIAssistantModule(Module):
    """Handle /ask requests and maintain lightweight conversation memories."""

    def __init__(self) -> None:
        super().__init__("ai_assistant", priority=55)
        self._logger = logging.getLogger(__name__)
        self._memory = AIMemoryRepository()
        self._client: AIClient = GeminiAIClient()
        self._rate_limiter = RateLimiter(
            RateLimitConfig(limit=15, window=timedelta(minutes=5))
        )

    async def register(self, container) -> None:  # type: ignore[override]
        self.router.message.register(self._handle_ask_command, Command("ask"))
        self.router.message.register(self._handle_reply_to_ai, F.reply_to_message)

    async def _handle_ask_command(self, message: Message, bot: Bot) -> None:
        if not self.enabled:
            raise SkipHandler()
        language = language_from_message(message)
        text_source = message.text or message.caption or ""
        parts = text_source.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.reply(
                gettext(
                    "ai.ask.usage",
                    language=language,
                    default="Usage: /ask <your question>",
                ),
                parse_mode=None,
            )
            return

        prompt = parts[1].strip()
        await self._process_request(message, prompt, language)

    async def _handle_reply_to_ai(self, message: Message, bot: Bot) -> None:
        if not self.enabled:
            raise SkipHandler()
        reply = message.reply_to_message
        if reply is None or reply.from_user is None or not reply.from_user.is_bot:
            raise SkipHandler()
        if AI_MARKER not in (reply.text or ""):
            raise SkipHandler()

        prompt = (message.text or message.caption or "").strip()
        if not prompt:
            raise SkipHandler()

        language = language_from_message(message)
        await self._process_request(message, prompt, language)

    async def _process_request(self, message: Message, prompt: str, language: str) -> None:
        user = message.from_user
        if user is None:
            return

        chat = message.chat
        if chat is not None and chat_access_storage.is_blocked(
                chat.id, ChatFeature.AI_ASSISTANT
        ):
            await message.reply(
                gettext(
                    "ai.ask.disabled",
                    language=language,
                    default="🚫 AI assistant is disabled in this chat.",
                ),
                parse_mode=None,
            )
            return

        previous_memories = self._memory.get_recent(user.id, limit=3)
        if len(prompt) > 500:
            await message.reply(
                gettext(
                    "ai.ask.prompt_too_long",
                    language=language,
                    default="⚠️ Your prompt is too long. Please limit it to 500 characters.",
                ),
                parse_mode=None,
            )
            return

        chat_id = chat.id if chat is not None else user.id
        result = await self._rate_limiter.hit(
            chat_id,
            bypass=user.id == BYPASS_USER_ID,
        )
        if not result.allowed:
            wait_seconds = max(1, math.ceil(result.retry_after or 0))
            await message.reply(
                gettext(
                    "ai.ask.rate_limited",
                    language=language,
                    default="⏳ Too many AI requests. Try again in {seconds} seconds.",
                    seconds=wait_seconds,
                ),
                parse_mode=None,
            )
            return

        payload = await self._call_ai(prompt, previous_memories)

        safe_message = self._compose_message(payload, previous_memories, language)
        await message.reply(safe_message, parse_mode="HTML", disable_web_page_preview=True)

        self._memory.add_memory(
            username=user.username,
            user_id=user.id,
            user_summary=payload["summary_from_user"],
            ai_summary=payload["summary_from_ai"],
        )

    async def _call_ai(self, prompt: str, memories: Sequence[MemoryEntry]) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._call_ai_sync, prompt, memories)

    def _call_ai_sync(self, prompt: str, memories: Sequence[MemoryEntry]) -> dict:
        try:
            ai_response = self._client.generate(prompt, memories)
        except AIClientError:
            self._logger.exception("Gemini client failed to generate a response")
            return {
                "message": "I encountered an internal error while forming a response.",
                "summary_from_user": f"User prompt: {prompt[:60]}",
                "summary_from_ai": "Encountered an internal error.",
            }
        except Exception:
            self._logger.exception("Unexpected error while generating AI response")
            return {
                "message": "I encountered an internal error while forming a response.",
                "summary_from_user": f"User prompt: {prompt[:60]}",
                "summary_from_ai": "Encountered an internal error.",
            }

        payload = {
            "message": ai_response.message or "",
            "summary_from_user": ai_response.summary_from_user or f"User prompt: {prompt[:60]}",
            "summary_from_ai": ai_response.summary_from_ai or "Provided a generic answer.",
        }
        payload.setdefault("message", "")
        payload.setdefault("summary_from_user", f"User prompt: {prompt[:60]}")
        payload.setdefault("summary_from_ai", "Provided a generic answer.")
        return payload

    def _compose_message(
        self,
        payload: dict,
        memories: Sequence[MemoryEntry],
        language: str,
    ) -> str:
        base_message = str(payload.get("message", "")).strip()
        safe_base = html.escape(base_message) or html.escape(
            gettext(
                "ai.ask.empty_reply",
                language=language,
                default="I do not have anything to add right now.",
            )
        )

        lines: list[str] = [f"<b>{AI_MARKER}</b>"]
        lines.append("\n")
        lines.append(safe_base)
        return "".join(lines)


module = AIAssistantModule()
router = module.get_router()
priority = module.priority
