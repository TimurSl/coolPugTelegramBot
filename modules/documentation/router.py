from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.localization import gettext, language_from_message, normalize_language_code

router = Router(name="documentation")
priority = 10

CALLBACK_PREFIX = "help"

DEFAULT_TEXTS = {
    "documentation.sections.overview.title": "ℹ️ Main commands",
    "documentation.sections.overview.button": "Overview",
    "documentation.sections.overview.content.0": "<b>/help</b> — show this help menu.",
    "documentation.sections.overview.content.1": "<b>/ban</b> / <b>/mute</b> — main moderation tools.",
    "documentation.sections.overview.content.2": "<b>/filteradd</b> — add a forbidden-words filter.",
    "documentation.sections.overview.content.3": "<b>/autodelete</b> — configure command auto-delete.",
    "documentation.sections.overview.content.4": "<b>/rpnick</b> — manage your roleplay nickname.",
    "documentation.sections.overview.content.5": "<b>/menu</b> — leave the current menu and return to the main view.",
    "documentation.sections.moderation.title": "🛡 Moderation module",
    "documentation.sections.moderation.button": "Moderation",
    "documentation.sections.moderation.content.0": "<b>/ban</b> — ban a user.",
    "documentation.sections.moderation.content.1": "<b>/unban</b> — restore chat access.",
    "documentation.sections.moderation.content.2": "<b>/mute</b> — restrict sending messages.",
    "documentation.sections.moderation.content.3": "<b>/unmute</b> — lift the restrictions.",
    "documentation.sections.moderation.content.4": "<b>/warn</b> — issue a warning.",
    "documentation.sections.moderation.content.5": "<b>/unwarn</b> — remove a warning.",
    "documentation.sections.moderation.content.6": "<b>/kick</b> — kick a user without a ban.",
    "documentation.sections.moderation.content.7": "<b>/modlevel</b> — assign moderation levels (0 = members, 5 = chat creator; levels control all moderation actions).",
    "documentation.sections.moderation.content.8": "<b>/restrict</b> — list members with a specific moderation level (add <code>mention=off</code> to hide profile links).",
    "documentation.sections.moderation.content.9": "<b>/restrictcommand</b> — limit a command to a specific moderator level.",
    "documentation.sections.moderation.content.10": "<b>/award</b> — give a user a custom award.",
    "documentation.sections.moderation.content.11": "<b>/delreward</b> — remove a previously issued award.",
    "documentation.sections.moderation.content.12": "<b>/mods</b> — show every moderator grouped by level (add <code>mention=off</code> to hide profile links).",
    "documentation.sections.filters.title": "🚦 Filters",
    "documentation.sections.filters.button": "Filters",
    "documentation.sections.filters.content.0": "<b>/filteradd</b> — add a new rule (reply to a message).",
    "documentation.sections.filters.content.1": "<b>/filterlist</b> — show active filters.",
    "documentation.sections.filters.content.2": "<b>/filterreplace</b> — replace filter text.",
    "documentation.sections.filters.content.3": "<b>/filterremove</b> — delete a specific rule.",
    "documentation.sections.filters.content.4": "<b>/filterclear</b> — remove all filters in the chat.",
    "documentation.sections.filters.content.5": "<b>/filterlistall</b> — browse filters saved across chats (admin only).",
    "documentation.sections.filters.content.6": "Use <code>{randomUser}</code>, <code>{randomMention}</code> or <code>{randomRpUser}</code> in templates to mention a random member.",
    "documentation.sections.filters.content.7": "Tags <code>{argument}</code> and <code>{argumentNoQuestion}</code> insert text after the trigger (with or without question marks).",
    "documentation.sections.autodelete.title": "♻️ Auto-delete",
    "documentation.sections.autodelete.button": "Auto-delete",
    "documentation.sections.autodelete.content.0": "<b>/autodelete /command</b> — add a command to auto-delete.",
    "documentation.sections.autodelete.content.1": "<b>/nodelete /command</b> — exclude a command from auto-delete.",
    "documentation.sections.autodelete.content.2": "<b>/autodeletelist</b> — show the command list.",
    "documentation.sections.entertainment.title": "🎭 Entertainment",
    "documentation.sections.entertainment.button": "Entertainment",
    "documentation.sections.entertainment.content.0": "<b>/joke</b> — random joke.",
    "documentation.sections.entertainment.content.1": "<b>/amd</b> / <b>/intel</b> — themed memes.",
    "documentation.sections.entertainment.content.2": "<b>/perdoon</b>, <b>/politics</b>, <b>/murzik</b> — random responses.",
    "documentation.sections.entertainment.content.3": "<b>/holos</b>, <b>/quran</b>, <b>/bible</b> — curated quotes.",
    "documentation.sections.roleplay.title": "🎲 Roleplay",
    "documentation.sections.roleplay.button": "Roleplay",
    "documentation.sections.roleplay.content.0": "<b>/rpnick</b> — set a roleplay nickname.",
    "documentation.sections.roleplay.content.1": "<b>/rpnickclear</b> — reset the nickname.",
    "documentation.sections.roleplay.content.2": "<b>/addrp</b> — add a roleplay action.",
    "documentation.sections.roleplay.content.3": "<b>/delrp</b> — remove an action.",
    "documentation.sections.roleplay.content.4": "<b>/listrp</b> — show the current set.",
    "documentation.sections.roleplay.content.5": "<b>/profile</b> — view your RP profile.",
    "documentation.sections.settings.title": "⚙️ Settings",
    "documentation.sections.settings.button": "Settings",
    "documentation.sections.settings.content.0": "<b>/language</b> — choose the bot language for this chat.",
    "documentation.unknown_section": "Unknown section",
}

SECTIONS = {
    "overview": {
        "title_key": "documentation.sections.overview.title",
        "button_key": "documentation.sections.overview.button",
        "content_keys": [
            "documentation.sections.overview.content.0",
            "documentation.sections.overview.content.1",
            "documentation.sections.overview.content.2",
            "documentation.sections.overview.content.3",
            "documentation.sections.overview.content.4",
            "documentation.sections.overview.content.5",
        ],
    },
    "moderation": {
        "title_key": "documentation.sections.moderation.title",
        "button_key": "documentation.sections.moderation.button",
        "content_keys": [
            "documentation.sections.moderation.content.0",
            "documentation.sections.moderation.content.1",
            "documentation.sections.moderation.content.2",
            "documentation.sections.moderation.content.3",
            "documentation.sections.moderation.content.4",
            "documentation.sections.moderation.content.5",
            "documentation.sections.moderation.content.6",
            "documentation.sections.moderation.content.7",
            "documentation.sections.moderation.content.8",
            "documentation.sections.moderation.content.9",
            "documentation.sections.moderation.content.10",
            "documentation.sections.moderation.content.11",
            "documentation.sections.moderation.content.12",
        ],
    },
    "filters": {
        "title_key": "documentation.sections.filters.title",
        "button_key": "documentation.sections.filters.button",
        "content_keys": [
            "documentation.sections.filters.content.0",
            "documentation.sections.filters.content.1",
            "documentation.sections.filters.content.2",
            "documentation.sections.filters.content.3",
            "documentation.sections.filters.content.4",
            "documentation.sections.filters.content.5",
            "documentation.sections.filters.content.6",
            "documentation.sections.filters.content.7",
        ],
    },
    "autodelete": {
        "title_key": "documentation.sections.autodelete.title",
        "button_key": "documentation.sections.autodelete.button",
        "content_keys": [
            "documentation.sections.autodelete.content.0",
            "documentation.sections.autodelete.content.1",
            "documentation.sections.autodelete.content.2",
        ],
    },
    "roleplay": {
        "title_key": "documentation.sections.roleplay.title",
        "button_key": "documentation.sections.roleplay.button",
        "content_keys": [
            "documentation.sections.roleplay.content.0",
            "documentation.sections.roleplay.content.1",
            "documentation.sections.roleplay.content.2",
            "documentation.sections.roleplay.content.3",
            "documentation.sections.roleplay.content.4",
            "documentation.sections.roleplay.content.5",
        ],
    },
    "settings": {
        "title_key": "documentation.sections.settings.title",
        "button_key": "documentation.sections.settings.button",
        "content_keys": [
            "documentation.sections.settings.content.0",
        ],
    },
}

SECTION_ORDER = [
    "overview",
    "moderation",
    "filters",
    "autodelete",
    "roleplay",
    "settings",
]


def _translate(key: str, language: str) -> str:
    default_value = DEFAULT_TEXTS[key]
    return gettext(key, language=language, default=default_value)


def build_keyboard(active_key: str, language: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key in SECTION_ORDER:
        section = SECTIONS[key]
        label = _translate(section["button_key"], language)
        if key == active_key:
            label = f"• {label}"
        builder.button(text=label, callback_data=f"{CALLBACK_PREFIX}:{key}")
    builder.adjust(2)
    return builder.as_markup()


def render_section(key: str, language: str) -> str:
    section = SECTIONS[key]
    header = f"<b>{_translate(section['title_key'], language)}</b>\n"
    body = "\n".join(
        _translate(content_key, language) for content_key in section["content_keys"]
    )
    return f"{header}{body}"


@router.message(Command("help"))
async def command_help(message: Message) -> None:
    active_key = "overview"
    language = language_from_message(message)
    await message.answer(
        render_section(active_key, language),
        reply_markup=build_keyboard(active_key, language),
    )


@router.callback_query(F.data.startswith(f"{CALLBACK_PREFIX}:"))
async def callback_help(callback: CallbackQuery) -> None:
    language = normalize_language_code(callback.from_user.language_code)
    key = callback.data.split(":", 1)[1]
    if key not in SECTIONS:
        await callback.answer(
            _translate("documentation.unknown_section", language), show_alert=True
        )
        return

    try:
        await callback.message.edit_text(
            render_section(key, language),
            reply_markup=build_keyboard(key, language),
        )
    except Exception:
        pass

    await callback.answer()
