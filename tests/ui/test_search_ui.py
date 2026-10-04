import json
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import conv_id, open_app, open_chat_settings, open_sidebar, saved_messages, send


def toggle(page):
    return page.get_by_role("button", name="Web search")


def saved_tools(page):
    origin = page.url.split("#")[0]
    return page.request.get(f"{origin}api/conversations/{conv_id(page)}").json()["settings"]["tools"]


def search_on(page):
    toggle(page).click()
    expect(toggle(page)).to_have_attribute("aria-pressed", "true")


# ---- the toggle ----

def test_the_toggle_is_off_by_default_and_turns_on_and_off(page, app_url):
    open_app(page, app_url)
    expect(toggle(page)).to_be_visible()
    expect(toggle(page)).to_have_attribute("aria-pressed", "false")
    expect(toggle(page)).to_have_attribute("title", "Web search: off")
    toggle(page).click()
    expect(toggle(page)).to_have_attribute("aria-pressed", "true")
    expect(toggle(page)).to_have_attribute("title", "Web search: on")
    expect(toggle(page)).not_to_contain_text("Search")  # on is shown by color alone, with no label
    expect(toggle(page)).to_have_text("")
    expect(page.locator(".toggle-label")).to_have_count(0)
    toggle(page).click()
    expect(toggle(page)).to_have_attribute("aria-pressed", "false")


def test_the_toggle_is_named_after_the_tool_the_server_offers(page, app_url):
    # The tool carries its own display name, so the button takes it from /api/tools rather than from the
    # wording baked into the page.
    page.route("**/api/tools", lambda route: route.fulfill(json=[{"name": "web_search", "label": "Brave search"}]))
    open_app(page, app_url)
    named = page.get_by_role("button", name="Brave search")
    expect(named).to_be_visible()
    expect(named).to_have_attribute("title", "Brave search: off")


def test_it_is_shown_but_disabled_when_search_is_not_configured(page, app_url):
    page.route("**/api/tools", lambda route: route.fulfill(json=[]))
    open_app(page, app_url)
    expect(toggle(page)).to_be_visible()
    expect(toggle(page)).to_be_disabled()
    expect(toggle(page)).to_have_attribute("title", "Web search is unavailable: set BRAVE_API_KEY on the server")


def test_a_choice_made_on_the_new_chat_screen_applies_to_the_first_message(page, app_url):
    open_app(page, app_url)
    search_on(page)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("[tools=web_search]")
    assert saved_tools(page) == ["web_search"]


def test_with_the_toggle_off_the_model_gets_no_tools(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    expect(page.locator(".msg.assistant .body")).not_to_contain_text("[tools=")


def test_the_setting_persists_per_conversation(page, app_url):
    open_app(page, app_url)
    search_on(page)
    send(page, "with search")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    page.reload()
    expect(toggle(page)).to_have_attribute("aria-pressed", "true")

    open_sidebar(page)
    page.get_by_role("button", name="New chat").click()
    expect(toggle(page)).to_have_attribute("aria-pressed", "false")  # a new chat starts off
    send(page, "without search")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #2")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved

    page.get_by_role("link", name="with search").click()
    expect(page.locator(".msg.user .body")).to_have_text("with search")
    expect(toggle(page)).to_have_attribute("aria-pressed", "true")


def test_turning_it_on_mid_conversation_applies_from_the_next_message(page, app_url):
    open_app(page, app_url)
    send(page, "first")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    search_on(page)
    send(page, "second")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("[tools=web_search]")
    expect(page.locator(".msg.assistant").nth(0)).not_to_contain_text("[tools=")


def test_saving_the_settings_dialog_keeps_the_search_setting(page, app_url):
    """The dialog doesn't show the tools; saving it must not drop them."""
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    search_on(page)
    open_chat_settings(page)
    page.get_by_label("System prompt").fill("Be brief")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("dialog")).to_be_hidden()
    expect(toggle(page)).to_have_attribute("aria-pressed", "true")
    assert saved_tools(page) == ["web_search"]


def test_the_toggle_does_not_light_the_settings_dot_and_picking_a_model_keeps_it(page, app_url):
    open_app(page, app_url)
    search_on(page)
    expect(page.get_by_role("button", name="Chat actions")).not_to_have_attribute("data-active", "")
    page.get_by_role("button", name=re.compile("^Model")).click()
    page.get_by_role("menuitemradio", name=re.compile("^alpha-model")).click()
    expect(toggle(page)).to_have_attribute("aria-pressed", "true")  # saving the model kept the tools


def test_a_failed_save_says_so_and_keeps_the_old_state(page, app_url, expected_console_errors):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    expected_console_errors.append("net::ERR_FAILED")

    def abort_patch(route):
        route.abort() if route.request.method == "PATCH" else route.continue_()

    page.route("**/api/conversations/*", abort_patch)
    toggle(page).click()
    expect(page.get_by_role("alert").filter(has_text="Couldn't change web search")).to_be_visible()
    expect(toggle(page)).to_have_attribute("aria-pressed", "false")
    page.unroute("**/api/conversations/*")
    toggle(page).click()
    expect(toggle(page)).to_have_attribute("aria-pressed", "true")


def test_the_toggle_works_from_the_keyboard(page, app_url):
    open_app(page, app_url)
    expect(toggle(page)).to_be_enabled()  # it is disabled until the page has asked which tools exist
    toggle(page).focus()
    page.keyboard.press("Space")
    expect(toggle(page)).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("Enter")
    expect(toggle(page)).to_have_attribute("aria-pressed", "false")


# ---- a search in a reply ----

def test_a_search_shows_while_it_runs_then_its_results_and_the_cited_answer(page, app_url):
    open_app(page, app_url)
    search_on(page)
    send(page, "findweb python")
    call = page.locator(".tool-call")
    expect(call).to_have_attribute("data-status", "running")
    expect(call.locator("summary")).to_have_text("Searching the web for “python version”…")
    expect(call).to_have_attribute("aria-busy", "true")
    expect(page.locator(".dots")).to_have_count(0)  # the search line is the progress indicator

    expect(call).to_have_attribute("data-status", "done")
    expect(call.locator("summary")).to_have_text("Searched the web for “python version” · 3 results")
    expect(call).not_to_have_attribute("open", "")  # collapsed
    expect(page.locator(".msg.assistant .body a")).to_have_attribute("href", "https://www.python.org/")
    expect(page.locator(".msg.assistant .body strong")).to_have_text("3.14")


def test_the_results_open_to_titles_domains_and_snippets_with_safe_links(page, app_url):
    open_app(page, app_url)
    search_on(page)
    send(page, "findweb python")
    call = page.locator(".tool-call")
    expect(call).to_have_attribute("data-status", "done")
    call.locator("summary").click()
    links = call.locator(".tool-body a")
    expect(links).to_have_text(["Python Releases", "What's new"])  # the javascript: result is not a link
    expect(links.first).to_have_attribute("href", "https://www.python.org/downloads/")
    expect(links.first).to_have_attribute("target", "_blank")
    expect(links.first).to_have_attribute("rel", re.compile("noopener"))
    expect(call.locator(".domain")).to_have_text(["python.org", "docs.python.org"])
    expect(call.locator(".tool-body p")).to_have_text("The latest release.")
    assert page.evaluate("window.__xss") is None


def test_a_search_survives_a_reload(page, app_url):
    open_app(page, app_url)
    search_on(page)
    send(page, "findweb python")
    expect(page.locator(".tool-call")).to_have_attribute("data-status", "done")
    expect(page.locator(".msg.assistant .body strong")).to_have_text("3.14")
    page.reload()
    call = page.locator(".tool-call")
    expect(call.locator("summary")).to_have_text("Searched the web for “python version” · 3 results")
    call.locator("summary").click()
    expect(call.locator(".tool-body a")).to_have_count(2)
    saved = saved_messages(page)[-1]["meta"]["tools"]
    assert [(t["name"], t["status"]) for t in saved] == [("web_search", "done")]


def test_a_failed_search_says_why_and_the_reply_carries_on(page, app_url):
    open_app(page, app_url)
    search_on(page)
    send(page, "findwebbroken")
    call = page.locator(".tool-call")
    expect(call).to_have_attribute("data-status", "error")
    expect(call.locator("summary")).to_have_text("Web search failed: Search rate limit reached.")
    expect(page.locator(".msg.assistant .body")).to_contain_text("Sorry, I couldn't search.")


def test_stopping_during_a_search_marks_it_stopped_and_keeps_the_text_so_far(page, app_url):
    open_app(page, app_url)
    search_on(page)
    send(page, "findwebhang")
    expect(page.locator(".tool-call")).to_have_attribute("data-status", "running")
    page.get_by_role("button", name="Stop generating").click()
    call = page.locator(".tool-call")
    expect(call).to_have_attribute("data-status", "stopped")
    expect(call.locator("summary")).to_have_text("Web search stopped")
    expect(page.locator(".msg.assistant .body")).to_contain_text("Let me look.")
    page.wait_for_function(
        "async (url) => (await (await fetch(url)).json()).messages.length === 2",
        arg=f"{app_url}/api/conversations/{conv_id(page)}",
    )
    page.reload()
    expect(page.locator(".tool-call summary")).to_have_text("Web search stopped")


def sse_body(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events)


def fake_turn(page, *events):
    """Answer the chat POST with these events instead of the scripted model."""
    page.route("**/api/conversations/*/chat", lambda route: route.fulfill(
        status=200, headers={"content-type": "text/event-stream"}, body=sse_body(*events)))


RUNNING = {"type": "tool_call", "id": "c1", "name": "web_search", "status": "running", "arguments": {"query": "q"}}


def test_a_reply_that_fails_after_a_search_drops_its_search_lines(page, app_url):
    open_app(page, app_url)
    search_on(page)
    fake_turn(page, RUNNING, {"type": "error", "message": "the model fell over"})
    send(page, "anything")
    expect(page.locator(".msg.error")).to_contain_text("the model fell over")
    expect(page.locator(".tool-call")).to_have_count(0)


def test_the_search_line_and_results_are_text_not_markup(page, app_url):
    open_app(page, app_url)
    search_on(page)
    nasty = "<img src=x onerror=window.__xss=1>"
    arguments = {"query": nasty}
    shown = {"query": nasty, "results": [
        {"title": nasty, "url": "https://example.com/a", "description": f"<b>{nasty}</b>"}]}
    fake_turn(page, {**RUNNING, "arguments": arguments},
              {**RUNNING, "status": "done", "arguments": arguments, "display": shown},
              {"type": "delta", "text": "ok"}, {"type": "done"})
    send(page, "anything")
    call = page.locator(".tool-call")
    expect(call).to_have_attribute("data-status", "done")
    expect(call.locator("summary")).to_contain_text(nasty)  # shown literally
    call.locator("summary").click()
    expect(call.locator(".tool-body a")).to_have_text(nasty)
    expect(call.locator("img, b")).to_have_count(0)
    assert page.evaluate("window.__xss") is None


def test_a_tool_the_page_does_not_know_still_shows_up(page, app_url):
    open_app(page, app_url)
    unknown = {"type": "tool_call", "id": "x1", "name": "mystery_tool", "arguments": {}}
    fake_turn(page, {**unknown, "status": "running"}, {**unknown, "status": "done", "display": {}},
              {"type": "delta", "text": "42"}, {"type": "done"})
    send(page, "6 times 7")
    expect(page.locator(".tool-call summary")).to_have_text("Used mystery_tool")


def test_on_a_phone_the_toggle_fits_when_on(page, app_url):
    page.set_viewport_size({"width": 375, "height": 700})
    open_app(page, app_url)
    search_on(page)
    composer = page.locator(".composer").bounding_box()
    box = toggle(page).bounding_box()
    assert box["x"] >= composer["x"] and box["x"] + box["width"] <= composer["x"] + composer["width"]
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_the_pressed_toggle_changes_color_only_with_no_label_or_background(page, app_url):
    open_app(page, app_url)
    colors = lambda: toggle(page).evaluate(  # noqa: E731
        "e => { const s = getComputedStyle(e); return [s.color, s.backgroundColor]; }")
    page.locator("#search-toggle").evaluate("e => e.style.transition = 'none'")
    off = colors()
    search_on(page)
    page.mouse.move(0, 0)  # the hover background is not the pressed state
    on = colors()
    assert on[0] != off[0]  # accent color
    assert on[1] == off[1]  # no background highlight
    assert toggle(page).bounding_box()["width"] == page.locator("#attach").bounding_box()["width"]  # no wider when on
