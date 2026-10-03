"""How long the page's main thread is blocked while a long reply streams in (docs/rendering.md).

    uv run python -m scripts.bench_render mixed 5000 20000 100000     # sizes are characters
    uv run python -m scripts.bench_render code 1000 5000 20000        # sizes are lines, all in ONE block
    uv run python -m scripts.bench_render list 1000 5000              # one list item
    uv run python -m scripts.bench_render para 1000 5000              # one paragraph

`mixed` is ordinary markdown (sections with prose, a list, a code block and math); the other shapes put everything in
one top-level block, which the incremental renderer cannot split. It starts the real app on a free port with a
scripted model and drives a real Chromium (`uv run playwright install chromium`), so it needs no network or key.
Columns: long tasks are main-thread tasks over 50 ms; "blocked" is their total.
"""
import asyncio
import pathlib
import socket
import sys
import tempfile
import threading
import time

import uvicorn
from playwright.sync_api import sync_playwright

from app.config import Settings
from app.main import create_app

SECTION = (
    "## Section {i}\n\nThis paragraph has **bold text**, *emphasis*, `inline code` and a "
    "[link](https://example.com/{i}). It goes on for a while so that it behaves like real prose from a model, with "
    "enough words to wrap over a few lines of the column.\n\n"
    "- first point about item {i}\n- second point with `code`\n- third point\n\n"
    "```python\ndef f_{i}(x):\n    total = 0\n    for n in range(x):\n        total += n * {i}\n"
    "    return total\n```\n\n"
    "Math: \\(a_{i}^2 + b_{i}^2 = c_{i}^2\\)\n\n"
)
LINE = "total_{i} = compute(value_{i}, scale=3) + offset  # line {i}"
SHAPE = sys.argv[1] if len(sys.argv) > 1 else "mixed"
CHUNK = 24 if SHAPE == "mixed" else 200  # characters per streamed piece


def make(size: int) -> str:
    if SHAPE == "mixed":
        text, i = "", 0
        while len(text) < size:
            text += SECTION.format(i=i)
            i += 1
        return text[:size]
    lines = [LINE.format(i=i) for i in range(size)]
    if SHAPE == "code":
        return "Here is the code:\n\n```python\n" + "\n".join("    " + line for line in lines) + "\n```\n"
    if SHAPE == "list":
        return "- " + "\n  ".join(line + " and some **bold** text" for line in lines) + "\n"
    return "\n".join(line + " with *emphasis* and `code`" for line in lines) + "\n"


class BigLLM:
    default_model = "m"
    size = 5000

    async def stream_reply(self, model, messages, **kwargs):
        text = make(self.size)
        for k in range(0, len(text), CHUNK):
            yield {"type": "delta", "text": text[k:k + CHUNK]}
            await asyncio.sleep(0.004)
        yield {"type": "done"}

    async def generate_title(self, *args):
        return "t"

    async def list_models(self):
        return ["m"]


INSTRUMENT = """() => { window.__long = []; window.__frames = []; let last = performance.now();
  new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__long.push(e.duration)))
    .observe({entryTypes: ['longtask']});
  const tick = (t) => { window.__frames.push(t - last); last = t; requestAnimationFrame(tick); };
  requestAnimationFrame(tick); }"""


def main() -> None:
    tmp = pathlib.Path(tempfile.mkdtemp())
    app = create_app(Settings(_env_file=None, db_path=str(tmp / "d.db"), attachments_dir=str(tmp / "f"),
                              openai_api_key="t", openai_model="m", default_system_prompt="", log_level="WARNING"))
    llm = BigLLM()
    app.state.llm = llm
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True).start()
    while not server.started:
        time.sleep(0.01)
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    unit = "chars" if SHAPE == "mixed" else "lines"
    print(f"{SHAPE:>6} {unit:>6} {'ideal s':>8} {'actual s':>9} {'long tasks':>11} {'longest ms':>11} "
          f"{'blocked s':>10} {'worst frame ms':>15}")
    sizes = [int(a) for a in sys.argv[2:]] or [5000, 20000, 50000, 100000]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for size in sizes:
            llm.size = size
            page = browser.new_context(viewport={"width": 1100, "height": 800}).new_page()
            page.goto(url)
            page.wait_for_selector("#empty")
            page.evaluate(INSTRUMENT)
            ideal = len(make(size)) / CHUNK * 0.0045  # what the stream alone takes
            started = time.time()
            page.get_by_label("Message", exact=True).fill("go")
            page.keyboard.press("Enter")
            page.wait_for_selector(".msg.assistant .actions button", timeout=600_000)
            actual = time.time() - started
            long, frames = page.evaluate("window.__long"), page.evaluate("window.__frames")
            print(f"{'':>6} {size:>6} {ideal:>8.1f} {actual:>9.1f} {len(long):>11} {max(long, default=0):>11.0f} "
                  f"{sum(long) / 1000:>10.1f} {max(frames):>15.0f}")
            page.context.close()
        browser.close()
    server.should_exit = True


if __name__ == "__main__":
    main()
