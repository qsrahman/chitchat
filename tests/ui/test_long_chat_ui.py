"""Opening a long conversation (scripts/bench_scale.py has the timings: docs/round-8.md)."""
import json

from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app

CID = "9" * 32


def long_chat(count):
    return {"conversations": [{"id": CID, "title": "A long chat", "messages": [
        {"role": "user" if i % 2 == 0 else "assistant",
         "content": f"message number {i} with **bold** words and `code`, long enough to wrap onto more than one line "
                    "of the column so that laying the page out costs something"} for i in range(count)]}]}


def test_opening_a_long_chat_lays_the_page_out_a_few_times_not_once_per_message(page, app_url):
    """render() scrolls to the end, and reading the scroll height makes the browser lay everything out again: done
    for each of 1,000 messages that is quadratic (3,000 messages took 2.2 s, now 0.4 s). Count the reads."""
    count = 400
    page.request.post(f"{app_url}/api/import", multipart={
        "file": {"name": "c.json", "mimeType": "application/json", "buffer": json.dumps(long_chat(count)).encode()}})
    open_app(page, app_url)
    page.evaluate("""() => {
        const el = document.getElementById('messages');
        const real = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollHeight').get;
        window.__reads = 0;
        Object.defineProperty(el, 'scrollHeight', { get() { window.__reads++; return real.call(this); } });
    }""")
    page.evaluate(f"location.hash = '{CID}'")
    expect(page.locator(".msg")).to_have_count(count)
    expect(page.locator(".msg").last).to_contain_text(f"message number {count - 1}")
    reads = page.evaluate("window.__reads")
    assert reads < 20, reads  # one per message would be 400
    # and the end of the conversation is what is in view
    assert page.evaluate("""() => { const m = document.getElementById('messages');
        return m.scrollHeight - m.scrollTop - m.clientHeight < 80; }""")
