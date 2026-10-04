"""Automated accessibility checks (axe-core, tests/ui/assets/axe.min.js) on every state of the page, in the light and
the dark theme and on a phone, plus keyboard checks for what axe can't judge. Zero violations is the bar: a new one
means a change made something less accessible. axe finds roughly a third of accessibility problems; the rest
(reading order, announcements by a screen reader) need a person, see docs/accessibility.md."""
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.helpers import PNG
from tests.ui.test_chat_ui import chat_menu, open_chat_settings, open_prefs, row_action

AXE = (Path(__file__).parent / "assets" / "axe.min.js").read_text()

RUN_AXE = """() => axe.run(document, {resultTypes: ['violations']}).then((r) => r.violations.map((v) =>
    `${v.id} (${v.impact}): ${v.help} -> ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`))"""
# Entrances fade in, and colors are read mid-fade otherwise: wait until everything is fully opaque.
# Nor mid-slide: the phone's sidebar is off screen while it moves, and axe takes a link to a "#..." in an off-screen
# element for a skip link whose target is missing (and a color changing in a transition is read halfway).
SETTLED = """() => [...document.querySelectorAll('.msg, dialog[open], [popover]:popover-open')]
    .every((e) => getComputedStyle(e).opacity === '1')
    && document.getAnimations().every((a) => !(a instanceof CSSTransition))"""


@pytest.fixture(params=["light", "dark"])
def scheme(request):
    return request.param


def open_page(browser, app_url, scheme, viewport=None, **context_args):
    # bypass_csp: the policy forbids the injected script, and only the script. It is tested in test_csp_ui.py.
    context = browser.new_context(viewport=viewport or {"width": 1100, "height": 800}, color_scheme=scheme,
                                  bypass_csp=True, **context_args)
    page = context.new_page()
    page.goto(app_url)
    page.locator("body[data-ready]").wait_for(state="attached")
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()
    page.add_script_tag(content=AXE)
    return context, page


@pytest.fixture
def page_with_axe(browser, app_url, scheme):
    context, page = open_page(browser, app_url, scheme)
    yield page
    context.close()


def violations(page):
    page.wait_for_function(SETTLED)
    return page.evaluate(RUN_AXE)


def say(page, text):
    page.get_by_label("Message", exact=True).fill(text)
    page.keyboard.press("Enter")
    # the actions row appears when the reply is done (the code blocks have a Copy of their own)
    expect(page.locator(".msg.assistant").last.locator(".actions").get_by_role("button", name="Copy", exact=True)
           ).to_be_visible()


# ---- the states ----

def test_the_home_screen(page_with_axe):
    assert violations(page_with_axe) == []


def test_a_conversation_with_every_kind_of_content(page_with_axe):
    """Headings, links, lists, a table, a quote, code, math, reasoning, tool calls, an error and notes."""
    page = page_with_axe
    for text in ("richreply", "ponder this", "findweb", "calcsum", "findchats", "readpage", "compactme"):
        say(page, text)
    page.get_by_label("Message", exact=True).fill("fail please")
    page.keyboard.press("Enter")
    expect(page.locator(".msg.error")).to_be_visible()
    assert violations(page) == []


def test_content_wider_than_the_column_can_be_scrolled_from_the_keyboard(page_with_axe):
    page = page_with_axe
    say(page, "widereply")
    overflowing = page.evaluate("""() => [...document.querySelectorAll(
        '.msg.assistant pre, .msg.assistant table, .math-block, .reasoning-body')]
        .filter((e) => e.scrollWidth > e.clientWidth || e.scrollHeight > e.clientHeight).map((e) => e.tagName)""")
    assert sorted(overflowing) == ["DIV", "DIV", "PRE", "TABLE"]  # the audit below really has something to judge
    assert violations(page) == []


def test_the_audit_does_notice_a_scrolling_region_a_keyboard_cannot_reach(page_with_axe):
    page = page_with_axe
    say(page, "widereply")
    page.locator(".msg.assistant pre").evaluate("e => e.removeAttribute('tabindex')")
    found = violations(page)
    assert len(found) == 1 and found[0].startswith("scrollable-region-focusable (serious)")


def test_the_sidebar_with_search_results_and_with_none(page_with_axe):
    page = page_with_axe
    say(page, "richreply")
    page.get_by_role("button", name="Show conversations").first.click()
    expect(page.locator("#conversations a[aria-current=page]")).to_be_visible()
    assert violations(page) == []
    page.get_by_label("Search conversations").fill("rich")
    expect(page.locator(".result")).to_have_count(1)
    assert violations(page) == []
    page.get_by_label("Search conversations").fill("zzzz")
    expect(page.locator("#conversations")).to_contain_text("No chats match.")
    assert violations(page) == []


def test_the_model_menu(page_with_axe):
    page = page_with_axe
    page.locator("#model-btn").click()
    expect(page.locator("#model-menu")).to_be_visible()
    assert violations(page) == []


def test_the_tools_menu(page_with_axe):
    page = page_with_axe
    page.get_by_role("button", name="Tools", exact=True).click()
    expect(page.locator("#tools-menu")).to_be_visible()
    page.get_by_label("Calculator").check()
    assert violations(page) == []


def test_attachments_ready_and_failed(page_with_axe):
    page = page_with_axe
    page.locator("#file-input").set_input_files([
        {"name": "cat.png", "mimeType": "image/png", "buffer": PNG},
        {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello"},
        {"name": "bad.bin", "mimeType": "application/octet-stream", "buffer": b"MZ\x00\x00\x01"},
    ])
    expect(page.locator(".chip.is-error")).to_be_visible()
    expect(page.locator(".chip[aria-busy=true]")).to_have_count(0)
    assert violations(page) == []


def test_the_drop_overlay(page_with_axe):
    page = page_with_axe
    page.evaluate("document.getElementById('drop').hidden = false")
    assert violations(page) == []


@pytest.mark.parametrize("opener, dialog", [
    (lambda p: open_chat_settings(p), "Instructions for this chat"),
    (lambda p: open_prefs(p, "General"), "Settings"),
    (lambda p: open_prefs(p, "Personalization"), "Settings"),
    (lambda p: open_prefs(p, "Data controls"), "Settings"),
    (lambda p: open_prefs(p, "Server"), "Settings"),
    (lambda p: row_action(p, "hello", "Rename…"), "Rename conversation"),
    (lambda p: row_action(p, "hello", "Delete…"), "Delete this conversation?"),
])
def test_each_dialog(page_with_axe, opener, dialog):
    page = page_with_axe
    say(page, "hello")
    page.get_by_role("button", name="Show conversations").first.click()
    expect(page.locator("#conversations a[aria-current=page]")).to_be_visible()
    opener(page)
    expect(page.get_by_role("dialog", name=dialog)).to_be_visible()
    assert violations(page) == []


def test_while_a_reply_is_streaming(page_with_axe):
    page = page_with_axe
    page.get_by_label("Message", exact=True).fill("slow please")
    page.keyboard.press("Enter")
    expect(page.locator(".msg.assistant .body")).to_contain_text("word1")
    assert violations(page) == []
    page.keyboard.press("Escape")


def test_with_thinking_effort_and_search_switched_on(page_with_axe):
    page = page_with_axe
    page.locator("#model-btn").click()
    page.get_by_role("menuitemradio", name="gpt-5-mini").click()
    page.locator("#effort").select_option("high")
    page.get_by_role("button", name="Web search").click()
    expect(page.get_by_role("button", name="Web search")).to_have_attribute("aria-pressed", "true")
    assert violations(page) == []


def test_right_to_left_text(page_with_axe):
    page = page_with_axe
    say(page, "السلام عليكم urdu")
    assert violations(page) == []


def test_on_a_phone(browser, app_url, scheme):
    context, page = open_page(browser, app_url, scheme, viewport={"width": 390, "height": 760},
                              has_touch=True, is_mobile=True)
    assert violations(page) == []
    say(page, "richreply")
    page.get_by_role("button", name="Show conversations").first.click()
    expect(page.locator("#sidebar")).to_be_in_viewport()
    assert violations(page) == []
    context.close()


# ---- what axe can't judge: a keyboard can use it ----

@pytest.mark.parametrize("selector, key, axis", [
    (".msg.assistant pre", "ArrowRight", "scrollLeft"),
    (".msg.assistant table", "ArrowRight", "scrollLeft"),
    (".msg.assistant .math-block", "ArrowRight", "scrollLeft"),
    (".msg.assistant .reasoning-body", "ArrowDown", "scrollTop"),
])
def test_a_keyboard_can_focus_and_scroll_each_overflowing_region(page_with_axe, selector, key, axis):
    page = page_with_axe
    say(page, "widereply")
    if "reasoning" in selector:
        page.locator(".msg.assistant details.reasoning summary").click()
    region = page.locator(selector).first
    region.focus()
    expect(region).to_be_focused()
    before = region.evaluate(f"e => e.{axis}")
    page.keyboard.press(key)
    page.keyboard.press(key)
    # the browser scrolls with the keyboard by animating, so wait for it to move rather than reading at once
    page.wait_for_function(f"([selector, before]) => document.querySelector(selector).{axis} > before",
                           arg=[selector, before])


def test_the_page_has_one_main_landmark_a_language_and_a_title(page_with_axe):
    page = page_with_axe
    assert page.evaluate("document.documentElement.lang") == "en"
    assert page.title() == "ChitChat"
    assert page.locator("main").count() == 1 and page.locator("aside[aria-label=Conversations]").count() == 1
    assert page.locator("h1:visible").count() == 1  # one level-one heading at a time: the greeting, then the title
    say(page, "hello")
    assert page.locator("h1:visible").count() == 1


def test_the_undo_toast(page_with_axe):
    page = page_with_axe
    say(page, "hello")
    page.get_by_role("button", name="Show conversations").first.click()
    row_action(page, "hello", "Delete…")
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()
    expect(page.locator("#toast")).to_be_visible()
    assert violations(page) == []


def test_a_forced_theme_on_either_system_theme(page_with_axe):
    """Light and Dark chosen in Settings, against whichever theme the system has (the two params), with the dialog
    open: it is the page that changes colour behind it and the dialog itself."""
    page = page_with_axe
    dialog = open_prefs(page)
    dialog.get_by_role("switch", name="Web search").check()  # the switch's "on" colors too
    for choice in ("light", "dark"):
        dialog.get_by_label("Appearance").select_option(choice)
        # colors are read mid-fade otherwise
        page.wait_for_function("() => document.getAnimations().every((a) => !(a instanceof CSSTransition))")
        assert violations(page) == []


def test_a_message_with_versions(page_with_axe):
    page = page_with_axe
    say(page, "hello")
    page.get_by_role("button", name="Regenerate").click()
    expect(page.locator(".versions")).to_be_visible()
    expect(page.locator(".versions-count")).to_have_text("2 / 2")
    assert violations(page) == []
    page.get_by_role("button", name="Previous version").click()
    expect(page.locator(".versions-count")).to_have_text("1 / 2")
    assert violations(page) == []  # with a disabled arrow, too


def test_the_try_again_menu(page_with_axe):
    page = page_with_axe
    say(page, "hello")
    expect(page.locator(".model-tag")).to_be_visible()
    assert violations(page) == []  # the model name next to the buttons
    page.get_by_role("button", name="Try again with another model").click()
    expect(page.locator("#retry-menu")).to_be_visible()
    assert violations(page) == []


def test_pinned_and_archived_lists(page_with_axe):
    page = page_with_axe
    say(page, "hello")
    page.get_by_role("button", name="Show conversations").first.click()
    row_action(page, "hello", "Pin")
    expect(page.locator("#conversations h2").first).to_have_text("Pinned")
    assert violations(page) == []
    row_action(page, "hello", "Archive")
    page.get_by_role("button", name="Archived chats").click()
    expect(page.get_by_role("button", name=re.compile('^Actions for "'))).to_be_visible()
    assert violations(page) == []


def test_the_chat_menus(page_with_axe):
    page = page_with_axe
    chat_menu(page)  # a new chat: just its instructions
    assert violations(page) == []
    page.keyboard.press("Escape")
    say(page, "hello")
    chat_menu(page)  # a chat: rename, pin, download, archive, delete
    assert violations(page) == []
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Show conversations").first.click()
    page.get_by_role("button", name=re.compile('^Actions for "')).click()  # the same menu from a row
    expect(page.get_by_role("menu", name="Chat actions")).to_be_visible()
    assert violations(page) == []


def test_settings_on_a_phone(browser, app_url, scheme):
    context, page = open_page(browser, app_url, scheme, viewport={"width": 390, "height": 760},
                              has_touch=True, is_mobile=True)
    for tab in ("General", "Personalization", "Data controls", "Server"):
        open_prefs(page, tab) if tab == "General" else page.get_by_role("dialog").get_by_role("tab", name=tab).click()
        assert violations(page) == []
    context.close()
