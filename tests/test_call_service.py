import re
from random import Random

import pytest

from modules.roleplay.call_service import CallCommandService


@pytest.fixture()
def call_service() -> CallCommandService:
    return CallCommandService(
        emojis=("🎈", "🎋", "🎇"),
        batch_size=5,
        random_choice=Random(0).choice,
    )


def test_build_call_messages_batches_mentions(call_service: CallCommandService) -> None:
    template = "{caller} is calling everyone! {mentions}"
    user_ids = list(range(1, 8))

    messages = call_service.build_call_messages("Caller", template, user_ids)

    assert len(messages) == 2
    pattern = re.compile(r'<a href="tg://user\?id=(\d+)">')
    first_mentions = pattern.findall(messages[0])
    second_mentions = pattern.findall(messages[1])

    assert len(first_mentions) == 5
    assert len(second_mentions) == 2


def test_build_call_messages_deduplicates(call_service: CallCommandService) -> None:
    template = "{caller} is calling everyone! {mentions}"
    user_ids = [42, 42, "not-int", 13]

    messages = call_service.build_call_messages("Caller", template, user_ids)

    assert len(messages) == 1
    pattern = re.compile(r'<a href="tg://user\?id=(\d+)">')
    ids = {int(match) for match in pattern.findall(messages[0])}
    assert ids == {42, 13}


def test_build_call_messages_empty(call_service: CallCommandService) -> None:
    template = "{caller} is calling everyone! {mentions}"

    assert call_service.build_call_messages("Caller", template, []) == []
