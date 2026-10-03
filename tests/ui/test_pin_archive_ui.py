"""Pinned and archived chats in the sidebar, and switching back to a version where you left it."""

from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_sidebar, send


def two_chats(page, app_url):
    """Two chats, 'older chat' then 'newer chat'; the sidebar is open."""
    open_app(page, app_url)
    for text in ("older chat", "newer chat"):
        send(page, text)
        expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
        expect(page.locator("#title")).to_have_text(text)
        page.get_by_role("button", name="New chat").first.click()
        expect(page.locator(".msg")).to_have_count(0)
    open_sidebar(page)


def titles(page):
    return page.locator("#conversations .conv a:not(.result)")


def test_pinning_moves_a_chat_to_a_group_at_the_top_and_unpinning_puts_it_back(page, app_url):
    two_chats(page, app_url)
    expect(titles(page)).to_have_text(["newer chat", "older chat"])
    page.get_by_role("button", name='Pin "older chat"').click()
    expect(page.locator("#conversations h2").first).to_have_text("Pinned")
    expect(titles(page)).to_have_text(["older chat", "newer chat"])
    expect(page.get_by_role("button", name='Unpin "older chat"')).to_be_visible()
    page.get_by_role("button", name='Unpin "older chat"').click()
    expect(titles(page)).to_have_text(["newer chat", "older chat"])
    expect(page.locator("#conversations h2")).to_have_text(["Today"])


def test_a_pinned_chat_shows_its_pin_without_the_mouse_over_it_and_the_others_do_not(page, app_url):
    two_chats(page, app_url)
    page.get_by_role("button", name='Pin "older chat"').click()
    page.mouse.move(700, 400)
    pinned = page.get_by_role("button", name='Unpin "older chat"')
    expect(pinned).to_have_css("opacity", "1")
    expect(page.get_by_role("button", name='Pin "newer chat"')).to_have_css("opacity", "0")


def test_the_pin_is_still_there_after_a_reload(page, app_url):
    two_chats(page, app_url)
    page.get_by_role("button", name='Pin "older chat"').click()
    expect(page.locator("#conversations h2").first).to_have_text("Pinned")
    page.reload()
    open_sidebar(page)
    expect(titles(page)).to_have_text(["older chat", "newer chat"])


def test_archiving_hides_a_chat_and_the_archive_button_lists_it_again(page, app_url):
    two_chats(page, app_url)
    page.get_by_role("button", name='Archive "older chat"').click()
    expect(titles(page)).to_have_text(["newer chat"])
    archive = page.get_by_role("button", name="Archived chats")
    expect(archive).to_have_attribute("aria-pressed", "false")
    archive.click()
    expect(archive).to_have_attribute("aria-pressed", "true")
    expect(titles(page)).to_have_text(["older chat"])
    expect(page.get_by_role("button", name='Pin "older chat"')).to_have_count(0)  # not offered in the archive
    page.get_by_role("button", name='Unarchive "older chat"').click()
    expect(page.get_by_text("Archived chats will show up here.")).to_be_visible()
    archive.click()
    expect(titles(page)).to_have_text(["newer chat", "older chat"])


def test_an_archived_chat_can_be_opened_from_the_archive(page, app_url):
    two_chats(page, app_url)
    page.get_by_role("button", name='Archive "older chat"').click()
    page.get_by_role("button", name="Archived chats").click()
    page.get_by_role("link", name="older chat").click()
    expect(page.locator(".msg.user .body")).to_have_text("older chat")


def test_the_empty_archive_says_so(page, app_url):
    open_app(page, app_url)
    open_sidebar(page)
    page.get_by_role("button", name="Archived chats").click()
    expect(page.get_by_text("Archived chats will show up here.")).to_be_visible()


def test_a_chat_in_the_archive_can_be_deleted_with_undo(page, app_url):
    two_chats(page, app_url)
    page.get_by_role("button", name='Archive "older chat"').click()
    page.get_by_role("button", name="Archived chats").click()
    page.get_by_role("button", name='Delete "older chat"').click()
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()
    expect(page.get_by_text("Archived chats will show up here.")).to_be_visible()
    page.get_by_role("button", name="Undo").click()
    expect(titles(page)).to_have_text(["older chat"])


def test_switching_back_to_a_version_shows_the_reply_that_was_showing_not_the_newest(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    page.get_by_role("button", name="Regenerate").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #2")
    expect(page.locator(".versions-count")).to_have_text("2 / 2")
    page.get_by_role("button", name="Previous version").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")  # the first reply, chosen on purpose
    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Edit your message").fill("hello there")
    page.get_by_role("button", name="Save").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #3 to hello there")
    expect(page.locator(".msg").last.locator(".actions button").first).to_be_visible()
    page.locator(".msg.user .versions").get_by_role("button", name="Previous version").click()
    expect(page.locator(".msg.user .body")).to_have_text("hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")  # not Reply #2, the newest
    expect(page.locator(".msg.assistant .versions-count")).to_have_text("1 / 2")
