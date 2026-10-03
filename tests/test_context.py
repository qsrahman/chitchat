import pytest

from app import context
from app.config import CUSTOM_ENDPOINT_CONTEXT, Settings


def msg(role, text, **extra):
    return {"role": role, "content": text, **extra}


# ---- estimate ----

@pytest.mark.parametrize("text, tokens", [
    ("", 0), ("a", 1), ("abc", 1), ("abcd", 2), ("x" * 300, 100), ("x" * 301, 101),
])
def test_estimate_counts_characters_rounded_up(text, tokens):
    assert context.estimate(msg("user", text)) == tokens


def test_estimate_counts_what_attachments_add():
    image = {"kind": "image", "name": "a.png", "path": "/x"}
    pdf = {"kind": "file", "name": "a.pdf", "path": "/x"}
    note = {"kind": "text", "name": "n.txt", "text": "x" * 300}
    assert context.estimate(msg("user", "", attachments=[image])) == context.IMAGE_TOKENS
    assert context.estimate(msg("user", "", attachments=[pdf])) == context.FILE_TOKENS
    assert context.estimate(msg("user", "", attachments=[note])) == 100
    assert context.estimate(msg("user", "x" * 30, attachments=[image, note])) == context.IMAGE_TOKENS + 110


def test_estimate_copes_with_no_text():
    assert context.estimate({"content": None}) == 0


# ---- fit ----

def chat(n, size=30):
    """n user/assistant pairs, 10 tokens each message at 3 characters per token."""
    pad = lambda text: text.ljust(size, "-")  # noqa: E731
    return [m for i in range(n) for m in (msg("user", pad(f"q{i}")), msg("assistant", pad(f"a{i}")))]


def test_a_history_that_fits_is_unchanged():
    history = chat(3)
    assert context.fit(history, 1_000) == (history, 0)


def test_the_oldest_messages_go_first():
    history = chat(4)  # 8 messages, 10 tokens each
    kept, dropped = context.fit(history, 45)  # room for four
    assert kept == history[4:] and dropped == 4
    assert [m["content"][:2] for m in kept] == ["q2", "a2", "q3", "a3"]


def test_what_is_kept_starts_with_a_user_message():
    history = chat(4)
    kept, dropped = context.fit(history, 35)  # room for three: a2 q3 a3, which would start with a reply
    assert kept[0]["role"] == "user" and [m["content"][:2] for m in kept] == ["q3", "a3"]
    assert dropped == 6


def test_the_message_being_answered_always_stays_even_if_it_is_too_big():
    history = [*chat(2), msg("user", "x" * 3_000)]
    kept, dropped = context.fit(history, 50)
    assert kept == [history[-1]] and dropped == 4


@pytest.mark.parametrize("budget", [0, -500])
def test_a_budget_of_nothing_keeps_only_the_message_being_answered(budget):
    history = [*chat(2), msg("user", "now")]
    assert context.fit(history, budget) == ([history[-1]], 4)


def test_one_message_is_returned_as_it_is():
    assert context.fit([msg("user", "hi")], 1) == ([msg("user", "hi")], 0)


def test_a_history_that_starts_with_a_compaction_item_is_left_alone():
    history = [{"compaction": {"type": "compaction", "encrypted_content": "x"}}, *chat(3)]
    assert context.fit(history, 1) == (history, 0)


def test_attachments_count_against_the_budget():
    image = {"kind": "image", "name": "a.png", "path": "/x"}
    history = [msg("user", "look", attachments=[image]), msg("assistant", "ok"), msg("user", "and now?")]
    kept, dropped = context.fit(history, 500)  # the image alone is 1,000
    assert kept == history[2:] and dropped == 2


def test_the_order_is_preserved_and_nothing_is_invented():
    history = chat(6)
    kept, dropped = context.fit(history, 100)
    assert kept == history[len(history) - len(kept):] and dropped + len(kept) == len(history)


# ---- the settings that drive it ----

def test_there_is_no_limit_on_openai_and_a_default_one_on_a_custom_endpoint():
    assert Settings(_env_file=None).history_tokens == 0
    local = Settings(_env_file=None, openai_base_url="http://localhost:11434/v1")
    assert local.history_tokens == CUSTOM_ENDPOINT_CONTEXT


def test_the_limit_can_be_set_or_switched_off_either_way():
    local = {"openai_base_url": "http://localhost:11434/v1"}
    assert Settings(_env_file=None, context_tokens=8_000, **local).history_tokens == 8_000
    assert Settings(_env_file=None, context_tokens=0, **local).history_tokens == 0
    assert Settings(_env_file=None, context_tokens=8_000).history_tokens == 8_000  # also on OpenAI, if asked


def test_compaction_is_only_for_openai_itself():
    assert Settings(_env_file=None).compaction_enabled is True
    assert Settings(_env_file=None, openai_base_url="http://localhost:11434/v1").compaction_enabled is False
    assert Settings(_env_file=None, compact_threshold=0).compaction_enabled is False
