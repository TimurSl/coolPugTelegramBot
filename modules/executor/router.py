from __future__ import annotations

import html
import logging
import json
import os

import aiohttp
from aiogram import F, Bot, Router
from aiogram.filters import Command
from aiogram.types import Message
from modules.executor.safe_utils import ast_sanitize

from modules.base import Module
from utils.localization import gettext, language_from_message

PISTON_API_URL = "https://emkc.org/api/v2/piston/execute"
JUDGE0_URL = os.getenv("JUDGE0_URL", "http://127.0.0.1:2358")
JUDGE0_LANG_ID = int(os.getenv("JUDGE0_LANGUAGE_ID", "71"))
EXEC_MARKER = "🧪 Executor: "

class ExecutorModule(Module):
    """Handle /exec requests and execute Python code in a remote sandbox."""

    def __init__(self, pass_router=None) -> None:
        super().__init__("executor", priority=60)
        self._logger = logging.getLogger(__name__)
        self.router = pass_router or Router(name="executor")

    async def register(self, container) -> None:  # type: ignore[override]
        self.router.message.register(self._handle_exec_command, Command("exec"))

    async def _handle_exec_command(self, message: Message, bot: Bot) -> None:
        if not self.enabled:
            return

        text = message.text or message.caption or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply(
                gettext(
                    "executor.usage",
                    language_from_message(message),
                    default="Usage: /exec <python code>",
                ),
                parse_mode=None,
            )
            return

        code = parts[1].strip()
        await self._execute_code(message, code)

    async def _handle_reply_exec(self, message: Message, bot: Bot) -> None:
        if not self.enabled:
            return

        reply = message.reply_to_message
        if reply is None or reply.from_user is None or not reply.from_user.is_bot:
            return
        if EXEC_MARKER not in (reply.text or ""):
            return

        code = (message.text or message.caption or "").strip()
        if not code:
            return

        await self._execute_code(message, code)

    async def _execute_code(self, message: Message, code: str) -> None:
        lang = language_from_message(message)
        if len(code) > 1000:
            await message.reply(
                gettext(
                    "executor.code_too_long",
                    lang,
                    default="⚠️ Code is too long. Limit: 1000 characters.",
                )
            )
            return

        # Basic sanitization before sending to sandbox
        is_allowed, reason = ast_sanitize(code)
        if not is_allowed:
            await message.reply(
                gettext(
                    "executor.forbidden",
                    lang,
                    default="🚫 Disallowed operation detected. Reason: {reason}",
                )
            )
            return

        try:
            result = await self._run_in_piston(code)
        except Exception:
            self._logger.exception("Executor request failed")
            await message.reply(
                gettext(
                    "executor.error",
                    lang,
                    default="💥 Executor internal error.",
                )
            )
            return

        output = result.get("output", "").strip()
        if not output:
            output = gettext(
                "executor.no_output",
                lang,
                default="(no output)",
            )

        safe_output = html.escape(output)
        safe_code = html.escape(code[:300])
        reply_text = (
            f"<b>{EXEC_MARKER}</b>\n"
            f"<pre><code>{safe_code}</code></pre>\n"
            f"<b>Output:</b>\n<pre><code>{safe_output[:1800]}</code></pre>"
        )

        await message.reply(reply_text, parse_mode="HTML", disable_web_page_preview=True)

    async def _run_in_piston(self, code: str) -> dict:
        """Send code to local Judge0 sandbox."""
        payload = {
            "language_id": JUDGE0_LANG_ID,
            "source_code": code,
            "stdin": "",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{JUDGE0_URL}/submissions?base64_encoded=false&wait=true",
                json=payload,
                timeout=15
            ) as resp:
                data = await resp.json()

        stdout = data.get("stdout") or ""
        stderr = data.get("stderr") or ""
        msg = data.get("message") or ""

        # merge into one output like before
        output = stdout
        if stderr:
            output += f"\nERR:\n{stderr}"
        if msg:
            output += f"\nSYS:\n{msg}"

        return {"output": output.strip()}


router = Router(name="executor")
module = ExecutorModule(pass_router=router)
priority = 56
