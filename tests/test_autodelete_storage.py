import pytest

from modules.autodelete.storage import AutoDeleteStorage


def test_toggle_and_is_enabled(tmp_path):
    storage = AutoDeleteStorage(db_name="test_autodelete.db")
    assert storage.db_path.parent == tmp_path
    assert storage.toggle(1, "/start")
    assert storage.is_enabled(1, "/start")
    assert not storage.toggle(1, "/start")
    assert not storage.is_enabled(1, "/start")


def test_normalise_command_validation():
    with pytest.raises(ValueError):
        AutoDeleteStorage.normalise_command("start")
