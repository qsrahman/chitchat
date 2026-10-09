"""The ⋯ menu of a chat: in the header for the open chat and on every sidebar row, one menu for both."""
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import chat_menu, open_app, open_sidebar, row_action, send


def saved_chat(page, text="a chat"):
    send(page, text)
    expect(page.locator(".msg.assistant").last.locator(".actions button").first).to_be_visible()  # saved


def test_a_row_has_one_button_not_four(page, app_url):
    open_app(page, app_url)
    saved_chat(page, "just one")
    open_sidebar(page)
    row = page.locator(".conv").first
    expect(row.get_by_role("button")).to_have_count(1)
    expect(row.get_by_role("button")).to_have_attribute("aria-label", 'Actions for "just one"')
    assert row.locator("a").bounding_box()["width"] > 120  # the title has the room the icons used to take


def test_the_items_are_grouped_and_a_new_chat_has_only_its_instructions(page, app_url):
    open_app(page, app_url)
    expect(chat_menu(page).get_by_role("menuitem")).to_have_text(["Instructions for this chat…"])
    page.keyboard.press("Escape")
    saved_chat(page)
    menu = chat_menu(page)
    expect(menu.get_by_role("menuitem")).to_have_text([
        "Instructions for this chat…", "Find in chat", "Pin", "Rename…", "Download as Markdown", "Download as JSON",
        "Archive", "Delete…"])
    expect(menu.get_by_role("separator")).to_have_count(3)


def test_a_row_menu_has_no_instructions_for_a_chat_that_is_not_open(page, app_url):
    open_app(page, app_url)
    saved_chat(page, "first")
    page.get_by_role("button", name="New chat").click()
    saved_chat(page, "second")
    open_sidebar(page)
    page.get_by_role("button", name='Actions for "first"').click()
    items = page.get_by_role("menu", name="Chat actions").get_by_role("menuitem")
    expect(items).to_have_text(["Pin", "Rename…", "Download as Markdown", "Download as JSON", "Archive", "Delete…"])
    page.keyboard.press("Escape")
    page.get_by_role("button", name='Actions for "second"').click()  # the open one has them
    expect(items.first).to_have_text("Instructions for this chat…")


def test_the_keyboard_opens_moves_and_closes_it_and_the_button_says_so(page, app_url):
    open_app(page, app_url)
    saved_chat(page)
    button = page.get_by_role("button", name="Chat actions")
    expect(button).to_have_attribute("aria-expanded", "false")
    button.focus()
    page.keyboard.press("Enter")
    menu = page.get_by_role("menu", name="Chat actions")
    expect(menu).to_be_visible()
    expect(button).to_have_attribute("aria-expanded", "true")
    expect(menu.get_by_role("menuitem").first).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(menu.get_by_role("menuitem", name="Find in chat")).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(menu.get_by_role("menuitem", name="Pin")).to_be_focused()
    page.keyboard.press("End")
    expect(menu.get_by_role("menuitem", name="Delete…")).to_be_focused()
    page.keyboard.press("ArrowDown")  # wraps
    expect(menu.get_by_role("menuitem").first).to_be_focused()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(button).to_have_attribute("aria-expanded", "false")
    expect(button).to_be_focused()


def test_choosing_an_item_closes_the_menu_and_does_it(page, app_url):
    open_app(page, app_url)
    saved_chat(page, "pin me")
    open_sidebar(page)
    row_action(page, "pin me", "Pin")
    expect(page.get_by_role("menu", name="Chat actions")).to_be_hidden()
    expect(page.locator("#conversations h2").first).to_have_text("Pinned")
    chat_menu(page).get_by_role("menuitem", name="Unpin").click()  # the header's menu has it too
    expect(page.locator("#conversations h2").first).to_have_text("Today")


def test_an_archived_chat_offers_unarchive_and_no_pin_in_the_header_too(page, app_url):
    open_app(page, app_url)
    saved_chat(page, "shelved")
    chat_menu(page).get_by_role("menuitem", name="Archive", exact=True).click()
    menu = chat_menu(page)
    expect(menu.get_by_role("menuitem", name="Unarchive")).to_be_visible()
    expect(menu.get_by_role("menuitem", name="Pin", exact=True)).to_have_count(0)


def test_deleting_the_open_chat_from_the_header_menu_asks_first(page, app_url):
    open_app(page, app_url)
    saved_chat(page, "to delete")
    chat_menu(page).get_by_role("menuitem", name="Delete…").click()
    dialog = page.get_by_role("dialog", name="Delete this conversation?")
    expect(dialog).to_contain_text("to delete")
    dialog.get_by_role("button", name="Delete").click()
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()


def test_the_menu_stays_on_screen_on_a_phone(page, app_url):
    page.set_viewport_size({"width": 375, "height": 700})
    open_app(page, app_url)
    saved_chat(page)
    box = chat_menu(page).bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    assert box["y"] >= 0 and box["y"] + box["height"] <= 700
    page.keyboard.press("Escape")
    open_sidebar(page)
    page.get_by_role("button", name='Actions for "a chat"').click()
    box = page.get_by_role("menu", name="Chat actions").bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375


def test_an_open_menu_closes_when_the_window_is_resized_and_opens_again_in_place(page, app_url):
    open_app(page, app_url)
    saved_chat(page)
    menu = page.get_by_role("menu", name="Chat actions")
    chat_menu(page)  # opens it
    expect(menu).to_be_visible()
    page.set_viewport_size({"width": 375, "height": 700})
    expect(menu).to_be_hidden()  # it was placed for the old window
    page.get_by_role("button", name="Chat actions").click()
    box = menu.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375


def test_the_tools_and_model_menus_close_on_a_resize_too(page, app_url):
    open_app(page, app_url)
    page.get_by_role("button", name="Tools", exact=True).click()
    expect(page.locator("#tools-menu")).to_be_visible()
    page.set_viewport_size({"width": 700, "height": 600})
    expect(page.locator("#tools-menu")).to_be_hidden()
    page.locator("#model-btn").click()
    expect(page.locator("#model-menu")).to_be_visible()
    page.set_viewport_size({"width": 900, "height": 600})
    expect(page.locator("#model-menu")).to_be_hidden()


def test_every_menu_row_is_a_44px_target_on_a_touch_screen(browser, app_url):
    context = browser.new_context(viewport={"width": 390, "height": 760}, has_touch=True, is_mobile=True)
    page = context.new_page()
    open_app(page, app_url)
    saved_chat(page)
    heights = lambda menu: menu.locator("[role=menuitem], .tool-row").evaluate_all(  # noqa: E731
        "rows => rows.map((r) => Math.round(r.getBoundingClientRect().height))")
    menu = chat_menu(page)
    assert len(heights(menu)) == 8 and min(heights(menu)) >= 44
    page.keyboard.press("Escape")
    page.get_by_role("button", name=re.compile("^Model")).click()
    model_menu = page.get_by_role("menu", name="Choose a model")
    expect(model_menu).to_be_visible()
    assert min(heights(model_menu)) >= 44
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Tools", exact=True).click()
    tools = page.locator("#tools-menu")
    expect(tools).to_be_visible()
    assert min(heights(tools)) >= 44
    context.close()
