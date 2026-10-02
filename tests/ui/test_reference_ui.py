"""UI details taken from looking at chatgpt.com and chat.qwen.ai (docs/ui-polish.md)."""
from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app
from tests.ui.test_model_picker_ui import pick


def box(page, selector):
    return page.locator(selector).bounding_box()


def test_the_thinking_select_sits_between_the_text_and_the_send_button(page, app_url):
    open_app(page, app_url)
    pick(page, "gpt-5-mini")
    text, mode, send = box(page, "#input"), box(page, "#effort-wrap"), box(page, "#send")
    assert text["x"] + text["width"] <= mode["x"] + 1
    assert mode["x"] + mode["width"] <= send["x"] + 1
    assert abs((mode["y"] + mode["height"] / 2) - (send["y"] + send["height"] / 2)) < 4  # one row


def test_the_thinking_select_moves_to_the_bottom_row_with_a_long_message(page, app_url):
    open_app(page, app_url)
    pick(page, "gpt-5-mini")
    page.get_by_label("Message", exact=True).fill("a\nb\nc")
    expect(page.locator(".composer.is-multiline")).to_be_visible()
    mode, send, text = box(page, "#effort-wrap"), box(page, "#send"), box(page, "#input")
    assert mode["y"] > text["y"] + text["height"] - 1  # below the text
    assert abs(mode["y"] - send["y"]) < 8 and mode["x"] < send["x"]


def test_the_greeting_is_plain_sans_text(page, app_url):
    open_app(page, app_url)
    heading = page.get_by_role("heading", name="What are you working on?")
    assert "Charter" not in heading.evaluate("e => getComputedStyle(e).fontFamily")
    assert heading.evaluate("e => getComputedStyle(e).fontWeight") == "400"


def test_the_model_menu_has_a_heading(page, app_url):
    open_app(page, app_url)
    page.get_by_role("button", name="Model:").click()
    expect(page.locator("#model-menu .menu-head")).to_have_text("Model")


def test_controls_are_44px_on_a_touch_screen(browser, app_url):
    context = browser.new_context(viewport={"width": 390, "height": 760}, has_touch=True, is_mobile=True)
    page = context.new_page()
    open_app(page, app_url)
    for selector in ("#send", "#attach", "#settings-btn"):
        b = page.locator(selector).bounding_box()
        assert b["width"] >= 44 and b["height"] >= 44, (selector, b)
    context.close()
