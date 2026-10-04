"""The Settings dialog: sections as tabs, what each holds, the keyboard, and the phone layout."""
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_prefs, open_sidebar, send

TABS = ["General", "Personalization", "Data controls", "Server"]


def dialog(page):
    return page.get_by_role("dialog", name="Settings", exact=True)


def test_the_gear_opens_settings_on_general_with_four_sections(page, app_url):
    open_app(page, app_url)
    d = open_prefs(page)
    expect(d.get_by_role("tab")).to_have_text(TABS)
    expect(d.get_by_role("tab", name="General")).to_have_attribute("aria-selected", "true")
    expect(d.get_by_role("tabpanel")).to_have_count(1)  # only the selected one is shown
    expect(d.get_by_role("heading", name="Keyboard shortcuts")).to_be_visible()


def test_settings_opens_on_the_tab_it_was_left_on_and_reload_keeps_it(page, app_url):
    open_app(page, app_url)
    open_prefs(page, "Data controls")
    page.keyboard.press("Escape")
    for _ in range(2):
        page.get_by_role("button", name="Settings", exact=True).click()
        expect(dialog(page).get_by_role("tab", name="Data controls")).to_have_attribute("aria-selected", "true")
        expect(dialog(page).get_by_role("tabpanel")).to_contain_text("Export")
        page.keyboard.press("Escape")
        page.reload()


def test_the_scattered_buttons_are_gone_from_the_sidebar(page, app_url):
    open_app(page, app_url)
    open_sidebar(page)
    footer = page.locator(".side-foot")
    expect(footer.get_by_role("button")).to_have_text(["Archived chats", "Settings"])
    for gone in ("Custom instructions", "Backup & import", "Theme"):
        expect(page.get_by_role("button", name=gone)).to_have_count(0)


def test_each_tab_shows_its_own_panel(page, app_url):
    open_app(page, app_url)
    d = open_prefs(page)
    for tab, heading in [("Personalization", "Custom instructions"), ("Data controls", "Export"),
                         ("Server", "Connection"), ("General", "Appearance")]:
        d.get_by_role("tab", name=tab).click()
        expect(d.get_by_role("tab", name=tab)).to_have_attribute("aria-selected", "true")
        expect(d.get_by_role("tabpanel")).to_have_count(1)
        expect(d.get_by_role("tabpanel")).to_contain_text(heading)


def test_the_tabs_work_with_arrows_home_and_end_and_only_one_is_in_the_tab_order(page, app_url):
    open_app(page, app_url)
    d = open_prefs(page)
    general = d.get_by_role("tab", name="General")
    general.focus()
    page.keyboard.press("ArrowDown")
    expect(d.get_by_role("tab", name="Personalization")).to_be_focused()
    expect(d.get_by_role("tab", name="Personalization")).to_have_attribute("aria-selected", "true")
    expect(d.get_by_role("tabpanel")).to_contain_text("Custom instructions")
    page.keyboard.press("End")
    expect(d.get_by_role("tab", name="Server")).to_be_focused()
    page.keyboard.press("ArrowDown")  # wraps
    expect(general).to_be_focused()
    page.keyboard.press("ArrowUp")
    expect(d.get_by_role("tab", name="Server")).to_be_focused()
    page.keyboard.press("Home")
    expect(general).to_be_focused()
    tabbable = d.get_by_role("tab").evaluate_all(
        "tabs => tabs.filter((t) => t.tabIndex === 0).map((t) => t.innerText)")
    assert tabbable == ["General"]


def test_it_closes_with_the_button_escape_or_a_click_outside_and_the_focus_goes_back(page, app_url):
    open_app(page, app_url)
    gear = page.get_by_role("button", name="Settings", exact=True)
    d = open_prefs(page)
    d.get_by_role("button", name="Close settings").click()
    expect(d).to_be_hidden()
    expect(gear).to_be_focused()
    open_prefs(page)
    page.keyboard.press("Escape")
    expect(d).to_be_hidden()
    open_prefs(page)
    page.mouse.click(5, 5)  # on the backdrop
    expect(d).to_be_hidden()


def test_the_shortcuts_are_listed_for_this_platform(page, app_url):
    open_app(page, app_url)
    d = open_prefs(page)
    rows = d.locator("#shortcut-list .pref-row")
    expect(rows).to_have_count(5)
    expect(rows.nth(0)).to_contain_text("Search chats")
    expect(rows.nth(0).locator("kbd")).to_have_text(re.compile(r"^(⌘|Ctrl\+)K$"))
    expect(rows.nth(1).locator("kbd")).to_have_text(re.compile(r"^(⌘|Ctrl\+)Shift\+O$"))
    expect(d.locator("#shortcut-list")).to_contain_text("Esc")


def test_the_note_says_where_the_per_chat_settings_are(page, app_url):
    open_app(page, app_url)
    expect(open_prefs(page)).to_contain_text("One chat can differ")


# ---- Personalization ----

def test_unsaved_instructions_survive_switching_tabs_and_saving_says_saved(page, app_url):
    open_app(page, app_url)
    d = open_prefs(page, "Personalization")
    box = d.get_by_label("What should the model know about you")
    box.fill("Answer in French.")
    d.get_by_role("tab", name="Server").click()
    d.get_by_role("tab", name="Personalization").click()
    expect(box).to_have_value("Answer in French.")  # not reloaded over what was typed
    d.get_by_role("button", name="Save").click()
    expect(d.get_by_role("status")).to_have_text("Saved.")
    box.fill("Answer in French, briefly.")
    expect(d.get_by_role("status")).to_have_text("")  # an edit makes "Saved." stale, so it goes


def test_a_failed_save_says_so_and_keeps_the_text(page, app_url, expected_console_errors):
    expected_console_errors.append("500")
    open_app(page, app_url)
    page.route("**/api/custom-instructions", lambda r: r.fulfill(status=500, body="no")
               if r.request.method == "PUT" else r.continue_())
    d = open_prefs(page, "Personalization")
    box = d.get_by_label("What should the model know about you")
    box.fill("keep me")
    d.get_by_role("button", name="Save").click()
    expect(d.get_by_role("status")).to_contain_text("Couldn't save")
    expect(box).to_have_value("keep me")
    expect(d.get_by_role("button", name="Save")).to_be_enabled()


def test_the_built_in_instructions_can_be_read(page, app_url):
    open_app(page, app_url)
    d = open_prefs(page, "Personalization")
    d.get_by_text("What ChitChat always tells the model").click()
    expect(d.locator("#default-instructions-text")).to_contain_text("DEFAULT_SYSTEM_PROMPT is empty")  # the test setup


# ---- Server ----

def test_the_server_tab_shows_what_it_is_set_up_with_and_the_names_to_change_it(page, app_url):
    open_app(page, app_url)
    d = open_prefs(page, "Server")
    row = lambda label: d.locator(f'.pref-row:has(.pref-label:text-is("{label}"))')  # noqa: E731
    expect(row("Endpoint").locator("dd")).to_have_text("OpenAI")
    expect(row("Endpoint").locator("code")).to_have_text("OPENAI_BASE_URL")
    expect(row("Default model").locator("dd")).to_have_text("scripted-default")
    expect(row("Web search").locator("dd")).to_contain_text("Off")
    expect(row("Long conversations").locator("dd")).to_contain_text("OpenAI compacts")
    expect(row("Tool calls in one reply").locator("dd")).to_have_text("8")
    for heading in ("Connection", "Conversations", "Tools", "Storage"):
        expect(d.get_by_role("heading", name=heading)).to_be_visible()
    expect(d.get_by_role("tabpanel")).to_contain_text("edit that and restart")


def test_the_server_tab_says_when_it_cannot_reach_the_server(page, app_url, expected_console_errors):
    expected_console_errors.append("500")
    open_app(page, app_url)
    page.route("**/api/config", lambda r: r.fulfill(status=500, body="no"))
    d = open_prefs(page, "Server")
    expect(d.get_by_role("alert")).to_have_text("Couldn't reach the server.")


# ---- New chats: the defaults ----

def test_the_default_model_applies_to_chats_that_pick_none_and_survives_a_reload(page, app_url):
    open_app(page, app_url)
    d = open_prefs(page)
    model = d.get_by_label("Model", exact=True)
    expect(model.locator("option")).to_have_text(
        ["Server default (scripted-default)", "scripted-default", "alpha-model", "gpt-5-mini"])
    model.select_option("alpha-model")
    expect(page.get_by_role("button", name="alpha-model")).to_be_visible()  # the header follows the new default
    page.keyboard.press("Escape")
    send(page, "hello")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[model=alpha-model]")

    page.reload()
    d = open_prefs(page)
    expect(d.get_by_label("Model", exact=True)).to_have_value("alpha-model")
    d.get_by_label("Model", exact=True).select_option("")  # back to the server's
    page.keyboard.press("Escape")
    page.get_by_role("button", name="New chat").click()
    send(page, "again")
    expect(page.locator(".msg.assistant .body")).not_to_contain_text("[model=")


def test_the_default_thinking_effort_is_used_by_a_thinking_model(page, app_url):
    open_app(page, app_url)
    d = open_prefs(page)
    d.get_by_label("Model", exact=True).select_option("gpt-5-mini")
    d.get_by_label("Thinking effort").select_option("high")
    page.keyboard.press("Escape")
    send(page, "think")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[effort=high]")


def test_new_chats_start_with_web_search_when_the_switch_is_on(page, app_url):
    open_app(page, app_url)
    d = open_prefs(page)
    switch = d.get_by_role("switch", name="Web search")
    expect(switch).not_to_be_checked()
    switch.check()
    page.keyboard.press("Escape")
    tools = page.get_by_role("button", name="Tools", exact=True)
    expect(tools).to_have_attribute("title", "Tools: Web search")  # the chat on screen is a new one: it follows at once
    send(page, "look it up")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[tools=web_search]")
    page.locator("#tools-btn").click()  # this chat turns it off for itself
    page.locator("#tools-menu .tool-row", has_text="Web search").get_by_role("checkbox").uncheck()
    page.keyboard.press("Escape")
    expect(tools).not_to_have_attribute("data-active", "")

    page.get_by_role("button", name="New chat").click()
    # other chats still start with it on
    expect(tools).to_have_attribute("title", "Tools: Web search")

    d = open_prefs(page)
    d.get_by_role("switch", name="Web search").uncheck()
    page.keyboard.press("Escape")
    expect(tools).not_to_have_attribute("data-active", "")


def test_a_failed_save_is_said_and_the_control_goes_back(page, app_url, expected_console_errors):
    open_app(page, app_url)
    expected_console_errors.append("net::ERR_FAILED")
    page.route("**/api/defaults", lambda route: route.abort() if route.request.method == "PUT" else route.continue_())
    d = open_prefs(page)
    d.get_by_label("Model", exact=True).select_option("alpha-model")
    expect(d.get_by_role("alert")).to_contain_text("Couldn't save")
    expect(d.get_by_label("Model", exact=True)).to_have_value("")
    page.unroute("**/api/defaults")
    d.get_by_label("Model", exact=True).select_option("alpha-model")
    expect(d.get_by_role("alert")).to_be_hidden()
    expect(d.get_by_label("Model", exact=True)).to_have_value("alpha-model")


def test_the_web_search_switch_is_off_and_says_why_when_the_server_has_no_search(page, app_url):
    page.route("**/api/tools", lambda route: route.fulfill(json=[]))
    open_app(page, app_url)
    d = open_prefs(page)
    expect(d.get_by_role("switch", name="Web search")).to_be_disabled()
    expect(d).to_contain_text("set BRAVE_API_KEY")


# ---- the phone ----

def test_on_a_phone_the_sections_are_a_row_and_nothing_overflows(page, app_url):
    page.set_viewport_size({"width": 375, "height": 640})
    open_app(page, app_url)
    d = open_prefs(page)
    box = d.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    assert box["y"] >= 0 and box["y"] + box["height"] <= 640
    tabs = d.get_by_role("tab")
    first, second = tabs.nth(0).bounding_box(), tabs.nth(1).bounding_box()
    assert abs(first["y"] - second["y"]) < 2 and second["x"] > first["x"]  # side by side, not stacked
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    d.get_by_role("tab", name="Server").click()
    expect(d.get_by_role("tab", name="Server")).to_have_attribute("aria-selected", "true")
    expect(d.get_by_role("tabpanel").locator(".pref-row").first).to_be_visible()
    assert d.locator(".prefs-panels").evaluate("e => e.scrollHeight > e.clientHeight")  # it scrolls, not the page


def test_on_a_short_window_the_panel_scrolls_inside_the_dialog(page, app_url):
    page.set_viewport_size({"width": 1100, "height": 420})
    open_app(page, app_url)
    d = open_prefs(page, "Server")
    expect(d.get_by_role("tabpanel").locator(".pref-row").first).to_be_visible()  # the rows arrive from the server
    expect(d).to_be_in_viewport(ratio=1)
    assert d.locator(".prefs-panels").evaluate("e => e.scrollHeight > e.clientHeight")
