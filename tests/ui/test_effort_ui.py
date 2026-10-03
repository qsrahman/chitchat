from playwright.sync_api import expect

from tests.ui.test_chat_ui import conv_id, open_app, send
from tests.ui.test_model_picker_ui import pick


def effort(page):
    return page.locator("#effort")


def saved_effort(page):
    origin = page.url.split("#")[0]
    return page.request.get(f"{origin}api/conversations/{conv_id(page)}").json()["settings"]["reasoning_effort"]


def test_it_is_only_offered_for_models_that_take_an_effort(page, app_url):
    open_app(page, app_url)
    expect(effort(page)).to_be_hidden()  # the default scripted model takes a temperature
    pick(page, "gpt-5-mini")
    expect(effort(page)).to_be_visible()
    expect(effort(page)).to_have_value("")  # Auto
    pick(page, "alpha-model")
    expect(effort(page)).to_be_hidden()


def test_it_lists_the_efforts_the_sdk_knows(page, app_url):
    open_app(page, app_url)
    pick(page, "gpt-5-mini")
    expect(effort(page).locator("option")).to_have_text(
        ["Auto", "None", "Minimal", "Low", "Medium", "High", "Xhigh", "Max"])


def test_a_choice_on_the_new_chat_screen_applies_to_the_first_message(page, app_url):
    open_app(page, app_url)
    pick(page, "gpt-5-mini")
    effort(page).select_option("low")
    send(page, "hello")
    expect(page.locator(".msg.assistant .body")).to_contain_text("[effort=low]")
    assert saved_effort(page) == "low"


def test_changing_it_in_a_chat_persists_and_none_turns_thinking_off(page, app_url):
    open_app(page, app_url)
    pick(page, "gpt-5-mini")
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    effort(page).select_option("none")
    expect(page.locator("#effort-wrap")).to_have_attribute("data-active", "")
    send(page, "again")
    expect(page.locator(".msg.assistant").last).to_contain_text("[effort=none]")
    page.reload()
    expect(effort(page)).to_have_value("none")
    effort(page).select_option("")  # Auto again: no override
    send(page, "third")
    expect(page.locator(".msg.assistant").last).not_to_contain_text("effort")
    assert saved_effort(page) is None


def test_it_stays_in_sync_with_the_settings_dialog(page, app_url):
    open_app(page, app_url)
    pick(page, "gpt-5-mini")
    effort(page).select_option("high")
    page.get_by_role("button", name="Chat settings").click()
    dialog = page.get_by_role("dialog", name="Chat settings")
    expect(dialog.get_by_label("Reasoning effort")).to_have_value("high")
    dialog.get_by_label("Reasoning effort").select_option("medium")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden()
    expect(effort(page)).to_have_value("medium")
