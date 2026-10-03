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

def test_the_menu_lists_the_tools_besides_web_search_with_a_hint_each(page, app_url):
    open_app(page, app_url)
    open_menu(page)
    rows = page.locator("#tools-menu .tool-row")
    expect(rows).to_have_count(3)
    expect(rows.nth(0)).to_contain_text("Calculator")
    expect(rows.nth(0)).to_contain_text("Exact arithmetic")
    expect(rows.nth(1)).to_contain_text("Search chats")
    expect(rows.nth(2)).to_contain_text("Read web pages")
    expect(page.locator("#tools-menu")).not_to_contain_text("Web search")  # that one is the globe
    for i in range(3):
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


def test_several_tools_and_the_search_globe_work_together_and_persist(page, app_url):
    open_app(page, app_url)
    page.get_by_role("button", name="Web search").click()
    open_menu(page)
    row(page, "Search chats").get_by_role("checkbox").check()
    row(page, "Read web pages").get_by_role("checkbox").check()
    page.keyboard.press("Escape")
    send(page, "hello")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[tools=web_search,search_chats,fetch_url]")
    page.reload()
    expect(tools_btn(page)).to_have_attribute("data-active", "")
    expect(tools_btn(page)).to_have_attribute("title", "Tools: Search chats, Read web pages")
    open_menu(page)
    expect(row(page, "Search chats").get_by_role("checkbox")).to_be_checked()
    expect(row(page, "Calculator").get_by_role("checkbox")).not_to_be_checked()
    row(page, "Search chats").get_by_role("checkbox").uncheck()
    expect(tools_btn(page)).to_have_attribute("title", "Tools: Read web pages")
    assert saved_tools(page) == ["web_search", "fetch_url"]  # the globe's choice is untouched


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
    expected_console_errors.append("500")
    page.route("**/api/conversations/*",
               lambda r: r.fulfill(status=500) if r.request.method == "PATCH" else r.fallback())
    open_menu(page)
    row(page, "Calculator").get_by_role("checkbox").check()
    expect(row(page, "Calculator").get_by_role("checkbox")).not_to_be_checked()
    expect(page.locator("#composer-note")).to_contain_text("Couldn't change Calculator")


def test_the_button_is_hidden_when_only_web_search_is_available(page, app_url):
    page.route("**/api/tools", lambda r: r.fulfill(json=[{"name": "web_search", "label": "Web search", "hint": ""}]))
    open_app(page, app_url)
    expect(page.get_by_role("button", name="Web search")).to_be_visible()
    expect(tools_btn(page)).to_be_hidden()


def test_the_menu_is_keyboard_operable(page, app_url):
    open_app(page, app_url)
    tools_btn(page).focus()
    page.keyboard.press("Enter")
    expect(page.locator("#tools-menu")).to_be_visible()
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
