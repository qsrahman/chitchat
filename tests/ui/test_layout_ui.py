"""Layout and interaction details taken from a look at chatgpt.com: the icon rail, the hero composer that
drops to the bottom, a composer that reflows as it grows, icon actions, and drafts that survive a reload."""
from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_sidebar, send

RAIL_MAX_WIDTH = 80  # the closed sidebar is 3.5rem


def box(locator):
    return locator.bounding_box()


def centre_y(locator):
    b = box(locator)
    return b["y"] + b["height"] / 2


# ---- sidebar rail ----

def test_closed_sidebar_is_an_icon_rail_that_keeps_the_main_actions_in_reach(page, app_url):
    open_app(page, app_url)
    expect(page.locator("#conversations")).to_be_hidden()
    expect(page.locator(".brand")).to_be_hidden()
    expect(page.locator("#new-chat .label")).to_be_hidden()
    assert box(page.locator("#sidebar"))["width"] < RAIL_MAX_WIDTH
    expect(page.get_by_role("button", name="Show conversations")).to_have_attribute("aria-expanded", "false")
    expect(page.get_by_role("button", name="Settings", exact=True)).to_be_visible()

    send(page, "from the rail")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    page.get_by_role("button", name="New chat").click()  # no need to open the sidebar first
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()

    page.get_by_role("button", name="Settings", exact=True).click()
    expect(page.get_by_role("dialog", name="Settings", exact=True)).to_be_visible()


def test_toggle_expands_the_rail_into_the_full_sidebar_and_back(page, app_url):
    open_app(page, app_url)
    main_closed = box(page.locator("main"))["width"]
    open_sidebar(page)
    expect(page.locator(".brand")).to_be_visible()
    expect(page.locator("#new-chat .label")).to_have_text("New chat")
    expect(page.get_by_role("button", name="Hide conversations")).to_have_attribute("aria-expanded", "true")
    assert box(page.locator("#sidebar"))["width"] > 200
    assert box(page.locator("main"))["width"] < main_closed  # pushes the content, no overlay
    page.get_by_role("button", name="Hide conversations").click()
    expect(page.locator("#conversations")).to_be_hidden()
    assert box(page.locator("#sidebar"))["width"] < RAIL_MAX_WIDTH


# ---- hero ----

def test_new_chat_centers_the_composer_and_it_drops_to_the_bottom_once_chatting(page, app_url):
    open_app(page, app_url)
    height = page.viewport_size["height"]
    composer = page.locator(".composer")
    centre = box(composer)["y"] + box(composer)["height"] / 2
    assert 0.3 * height < centre < 0.65 * height, "composer should sit in the middle of the page"
    assert box(page.get_by_role("heading", name="What are you working on?"))["y"] < box(composer)["y"]

    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_hidden()
    bottom = box(composer)["y"] + box(composer)["height"]
    assert height - bottom < 70, "composer should be pinned to the bottom"


# ---- composer ----

def test_composer_reflows_when_the_text_grows_and_back_when_cleared(page, app_url):
    open_app(page, app_url)
    composer, field = page.locator(".composer"), page.get_by_label("Message", exact=True)
    send_btn = page.locator("#send")
    expect(composer).not_to_have_class("composer is-multiline")
    assert abs(centre_y(send_btn) - centre_y(field)) < 12  # one row

    field.fill("first line")
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("second line")
    expect(composer).to_have_class("composer is-multiline")
    assert box(send_btn)["y"] >= box(field)["y"] + box(field)["height"] - 2, "send drops below the text"
    send_right = box(send_btn)["x"] + box(send_btn)["width"]
    composer_right = box(composer)["x"] + box(composer)["width"]
    assert abs(send_right - composer_right) < 24  # right-aligned

    field.fill("")
    expect(composer).not_to_have_class("composer is-multiline")
    assert box(send_btn)["y"] < box(field)["y"] + box(field)["height"], "back to a single row"


def test_long_text_without_a_newline_also_reflows_and_stays_reflowed_while_editing(page, app_url):
    open_app(page, app_url)
    composer, field = page.locator(".composer"), page.get_by_label("Message", exact=True)
    field.fill("word " * 80)
    expect(composer).to_have_class("composer is-multiline")
    field.fill("short now")  # still non-empty: it must not flip back and forth while the user edits
    expect(composer).to_have_class("composer is-multiline")
    field.fill("")
    expect(composer).not_to_have_class("composer is-multiline")


def test_rapid_typing_still_reflows_the_composer_and_saves_the_draft(page, app_url):
    open_app(page, app_url)
    field = page.get_by_label("Message", exact=True)
    field.click()
    page.keyboard.type("word " * 80, delay=0)  # many input events inside a few frames

    # The composer's layout work is coalesced into one pass per frame, so the last update must not be dropped.
    expect(page.locator(".composer")).to_have_class("composer is-multiline")
    expect(page.locator("#send")).to_be_enabled()
    page.reload()
    expect(field).to_have_value("word " * 80)  # and the draft is written as you type, never debounced away


def test_jump_button_is_a_round_icon_above_the_composer(page, app_url):
    page.set_viewport_size({"width": 1100, "height": 500})
    open_app(page, app_url)
    send(page, "long answer")
    messages = page.locator("#messages")
    page.wait_for_function(
        "() => { const el = document.getElementById('messages'); return el.scrollHeight - el.clientHeight > 300 }"
    )
    messages.evaluate("el => { el.scrollTop = 0 }")
    jump = page.get_by_role("button", name="Jump to latest")
    expect(jump).to_be_visible()
    j, c = box(jump), box(page.locator(".composer"))
    assert abs(j["width"] - j["height"]) < 1 and j["width"] < 48  # round
    assert j["y"] + j["height"] <= c["y"]  # above the composer, not over it
    expect(jump).to_have_text("")  # icon only; the name comes from aria-label


# ---- message actions ----

def test_message_actions_are_icon_buttons_with_tooltips_and_copy_confirms(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    for name in ("Copy", "Edit", "Regenerate"):
        button = page.locator(".actions").get_by_role("button", name=name, exact=True).first
        expect(button).to_have_attribute("title", name)
        expect(button).to_have_text("")
    copy = page.locator(".msg.assistant .actions").get_by_role("button", name="Copy", exact=True)
    copy.click()
    assert page.evaluate("navigator.clipboard.readText()") == "Reply #1 to **hello**"  # the raw markdown
    expect(page.locator(".msg.assistant .actions").get_by_role("button", name="Copied", exact=True)).to_be_visible()
    expect(copy).to_be_visible()  # back to "Copy" after a moment


# ---- drafts ----

def test_unsent_text_survives_a_reload(page, app_url):
    open_app(page, app_url)
    field = page.get_by_label("Message", exact=True)
    field.fill("half-written thought")
    page.reload()
    expect(field).to_have_value("half-written thought")
    expect(page.locator("#send")).to_be_enabled()


def test_drafts_are_kept_per_conversation_and_cleared_on_send(page, app_url):
    open_app(page, app_url)
    field = page.get_by_label("Message", exact=True)
    send(page, "first chat")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    field.fill("draft for the first chat")

    open_sidebar(page)
    page.get_by_role("button", name="New chat").click()
    expect(field).to_have_value("")  # a new chat does not inherit it
    field.fill("draft for a new chat")

    page.locator("#conversations").get_by_role("link", name="first chat").click()
    expect(page.locator(".msg.user .body")).to_have_text("first chat")
    expect(field).to_have_value("draft for the first chat")
    expect(field).to_be_focused()  # opening a chat focuses the box last; until then Enter goes to the link clicked

    page.keyboard.press("Enter")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("Reply #2")
    expect(page.locator(".msg.assistant").nth(1).locator(".actions button").first).to_be_visible()  # saved
    page.reload()
    expect(field).to_have_value("")  # sending cleared it

    page.get_by_role("button", name="New chat").click()
    expect(field).to_have_value("draft for a new chat")


# ---- tables on a phone ----

def test_a_table_on_a_phone_keeps_its_words_whole_and_scrolls_sideways(page, app_url):
    page.set_viewport_size({"width": 375, "height": 800})
    open_app(page, app_url)
    send(page, "narrowtable")
    table = page.locator(".msg.assistant table")
    expect(table).to_be_visible()
    cells = table.locator("th, td")
    widths = cells.evaluate_all("els => els.map((e) => e.getBoundingClientRect().width)")
    assert min(widths) >= 90, widths  # a column of single letters was 30px wide
    assert table.evaluate("e => e.scrollWidth > e.clientWidth")  # too wide for the screen: it scrolls
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")  # and the page does not
