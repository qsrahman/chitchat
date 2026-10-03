"""How the server and the page behave with a lot of data (docs/round-8.md).

    uv run python -m scripts.bench_scale chats 5000 20     # 5,000 chats of 20 messages (the import limit)
    uv run python -m scripts.bench_scale long 5000         # one chat of 5,000 messages, in a straight path
    uv run python -m scripts.bench_scale versions 2000     # 2,000 messages, every tenth with three versions
    uv run python -m scripts.bench_scale page 500          # open a 500-message chat in a real Chromium

It builds a database in a temporary folder (nothing of yours is touched), seeds it with plain SQL, then times what a
person would do: the chat list, search, opening a chat, sending a message, switching a version, exporting
everything. Times are in milliseconds, the median of a few runs. `page` needs Chromium
(`uv run playwright install chromium`).
"""
import asyncio
import pathlib
import random
import socket
import statistics
import sys
import tempfile
import threading
import time
from contextlib import closing

import httpx
import uvicorn

from app import db, store
from app.config import Settings
from app.main import create_app

WORDS = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon "
         "phi chi psi omega quokka wombat kangaroo python rust golang compiler thread mutex socket index query").split()


INSERT_MESSAGE = "INSERT INTO messages (conversation_id, parent_id, role, content, created_at) VALUES (?,?,?,?,?)"
LABEL = 48  # width of the left column of the report


def report(label: str, value: str, extra: str = "") -> None:
    print(f"  {label:<{LABEL}}{value}{extra}")


def sentence(rng: random.Random, n: int = 30) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n)) + "."


def seed_chats(path: str, chats: int, per_chat: int) -> None:
    rng = random.Random(1)
    with closing(db.connect(path)) as conn:
        for i in range(chats):
            cid = f"{i:032x}"
            conn.execute("INSERT INTO conversations (id, title, created_at, updated_at, settings) VALUES (?,?,?,?,?)",
                         (cid, f"chat {i} about {rng.choice(WORDS)}", "2026-01-01T00:00:00+00:00",
                          f"2026-01-01T00:{i // 60 % 60:02d}:{i % 60:02d}+00:00", "{}"))
            parent = None
            for j in range(per_chat):
                role = "user" if j % 2 == 0 else "assistant"
                cur = conn.execute(INSERT_MESSAGE, (cid, parent, role, sentence(rng, 40), "2026-01-01T00:00:00+00:00"))
                parent = cur.lastrowid
            conn.execute("UPDATE conversations SET leaf_id = ? WHERE id = ?", (parent, cid))
        conn.commit()


def seed_one(path: str, messages: int, versions: bool) -> str:
    """One chat of `messages` messages; with `versions`, every tenth message also has two siblings (the path shown
    runs through the newest, and each sibling is a short dead end of its own)."""
    rng = random.Random(2)
    cid = "f" * 32
    with closing(db.connect(path)) as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at, settings) VALUES (?,?,?,?,?)",
                     (cid, "one long chat", "x", "x", "{}"))
        parent = None
        for j in range(messages):
            role = "user" if j % 2 == 0 else "assistant"
            if versions and j % 10 == 0 and j:
                for _ in range(2):  # older versions of this message, each with one reply
                    other = conn.execute(INSERT_MESSAGE, (cid, parent, role, sentence(rng), "x")).lastrowid
                    conn.execute(INSERT_MESSAGE, (cid, other, "assistant", sentence(rng), "x"))
            parent = conn.execute(INSERT_MESSAGE, (cid, parent, role, sentence(rng, 60), "x")).lastrowid
        conn.execute("UPDATE conversations SET leaf_id = ? WHERE id = ?", (parent, cid))
        conn.commit()
    return cid


def ms(fn, runs: int = 5) -> str:
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        fn()
        times.append((time.perf_counter() - started) * 1000)
    return f"{statistics.median(times):8.1f} ms"


async def http_ms(client: httpx.AsyncClient, method: str, url: str, runs: int = 5, **kwargs) -> str:
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        response = await client.request(method, url, **kwargs)
        times.append((time.perf_counter() - started) * 1000)
        assert response.status_code < 400, (url, response.status_code, response.text[:200])
    return f"{statistics.median(times):8.1f} ms"


async def run_server_side(path: str, cid: str | None) -> None:
    app = create_app(Settings(_env_file=None, db_path=path, attachments_dir=path + "-files", log_level="WARNING",
                              openai_api_key="t", default_system_prompt=""))

    class Echo:
        default_model = "m"

        async def stream_reply(self, model, messages, **kwargs):
            yield {"type": "delta", "text": "ok"}
            yield {"type": "done"}

        async def generate_title(self, *args):
            return "t"

        async def list_models(self):
            return ["m"]

    app.state.llm = Echo()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x", timeout=300) as client:
        report("the chat list (first page of 50)", await http_ms(client, "GET", "/api/conversations"))
        report("the chat list, page 50 of 100 (offset 2,450)",
               await http_ms(client, "GET", "/api/conversations?limit=50&offset=2450"))
        report("search, a common word", await http_ms(client, "GET", "/api/search?q=python"))
        report("search, two words and a prefix", await http_ms(client, "GET", "/api/search?q=quokka+mut"))
        cid = cid or f"{0:032x}"
        report("open a chat (GET, the whole path)", await http_ms(client, "GET", f"/api/conversations/{cid}"))
        started = time.perf_counter()
        response = await client.post(f"/api/conversations/{cid}/chat", json={"content": "and one more"})
        assert response.status_code == 200
        report("send a message (to the fake model and back)", f"{(time.perf_counter() - started) * 1000:8.1f} ms")
        with closing(db.connect(path)) as conn:
            sibling = conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ? AND parent_id IN "
                "(SELECT parent_id FROM messages WHERE conversation_id = ? GROUP BY parent_id HAVING COUNT(*) > 1) "
                "ORDER BY id LIMIT 1", (cid, cid)).fetchone()
        if sibling:
            report("switch to another version", await http_ms(
                client, "POST", f"/api/conversations/{cid}/branch", json={"message_id": sibling["id"]}))
        started = time.perf_counter()
        export = await client.get("/api/export")
        report("export everything as JSON", f"{(time.perf_counter() - started) * 1000:8.1f} ms",
               f"   ({len(export.content) / 1e6:.1f} MB)")
        fresh = path + "-import.db"
        other = create_app(Settings(_env_file=None, db_path=fresh, attachments_dir=fresh + "-files",
                                    log_level="WARNING"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=other), base_url="http://y",
                                     timeout=600) as second:
            started = time.perf_counter()
            result = await second.post("/api/import", files={"file": ("b.json", export.content)})
            count = result.json().get("messages") if result.status_code < 400 else result.text[:80]
            report("import it into an empty app", f"{(time.perf_counter() - started) * 1000:8.1f} ms",
                   f"   ({result.status_code}, {count} messages)")


def server_side(kind: str, args: list[str]) -> None:
    folder = tempfile.mkdtemp()
    path = f"{folder}/bench.db"
    db.init(path)
    started = time.perf_counter()
    if kind == "chats":
        chats, per = int(args[0]), int(args[1])
        seed_chats(path, chats, per)
        cid, label = None, f"{chats:,} chats of {per} messages ({chats * per:,} messages)"
    else:
        count = int(args[0])
        cid = seed_one(path, count, versions=kind == "versions")
        label = f"one chat of {count:,} messages" + (", every tenth with three versions" if kind == "versions" else "")
    size = pathlib.Path(path).stat().st_size / 1e6
    print(f"{label}: seeded in {time.perf_counter() - started:.1f} s, database {size:.1f} MB")
    with closing(db.connect(path)) as conn:
        report("path length (messages shown)", f"{len(store.list_messages(conn, cid)) if cid else '-':>11}")
    asyncio.run(run_server_side(path, cid))


# ---- the page ----

def page_side(count: int) -> None:
    from playwright.sync_api import sync_playwright

    folder = tempfile.mkdtemp()
    path = f"{folder}/bench.db"
    db.init(path)
    cid = seed_one(path, count, versions=False)
    app = create_app(Settings(_env_file=None, db_path=path, attachments_dir=folder + "/f", log_level="WARNING"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True).start()
    while not server.started:
        time.sleep(0.01)
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1100, "height": 800}).new_page()
        page.goto(url)
        page.wait_for_selector("body[data-ready]", state="attached")
        page.evaluate("""() => { window.__long = [];
            new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__long.push(e.duration)))
              .observe({entryTypes: ['longtask']}); }""")
        started = time.time()
        page.evaluate(f"location.hash = '{cid}'")
        page.wait_for_selector(".msg[data-id]", timeout=300_000)
        page.wait_for_function(f"document.querySelectorAll('.msg').length === {count}", timeout=300_000)
        elapsed = time.time() - started
        long = page.evaluate("window.__long")
        print(f"opening a chat of {count:,} messages: on screen after {elapsed:.2f} s; main thread blocked "
              f"{sum(long) / 1000:.2f} s in {len(long)} long tasks, the longest {max(long, default=0):.0f} ms")
        browser.close()
    server.should_exit = True


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "chats"
    if kind == "page":
        page_side(int(sys.argv[2]) if len(sys.argv) > 2 else 500)
    else:
        server_side(kind, sys.argv[2:] or (["5000", "20"] if kind == "chats" else ["5000"]))
