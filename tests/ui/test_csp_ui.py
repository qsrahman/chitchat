"""The Content-Security-Policy in a real browser: the app works under it, and injected script does not run."""
from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_chat_settings, send


def watch_violations(page):
    page.evaluate("""() => {
        window.__violations = [];
        document.addEventListener('securitypolicyviolation', (e) => window.__violations.push(e.violatedDirective));
    }""")


def violations(page):
    return page.evaluate("window.__violations")


def test_an_injected_inline_script_does_not_run(page, app_url, expected_console_errors):
    expected_console_errors.append("Content Security Policy")  # the browser reports the block, as it should
    open_app(page, app_url)
    watch_violations(page)
    page.evaluate("""() => {
        const s = document.createElement('script');
        s.textContent = 'window.__ran = true';
        document.body.append(s);
    }""")
    page.wait_for_function("() => window.__violations.length > 0")
    assert page.evaluate("window.__ran") is None
    assert violations(page) == ["script-src-elem"]


def test_a_script_from_another_origin_is_blocked(page, app_url, expected_console_errors):
    expected_console_errors.append("Content Security Policy")
    open_app(page, app_url)
    watch_violations(page)
    page.evaluate("""() => {
        const s = document.createElement('script');
        s.src = 'https://example.com/evil.js';
        document.body.append(s);
    }""")
    page.wait_for_function("() => window.__violations.length > 0")
    assert violations(page) == ["script-src-elem"]


def test_an_injected_inline_event_handler_does_not_run(page, app_url, expected_console_errors):
    expected_console_errors.append("Content Security Policy")
    open_app(page, app_url)
    watch_violations(page)
    page.evaluate("""() => {
        const b = document.createElement('button');
        b.setAttribute('onclick', 'window.__ran = true');
        b.id = 'evil';
        document.body.append(b);
    }""")
    page.locator("#evil").click()
    page.wait_for_function("() => window.__violations.length > 0")
    assert page.evaluate("window.__ran") is None


def test_a_request_to_another_origin_is_blocked(page, app_url, expected_console_errors):
    expected_console_errors.extend(["Content Security Policy", "Failed to fetch", "Refused to connect"])
    open_app(page, app_url)
    result = page.evaluate("fetch('https://example.com/').then(() => 'allowed', () => 'blocked')")
    assert result == "blocked"


def test_the_app_itself_runs_without_a_single_violation(page, app_url):
    """Math (KaTeX inline styles), highlighted code, a file preview (blob:), popovers and dialogs, all under the policy.
    The page fixture fails the test on any console error, and a violation is one."""
    open_app(page, app_url)
    watch_violations(page)
    send(page, "math please")
    expect(page.locator(".msg.assistant .katex").first).to_be_visible()
    send(page, "show some code")
    expect(page.locator(".msg.assistant .hljs").first).to_be_visible()
    from tests.helpers import PNG

    page.locator("#file-input").set_input_files({"name": "cat.png", "mimeType": "image/png", "buffer": PNG})
    expect(page.locator(".chip img")).to_be_visible()  # a blob: preview
    page.get_by_role("button", name="Tools", exact=True).click()
    expect(page.locator("#tools-menu")).to_be_visible()
    page.keyboard.press("Escape")
    open_chat_settings(page)
    assert violations(page) == []


def test_the_page_cannot_be_framed_by_another_site(page, app_url):
    response = page.request.get(app_url)
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
