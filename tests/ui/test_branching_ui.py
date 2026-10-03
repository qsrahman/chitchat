"""Versions of a message in the browser: edit or regenerate, then move between the versions with "2 / 3"."""
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_sidebar, send


def saved(page, count):
    """The conversation has `count` messages and the last is saved (its action buttons are there)."""
    expect(page.locator(".msg")).to_have_count(count)
    expect(page.locator(".msg").last.locator(".actions button").first).to_be_visible()


def three_exchanges(page, app_url):
    open_app(page, app_url)
    for n, text in enumerate(["one", "two", "three"], 1):
        send(page, text)
        saved(page, 2 * n)


def edit_message(page, index, text):
    page.get_by_role("button", name="Edit").nth(index).click()
    page.get_by_label("Edit your message").fill(text)
    page.get_by_role("button", name="Save").click()


def versions(page, index):
    return page.locator(".msg").nth(index).locator(".versions")


def test_editing_an_older_message_drops_what_followed_from_view_and_adds_a_version(page, app_url):
    three_exchanges(page, app_url)
    edit_message(page, 1, "two, reworded")  # the second of three user messages
    expect(page.locator(".msg.user .body")).to_have_text(["one", "two, reworded"])
    saved(page, 4)
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("Reply #4 to two, reworded")
    expect(versions(page, 2)).to_contain_text("2 / 2")  # on the edited message, the new version is second


def test_moving_between_versions_shows_each_path_with_what_followed_it(page, app_url):
    three_exchanges(page, app_url)
    edit_message(page, 1, "two, reworded")
    saved(page, 4)
    versions(page, 2).get_by_role("button", name="Previous version").click()
    expect(page.locator(".msg.user .body")).to_have_text(["one", "two", "three"])  # the old path, whole
    saved(page, 6)
    expect(versions(page, 2)).to_contain_text("1 / 2")
    expect(versions(page, 2).get_by_role("button", name="Previous version")).to_be_disabled()
    versions(page, 2).get_by_role("button", name="Next version").click()
    expect(page.locator(".msg.user .body")).to_have_text(["one", "two, reworded"])
    expect(versions(page, 2).get_by_role("button", name="Next version")).to_be_disabled()


def test_regenerating_adds_a_version_of_the_reply_and_the_old_one_comes_back(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    saved(page, 2)
    page.get_by_role("button", name="Regenerate").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #2")
    saved(page, 2)
    expect(versions(page, 1)).to_contain_text("2 / 2")
    versions(page, 1).get_by_role("button", name="Previous version").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(versions(page, 1)).to_contain_text("1 / 2")


def test_the_chosen_version_is_the_one_a_reload_shows(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    saved(page, 2)
    page.get_by_role("button", name="Regenerate").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #2")
    saved(page, 2)
    versions(page, 1).get_by_role("button", name="Previous version").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    page.reload()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(versions(page, 1)).to_contain_text("1 / 2")


def test_a_message_with_one_version_has_no_switcher(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    saved(page, 2)
    expect(page.locator(".versions")).to_have_count(0)


def test_you_can_keep_talking_on_a_version_you_switched_to(page, app_url):
    three_exchanges(page, app_url)
    edit_message(page, 0, "one, reworded")
    saved(page, 2)
    send(page, "and then")
    saved(page, 4)
    expect(page.locator(".msg.user .body")).to_have_text(["one, reworded", "and then"])
    versions(page, 0).get_by_role("button", name="Previous version").click()
    expect(page.locator(".msg.user .body")).to_have_text(["one", "two", "three"])


def test_a_search_result_in_a_version_that_is_not_shown_opens_that_version(page, app_url):
    open_app(page, app_url)
    send(page, "tell me about quokkas")
    saved(page, 2)
    edit_message(page, 0, "something else entirely")
    saved(page, 2)
    expect(page.locator("#title")).to_have_text(re.compile(".+"))
    open_sidebar(page)
    page.get_by_role("searchbox", name="Search conversations").fill("quokkas")
    page.locator(".result").first.click()
    expect(page.locator(".msg.user .body")).to_have_text("tell me about quokkas")
    expect(page.locator(".msg.user.is-found")).to_have_count(1)


def test_a_reply_that_was_stopped_can_be_edited_around(page, app_url):
    """The stopped reply and its message have no ids on the page; Edit asks the server for them."""
    open_app(page, app_url)
    send(page, "slow please")
    expect(page.locator(".msg.assistant .body")).to_contain_text("word2")
    page.get_by_role("button", name="Stop generating").click()
    expect(page.locator(".msg.assistant > .note")).to_have_text("Stopped.")
    edit_message(page, 0, "quick please")
    expect(page.locator(".msg.assistant .body")).to_contain_text("Reply #")
    saved(page, 2)
    expect(versions(page, 0)).to_contain_text("2 / 2")


def test_the_switcher_is_always_visible_not_only_on_hover(page, app_url):
    three_exchanges(page, app_url)
    edit_message(page, 0, "one, reworded")
    saved(page, 2)
    send(page, "more")
    saved(page, 4)
    page.mouse.move(0, 0)
    expect(versions(page, 0)).to_be_visible()
    expect(page.locator(".msg").nth(0).locator(".actions")).to_have_css("opacity", "1")  # not faded like the others
    expect(page.locator(".msg").nth(1).locator(".actions")).to_have_css("opacity", "0")
