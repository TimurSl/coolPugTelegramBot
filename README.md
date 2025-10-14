# CoolPugBot

CoolPugBot is a modular [Aiogram 3](https://docs.aiogram.dev/) Telegram bot that bundles
moderation, entertainment and utility commands with extensive localisation support.
The repository now includes environment-based configuration, structured logging and
unit tests so it can be shared and maintained as an open-source project.

## Features

- Modular architecture with dependency injection and dynamic module discovery.
- Roleplay, entertainment, moderation, filters, auto-delete and statistics modules.
- JSON-based localisation with runtime key generation.
- Structured logging to rotating text and JSON files for easier observability.
- Comprehensive documentation of bot commands.

## Requirements

- Python 3.11+
- A Telegram bot token obtained from [@BotFather](https://t.me/BotFather)

Install dependencies with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root (or provide variables directly in the
environment) with the following variables:

| Variable    | Description                                              |
|-------------|----------------------------------------------------------|
| `BOT_TOKEN` | Telegram bot token from BotFather (**required**).        |
| `LOG_LEVEL` | Optional logging level for console output (default `INFO`). |

The application loads the `.env` file automatically on startup and will raise a
`RuntimeError` if any required variables are missing.

## Running the bot

```bash
python main.py
```

Logs are written to `logs/` as a timestamped text file, a rolling `latest.log`
and a JSONL file that is ready for ingestion into log analysis tools.

## Tests

The project ships with unit tests covering configuration loading, localisation and
storage helpers.

```bash
pytest
```

## Command reference

Below is a high-level overview of the commands provided by the bundled modules.
Use `/help` in chat to access an interactive version of this documentation.

### Overview

| Command      | Description                                |
|--------------|--------------------------------------------|
| `/help`      | Show the interactive help menu.             |
| `/menu`      | Exit the current menu.                      |

### Moderation

| Command              | Description |
|----------------------|-------------|
| `/ban`               | Ban a user (supports duration and reason). |
| `/unban`             | Remove a ban. |
| `/mute`              | Temporarily or permanently mute a user. |
| `/unmute`            | Remove mute restrictions. |
| `/warn`              | Issue a warning. Automatically mutes after three warnings. |
| `/unwarn`            | Remove a warning. |
| `/kick`              | Kick without ban. |
| `/modlevel`          | Assign moderation levels (0–5). |
| `/restrict`          | List members with a specific moderation level. |
| `/restrictcommand`   | Restrict commands to a minimum level. |
| `/award` / `/delreward` | Manage custom awards. |
| `/mods`              | List moderators with optional mentions. |

### Filters

| Command            | Description |
|--------------------|-------------|
| `/filteradd`       | Add a filter (reply to a template message). |
| `/filterlist`      | View filters for a trigger. |
| `/filterreplace`   | Replace an existing filter template. |
| `/filterremove`    | Delete a filter template. |
| `/filterclear`     | Clear all filters for a trigger. |
| `/filterlistall`   | List every stored filter in the chat. |

Supported placeholders inside filter templates:
`{randomUser}`, `{randomMention}`, `{randomRpUser}`, `{argument}` and `{argumentNoQuestion}`.

### Auto-delete

| Command             | Description |
|---------------------|-------------|
| `/autodelete`       | Toggle auto-deleting a command. |
| `/nodelete`         | Explicitly disable auto-delete for a command. |
| `/autodeletelist`   | Show the configured auto-delete commands. |

### Entertainment

| Command            | Description |
|--------------------|-------------|
| `/joke`            | Send a random programming joke. |
| `/amd`, `/intel`   | Send themed stickers. |
| `/perdoon`, `/politics`, `/murzik`, `/holos` | Send curated memes. |
| `/quran`, `/bible` | Fetch inspirational verses. |

### Roleplay

| Command            | Description |
|--------------------|-------------|
| `/rpnick` / `/rpnickclear` | Manage roleplay nicknames. |
| `/addrp` / `/delrp`        | Manage roleplay actions. |
| `/listrp`                 | List available actions. |
| `/profile`                | Show roleplay stats for a user. |

### Settings & statistics

| Command        | Description |
|----------------|-------------|
| `/language`    | Change the bot language for the current chat or private conversation. |
| `/top`         | Show the top message senders for the current chat. |

## Localisation

All localisation files live in `locales/`. New languages can be added by copying
`locales/en.json` and translating the values. When the bot encounters a missing
key it automatically records the default string, making it easy to keep
translations in sync.

## Contributing

1. Fork and clone the repository.
2. Create a virtual environment and install dependencies.
3. Run `pytest` before submitting pull requests.
4. Ensure new strings are wrapped in `gettext()` so they can be localised.

