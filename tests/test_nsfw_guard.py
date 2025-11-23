from contextlib import contextmanager

import utils.path_utils as path_utils
from modules.nsfw_guard.detector import NsfwDetectionService
from modules.nsfw_guard.storage import NsfwSettingsStorage


@contextmanager
def temporary_home(tmp_path):
    original = path_utils.home_dir
    path_utils.set_home_dir(tmp_path)
    try:
        yield tmp_path
    finally:
        path_utils.home_dir = original


def test_storage_enable_disable(tmp_path):
    with temporary_home(tmp_path):
        storage = NsfwSettingsStorage()
        chat_id = 123
        assert not storage.is_chat_enabled(chat_id)

        storage.enable_chat(chat_id)
        assert storage.is_chat_enabled(chat_id)

        storage.disable_chat(chat_id)
        assert not storage.is_chat_enabled(chat_id)


def test_storage_ignore_topics(tmp_path):
    with temporary_home(tmp_path):
        storage = NsfwSettingsStorage()
        chat_id = 123
        topic_id = 10

        storage.enable_chat(chat_id)
        assert not storage.is_topic_ignored(chat_id, topic_id)

        storage.ignore_topic(chat_id, topic_id)
        assert storage.is_topic_ignored(chat_id, topic_id)
        assert storage.list_ignored_topics(chat_id) == {topic_id}

        storage.unignore_topic(chat_id, topic_id)
        assert not storage.is_topic_ignored(chat_id, topic_id)
        assert storage.list_ignored_topics(chat_id) == set()


def test_detector_label_evaluation():
    detector = NsfwDetectionService()

    neutral = [
<<<<<<< ours
        {"label": "neutral", "score": 0.9},
        {"label": "porn", "score": 0.1},
    ]
    nsfw = [
        {"label": "neutral", "score": 0.2},
        {"label": "porn", "score": 0.8},
=======
        {"label": "normal", "score": 0.9},
        {"label": "nsfw", "score": 0.1},
    ]
    nsfw = [
        {"label": "normal", "score": 0.2},
        {"label": "nsfw", "score": 0.8},
>>>>>>> theirs
    ]

    assert not detector.is_nsfw_label(neutral)
    assert detector.is_nsfw_label(nsfw)

