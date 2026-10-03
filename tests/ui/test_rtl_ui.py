"""Text direction follows the text: Arabic and Urdu run right to left, English and code stay left to right."""
from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_sidebar, send

ARABIC = "السلام عليكم urdu"


def direction(locator):
    return locator.evaluate("e => getComputedStyle(e).direction")


def test_the_input_follows_the_script_being_typed(page, app_url):
    open_app(page, app_url)
    field = page.get_by_label("Message", exact=True)
    field.fill("hello")
    assert direction(field) == "ltr"
    field.fill("مرحبا")
    assert direction(field) == "rtl"
    field.fill("")


def test_your_own_message_is_aligned_by_its_script(page, app_url):
    open_app(page, app_url)
    send(page, ARABIC)
    expect(page.locator(".msg.assistant .body p").first).to_be_visible()
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()  # done (Enter would stop it)
    body = page.locator(".msg.user .body")
    assert direction(body) == "rtl"
    assert body.evaluate("e => getComputedStyle(e).textAlign") in ("start", "right")
    send(page, "plain english question")
    expect(page.locator(".msg.assistant").nth(1)).to_be_visible()
    assert direction(page.locator(".msg.user .body").nth(1)) == "ltr"


def test_each_block_of_a_reply_gets_its_own_direction_and_code_stays_ltr(page, app_url):
    open_app(page, app_url)
    send(page, ARABIC)
    body = page.locator(".msg.assistant .body")
    expect(body.locator(".code")).to_be_visible()
    paragraphs = body.locator(":scope > p")
    assert direction(paragraphs.nth(0)) == "rtl"  # the Arabic paragraph
    assert direction(paragraphs.nth(1)) == "ltr"  # the English one in the same reply
    assert direction(body.locator("li").first) == "rtl"  # inherited from the list, whose own dir is auto
    assert direction(body.locator("ul")) == "rtl"  # so the bullets sit on the right
    assert direction(body.locator("blockquote")) == "rtl"
    assert direction(body.locator(".code")) == "ltr" and direction(body.locator(".code code")) == "ltr"


def test_the_list_markers_and_quote_bar_move_to_the_start_side(page, app_url):
    open_app(page, app_url)
    send(page, ARABIC)
    body = page.locator(".msg.assistant .body")
    expect(body.locator("blockquote")).to_be_visible()
    quote = body.locator("blockquote").evaluate(
        "e => { const s = getComputedStyle(e); return [s.borderRightWidth, s.borderLeftWidth]; }")
    assert quote == ["3px", "0px"]  # the bar is on the right of an Arabic quote
    list_box = body.locator("ul").evaluate(
        "e => { const s = getComputedStyle(e); return [s.paddingRight, s.paddingLeft]; }")
    assert float(list_box[0].removesuffix("px")) > 0 and list_box[1] == "0px"


def test_the_sidebar_title_and_the_header_follow_the_script(page, app_url):
    open_app(page, app_url)
    send(page, ARABIC)
    expect(page.locator(".msg.assistant .body p").first).to_be_visible()
    open_sidebar(page)
    link = page.locator("#conversations a[aria-current=page]")
    expect(link).to_be_visible()
    assert direction(link) == "rtl"
    assert direction(page.locator("#title")) == "rtl"


def test_english_replies_are_unchanged(page, app_url):
    open_app(page, app_url)
    send(page, "show some code")
    body = page.locator(".msg.assistant .body")
    expect(body.locator(".code")).to_be_visible()
    assert all(direction(body.locator(":scope > p").nth(i)) == "ltr" for i in range(body.locator(":scope > p").count()))
    quote = body.locator(".code").evaluate("e => getComputedStyle(e).textAlign")
    assert quote in ("start", "left")


def test_right_to_left_blocks_sit_at_the_right_edge_of_the_column(page, app_url):
    page.set_viewport_size({"width": 1300, "height": 800})  # wide enough for the reading measure to be narrower
    open_app(page, app_url)
    send(page, ARABIC)
    body = page.locator(".msg.assistant .body")
    expect(body.locator(".code")).to_be_visible()
    code = body.locator(".code").bounding_box()
    arabic = body.locator(":scope > p").nth(0).bounding_box()
    english = body.locator(":scope > p").nth(1).bounding_box()
    assert abs((arabic["x"] + arabic["width"]) - (code["x"] + code["width"])) < 1.5  # flush right with the column
    assert abs(english["x"] - code["x"]) < 1.5  # English stays flush left
