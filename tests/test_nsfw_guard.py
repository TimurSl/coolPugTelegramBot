from contextlib import contextmanager

import utils.path_utils as path_utils
from modules.nsfw_guard.detector import NsfwDetectionService
from modules.nsfw_guard.media import MediaFrameCollector
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
        {"label": "neutral", "score": 0.9},
        {"label": "porn", "score": 0.1},
    ]
    nsfw_variants = [
        [
            {"label": "neutral", "score": 0.2},
            {"label": "porn", "score": 0.8},
        ],
        [
            {"label": "normal", "score": 0.2},
            {"label": "nsfw", "score": 0.8},
        ],
    ]

    assert not detector.is_nsfw_label(neutral)
    for result_set in nsfw_variants:
        assert detector.is_nsfw_label(result_set)


def test_gif_frame_extraction():
    collector = MediaFrameCollector()

    from PIL import Image
    from io import BytesIO

    frames = [Image.new("RGB", (10, 10), color=color) for color in [(255, 0, 0), (0, 255, 0)]]
    buffer = BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], loop=0, duration=200)

    extracted = collector._extract_gif_frames(buffer.getvalue(), "test_gif")

    assert len(extracted) == 2
    assert extracted[0].data != extracted[1].data

