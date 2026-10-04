import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import conv_id, open_app, open_chat_settings, open_sidebar, send

DEFAULT = "scripted-default"  # the model the UI test server is configured with


def picker(page):
    return page.get_by_role("button", name=re.compile("^Model"))


def menu(page):
    return page.get_by_role("menu", name="Choose a model")


def open_menu(page):
    picker(page).click()
    expect(menu(page)).to_be_visible()
    return menu(page)


def row(page, model):
    return page.get_by_role("menuitemradio", name=re.compile(f"^{re.escape(model)}( |$)"))


def pick(page, model):
    open_menu(page)
    row(page, model).click()
    expect(menu(page)).to_be_hidden()


def saved_model(page):
    origin = page.url.split("#")[0]
    return page.request.get(f"{origin}api/conversations/{conv_id(page)}").json()["settings"]["model"]


def test_header_shows_the_default_model_on_a_new_chat(page, app_url):
    open_app(page, app_url)
    expect(picker(page)).to_have_text(DEFAULT)
    expect(picker(page)).to_have_attribute("aria-label", f"Model: {DEFAULT}")


def test_menu_lists_models_marks_the_current_one_and_tags_them(page, app_url):
    open_app(page, app_url)
    open_menu(page)
    rows = page.get_by_role("menuitemradio")
    expect(rows).to_have_count(3)
    expect(rows.nth(0)).to_contain_text(DEFAULT)
    expect(rows.nth(0)).to_contain_text("default")
    expect(rows.nth(1)).to_contain_text("alpha-model")
    expect(rows.nth(2)).to_contain_text("gpt-5-mini")
    expect(rows.nth(2)).to_contain_text("reasoning")
    expect(rows.nth(0)).to_have_attribute("aria-checked", "true")
    expect(rows.nth(1)).to_have_attribute("aria-checked", "false")


def test_choosing_a_model_switches_it_for_the_next_message_and_persists(page, app_url):
    open_app(page, app_url)
    send(page, "first")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    expect(page.locator(".msg.assistant .body")).not_to_contain_text("[model=")

    pick(page, "alpha-model")
    expect(picker(page)).to_have_text("alpha-model")
    assert saved_model(page) == "alpha-model"
    send(page, "second")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("[model=alpha-model]")

    page.reload()
    expect(picker(page)).to_have_text("alpha-model")
    open_menu(page)
    expect(row(page, "alpha-model")).to_have_attribute("aria-checked", "true")


def test_choosing_the_default_again_stores_no_override(page, app_url):
    open_app(page, app_url)
    send(page, "first")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    pick(page, "alpha-model")
    assert saved_model(page) == "alpha-model"
    pick(page, DEFAULT)
    expect(picker(page)).to_have_text(DEFAULT)
    assert saved_model(page) is None  # follows the default from now on
    send(page, "again")
    expect(page.locator(".msg.assistant").nth(1)).not_to_contain_text("[model=")


def test_a_model_picked_on_the_new_chat_screen_is_used_for_the_first_message(page, app_url):
    open_app(page, app_url)
    pick(page, "gpt-5-mini")
    expect(picker(page)).to_have_text("gpt-5-mini")
    send(page, "hello")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[model=gpt-5-mini]")
    assert saved_model(page) == "gpt-5-mini"


def test_each_conversation_keeps_its_own_model(page, app_url):
    open_app(page, app_url)
    pick(page, "alpha-model")
    send(page, "chat a")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved

    open_sidebar(page)
    page.get_by_role("button", name="New chat").click()
    expect(picker(page)).to_have_text(DEFAULT)  # a new chat starts on the default
    send(page, "chat b")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #2")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved

    page.get_by_role("link", name="chat a").click()
    expect(page.locator(".msg.user .body")).to_have_text("chat a")
    expect(picker(page)).to_have_text("alpha-model")


def test_the_chat_dialog_has_no_model_of_its_own_and_follows_the_picker(page, app_url):
    open_app(page, app_url)
    dialog = open_chat_settings(page)
    expect(dialog.get_by_label("Model", exact=True)).to_have_count(0)  # the model is chosen at the top of the chat
    expect(dialog.get_by_label("Temperature")).to_be_visible()  # the default model takes a temperature
    expect(dialog.get_by_label("Reasoning effort")).to_be_hidden()
    page.keyboard.press("Escape")
    pick(page, "gpt-5-mini")
    dialog = open_chat_settings(page)
    expect(dialog.get_by_label("Reasoning effort")).to_be_visible()  # now the fields are those of a thinking model
    expect(dialog.get_by_label("Temperature")).to_be_hidden()
    dialog.get_by_role("button", name="Save").click()
    expect(picker(page)).to_have_text("gpt-5-mini")  # saving the instructions kept the model


def test_the_menu_links_to_the_full_settings(page, app_url):
    open_app(page, app_url)
    open_menu(page).get_by_role("menuitem", name="Instructions for this chat…").click()
    expect(menu(page)).to_be_hidden()
    expect(page.get_by_role("dialog", name="Instructions for this chat")).to_be_visible()


def test_choosing_a_model_does_not_light_the_settings_dot(page, app_url):
    open_app(page, app_url)
    pick(page, "alpha-model")
    expect(page.get_by_role("button", name="Chat actions")).not_to_have_attribute("data-active", "")
    open_chat_settings(page)
    page.get_by_label("System prompt").fill("Be brief")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("button", name="Chat actions")).to_have_attribute("data-active", "")


def test_keyboard_opens_navigates_selects_and_escape_closes(page, app_url):
    open_app(page, app_url)
    picker(page).focus()
    page.keyboard.press("Enter")
    expect(menu(page)).to_be_visible()
    expect(row(page, DEFAULT)).to_be_focused()  # focus starts on the current model
    page.keyboard.press("ArrowDown")
    expect(row(page, "alpha-model")).to_be_focused()
    page.keyboard.press("End")
    expect(page.get_by_role("menuitem", name="Instructions for this chat…")).to_be_focused()
    page.keyboard.press("ArrowDown")  # wraps
    expect(row(page, DEFAULT)).to_be_focused()
    page.keyboard.press("ArrowUp")
    expect(page.get_by_role("menuitem", name="Instructions for this chat…")).to_be_focused()
    page.keyboard.press("Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(menu(page)).to_be_hidden()
    expect(picker(page)).to_have_text("alpha-model")
    expect(picker(page)).to_be_focused()

    page.keyboard.press("Enter")
    expect(menu(page)).to_be_visible()
    page.keyboard.press("Escape")
    expect(menu(page)).to_be_hidden()
    expect(picker(page)).to_be_focused()


def test_clicking_outside_closes_the_menu(page, app_url):
    open_app(page, app_url)
    open_menu(page)
    page.mouse.click(1050, 700)  # empty page area, well clear of the menu
    expect(menu(page)).to_be_hidden()


def test_a_failed_switch_says_so_and_keeps_the_old_model(page, app_url, expected_console_errors):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    expected_console_errors.append("net::ERR_FAILED")

    def abort_patch(route):
        route.abort() if route.request.method == "PATCH" else route.continue_()

    page.route("**/api/conversations/*", abort_patch)
    open_menu(page)
    row(page, "alpha-model").click()
    expect(page.get_by_role("alert").filter(has_text="Couldn't switch model")).to_be_visible()
    expect(menu(page)).to_be_visible()
    expect(picker(page)).to_have_text(DEFAULT)
    page.unroute("**/api/conversations/*")
    row(page, "alpha-model").click()
    expect(menu(page)).to_be_hidden()
    expect(picker(page)).to_have_text("alpha-model")


def test_a_saved_model_that_is_no_longer_listed_is_still_shown_and_checked(page, app_url):
    open_app(page, app_url)
    created = page.request.post(f"{app_url}/api/conversations", data={"settings": {"model": "ghost-model"}})
    page.goto(f"{app_url}/#{created.json()['id']}")
    expect(picker(page)).to_have_text("ghost-model")
    open_menu(page)
    expect(row(page, "ghost-model")).to_have_attribute("aria-checked", "true")
    expect(row(page, "ghost-model")).to_contain_text("not listed")


def test_when_models_cannot_be_loaded_the_button_degrades_and_recovers(page, app_url, expected_console_errors):
    expected_console_errors.append("net::ERR_FAILED")
    page.route("**/api/models", lambda route: route.abort())
    open_app(page, app_url)
    expect(picker(page)).to_have_text("Model")  # the default is unknown
    page.unroute("**/api/models")
    open_menu(page)  # opening the menu loads the list again
    expect(picker(page)).to_have_text(DEFAULT)
    expect(page.get_by_role("menuitemradio")).to_have_count(3)


def test_on_a_phone_the_menu_stays_inside_the_screen(page, app_url):
    page.set_viewport_size({"width": 375, "height": 700})
    open_app(page, app_url)
    box = open_menu(page).bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375
    assert box["y"] + box["height"] <= 700
    picker_box = picker(page).bounding_box()
    assert picker_box["x"] + picker_box["width"] <= 375  # the header doesn't overflow either
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_a_long_model_name_is_truncated_not_overflowing_the_header(page, app_url):
    page.set_viewport_size({"width": 375, "height": 700})
    open_app(page, app_url)
    long_name = "a-very-long-model-name-" * 4
    created = page.request.post(f"{app_url}/api/conversations", data={"settings": {"model": long_name}})
    page.goto(f"{app_url}/#{created.json()['id']}")
    expect(picker(page)).to_contain_text("a-very-long-model-name-")
    box = picker(page).bounding_box()
    assert box["x"] + box["width"] <= 375 * 0.7
    more = page.get_by_role("button", name="Chat actions").bounding_box()
    assert more["x"] + more["width"] <= 375  # the chat menu button is still on screen
