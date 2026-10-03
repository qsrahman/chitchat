"""What a tool is: the shapes every tool module and the registry (`__init__.py`) share."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from functools import partial


def bound_to(tool: Tool, conversation_id: str) -> Tool:
    """The tool as it runs in one conversation: those that want to know which one get its id."""
    return replace(tool, run=partial(tool.run, conversation_id=conversation_id)) if tool.per_chat else tool


class ToolError(Exception):
    """A tool failed; the message goes to the model and is shown to the user, so keep it free of secrets."""


@dataclass(frozen=True)
class ToolResult:
    output: str
    display: dict


@dataclass(frozen=True)
class Tool:
    name: str
    label: str
    description: str
    parameters: dict  # JSON schema, written to satisfy OpenAI's strict mode (every property required)
    run: Callable[..., Awaitable[ToolResult]]  # (args), and (args, conversation_id=) when per_chat
    guidance: str = ""  # added to the instructions while the tool is switched on
    hint: str = ""  # one line for the user, in the Tools menu
    per_chat: bool = False  # run() also takes `conversation_id`, bound for each reply by the route (see bound_to)
