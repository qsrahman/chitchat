"""The events of a turn are described twice: where the server sends them (llm.py and routes.py) and in the UI's types
(`StreamEvent` in app/static/types.d.ts, which tsc checks chat.js against). Nothing else keeps the two together."""
import inspect
import re
from pathlib import Path

from app import llm, routes

TYPES = (Path(__file__).parent.parent / "app" / "static" / "types.d.ts").read_text()


def sent_by_the_server() -> set[str]:
    """llm.py lists its events in its docstring; routes.py adds its own (the title, trimmed context)."""
    return set(re.findall(r'\{"type": "(\w+)"', llm.__doc__ or "")) | set(
        re.findall(r'\{"type": "(\w+)"', inspect.getsource(routes)))


def typed_in_the_ui() -> set[str]:
    union = TYPES[TYPES.index("type StreamEvent"):]
    union = union[:union.index("\n\n")]  # up to the blank line after the union
    return set(re.findall(r"type: '(\w+)'", union))


def test_the_ui_types_name_exactly_the_events_the_server_sends():
    sent, typed = sent_by_the_server(), typed_in_the_ui()
    assert sent >= {"delta", "done", "error"}, "the lists were not found: this test needs updating"
    assert sent - typed == set(), "events the server sends that StreamEvent does not describe: add them to types.d.ts"
    assert typed - sent == set(), "events StreamEvent describes that the server never sends: remove or send them"
