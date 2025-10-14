from modules.filters.storage import (
    MATCH_TYPE_CONTAINS,
    MATCH_TYPE_REGEX,
    FilterStorage,
)


def test_filter_storage_add_and_list(tmp_path):
    storage = FilterStorage(db_name="filters_test.db")
    template_id = storage.add_template(
        1,
        "hello",
        text="Hi there",
        entities=None,
        media_type=None,
        file_id=None,
    )
    assert template_id == 1

    templates = storage.list_templates(1, "hello")
    assert len(templates) == 1
    assert templates[0].text == "Hi there"
    assert templates[0].match_type == MATCH_TYPE_CONTAINS


def test_filter_storage_regex(tmp_path):
    storage = FilterStorage(db_name="filters_test.db")
    storage.add_template(
        1,
        r"h.*o",
        text="Hi",
        entities=None,
        media_type=None,
        file_id=None,
        match_type=MATCH_TYPE_REGEX,
    )

    assert storage.has_templates(1, r"h.*o", match_type=MATCH_TYPE_REGEX)
    template = storage.get_random_template(1, r"h.*o", match_type=MATCH_TYPE_REGEX)
    assert template is not None
    assert template.match_type == MATCH_TYPE_REGEX
