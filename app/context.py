"""Keeping a conversation inside a model's context window where OpenAI's compaction isn't there to do it: on a
custom endpoint such as a local Ollama model. Without this a long chat just overruns the window and the server
quietly cuts the start of it, or fails. See docs/context-window.md.

There is no exact tokenizer for an arbitrary local model, so sizes are estimated, and on the high side.
"""

CHARS_PER_TOKEN = 3  # English is about 4, code and non-Latin scripts nearer 2: err towards counting too much
IMAGE_TOKENS = 1_000  # an image attachment, whatever its size
FILE_TOKENS = 2_000  # a PDF sent as a file


def estimate(message: dict) -> int:
    """Rough tokens of one history message: its text, plus what its attachments add."""
    chars, tokens = len(message.get("content") or ""), 0
    for attachment in message.get("attachments", []):
        match attachment["kind"]:
            case "image":
                tokens += IMAGE_TOKENS
            case "file":
                tokens += FILE_TOKENS
            case _:
                chars += len(attachment["text"])
    return tokens + -(-chars // CHARS_PER_TOKEN)  # rounded up


def fit(history: list[dict], budget: int) -> tuple[list[dict], int]:
    """The newest messages of `history` that fit in `budget` tokens, and how many older ones were left out.

    The last message, the one being answered, always stays, however big. What is kept starts with a user message,
    so a reply is never the first thing the model sees. A history that starts with an OpenAI compaction item is
    left alone: it already stands for the older turns.
    """
    if any("compaction" in m for m in history):
        return history, 0
    kept, used = [], 0
    for message in reversed(history):
        cost = estimate(message)
        if kept and used + cost > budget:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    while len(kept) > 1 and kept[0]["role"] != "user":
        kept.pop(0)
    return kept, len(history) - len(kept)
