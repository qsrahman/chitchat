import re

from playwright.sync_api import Page, expect


def send(page: Page, text: str):
    page.get_by_label("Message", exact=True).fill(text)
    page.keyboard.press("Enter")


def open_app(page: Page, app_url: str):
    page.goto(app_url)
    page.locator("body[data-ready]").wait_for(state="attached")  # the scripts have run (see conftest.wait_until_ready)
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()


def open_sidebar(page: Page):
    page.get_by_role("button", name="Show conversations").click()
    expect(page.locator("#conversations")).to_be_visible()


def open_prefs(page: Page, tab: str = "General"):
    """Open the Settings dialog (the sidebar's gear, which the icon rail keeps in reach) on a tab; returns it."""
    gear = page.get_by_role("button", name="Settings", exact=True)
    if not gear.is_visible():  # on a phone the sidebar is a drawer, closed until asked for
        open_sidebar(page)
    gear.click()
    dialog = page.get_by_role("dialog", name="Settings", exact=True)
    expect(dialog).to_be_visible()
    dialog.get_by_role("tab", name=tab).click()
    return dialog


def chat_menu(page: Page):
    """Open the header's ⋯ menu (everything you can do with the open chat); returns it."""
    page.get_by_role("button", name="Chat actions").click()
    menu = page.get_by_role("menu", name="Chat actions")
    expect(menu).to_be_visible()
    return menu


def open_chat_settings(page: Page):
    """Open "Instructions for this chat" (system prompt, temperature, effort) from the chat menu; returns the dialog."""
    chat_menu(page).get_by_role("menuitem", name="Instructions for this chat…").click()
    dialog = page.get_by_role("dialog", name="Instructions for this chat")
    expect(dialog).to_be_visible()
    return dialog


def row_action(page: Page, title: str, action: str):
    """Choose an action from the ⋯ menu of a sidebar row (the sidebar must be open)."""
    page.get_by_role("button", name=f'Actions for "{title}"').click()
    menu = page.get_by_role("menu", name="Chat actions")
    expect(menu).to_be_visible()
    menu.get_by_role("menuitem", name=action, exact=True).click()


def conv_id(page: Page) -> str:
    return page.url.split("#")[1]


def wait_until_saved(page: Page, count: int):
    """Wait until the server has stored `count` messages for the open conversation."""
    page.wait_for_function(
        "async ([url, n]) => (await (await fetch(url)).json()).messages.length === n",
        arg=[f"{page.url.split('#')[0]}api/conversations/{conv_id(page)}", count],
    )


def saved_messages(page: Page) -> list[dict]:
    origin = page.url.split("#")[0]
    return page.request.get(f"{origin}api/conversations/{conv_id(page)}").json()["messages"]


# ---- composing and sending ----

def test_a_new_chat_offers_no_suggestions_and_no_keyboard_hint(page, app_url):
    open_app(page, app_url)
    expect(page.get_by_text("Enter to send")).to_have_count(0)
    expect(page.get_by_role("button", name="Compare SQLite")).to_have_count(0)
    expect(page.locator("#starters, .hint")).to_have_count(0)


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


def test_code_block_text_is_shown_literally_whatever_the_language(page, app_url):
    open_app(page, app_url)
    send(page, "literal code")
    block = page.locator(".code")
    expect(block.locator(".code-bar span")).to_have_text("weird")
    expect(block.locator("code")).to_have_text("<b>not bold</b> & 'q' <script>window.__xss=1</script>")
    expect(block.locator("code b, code script")).to_have_count(0)
    assert page.evaluate("window.__xss") is None


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
    wait_until_saved(page, 2)
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


def test_edit_the_last_message_and_resend(page, app_url):
    open_app(page, app_url)
    send(page, "first")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    send(page, "second")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("Reply #2")
    expect(page.locator(".msg.assistant").nth(1).locator(".actions button").first).to_be_visible()  # saved
    expect(page.get_by_role("button", name="Edit")).to_have_count(2)  # every message of yours can be edited
    page.get_by_role("button", name="Edit").nth(1).click()
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


def test_the_retry_action_looks_like_the_other_message_actions(page, app_url):
    open_app(page, app_url)
    send(page, "please fail")
    expect(page.locator(".msg.error")).to_be_visible()
    retry = page.get_by_role("button", name="Retry")
    # Copy, Edit and Regenerate are icon buttons named by aria-label, so Retry is one too: it carries a title
    # and no visible text of its own.
    expect(retry).to_have_class("icon-btn")
    expect(retry).to_have_attribute("title", "Retry")
    expect(retry).to_have_text("")


def test_retry_resends_when_the_send_never_reached_the_server(page, app_url, expected_console_errors):
    """The user message is in the DOM only, so regenerate would 409 forever; Retry must resend."""
    open_app(page, app_url)
    expected_console_errors.append("net::ERR_FAILED")  # the aborted POST below
    first = []

    def kill_first(route):
        if first:
            route.continue_()
        else:
            first.append(1)
            route.abort()

    page.route("**/api/conversations/*/chat", kill_first)
    send(page, "hello")
    expect(page.locator(".msg.error")).to_contain_text("Couldn't get a reply")
    assert saved_messages(page) == []

    page.get_by_role("button", name="Retry").click()
    expect(page.locator(".msg.error")).to_have_count(0)
    expect(page.locator(".msg.assistant")).to_contain_text("hello")
    assert [(m["role"], m["content"]) for m in saved_messages(page)] == [
        ("user", "hello"),
        ("assistant", "Reply #1 to **hello**"),
    ]


def test_reply_that_ends_without_done_is_an_error_and_retry_does_not_duplicate_the_turn(page, app_url):
    """The server saves the partial reply when a stream breaks; Retry must replace it, not append to it."""
    open_app(page, app_url)
    send(page, "please drop")
    expect(page.locator(".msg.error")).to_contain_text("closed before the reply finished")
    page.get_by_role("button", name="Retry").click()
    expect(page.locator(".msg.error")).to_have_count(0)
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #2 to please drop")
    assert [(m["role"], m["content"]) for m in saved_messages(page)] == [
        ("user", "please drop"),
        ("assistant", "Reply #2 to **please drop**"),
    ]


def test_retry_after_an_edit_that_never_landed_replaces_the_old_turn(page, app_url, expected_console_errors):
    open_app(page, app_url)
    send(page, "first")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    expected_console_errors.append("net::ERR_FAILED")
    page.route("**/api/conversations/*/edit", lambda route: route.abort())
    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Edit your message").fill("first, reworded")
    page.get_by_role("button", name="Save").click()
    expect(page.locator(".msg.error")).to_contain_text("Couldn't get a reply")
    page.unroute("**/api/conversations/*/edit")
    page.get_by_role("button", name="Retry").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #2 to first, reworded")
    assert [(m["role"], m["content"]) for m in saved_messages(page)] == [
        ("user", "first, reworded"),
        ("assistant", "Reply #2 to **first, reworded**"),
    ]


def test_retry_when_the_server_cannot_be_reached_says_so_and_can_be_retried(page, app_url, expected_console_errors):
    open_app(page, app_url)
    expected_console_errors.append("net::ERR_FAILED")
    page.route("**/api/conversations/*/chat", lambda route: route.abort())
    send(page, "hello")
    expect(page.locator(".msg.error")).to_contain_text("Couldn't get a reply")
    page.unroute("**/api/conversations/*/chat")

    def abort_reads(route):
        route.abort() if route.request.method == "GET" else route.continue_()

    page.route("**/api/conversations/*", abort_reads)
    page.get_by_role("button", name="Retry").click()
    expect(page.locator(".msg.error")).to_contain_text("Couldn't reach the server")
    page.unroute("**/api/conversations/*")
    page.get_by_role("button", name="Retry").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1 to hello")


# ---- scrolling ----

def test_reader_scrolling_up_is_not_yanked_down_and_can_jump_back(page, app_url):
    page.set_viewport_size({"width": 1100, "height": 500})
    open_app(page, app_url)
    send(page, "long answer")
    messages = page.locator("#messages")
    page.wait_for_function(
        "() => { const el = document.getElementById('messages'); return el.scrollHeight - el.clientHeight > 300 }"
    )
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
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
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
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    open_sidebar(page)
    row_action(page, "old name", "Rename…")
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
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    open_sidebar(page)
    row_action(page, "stay put", "Rename…")
    page.get_by_label("Conversation title").fill("nope")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.locator("#conversations a")).to_have_text("stay put")


def finish_delete(page):
    """The chat is hidden at once and deleted on the server after a few seconds; leaving the page makes it final."""
    with page.expect_response(lambda r: r.request.method == "DELETE"):
        page.evaluate("window.dispatchEvent(new Event('pagehide'))")


def test_delete_asks_first_then_removes(page, app_url):
    open_app(page, app_url)
    send(page, "doomed chat")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    open_sidebar(page)
    row_action(page, "doomed chat", "Delete…")
    dialog = page.get_by_role("dialog", name="Delete this conversation?")
    expect(dialog).to_contain_text("doomed chat")
    dialog.get_by_role("button", name="Keep it").click()
    expect(page.locator("#conversations a")).to_have_text("doomed chat")
    row_action(page, "doomed chat", "Delete…")
    dialog.get_by_role("button", name="Delete").click()
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()
    expect(page.get_by_text("Your conversations will show up here.")).to_be_visible()


# ---- layout and theme ----

def test_sidebar_stays_open_when_switching_chats_on_desktop(page, app_url):
    open_app(page, app_url)
    send(page, "alpha")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    open_sidebar(page)
    page.get_by_role("button", name="New chat").click()
    send(page, "beta")
    expect(page.locator("#conversations li")).to_have_count(2)
    page.get_by_role("link", name="alpha").click()
    expect(page.locator(".msg.user .body")).to_have_text("alpha")
    expect(page.locator("#conversations")).to_be_visible()


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
    expect(page.locator("body")).to_have_css("background-color", "rgb(252, 251, 250)")
    page.emulate_media(color_scheme="dark")
    expect(page.locator("body")).to_have_css("background-color", "rgb(27, 26, 25)")
