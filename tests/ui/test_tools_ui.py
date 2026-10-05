"""The Tools menu and how the calculator, search_chats and fetch_url calls read in a reply."""
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import conv_id, open_app, send


def tools_btn(page):
    return page.get_by_role("button", name="Tools", exact=True)


def open_menu(page):
    tools_btn(page).click()
    expect(page.locator("#tools-menu")).to_be_visible()


def saved_tools(page):
    origin = page.url.split("#")[0]
    return page.request.get(f"{origin}api/conversations/{conv_id(page)}").json()["settings"]["tools"]


def row(page, label):
    return page.locator("#tools-menu .tool-row").filter(has_text=label)


# ---- the menu ----

def test_the_menu_lists_every_tool_in_the_order_the_server_gives_them(page, app_url):
    open_app(page, app_url)
    open_menu(page)
    rows = page.locator("#tools-menu .tool-row")
    expect(rows).to_have_count(7)
    expect(rows.nth(0)).to_contain_text("Web search")
    expect(rows.nth(1)).to_contain_text("Calculator")
    expect(rows.nth(1)).to_contain_text("Exact arithmetic")  # a hint each, where the tool has one
    expect(rows.nth(2)).to_contain_text("Search chats")
    expect(rows.nth(3)).to_contain_text("Read web pages")
    expect(rows.nth(4)).to_contain_text("Date and time")
    expect(rows.nth(5)).to_contain_text("Read chats")
    expect(rows.nth(6)).to_contain_text("Read attached files")
    for i in range(7):
        expect(rows.nth(i).get_by_role("checkbox")).not_to_be_checked()  # all off by default


def test_the_menu_opens_above_the_composer_and_inside_the_window(page, app_url):
    open_app(page, app_url)
    open_menu(page)
    menu, button = page.locator("#tools-menu").bounding_box(), tools_btn(page).bounding_box()
    assert menu["y"] + menu["height"] <= button["y"] + 1
    assert menu["x"] >= 0 and menu["x"] + menu["width"] <= page.viewport_size["width"]


def test_switching_a_tool_on_applies_to_the_first_message_of_a_new_chat(page, app_url):
    open_app(page, app_url)
    open_menu(page)
    row(page, "Calculator").get_by_role("checkbox").check()
    page.keyboard.press("Escape")
    expect(tools_btn(page)).to_have_attribute("data-active", "")
    send(page, "hello")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[tools=calculator]")
    assert saved_tools(page) == ["calculator"]


def test_several_tools_work_together_and_persist(page, app_url):
    open_app(page, app_url)
    open_menu(page)
    row(page, "Web search").get_by_role("checkbox").check()
    row(page, "Search chats").get_by_role("checkbox").check()
    row(page, "Read web pages").get_by_role("checkbox").check()
    page.keyboard.press("Escape")
    send(page, "hello")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[tools=web_search,search_chats,fetch_url]")
    page.reload()
    expect(tools_btn(page)).to_have_attribute("data-active", "")
    expect(tools_btn(page)).to_have_attribute("title", "Tools: Web search, Search chats, Read web pages")
    open_menu(page)
    expect(row(page, "Web search").get_by_role("checkbox")).to_be_checked()
    expect(row(page, "Search chats").get_by_role("checkbox")).to_be_checked()
    expect(row(page, "Calculator").get_by_role("checkbox")).not_to_be_checked()
    row(page, "Search chats").get_by_role("checkbox").uncheck()
    expect(tools_btn(page)).to_have_attribute("title", "Tools: Web search, Read web pages")
    assert saved_tools(page) == ["web_search", "fetch_url"]


def test_each_chat_keeps_its_own_tools(page, app_url):
    open_app(page, app_url)
    open_menu(page)
    row(page, "Calculator").get_by_role("checkbox").check()
    page.keyboard.press("Escape")
    send(page, "first chat")
    expect(page.locator(".msg.assistant")).to_contain_text("[tools=calculator]")
    page.get_by_role("button", name="New chat").click()
    expect(tools_btn(page)).not_to_have_attribute("data-active", "")
    send(page, "second chat")
    expect(page.locator(".msg.assistant .body")).not_to_contain_text("tools=")


def test_a_failed_save_puts_the_checkbox_back_and_says_so(page, app_url, expected_console_errors):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    expected_console_errors.append("500")
    page.route("**/api/conversations/*",
               lambda r: r.fulfill(status=500) if r.request.method == "PATCH" else r.fallback())
    open_menu(page)
    row(page, "Calculator").get_by_role("checkbox").check()
    expect(row(page, "Calculator").get_by_role("checkbox")).not_to_be_checked()
    expect(page.locator("#composer-note")).to_contain_text("Couldn't change Calculator")


def test_the_button_is_shown_when_only_web_search_is_available(page, app_url):
    page.route("**/api/tools", lambda r: r.fulfill(json=[{"name": "web_search", "label": "Web search", "hint": ""}]))
    open_app(page, app_url)
    expect(tools_btn(page)).to_be_visible()  # it used to be hidden, when web search had a globe of its own
    open_menu(page)
    expect(row(page, "Web search").get_by_role("checkbox")).not_to_be_checked()


def test_the_button_is_hidden_when_the_server_offers_no_tools(page, app_url):
    page.route("**/api/tools", lambda r: r.fulfill(json=[]))
    open_app(page, app_url)
    expect(tools_btn(page)).to_be_hidden()


def test_the_button_is_the_accent_when_a_tool_is_on_and_never_resizes(page, app_url):
    open_app(page, app_url)
    page.locator("#tools-btn").evaluate("e => e.style.transition = 'none'")
    colors = lambda: tools_btn(page).evaluate(  # noqa: E731
        "e => { const s = getComputedStyle(e); return [s.color, s.backgroundColor]; }")
    off = colors()
    off_box = tools_btn(page).bounding_box()
    open_menu(page)
    row(page, "Web search").get_by_role("checkbox").check()
    page.keyboard.press("Escape")
    page.mouse.move(0, 0)  # the hover background is not the active state
    on = colors()
    assert on[0] != off[0]  # accent color
    assert on[1] == off[1]  # no background highlight: that was taken out on purpose
    assert tools_btn(page).bounding_box() == off_box  # nothing is written beside the wrench


def test_the_menu_is_keyboard_operable(page, app_url):
    open_app(page, app_url)
    tools_btn(page).focus()
    page.keyboard.press("Enter")
    expect(page.locator("#tools-menu")).to_be_visible()
    expect(row(page, "Web search").get_by_role("checkbox")).to_be_focused()  # the first tool is first
    page.keyboard.press("Tab")
    expect(row(page, "Calculator").get_by_role("checkbox")).to_be_focused()
    page.keyboard.press("Space")
    expect(row(page, "Calculator").get_by_role("checkbox")).to_be_checked()
    page.keyboard.press("Escape")
    expect(page.locator("#tools-menu")).to_be_hidden()
    expect(tools_btn(page)).to_be_focused()


# ---- how the calls read ----

def test_the_calculator_shows_the_sum_and_the_answer(page, app_url):
    open_app(page, app_url)
    send(page, "calcsum")
    summary = page.locator(".tool-call summary")
    expect(summary).to_have_text("Calculating 17 * 23…")
    expect(summary).to_have_text("17 * 23 = 391")
    expect(page.locator(".msg.assistant .body")).to_contain_text("It is 391.")
    expect(page.locator(".tool-call .tool-body > *")).to_have_count(0)  # nothing more to open
    page.reload()
    expect(page.locator(".tool-call summary")).to_have_text("17 * 23 = 391")


def test_a_calculator_error_is_shown_and_the_reply_goes_on(page, app_url):
    open_app(page, app_url)
    send(page, "calcbad")
    expect(page.locator(".tool-call summary")).to_have_text("Calculator: Division by zero.")
    expect(page.locator(".tool-call")).to_have_attribute("data-status", "error")
    expect(page.locator(".msg.assistant .body")).to_contain_text("can't be calculated")


def test_a_chat_search_lists_matches_as_links_to_those_chats_with_inert_text(page, app_url):
    open_app(page, app_url)
    send(page, "findchats")
    summary = page.locator(".tool-call summary")
    expect(summary).to_have_text("Searched your chats for “mutex” · 1 chat")
    summary.click()
    link = page.locator(".tool-body a")
    expect(link).to_have_text("Threads <i>and</i> locks")  # text, not markup
    expect(link).to_have_attribute("href", "#abc123")
    expect(page.locator(".tool-body p")).to_have_text("use a mutex <b>around</b> it")
    expect(page.locator(".tool-body i, .tool-body b")).to_have_count(0)
    assert link.get_attribute("target") is None  # a chat in this app opens in this tab


def test_a_fetched_page_shows_its_title_link_and_size(page, app_url):
    open_app(page, app_url)
    send(page, "readpage")
    summary = page.locator(".tool-call summary")
    expect(summary).to_have_text("Read Example post")
    summary.click()
    link = page.locator(".tool-body a")
    expect(link).to_have_attribute("href", "https://example.com/post")
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    expect(link).to_have_attribute("target", "_blank")
    expect(page.locator(".tool-body p")).to_have_text("1,234 characters read of 5,000; there is more")


def test_a_fetched_page_with_a_hostile_url_and_title_stays_inert(page, app_url):
    open_app(page, app_url)
    send(page, "readevil")
    summary = page.locator(".tool-call summary")
    expect(summary).to_have_text("Read <img src=x onerror=window.__xss=1>")
    summary.click()
    expect(page.locator(".tool-body a")).to_have_count(0)  # not a web URL, so no link at all
    expect(page.locator(".tool-call img")).to_have_count(0)
    assert page.evaluate("window.__xss") is None


def test_the_running_lines_name_what_is_happening(page, app_url):
    open_app(page, app_url)
    send(page, "readpage")
    expect(page.locator(".tool-call summary")).to_have_text(re.compile(r"Reading example\.com…|Read Example post"))


def fetched(page, display):
    from tests.ui.test_search_ui import fake_turn

    call = {"type": "tool_call", "id": "f1", "name": "fetch_url", "arguments": {"url": "https://example.com/p"}}
    fake_turn(page, {**call, "status": "running"}, {**call, "status": "done", "display": display},
              {"type": "delta", "text": "ok"}, {"type": "done"})
    send(page, "read it")
    page.locator(".tool-call summary").click()
    return page.locator(".tool-body p")


def test_a_later_part_of_a_page_says_where_it_starts(page, app_url):
    open_app(page, app_url)
    shown = {"url": "https://example.com/p", "title": "Long", "characters": 12000, "offset": 12000, "total": 30000,
             "truncated": True}
    expect(fetched(page, shown)).to_have_text("12,000 characters read from character 12,000 of 30,000; there is more")


def test_the_last_part_does_not_claim_there_is_more(page, app_url):
    open_app(page, app_url)
    shown = {"url": "https://example.com/p", "title": "Long", "characters": 6000, "offset": 24000, "total": 30000,
             "truncated": False}
    expect(fetched(page, shown)).to_have_text("6,000 characters read from character 24,000 of 30,000")


def test_a_page_saved_before_pages_came_in_parts_still_shows(page, app_url):
    open_app(page, app_url)
    older = {"url": "https://example.com/p", "title": "Old", "characters": 900, "truncated": False}  # no offset, total
    expect(fetched(page, older)).to_have_text("900 characters read")


def test_the_date_tool_shows_the_time_and_opens_to_the_extra_lines_as_text(page, app_url):
    open_app(page, app_url)
    send(page, "checktime")
    summary = page.locator(".tool-call summary")
    expect(summary).to_have_text("Checking the time…")
    expect(summary).to_have_text("Monday 5 October 2026, 14:03 · PKT, UTC+05:00")
    summary.click()
    line = "Friday 25 December 2026, 00:00 (UTC+05:00) is in 80 days <b>9</b> hours"
    expect(page.locator(".tool-body li")).to_have_text(line)
    expect(page.locator(".tool-body b")).to_have_count(0)
    page.reload()
    expect(page.locator(".tool-call summary")).to_have_text("Monday 5 October 2026, 14:03 · PKT, UTC+05:00")


def test_a_chat_read_links_to_that_chat_with_inert_text(page, app_url):
    open_app(page, app_url)
    send(page, "readchatx")
    summary = page.locator(".tool-call summary")
    expect(summary).to_have_text("Read “Plans <i>for</i> May” · messages 4 to 9 of 20")
    summary.click()
    link = page.locator(".tool-body a")
    expect(link).to_have_text("Plans <i>for</i> May")
    expect(link).to_have_attribute("href", "#abc123")
    expect(page.locator(".tool-body i")).to_have_count(0)


def test_a_file_read_names_the_file_and_where_it_stopped_and_a_listing_names_them_all(page, app_url):
    open_app(page, app_url)
    send(page, "readfilex")
    summary = page.locator(".tool-call summary")
    expect(summary).to_have_text("Reading notes.txt…")
    expect(summary).to_have_text("Read <img src=x onerror=window.__xss=1>.txt from character 12,000")
    summary.click()
    expect(page.locator(".tool-body p")).to_have_text(
        "12,000 characters read from character 12,000 of 30,000; there is more")
    assert page.evaluate("window.__xss") is None and page.locator(".tool-call img").count() == 0

    page.get_by_role("button", name="New chat").click()
    send(page, "listfilesx")
    summary = page.locator(".tool-call summary")
    expect(summary).to_have_text("Looking at the attached files…")
    expect(summary).to_have_text("Listed the attached files · 2 files")
    summary.click()
    expect(page.locator(".tool-body li")).to_have_text(["a <b>b</b>.txt", "c.pdf"])
    expect(page.locator(".tool-body b")).to_have_count(0)


def test_the_tools_list_scrolls_when_there_are_more_tools_than_room_and_every_one_is_reachable(page, app_url):
    open_app(page, app_url)
    open_menu(page)
    assert page.locator("#tools-list").evaluate("e => e.scrollHeight > e.clientHeight")  # seven tools, a hint each
    expect(page.locator("#tools-list input").first).to_be_focused()  # the menu puts the focus on the first row
    last = row(page, "Read attached files").get_by_role("checkbox")
    last.focus()
    expect(last).to_be_in_viewport()  # focusing it scrolled the list to it
    page.keyboard.press("Space")
    expect(last).to_be_checked()


# ---- on by default ----

def test_a_new_chat_has_every_tool_but_web_search_on_until_the_user_chooses_otherwise(page, app_url):
    # the shipped default (the fixture starts with none on)
    page.request.put(f"{app_url}/api/defaults", data={"tools": None})
    open_app(page, app_url)
    expect(tools_btn(page)).to_have_attribute("data-active", "")
    open_menu(page)
    for label in ("Calculator", "Search chats", "Read web pages", "Date and time", "Read chats", "Read attached files"):
        expect(row(page, label).get_by_role("checkbox")).to_be_checked()
    expect(row(page, "Web search").get_by_role("checkbox")).not_to_be_checked()
    page.keyboard.press("Escape")
    send(page, "hello")
    expect(page.locator(".msg.assistant .body")).to_contain_text(
        "[tools=calculator,search_chats,fetch_url,get_datetime,read_chat,read_attachment]")
    assert saved_tools(page) == ["calculator", "search_chats", "fetch_url", "get_datetime", "read_chat",
                                 "read_attachment"]


def test_switching_a_tool_off_in_one_chat_leaves_the_next_chat_on_the_default(page, app_url):
    page.request.put(f"{app_url}/api/defaults", data={"tools": None})
    open_app(page, app_url)
    open_menu(page)
    row(page, "Calculator").get_by_role("checkbox").uncheck()
    page.keyboard.press("Escape")
    send(page, "first")
    expect(page.locator(".msg.assistant .body")).not_to_contain_text("calculator")
    page.get_by_role("button", name="New chat").click()
    open_menu(page)
    expect(row(page, "Calculator").get_by_role("checkbox")).to_be_checked()


def test_changing_something_in_settings_does_not_turn_the_default_tools_off(page, app_url):
    """The bug that made the menu look wrong: Settings used to save every default whatever was changed, tools included
    (then an empty list), so after touching the thinking effort a new chat started with none on."""
    page.request.put(f"{app_url}/api/defaults", data={"tools": None})
    open_app(page, app_url)
    page.get_by_role("button", name="Settings", exact=True).click()
    dialog = page.get_by_role("dialog", name="Settings", exact=True)
    dialog.get_by_label("Model", exact=True).select_option("gpt-5-mini")
    dialog.get_by_label("Thinking effort").select_option("high")
    page.wait_for_function(
        "async () => (await (await fetch('/api/defaults')).json()).reasoning_effort === 'high'")
    page.keyboard.press("Escape")
    page.reload()
    open_menu(page)
    expect(row(page, "Calculator").get_by_role("checkbox")).to_be_checked()
    expect(row(page, "Read attached files").get_by_role("checkbox")).to_be_checked()
    expect(row(page, "Web search").get_by_role("checkbox")).not_to_be_checked()


def test_the_web_search_switch_in_settings_leaves_the_other_default_tools_on(page, app_url):
    page.request.put(f"{app_url}/api/defaults", data={"tools": None})
    open_app(page, app_url)
    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("dialog", name="Settings", exact=True).get_by_role("switch", name="Web search").check()
    page.wait_for_function(
        "async () => (await (await fetch('/api/defaults')).json()).tools.includes('web_search')")
    page.keyboard.press("Escape")
    open_menu(page)
    expect(row(page, "Web search").get_by_role("checkbox")).to_be_checked()  # the new chat on screen follows at once
    expect(row(page, "Calculator").get_by_role("checkbox")).to_be_checked()
    expect(row(page, "Read chats").get_by_role("checkbox")).to_be_checked()
