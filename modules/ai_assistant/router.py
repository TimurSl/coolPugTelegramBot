from __future__ import annotations

import html
import json
import logging
from typing import Sequence

from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram import Bot

from modules.base import Module
from modules.ai_assistant.memory import AIMemoryRepository, MemoryEntry
from utils.localization import gettext, language_from_message

AI_MARKER = "🤖 AI Assistant"


class DummyAIClient:
    """Simple stand-in that produces deterministic JSON responses."""

    def generate(self, prompt: str, memories: Sequence[MemoryEntry]) -> str:
        prompt = prompt.strip()
        summary_from_user = (
            f"User asked about '{prompt[:60]}'" if prompt else "User shared an empty prompt"
        )
        summary_from_ai = "Shared a helpful summary"

        intro = "I'm a friendly placeholder AI."
        details = (
            "I do not access the internet, but I can reflect on your message and prior memories."
        )
        if prompt:
            analysis = f"You said: {prompt}"
        else:
            analysis = "You did not provide additional details."

        payload = {
            "message": "\n".join([intro, details, analysis]),
            "summary_from_user": summary_from_user,
            "summary_from_ai": summary_from_ai,
        }
        return json.dumps(payload)


class AIAssistantModule(Module):
    """Handle /ask requests and maintain lightweight conversation memories."""

    def __init__(self) -> None:
        super().__init__("ai_assistant", priority=70)
        self._logger = logging.getLogger(__name__)
        self._memory = AIMemoryRepository()
        self._client = DummyAIClient()

    async def register(self, container) -> None:  # type: ignore[override]
        self.router.message.register(self._handle_ask_command, Command("ask"))
        self.router.message.register(self._handle_reply_to_ai, F.reply_to_message)

    async def _handle_ask_command(self, message: Message, bot: Bot) -> None:
        if not self.enabled:
            return
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
            return
        reply = message.reply_to_message
        if reply is None or reply.from_user is None or not reply.from_user.is_bot:
            return
        if AI_MARKER not in (reply.text or ""):
            return

        prompt = (message.text or message.caption or "").strip()
        if not prompt:
            return

        language = language_from_message(message)
        await self._process_request(message, prompt, language)

    async def _process_request(self, message: Message, prompt: str, language: str) -> None:
        user = message.from_user
        if user is None:
            return

        previous_memories = self._memory.get_recent(user.id, limit=3)
        payload = self._call_ai(prompt, previous_memories)

        safe_message = self._compose_message(payload, previous_memories, language)
        await message.reply(safe_message, parse_mode="HTML", disable_web_page_preview=True)

        self._memory.add_memory(
            username=user.username,
            user_id=user.id,
            user_summary=payload["summary_from_user"],
            ai_summary=payload["summary_from_ai"],
        )

    def _call_ai(self, prompt: str, memories: Sequence[MemoryEntry]) -> dict:
        raw_response = self._client.generate(prompt, memories)
        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            self._logger.exception("Failed to decode AI response: %s", raw_response)
            parsed = {
                "message": "I encountered an internal error while forming a response.",
                "summary_from_user": f"User prompt: {prompt[:60]}",
                "summary_from_ai": "Encountered an internal error.",
            }

        parsed.setdefault("message", "")
        parsed.setdefault("summary_from_user", f"User prompt: {prompt[:60]}")
        parsed.setdefault("summary_from_ai", "Provided a generic answer.")
        return parsed

    def _compose_message(
        self,
        payload: dict,
        memories: Sequence[MemoryEntry],
        language: str,
    ) -> str:
        base_message = str(payload.get("message", "")).strip()
        safe_base = html.escape(base_message).replace("\n", "<br>") or html.escape(
            gettext(
                "ai.ask.empty_reply",
                language=language,
                default="I do not have anything to add right now.",
            )
        )

        lines: list[str] = [f"<b>{AI_MARKER}</b>"]
        lines.append("<br>")
        lines.append(safe_base)

        if memories:
            lines.append("<br><br>")
            lines.append(
                html.escape(
                    gettext(
                        "ai.ask.memory.header",
                        language=language,
                        default="🧠 Recent memories:",
                    )
                )
            )
            memory_lines: list[str] = []
            for entry in memories:
                memory_lines.append(
                    gettext(
                        "ai.ask.memory.entry",
                        language=language,
                        default="• {user} → {ai}",
                        user=html.escape(entry.user_summary),
                        ai=html.escape(entry.ai_summary),
                    )
                )
            lines.append("<br>".join(memory_lines))

        return "".join(lines)


module = AIAssistantModule()
router = module.get_router()
priority = module.priority