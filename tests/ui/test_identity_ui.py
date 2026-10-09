"""The visual identity: the teal accent, the streaming edge and the answer measure (docs/ui-polish.md)."""
from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, send

INK_BLUE = "rgb(45, 79, 135)"
DANGER = "rgb(180, 35, 24)"
TRANSPARENT = "rgba(0, 0, 0, 0)"


def send_color(page):
    page.get_by_label("Message", exact=True).fill("hi")
    expect(page.locator("#send")).to_be_enabled()
    page.locator("#send").evaluate("e => e.style.transition = 'none'")  # not mid-fade from the disabled color
    return page.locator("#send").evaluate("e => getComputedStyle(e).backgroundColor")


def wait_for_edge(page, color):
    page.wait_for_function(
        """c => { const e = document.querySelector('.msg.assistant .body');
                  return e && getComputedStyle(e).borderLeftColor === c; }""", arg=color)


def test_the_accent_is_ink_blue_in_light_mode(page, app_url):
    open_app(page, app_url)
    assert send_color(page) == INK_BLUE


def test_the_accent_is_a_lighter_blue_in_dark_mode(page, app_url):
    page.emulate_media(color_scheme="dark")
    open_app(page, app_url)
    assert send_color(page) == "rgb(147, 178, 238)"


def test_the_reply_being_written_has_an_accent_edge_that_goes_when_it_is_done(page, app_url):
    open_app(page, app_url)
    send(page, "slow please")
    wait_for_edge(page, INK_BLUE)
    expect(page.locator(".msg.assistant .body")).to_contain_text("word0")  # stopping before any text drops the reply
    page.keyboard.press("Escape")  # stop it
    wait_for_edge(page, TRANSPARENT)


def test_a_failed_reply_has_a_red_edge(page, app_url):
    open_app(page, app_url)
    send(page, "this will fail")
    expect(page.locator(".msg.error")).to_be_visible()
    page.wait_for_function(
        "c => getComputedStyle(document.querySelector('.msg.error .body')).borderLeftColor === c", arg=DANGER)


def test_answer_text_keeps_its_place_next_to_code_blocks(page, app_url):
    open_app(page, app_url)
    send(page, "show some code")
    expect(page.locator(".msg.assistant .code")).to_be_visible()
    paragraph = page.locator(".msg.assistant .body p").first.bounding_box()
    code = page.locator(".msg.assistant .code").bounding_box()
    assert abs(paragraph["x"] - code["x"]) < 1  # the edge lives in the margin, not in the text's way


def test_paragraphs_stop_at_the_reading_measure_but_the_column_can_be_wider(page, app_url):
    page.set_viewport_size({"width": 1400, "height": 800})
    open_app(page, app_url)
    send(page, "long answer please")
    expect(page.locator(".msg.assistant .body p").first).to_be_visible()
    width = page.locator(".msg.assistant .body p").first.evaluate("e => e.getBoundingClientRect().width")
    column = page.locator("#thread").evaluate("e => e.getBoundingClientRect().width")
    assert width <= 640 and width < column
    page.keyboard.press("Escape")
