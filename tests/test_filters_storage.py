from __future__ import annotations

from modules.filters.storage import MATCH_TYPE_EVENT, FilterStorage
from utils.path_utils import set_home_dir


def test_delete_original_persistence(tmp_path):
    set_home_dir(tmp_path)
    storage = FilterStorage(db_name="test_filters.db")

    template_id = storage.add_template(
        chat_id=123,
        trigger="hello",
        text="hi",
        entities=None,
        media_type=None,
        file_id=None,
        delete_original=True,
    )

    template = storage.get_random_template(123, "hello")

    assert template is not None
    assert template.template_id == template_id
    assert template.delete_original is True


def test_replace_updates_delete_flag(tmp_path):
    set_home_dir(tmp_path)
    storage = FilterStorage(db_name="test_filters.db")
    storage.add_template(
        chat_id=123,
        trigger="hello",
        text="hi",
        entities=None,
        media_type=None,
        file_id=None,
    )

    updated = storage.replace_template(
        chat_id=123,
        trigger="hello",
        template_id=1,
        text="hi",
        entities=None,
        media_type=None,
        file_id=None,
        delete_original=True,
    )

    template = storage.get_random_template(123, "hello")

    assert updated is True
    assert template is not None
    assert template.delete_original is True


def test_event_trigger_is_normalised(tmp_path):
    set_home_dir(tmp_path)
    storage = FilterStorage(db_name="test_filters.db")

    storage.add_template(
        chat_id=1,
        trigger="User_Joined",
        text="welcome",
        entities=None,
        media_type=None,
        file_id=None,
        match_type=MATCH_TYPE_EVENT,
    )

    template = storage.get_random_template(1, "user_joined", match_type=MATCH_TYPE_EVENT)
    assert template is not None
    assert template.pattern == "user_joined"

    definitions = storage.list_filter_definitions(1)
    assert definitions == [("event::user_joined", "user_joined", MATCH_TYPE_EVENT)]
