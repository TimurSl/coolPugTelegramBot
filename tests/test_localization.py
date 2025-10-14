from utils.localization import LocalizationManager


def test_localization_creates_file(tmp_path):
    manager = LocalizationManager(locales_dir=tmp_path / "locales", default_language="en")
    text = manager.get_text("example.key", default="Hello")
    assert text == "Hello"

    saved = (tmp_path / "locales" / "en.json").read_text(encoding="utf-8")
    assert "example.key" in saved


def test_localization_fallback_to_default(tmp_path):
    manager = LocalizationManager(locales_dir=tmp_path / "locales", default_language="en")
    manager.ensure_key("shared.key", "Value")

    translated = manager.get_text("shared.key", language="uk")
    assert translated == "Value"
