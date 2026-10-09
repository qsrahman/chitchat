"""Find in chat: Mod+F or the ⋯ menu, matches painted on the text with the CSS Custom Highlight API."""
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import chat_menu, open_app, send


def two_replies(page, app_url):
    open_app(page, app_url)
    send(page, "first question")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    send(page, "second question")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("Reply #2")
    expect(page.locator("#send")).to_be_disabled()  # the stream is over


def find_box(page):
    return page.get_by_role("searchbox", name="Find in chat")


def painted(page, name):
    return page.evaluate(f"CSS.highlights.get('{name}')?.size ?? 0")


def test_mod_f_opens_the_bar_in_a_chat_and_counts_the_matches(page, app_url):
    two_replies(page, app_url)
    page.keyboard.press("ControlOrMeta+f")
    expect(find_box(page)).to_be_focused()
    find_box(page).fill("reply")
    expect(page.locator("#find-count")).to_have_text("1 of 2")
    assert painted(page, "find") == 2 and painted(page, "find-current") == 1


def test_it_is_case_insensitive_and_searches_what_you_wrote_too(page, app_url):
    two_replies(page, app_url)
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("QUESTION")
    expect(page.locator("#find-count")).to_have_text("1 of 4")  # each question, and each reply that repeats it


def test_enter_and_shift_enter_step_through_and_wrap(page, app_url):
    two_replies(page, app_url)
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("reply")
    page.keyboard.press("Enter")
    expect(page.locator("#find-count")).to_have_text("2 of 2")
    page.keyboard.press("Enter")
    expect(page.locator("#find-count")).to_have_text("1 of 2")  # wraps
    page.keyboard.press("Shift+Enter")
    expect(page.locator("#find-count")).to_have_text("2 of 2")
    page.get_by_role("button", name="Previous match").click()
    expect(page.locator("#find-count")).to_have_text("1 of 2")
    page.get_by_role("button", name="Next match").click()
    expect(page.locator("#find-count")).to_have_text("2 of 2")


def test_the_current_match_is_scrolled_into_view(page, app_url):
    page.set_viewport_size({"width": 1100, "height": 500})
    two_replies(page, app_url)
    for i in range(5):  # enough replies that the first is out of sight
        send(page, f"more {i}")
        expect(page.locator(".msg.assistant").nth(2 + i)).to_contain_text("Reply")
        expect(page.locator("#send")).to_be_disabled()
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("Reply #1")
    top = page.locator(".msg.assistant").first.bounding_box()["y"]
    area = page.locator("#messages").bounding_box()
    assert area["y"] <= top <= area["y"] + area["height"]


def test_no_matches_says_so_and_paints_nothing(page, app_url):
    two_replies(page, app_url)
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("zebra")
    expect(page.locator("#find-count")).to_have_text("No matches")
    assert painted(page, "find") == 0 and painted(page, "find-current") == 0


def test_escape_closes_it_clears_the_paint_and_returns_to_the_composer(page, app_url):
    two_replies(page, app_url)
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("reply")
    page.keyboard.press("Escape")
    expect(page.locator("#find")).to_be_hidden()
    assert painted(page, "find") == 0
    expect(page.get_by_label("Message", exact=True)).to_be_focused()


def test_a_new_chat_has_nothing_to_find_so_the_browsers_own_find_is_left_alone(page, app_url):
    open_app(page, app_url)
    page.keyboard.press("ControlOrMeta+f")
    expect(page.locator("#find")).to_be_hidden()


def test_the_chat_menu_opens_it(page, app_url):
    two_replies(page, app_url)
    page.get_by_role("button", name="Chat actions").click()
    chat_menu(page).get_by_role("menuitem", name="Find in chat").click()
    expect(find_box(page)).to_be_focused()


def test_opening_another_chat_closes_it(page, app_url):
    two_replies(page, app_url)
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("reply")
    page.get_by_role("button", name="New chat").click()
    expect(page.locator("#find")).to_be_hidden()
    assert painted(page, "find") == 0


def test_a_match_runs_over_bold_and_italic_but_not_from_one_paragraph_into_the_next(page, app_url):
    open_app(page, app_url)
    send(page, "richreply")
    expect(page.locator(".msg.assistant h1")).to_be_visible()
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("with bold, italic, inline code and a link")  # bold, italic, code and a link in one paragraph
    expect(page.locator("#find-count")).to_have_text("1 of 1")
    find_box(page).fill("heading a paragraph")  # the end of the heading and the start of the paragraph
    expect(page.locator("#find-count")).to_have_text("No matches")


def test_reasoning_is_searched_and_its_section_opens_for_the_match(page, app_url):
    open_app(page, app_url)
    send(page, "widereply")
    expect(page.locator(".msg.assistant .math-block")).to_be_visible()
    reasoning = page.locator(".msg.assistant .reasoning")
    assert not reasoning.evaluate("e => e.open")  # closed once the reply is done
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("Thinking step 17 of")
    expect(page.locator("#find-count")).to_have_text("1 of 1")
    assert reasoning.evaluate("e => e.open")
    expect(page.locator(".msg.assistant .reasoning-body")).to_be_visible()


def test_a_tool_calls_results_are_searched_and_opened_too(page, app_url):
    open_app(page, app_url)
    send(page, "findweb")
    expect(page.locator(".msg.assistant .body")).to_contain_text("It is 3.14")
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("the latest release")  # a result's snippet, inside the closed tool line
    expect(page.locator("#find-count")).to_have_text("1 of 1")
    assert page.locator(".msg.assistant .tool-call").evaluate("e => e.open")


def test_the_matches_follow_a_reply_that_is_still_streaming(page, app_url):
    open_app(page, app_url)
    send(page, "slow please")
    expect(page.locator(".msg.assistant .body")).to_contain_text("word2")
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("word")
    first = page.locator("#find-count").inner_text()
    page.wait_for_function("(first) => document.getElementById('find-count').textContent !== first", arg=first)
    expect(page.locator("#find-count")).to_have_text(re.compile(r"^1 of \d+$"))  # still on the first
    page.keyboard.press("Escape")  # closes the bar
    page.keyboard.press("Escape")  # stops the reply


def test_math_is_searched_by_what_you_read_not_by_its_tex(page, app_url):
    open_app(page, app_url)
    send(page, "mathstream")
    expect(page.locator(".msg.assistant .katex")).to_be_visible()
    page.keyboard.press("ControlOrMeta+f")
    find_box(page).fill("is the sum")
    expect(page.locator("#find-count")).to_have_text("1 of 1")
