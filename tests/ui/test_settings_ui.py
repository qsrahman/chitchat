from playwright.sync_api import Page, expect

from tests.ui.test_chat_ui import conv_id, open_app, open_sidebar, send


def open_settings(page: Page):
    page.get_by_role("button", name="Chat settings").click()
    dialog = page.get_by_role("dialog", name="Chat settings")
    expect(dialog).to_be_visible()
    return dialog


def save(dialog):
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden()


def test_model_picker_lists_models_and_shows_the_control_that_applies(page, app_url):
    open_app(page, app_url)
    dialog = open_settings(page)
    model = dialog.get_by_label("Model")
    expect(model.locator("option")).to_have_text(["Default (scripted-default)", "alpha-model", "gpt-5-mini"])
    expect(dialog.get_by_label("Temperature")).to_be_visible()  # the default model is not a reasoning model
    expect(dialog.get_by_label("Reasoning effort")).to_be_hidden()
    model.select_option("gpt-5-mini")
    expect(dialog.get_by_label("Reasoning effort")).to_be_visible()
    expect(dialog.get_by_label("Temperature")).to_be_hidden()
    model.select_option("alpha-model")
    expect(dialog.get_by_label("Temperature")).to_be_visible()


def test_settings_chosen_before_the_first_message_apply_to_the_new_chat(page, app_url):
    open_app(page, app_url)
    dialog = open_settings(page)
    dialog.get_by_label("System prompt").fill("Be brief")
    dialog.get_by_label("Model").select_option("alpha-model")
    dialog.get_by_label("Temperature").fill("0.3")
    save(dialog)
    expect(page.get_by_role("button", name="Chat settings")).to_have_attribute("data-active", "")
    send(page, "hello")
    reply = page.locator(".msg.assistant .body")
    expect(reply).to_contain_text("[model=alpha-model]")
    expect(reply).to_contain_text("[instructions=Be brief]")
    expect(reply).to_contain_text("[temperature=0.3]")


def test_a_reasoning_model_gets_effort_and_not_temperature(page, app_url):
    open_app(page, app_url)
    dialog = open_settings(page)
    dialog.get_by_label("Model").select_option("alpha-model")
    dialog.get_by_label("Temperature").fill("0.9")  # then switch to a model where it no longer applies
    dialog.get_by_label("Model").select_option("gpt-5-mini")
    dialog.get_by_label("Reasoning effort").select_option("high")
    save(dialog)
    send(page, "think")
    reply = page.locator(".msg.assistant .body")
    expect(reply).to_contain_text("[effort=high]")
    expect(reply).not_to_contain_text("temperature")


def test_settings_persist_per_conversation(page, app_url):
    open_app(page, app_url)
    send(page, "first chat")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    dialog = open_settings(page)
    dialog.get_by_label("System prompt").fill("Only for the first chat")
    save(dialog)
    page.reload()
    expect(page.get_by_role("button", name="Chat settings")).to_have_attribute("data-active", "")
    assert "Only for the first chat" == open_settings(page).get_by_label("System prompt").input_value()
    page.keyboard.press("Escape")

    open_sidebar(page)
    page.get_by_role("button", name="New chat").click()
    expect(page.get_by_role("button", name="Chat settings")).not_to_have_attribute("data-active", "")
    assert "" == open_settings(page).get_by_label("System prompt").input_value()
    page.keyboard.press("Escape")

    send(page, "second chat")
    expect(page.locator(".msg.assistant .body")).not_to_contain_text("instructions")
    page.get_by_role("link", name="first chat").click()
    expect(page.locator(".msg.user .body")).to_have_text("first chat")
    expect(page.get_by_role("button", name="Chat settings")).to_have_attribute("data-active", "")


def test_settings_apply_from_the_next_message_in_an_existing_chat(page, app_url):
    open_app(page, app_url)
    send(page, "one")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    dialog = open_settings(page)
    dialog.get_by_label("System prompt").fill("Now with a prompt")
    save(dialog)
    send(page, "two")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("[instructions=Now with a prompt]")
    expect(page.locator(".msg.assistant").nth(0)).not_to_contain_text("instructions")


def test_cancel_and_escape_discard_changes(page, app_url):
    open_app(page, app_url)
    dialog = open_settings(page)
    dialog.get_by_label("System prompt").fill("discard me")
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    assert "" == open_settings(page).get_by_label("System prompt").input_value()
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Chat settings")).not_to_have_attribute("data-active", "")


def test_invalid_temperature_keeps_the_dialog_open(page, app_url):
    open_app(page, app_url)
    dialog = open_settings(page)
    dialog.get_by_label("Temperature").fill("5")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_visible()  # the browser's own range check blocks the save


def test_save_failure_is_shown_and_can_be_retried(page, app_url, expected_console_errors):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expected_console_errors.append("net::ERR_FAILED")

    def abort_patch(route):
        route.abort() if route.request.method == "PATCH" else route.continue_()

    page.route("**/api/conversations/*", abort_patch)
    dialog = open_settings(page)
    dialog.get_by_label("System prompt").fill("keep trying")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog.get_by_role("alert")).to_contain_text("Couldn't save")
    expect(dialog).to_be_visible()
    page.unroute("**/api/conversations/*")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden()
    saved = page.request.get(f"{app_url}/api/conversations/{conv_id(page)}").json()
    assert saved["settings"]["system_prompt"] == "keep trying"


def test_custom_instructions_apply_to_every_chat_and_persist(page, app_url):
    open_app(page, app_url)
    open_sidebar(page)
    page.get_by_role("button", name="Custom instructions").click()
    dialog = page.get_by_role("dialog", name="Custom instructions")
    dialog.get_by_role("textbox").fill("Call me Que")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden()
    send(page, "hello")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[instructions=Call me Que]")

    page.reload()
    open_sidebar(page)
    page.get_by_role("button", name="Custom instructions").click()
    expect(dialog.get_by_role("textbox")).to_have_value("Call me Que")
    page.keyboard.press("Escape")

    page.get_by_role("button", name="New chat").click()
    dialog = open_settings(page)
    dialog.get_by_label("System prompt").fill("Be brief")
    save(dialog)
    send(page, "again")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[instructions=Call me Que Be brief]")
