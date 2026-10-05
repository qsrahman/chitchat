"""get_datetime: the current date and time in a timezone, and the distance to another date."""
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from app.config import Settings
from app.tools.base import Tool, ToolError, ToolResult

MAX_DAYS = 36_500  # a hundred years either way


def _now(tz: tzinfo | None) -> datetime:
    """The time now (a function so that tests can fix it)."""
    return datetime.now(tz).astimezone(tz)


def _stamp(moment: datetime, seconds: bool = False) -> str:
    time = f"{moment:%H:%M:%S}" if seconds else f"{moment:%H:%M}"
    return f"{moment:%A} {moment.day} {moment:%B %Y}, {time}"


def _offset(moment: datetime) -> str:
    sign, rest = moment.strftime("%z")[0], moment.strftime("%z")[1:]
    return f"UTC{sign}{rest[:2]}:{rest[2:]}"


def _span(delta: timedelta) -> str:
    total = int(abs(delta).total_seconds()) // 60
    days, rest = divmod(total, 1440)
    hours, minutes = divmod(rest, 60)
    parts = [f"{n} {unit}{'' if n == 1 else 's'}" for n, unit in ((days, "day"), (hours, "hour"), (minutes, "minute"))
             if n]
    text = " ".join(parts) or "under a minute"
    return text if total == 0 else f"in {text}" if delta > timedelta(0) else f"{text} ago"


def _int(args: dict, key: str, low: int, high: int) -> int | None:
    if args.get(key) is None:
        return None
    try:
        value = int(args[key])
    except (TypeError, ValueError) as e:
        raise ToolError(f"{key} must be a whole number.") from e
    if not low <= value <= high:
        raise ToolError(f"{key} must be between {low:,} and {high:,}.")
    return value


async def get_datetime(args: dict) -> ToolResult:
    name = str(args.get("timezone") or "").strip()
    if name:
        try:
            tz: tzinfo | None = ZoneInfo(name)
        except (KeyError, ValueError, OSError) as e:  # not found, or not a valid key (e.g. "../x")
            raise ToolError("Unknown timezone. Use an IANA name such as Europe/London or Asia/Karachi.") from e
    else:
        tz = None  # this server's own: where the person using a local app is
    now = _now(tz)
    zone = f"{name or now.tzname()}, {_offset(now)}"
    lines = [f"Now: {_stamp(now, seconds=True)} ({zone})"]
    also = []
    days = _int(args, "days_from_now", -MAX_DAYS, MAX_DAYS)
    if days is not None:
        day = now + timedelta(days=days)  # the same wall-clock time, so a change of clocks in between is not counted
        also.append(f"{abs(days):,} day{'' if abs(days) == 1 else 's'} {'from now' if days >= 0 else 'ago'}: "
                    f"{day:%A} {day.day} {day:%B %Y}")
    until = str(args.get("until") or "").strip()
    if until:
        try:
            target = datetime.fromisoformat(until)
        except ValueError as e:
            raise ToolError("until must be an ISO date or time, such as 2026-12-25 or 2026-12-25T18:00.") from e
        if target.tzinfo is None:
            target = target.replace(tzinfo=now.tzinfo)
        calendar = (target.astimezone(now.tzinfo).date() - now.date()).days
        also.append(f"{_stamp(target)} ({_offset(target)}) is {_span(target - now)}, "
                    f"{abs(calendar):,} calendar day{'' if abs(calendar) == 1 else 's'} "
                    f"{'away' if calendar > 0 else 'ago' if calendar < 0 else '(today)'}")
    return ToolResult("\n".join([*lines, *also]), {"now": _stamp(now), "timezone": zone, "also": also})


def make(settings: Settings) -> Tool:
    return Tool(
        name="get_datetime",
        label="Date and time",
        hint="The current time in any timezone, and days until a date",
        description=(
            "Get the current date and time, in the server's timezone or a named one, and optionally the date a number "
            "of days from now, or how long it is until (or since) a given date or time."
        ),
        parameters={
            "type": "object",
            "properties": {
                "timezone": {
                    "type": ["string", "null"],
                    "description": "An IANA timezone name such as Europe/London, or null for the user's own.",
                },
                "days_from_now": {
                    "type": ["integer", "null"],
                    "description": "Also give the date this many days from now (negative: ago), or null.",
                },
                "until": {
                    "type": ["string", "null"],
                    "description": "Also say how long it is until (or since) this ISO date or time, e.g. "
                                   "2026-12-25 or 2026-12-25T18:00, or null.",
                },
            },
            "required": ["timezone", "days_from_now", "until"],
            "additionalProperties": False,
        },
        run=get_datetime,
        guidance=(
            "Use the get_datetime tool for the time of day, for another timezone, or for how long it is until or "
            "since a date, instead of working it out yourself. The date alone is already in your instructions."
        ),
    )
