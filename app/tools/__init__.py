"""Tools the model can call during a reply.

A tool is a name, a JSON schema for its arguments, and an async function. The function returns a ToolResult:
`output` is the text the model reads, `display` is what the UI shows, so the UI never has to parse model text.
Raise ToolError for a failure worth telling both the model and the user about.

One module per tool (`brave`, `calc`, `chats`, `fetch`, `clock`, `readchat`, `readfile`), each with its function
and a `make(settings)` that builds its Tool (schema, guidance); `base` has the shared types. Add a tool by writing a
module like those and listing it in NAMES and build() below. It then shows up in GET /api/tools and can be switched
on per conversation (settings.tools).
"""
import httpx

from app.config import Settings
from app.tools import brave, calc, chats, clock, fetch, readchat, readfile
from app.tools.base import Tool, ToolError, ToolResult, bound_to
from app.tools.brave import web_search
from app.tools.calc import calculator
from app.tools.chats import search_chats
from app.tools.clock import get_datetime
from app.tools.fetch import fetch_url
from app.tools.readchat import read_chat
from app.tools.readfile import read_attachment

__all__ = ["NAMES", "Tool", "ToolError", "ToolResult", "bound_to", "build", "calculator", "fetch_url", "get_datetime",
           "read_attachment", "read_chat", "search_chats", "web_search"]

# Every tool the app can have; web_search is only usable with a Brave key (see build()).
NAMES = ("web_search", "calculator", "search_chats", "fetch_url", "get_datetime", "read_chat", "read_attachment")


def build(settings: Settings, client: httpx.AsyncClient | None = None) -> dict[str, Tool]:
    """The tools that are usable with this configuration. `client` is for tests."""
    made = [brave.make(settings, client), calc.make(settings), chats.make(settings), fetch.make(settings, client),
            clock.make(settings), readchat.make(settings), readfile.make(settings)]
    return {t.name: t for t in made if t}
