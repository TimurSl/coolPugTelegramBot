import pytest

from utils.config import load_settings


def test_load_settings_missing_env(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    with pytest.raises(RuntimeError):
        load_settings()


def test_load_settings_reads_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_TOKEN=abc123\nLOG_LEVEL=DEBUG\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    settings = load_settings()
    assert settings.bot_token == "abc123"
    assert settings.log_level == "DEBUG"
