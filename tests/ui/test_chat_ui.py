import re
import time

from playwright.sync_api import Page, expect


def eventually(check, timeout=5.0):
    """Poll `check()` until it returns truthy (Playwright's Python API has no expect.poll)."""
    deadline = time.monotonic() + timeout
    while not (result := check()):
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.05)
    return result


def send(page: Page, text: str):
    page.get_by_label("Message", exact=True).fill(text)
    page.keyboard.press("Enter")


def open_app(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()


def open_sidebar(page: Page):
    page.get_by_role("button", name="Show conversations").click()
    expect(page.locator("#sidebar")).to_be_visible()


def conv_id(page: Page) -> str:
    return page.url.split("#")[1]


def saved_messages(page: Page) -> list[dict]:
    origin = page.url.split("#")[0]
    return page.request.get(f"{origin}api/conversations/{conv_id(page)}").json()["messages"]


# ---- composing and sending ----

def test_starter_prompt_sends_and_titles_the_chat(page, app_url):
    open_app(page, app_url)
    page.get_by_role("button", name="Compare SQLite and Postgres for a side project").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1 to Compare SQLite")
    expect(page.locator("#conversations a[aria-current=page]")).to_contain_text("Compare SQLite")
    expect(page.locator("#title")).to_contain_text("Compare SQLite")
    expect(page.locator("#empty")).to_be_hidden()


def test_send_button_follows_input_and_enter_semantics(page, app_url):
    open_app(page, app_url)
    box, send_btn = page.get_by_label("Message", exact=True), page.locator("#send")
    expect(send_btn).to_be_disabled()
    box.fill("line1")
    expect(send_btn).to_be_enabled()
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("line2")
    page.keyboard.press("Enter")
    expect(page.locator(".msg.user .body")).to_have_text("line1\nline2")
    expect(box).to_have_value("")
    expect(send_btn).to_be_disabled()


def test_thinking_indicator_shows_before_first_token(page, app_url):
    open_app(page, app_url)
    send(page, "slow please")
    expect(page.locator(".dots")).to_be_visible()
    expect(page.locator(".msg.assistant .body")).to_contain_text("word0")
    expect(page.locator(".dots")).to_have_count(0)


# ---- rendering ----

def test_code_block_is_highlighted_and_copyable(page, app_url):
    open_app(page, app_url)
    send(page, "show code")
    block = page.locator(".code")
    expect(block.locator(".code-bar span")).to_have_text("python")
    expect(block.locator("code .hljs-keyword").first).to_be_visible()
    expect(page.locator(".msg.assistant .body :not(pre) > code")).to_have_text("inline")
    block.get_by_role("button", name="Copy").click()
    expect(block.get_by_role("button", name="Copied")).to_be_visible()
    assert page.evaluate("navigator.clipboard.readText()") == "for i in range(3):\n    print(i)"


def test_untrusted_markup_is_sanitized(page, app_url):
    open_app(page, app_url)
    send(page, "xss please")
    body = page.locator(".msg.assistant .body")
    expect(body).to_contain_text("Hi")
    assert page.evaluate("window.__xss") is None
    expect(body.locator("script, img")).to_have_count(0)
    link = body.get_by_role("link", name="docs")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", re.compile("noopener"))
    expect(body.locator("a[href^=javascript]")).to_have_count(0)


def test_cut_off_reply_is_flagged_and_stays_flagged(page, app_url):
    open_app(page, app_url)
    send(page, "cutoff")
    expect(page.locator(".msg.assistant > .note")).to_have_text("Reply cut off: output limit reached.")
    page.reload()
    expect(page.locator(".msg.assistant > .note")).to_have_text("Reply cut off: output limit reached.")


# ---- stop, regenerate, edit, retry ----

def test_stop_button_keeps_partial_reply(page, app_url):
    open_app(page, app_url)
    send(page, "slow please")
    expect(page.locator(".msg.assistant .body")).to_contain_text("word2")
    page.get_by_role("button", name="Stop generating").click()
    expect(page.locator(".msg.assistant > .note")).to_have_text("Stopped.")
    expect(page.get_by_role("button", name="Send message")).to_be_disabled()
    expect(page.get_by_role("button", name="Regenerate")).to_be_visible()
    shown = page.locator(".msg.assistant .body").inner_text()
    assert "word2" in shown and "word59" not in shown
    eventually(lambda: len(saved_messages(page)) == 2)
    page.reload()
    expect(page.locator(".msg.assistant .body")).to_contain_text("word2")
    expect(page.locator(".msg.assistant > .note")).to_have_text("Stopped.")


def test_escape_stops_the_reply(page, app_url):
    open_app(page, app_url)
    send(page, "slow please")
    expect(page.locator(".msg.assistant .body")).to_contain_text("word1")
    page.keyboard.press("Escape")
    expect(page.locator(".msg.assistant > .note")).to_have_text("Stopped.")


def test_regenerate_replaces_the_reply(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1 to hello")
    page.get_by_role("button", name="Regenerate").click()
    expect(page.locator(".msg.assistant")).to_have_count(1)
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #2 to hello")


def test_edit_last_message_only_and_resend(page, app_url):
    open_app(page, app_url)
    send(page, "first")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    send(page, "second")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("Reply #2")
    expect(page.get_by_role("button", name="Edit")).to_have_count(1)
    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Edit your message").fill("second, reworded")
    page.get_by_role("button", name="Save").click()
    expect(page.locator(".msg.user").nth(1)).to_have_text("second, reworded")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("Reply #3 to second, reworded")
    expect(page.locator(".msg")).to_have_count(4)


def test_cancel_edit_restores_message(page, app_url):
    open_app(page, app_url)
    send(page, "keep me")
    expect(page.get_by_role("button", name="Regenerate")).to_be_visible()
    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Edit your message").fill("changed my mind")
    page.get_by_role("button", name="Cancel").click()
    expect(page.locator(".msg.user .body")).to_have_text("keep me")
    expect(page.get_by_role("button", name="Edit")).to_be_visible()


def test_error_offers_retry(page, app_url):
    open_app(page, app_url)
    send(page, "please fail")
    expect(page.locator(".msg.error")).to_contain_text("Couldn't get a reply. simulated failure")
    page.get_by_role("button", name="Retry").click()
    expect(page.locator(".msg.error")).to_have_count(0)
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #2 to please fail")


# ---- scrolling ----

def test_reader_scrolling_up_is_not_yanked_down_and_can_jump_back(page, app_url):
    page.set_viewport_size({"width": 1100, "height": 500})
    open_app(page, app_url)
    send(page, "long answer")
    messages = page.locator("#messages")
    eventually(lambda: messages.evaluate("el => el.scrollHeight - el.clientHeight") > 300)
    messages.evaluate("el => { el.scrollTop = 0 }")
    jump = page.get_by_role("button", name="Jump to latest")
    expect(jump).to_be_visible()
    page.wait_for_timeout(400)
    assert messages.evaluate("el => el.scrollTop") < 50
    jump.click()
    expect(jump).to_be_hidden()
    assert messages.evaluate("el => el.scrollHeight - el.scrollTop - el.clientHeight") < 80


# ---- sidebar ----

def test_conversations_are_grouped_and_survive_reload_and_deep_links(page, app_url):
    open_app(page, app_url)
    send(page, "remember me")
    expect(page.locator("#conversations h2")).to_have_text("Today")
    url = page.url
    page.reload()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1 to remember me")
    other = page.context.new_page()
    other.goto(url)
    expect(other.locator(".msg.user .body")).to_have_text("remember me")
    other.close()


def test_new_chat_returns_to_empty_state_and_keeps_old_chat(page, app_url):
    open_app(page, app_url)
    send(page, "first topic")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    open_sidebar(page)
    page.get_by_role("button", name="New chat").click()
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()
    expect(page.locator("#title")).to_have_text("New chat")
    send(page, "second topic")
    expect(page.locator("#conversations li")).to_have_count(2)
    page.get_by_role("link", name="first topic").click()
    expect(page.locator(".msg.user .body")).to_have_text("first topic")


def test_rename_via_dialog_with_enter(page, app_url):
    open_app(page, app_url)
    send(page, "old name")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    open_sidebar(page)
    page.get_by_role("button", name='Rename "old name"').click()
    dialog = page.get_by_role("dialog", name="Rename conversation")
    expect(dialog.get_by_label("Conversation title")).to_be_focused()
    dialog.get_by_label("Conversation title").fill("Shiny new name")
    page.keyboard.press("Enter")  # must save, not cancel
    expect(dialog).to_be_hidden()
    expect(page.locator("#conversations a")).to_have_text("Shiny new name")
    expect(page.locator("#title")).to_have_text("Shiny new name")
    page.reload()
    expect(page.locator("#title")).to_have_text("Shiny new name")


def test_rename_can_be_cancelled_with_escape(page, app_url):
    open_app(page, app_url)
    send(page, "stay put")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    open_sidebar(page)
    page.get_by_role("button", name='Rename "stay put"').click()
    page.get_by_label("Conversation title").fill("nope")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.locator("#conversations a")).to_have_text("stay put")


def test_delete_asks_first_then_removes(page, app_url):
    open_app(page, app_url)
    send(page, "doomed chat")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    open_sidebar(page)
    page.get_by_role("button", name='Delete "doomed chat"').click()
    dialog = page.get_by_role("dialog", name="Delete this conversation?")
    expect(dialog).to_contain_text("doomed chat")
    dialog.get_by_role("button", name="Keep it").click()
    expect(page.locator("#conversations a")).to_have_text("doomed chat")
    page.get_by_role("button", name='Delete "doomed chat"').click()
    dialog.get_by_role("button", name="Delete").click()
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()
    expect(page.get_by_text("Your conversations will show up here.")).to_be_visible()


# ---- layout and theme ----

def test_sidebar_is_closed_by_default_and_toggles(page, app_url):
    open_app(page, app_url)
    sidebar, toggle = page.locator("#sidebar"), page.get_by_role("button", name="Show conversations")
    expect(sidebar).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    page.keyboard.press("Tab")  # focus goes to the toggle / composer, never into the hidden sidebar
    assert not page.evaluate("document.activeElement.closest('#sidebar')")
    width_closed = page.locator("main").bounding_box()["width"]
    toggle.click()
    expect(sidebar).to_be_visible()
    expect(page.get_by_role("button", name="Hide conversations")).to_have_attribute("aria-expanded", "true")
    assert page.locator("main").bounding_box()["width"] < width_closed  # pushes content, no overlay
    page.get_by_role("button", name="Hide conversations").click()
    expect(sidebar).to_be_hidden()


def test_sidebar_stays_open_when_switching_chats_on_desktop(page, app_url):
    open_app(page, app_url)
    send(page, "alpha")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    open_sidebar(page)
    page.get_by_role("button", name="New chat").click()
    send(page, "beta")
    expect(page.locator("#conversations li")).to_have_count(2)
    page.get_by_role("link", name="alpha").click()
    expect(page.locator(".msg.user .body")).to_have_text("alpha")
    expect(page.locator("#sidebar")).to_be_visible()


def test_mobile_sidebar_is_a_drawer(page, app_url):
    page.set_viewport_size({"width": 390, "height": 800})
    open_app(page, app_url)
    sidebar, toggle = page.locator("#sidebar"), page.locator("#toggle-nav")
    expect(sidebar).not_to_be_in_viewport()
    toggle.click()
    expect(sidebar).to_be_in_viewport()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    page.locator("#scrim").click(position={"x": 370, "y": 400})
    expect(sidebar).not_to_be_in_viewport()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_follows_system_color_scheme(page, app_url):
    page.emulate_media(color_scheme="light")
    open_app(page, app_url)
    expect(page.locator("body")).to_have_css("background-color", "rgb(255, 255, 255)")
    page.emulate_media(color_scheme="dark")
    expect(page.locator("body")).to_have_css("background-color", "rgb(22, 25, 31)")
