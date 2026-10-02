from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app


def layer(page):
    """The hover gradient layer of the send button: (opacity, animation name, play state, image)."""
    return page.locator("#send").evaluate(
        """e => { const s = getComputedStyle(e, '::before');
                 return [s.opacity, s.animationName, s.animationPlayState, s.backgroundImage]; }"""
    )


def type_text(page):
    page.get_by_label("Message", exact=True).fill("hello")
    expect(page.locator("#send")).to_be_enabled()


def test_hovering_the_send_button_fades_in_a_moving_multicolor_gradient(page, app_url):
    open_app(page, app_url)
    type_text(page)
    opacity, name, state, _ = layer(page)
    assert opacity == "0" and state == "paused"  # at rest: plain accent button, nothing running
    page.locator("#send").hover()
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('#send'), '::before').opacity === '1'")
    opacity, name, state, image = layer(page)
    assert (name, state) == ("spark", "running")
    assert image.count("rgb") >= 4  # several different colors


def test_the_gradient_actually_moves_while_hovering(page, app_url):
    open_app(page, app_url)
    type_text(page)
    page.locator("#send").hover()
    position = "getComputedStyle(document.querySelector('#send'), '::before').backgroundPositionX"
    first = page.evaluate(f"() => {position}")
    page.wait_for_function(f"p => {position} !== p", arg=first)


def test_it_does_not_show_on_a_disabled_button(page, app_url):
    open_app(page, app_url)
    expect(page.locator("#send")).to_be_disabled()
    page.locator("#send").hover(force=True)
    page.wait_for_timeout(300)
    assert layer(page)[0] == "0"


def test_the_gradient_is_still_but_visible_with_reduced_motion(page, app_url):
    page.emulate_media(reduced_motion="reduce")
    open_app(page, app_url)
    type_text(page)
    page.locator("#send").hover()
    opacity, name, state, _ = layer(page)
    assert opacity == "1" and name == "none"
