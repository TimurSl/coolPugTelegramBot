from modules.moderation.router import AdvancedModerationModule, ModeratorDisplay


def test_strip_link_markup_with_anchor():
    anchor = '<a href="https://t.me/example">Nick &amp; Co</a>'
    result = AdvancedModerationModule._strip_link_markup(anchor)
    assert result == "Nick & Co"


def test_strip_link_markup_without_markup():
    plain_text = "Plain &amp; Simple"
    result = AdvancedModerationModule._strip_link_markup(plain_text)
    assert result == "Plain & Simple"


def test_moderator_display_render_variants():
    entry = ModeratorDisplay(
        level=3,
        raw_text="Display",
        plain_label="Display",
        mention_label='<a href="https://t.me/example">Display</a>',
        is_admin=False,
    )

    assert entry.render(use_mentions=False) == "Display"
    assert entry.render(use_mentions=True) == '<a href="https://t.me/example">Display</a>'


def test_moderator_display_admin_prefix():
    entry = ModeratorDisplay(
        level=5,
        raw_text="Admin",
        plain_label="Admin",
        mention_label="Admin",
        is_admin=True,
    )

    assert entry.render(use_mentions=False) == "🛡 Admin"
    assert entry.render(use_mentions=True) == "🛡 Admin"


def test_extract_mention_preference_defaults_to_true():
    module = AdvancedModerationModule()

    assert module._extract_mention_preference(()) is True


def test_extract_mention_preference_handles_off():
    module = AdvancedModerationModule()

    assert module._extract_mention_preference(("mention=off",)) is False


def test_extract_mention_preference_invalid_value():
    module = AdvancedModerationModule()

    assert module._extract_mention_preference(("mention=sometimes",)) is None
