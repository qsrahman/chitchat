from playwright.sync_api import Page, expect

from tests.ui.test_chat_ui import conv_id, open_app, open_chat_settings, open_prefs, open_sidebar, send
from tests.ui.test_model_picker_ui import pick


def open_settings(page: Page):
    return open_chat_settings(page)


def save(dialog):
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden()


def test_settings_chosen_before_the_first_message_apply_to_the_new_chat(page, app_url):
    open_app(page, app_url)
    pick(page, "alpha-model")
    dialog = open_settings(page)
    dialog.get_by_label("System prompt").fill("Be brief")
    dialog.get_by_label("Temperature").fill("0.3")
    save(dialog)
    expect(page.get_by_role("button", name="Chat actions")).to_have_attribute("data-active", "")
    send(page, "hello")
    reply = page.locator(".msg.assistant .body")
    expect(reply).to_contain_text("[model=alpha-model]")
    expect(reply).to_contain_text("[instructions=Be brief]")
    expect(reply).to_contain_text("[temperature=0.3]")


def test_a_reasoning_model_gets_effort_and_not_temperature(page, app_url):
    open_app(page, app_url)
    pick(page, "alpha-model")
    dialog = open_settings(page)
    dialog.get_by_label("Temperature").fill("0.9")
    dialog.get_by_role("button", name="Save").click()
    pick(page, "gpt-5-mini")  # a model where the temperature no longer applies
    dialog = open_settings(page)
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
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    dialog = open_settings(page)
    dialog.get_by_label("System prompt").fill("Only for the first chat")
    save(dialog)
    page.reload()
    expect(page.get_by_role("button", name="Chat actions")).to_have_attribute("data-active", "")
    assert "Only for the first chat" == open_settings(page).get_by_label("System prompt").input_value()
    page.keyboard.press("Escape")

    open_sidebar(page)
    page.get_by_role("button", name="New chat").click()
    expect(page.get_by_role("button", name="Chat actions")).not_to_have_attribute("data-active", "")
    assert "" == open_settings(page).get_by_label("System prompt").input_value()
    page.keyboard.press("Escape")

    send(page, "second chat")
    expect(page.locator(".msg.assistant .body")).not_to_contain_text("instructions")
    page.get_by_role("link", name="first chat").click()
    expect(page.locator(".msg.user .body")).to_have_text("first chat")
    expect(page.get_by_role("button", name="Chat actions")).to_have_attribute("data-active", "")


def test_settings_apply_from_the_next_message_in_an_existing_chat(page, app_url):
    open_app(page, app_url)
    send(page, "one")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
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
    expect(page.get_by_role("button", name="Chat actions")).not_to_have_attribute("data-active", "")


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
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
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
    dialog = open_prefs(page, "Personalization")
    dialog.get_by_label("What should the model know about you").fill("Call me Que")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog.get_by_role("status")).to_have_text("Saved.")
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    send(page, "hello")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[instructions=Call me Que]")

    page.reload()
    dialog = open_prefs(page, "Personalization")
    expect(dialog.get_by_label("What should the model know about you")).to_have_value("Call me Que")
    page.keyboard.press("Escape")

    page.get_by_role("button", name="New chat").click()
    dialog = open_settings(page)
    dialog.get_by_label("System prompt").fill("Be brief")
    save(dialog)
    send(page, "again")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[instructions=Call me Que Be brief]")


def test_the_dialog_does_not_depend_on_the_order_the_models_arrive_in(page, app_url):
    # The same models, but with the default last and reasoning while the first one is not: the fields are those of
    # the default model, found by its id rather than by its position in the list.
    page.route("**/api/models", lambda route: route.fulfill(json={
        "default": "scripted-default", "efforts": ["low", "high"],
        "models": [{"id": "alpha-model", "reasoning": False},
                   {"id": "gpt-5-mini", "reasoning": True},
                   {"id": "scripted-default", "reasoning": True}],
    }))
    open_app(page, app_url)
    dialog = open_settings(page)
    expect(dialog.get_by_label("Reasoning effort")).to_be_visible()  # the default's own flag, not the first listed
    expect(dialog.get_by_label("Temperature")).to_be_hidden()
    expect(dialog.get_by_label("Reasoning effort").locator("option")).to_have_text(["Default", "low", "high"])
