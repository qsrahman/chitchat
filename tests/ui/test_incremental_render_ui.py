# ruff: noqa: E501  (the documents below are test data, kept on one line each for reading)
"""Streaming a reply re-renders only what changed (markdown.js, renderBlocks). It must give exactly the HTML a full
render gives, at every step, whatever arrives next, and it must really leave finished blocks alone."""
import json

from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, send

BLOCK = ("## Section {i}\n\nA paragraph with **bold**, *emphasis*, `code` and a [link](https://example.com/{i}).\n\n"
         "- one\n- two with `code`\n\n```python\ndef f_{i}(x):\n    return x * {i}\n```\n\nMath: \\(a^2 + b^2\\)\n\n")

DOCUMENTS = {
    "plain": "First paragraph.\n\nSecond paragraph with more words.\n\nThird.",
    "headings and rules": "# One\n\n## Two\n\n---\n\n### Three\n\ntext\n***\nmore",
    "setext heading that appears late": "A line of text\nand another line\n==========\n\nafter\n\nSecond\n---\n",
    "a paragraph that becomes a table": "Intro\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\nOutro",
    "lists, nested and continued": "- a\n  - b\n    - c\n\n- d\n\n  continued paragraph\n\n1. x\n2. y\n   1. z\n\n3. w\n",
    "task list and numbering": "3. three\n4. four\n\n- [ ] todo\n- [x] done\n",
    "reference links defined at the end": "See [the docs][1] and [other] and ![alt][1].\n\nMore text here.\n\n"
                                          "[1]: https://example.com/docs\n[other]: https://example.org/other\n",
    "code that is not closed yet, then is": "Before\n\n```js\nconst a = 1;\nconst b = 2;\n\nconst c = 3;\n```\n\nAfter\n\n"
                                            "    indented code\n    more\n",
    "nested quotes": "> quote\n> > inner\n> - item\n> - item two\n\nafter the quote\n",
    "math in every form": "Inline \\(x^2\\) and $y_1$ and costs $5 and $10, display:\n\n$$\n\\int_0^1 x\\,dx\n$$\n\n"
                          "\\[\\sum_i i\\]\n\nunfinished \\(a + b",
    "hostile html": "<script>window.__xss=1</script>\n\n<b onclick=\"window.__xss=1\">bold</b> <img src=x onerror=\"window.__xss=1\">\n\n"
                    "[js](javascript:window.__xss=1) <details><summary>s</summary>inside</details>\n\n<iframe src=x></iframe>",
    "emphasis that spans and breaks": "**bold that is long\n\nacross paragraphs** and _under_scored_ words and *star*\n\n"
                                      "line one  \nline two\\\nline three \\*escaped\\*",
    "right to left and mixed": "السلام عليكم\n\nEnglish here.\n\n- بند أول\n- بند ثان\n\n> اقتباس\n\n| ع | b |\n|---|---|\n| 1 | 2 |\n",
    "windows line endings and tabs": "one\r\n\r\ntwo\r\n\r\n- a\r\n- b\r\n\r\n```\r\ncode\r\n```\r\n\tindented\r\n",
    "a long document": "".join(BLOCK.format(i=i) for i in range(5)),
}

STREAM = """async ([name, text, size, reasoning]) => {
    const m = await import('/markdown.js');
    const into = reasoning ? m.renderReasoningInto : m.renderMarkdownInto;
    const full = reasoning ? m.renderReasoning : m.renderMarkdown;
    const container = document.createElement('div'), expected = document.createElement('div');
    document.body.append(container);
    let steps = 0;
    for (let end = size; ; end = Math.min(end + size, text.length)) {
        const prefix = text.slice(0, end);
        into(container, prefix);
        expected.innerHTML = full(prefix);
        steps++;
        if (container.innerHTML !== expected.innerHTML) {
            return {name, size, end, got: container.innerHTML.slice(-300), want: expected.innerHTML.slice(-300)};
        }
        if (end >= text.length) break;
    }
    container.remove();
    return {name, ok: true, steps, xss: window.__xss ?? null};
}"""


def check(page, name, size, reasoning=False):
    result = page.evaluate(STREAM, [name, DOCUMENTS[name], size, reasoning])
    assert result.get("ok"), json.dumps(result, ensure_ascii=False, indent=1)
    assert result["xss"] is None  # sanitized the same way, so nothing ran
    return result


def test_every_document_streams_to_exactly_the_full_render_in_small_steps(page, app_url):
    open_app(page, app_url)
    total = 0
    for name in DOCUMENTS:
        total += check(page, name, 1 if len(DOCUMENTS[name]) < 400 else 3)["steps"]
    assert total > 1_000  # a lot of intermediate states were compared, not a handful


def test_the_same_in_larger_steps_like_real_chunks_of_text(page, app_url):
    open_app(page, app_url)
    for name in DOCUMENTS:
        for size in (7, 24, 61):
            check(page, name, size)


def test_reasoning_text_streams_to_exactly_its_full_render_too(page, app_url):
    open_app(page, app_url)
    for name in DOCUMENTS:
        check(page, name, 11, reasoning=True)


def test_text_that_jumps_around_still_matches(page, app_url):
    """Edit and regenerate replace the text, or shorten it: nothing may be left over from before."""
    open_app(page, app_url)
    ok = page.evaluate("""async ([a, b, c]) => {
        const m = await import('/markdown.js');
        const box = document.createElement('div'), want = document.createElement('div');
        document.body.append(box);
        for (const text of [a, b, a.slice(0, 40), c, '', b, b + b, a, '']) {
            m.renderMarkdownInto(box, text);
            want.innerHTML = m.renderMarkdown(text);
            if (box.innerHTML !== want.innerHTML) return text.slice(0, 60);
        }
        return true;
    }""", [DOCUMENTS["a long document"], DOCUMENTS["a paragraph that becomes a table"], DOCUMENTS["hostile html"]])
    assert ok is True, ok


def test_a_late_link_definition_rewrites_the_paragraph_that_uses_it(page, app_url):
    open_app(page, app_url)
    html = page.evaluate("""async () => {
        const m = await import('/markdown.js');
        const box = document.createElement('div');
        m.renderMarkdownInto(box, 'A [ref][x] link.\\n\\nmore text');
        const before = box.querySelectorAll('a').length;
        m.renderMarkdownInto(box, 'A [ref][x] link.\\n\\nmore text\\n\\n[x]: https://example.com/');
        return [before, box.querySelector('a')?.getAttribute('href')];
    }""")
    assert html == [0, "https://example.com/"]


# ---- the point of it: finished blocks are left alone ----

def test_a_long_stream_sanitizes_only_the_last_block_per_update(page, app_url):
    open_app(page, app_url)
    result = page.evaluate("""async (text) => {
        const m = await import('/markdown.js');
        const sanitize = DOMPurify.sanitize.bind(DOMPurify);
        let calls = 0;
        DOMPurify.sanitize = (...args) => { calls++; return sanitize(...args); };
        const box = document.createElement('div');
        document.body.append(box);
        const per = [];
        let firstNode = null;
        for (let end = 24; ; end = Math.min(end + 24, text.length)) {
            calls = 0;
            m.renderMarkdownInto(box, text.slice(0, end));
            per.push(calls);
            firstNode ??= box.querySelector('h2');
            if (end >= text.length) break;
        }
        DOMPurify.sanitize = sanitize;
        return {updates: per.length, mean: per.reduce((a, b) => a + b) / per.length, worst: Math.max(...per),
                firstKept: box.querySelector('h2') === firstNode, blocks: box.children.length};
    }""", "".join(BLOCK.format(i=i) for i in range(100)))
    assert result["updates"] > 700 and result["blocks"] > 150
    assert result["mean"] <= 3 and result["worst"] <= 12, result  # a full render would be 150+ per update
    assert result["firstKept"]  # the very first block is still the same element after hundreds of updates


def test_while_a_reply_streams_its_finished_paragraphs_are_not_rebuilt(page, app_url):
    open_app(page, app_url)
    send(page, "long answer please")
    expect(page.locator(".msg.assistant .body p").nth(8)).to_be_visible()
    page.evaluate("document.querySelector('.msg.assistant .body p').dataset.kept = 'yes'")
    count = page.locator(".msg.assistant .body p").count()
    page.wait_for_function("n => document.querySelectorAll('.msg.assistant .body p').length > n + 10", arg=count)
    assert page.evaluate("document.querySelector('.msg.assistant .body p').dataset.kept") == "yes"
    page.keyboard.press("Escape")


def test_text_selected_in_a_finished_paragraph_survives_the_stream(page, app_url):
    open_app(page, app_url)
    send(page, "long answer please")
    expect(page.locator(".msg.assistant .body p").nth(6)).to_be_visible()
    page.evaluate("""() => { const p = document.querySelector('.msg.assistant .body p');
        const r = document.createRange(); r.selectNodeContents(p); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")
    selected = page.evaluate("getSelection().toString()")
    page.wait_for_function("() => document.querySelectorAll('.msg.assistant .body p').length > 16")
    assert selected and page.evaluate("getSelection().toString()") == selected  # it used to vanish every frame
    page.keyboard.press("Escape")


def test_when_a_reply_ends_it_is_rendered_once_in_full_and_equals_a_reload(page, app_url):
    open_app(page, app_url)
    send(page, "richreply")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    streamed = page.locator(".msg.assistant .body").inner_html()
    page.reload()
    expect(page.locator(".msg.assistant .body .katex").first).to_be_visible()
    assert page.locator(".msg.assistant .body").inner_html() == streamed
