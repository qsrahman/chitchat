"""Phase 8 in the browser: searching chats, exporting one, and the compaction note."""
from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_sidebar, send


def search_box(page):
    return page.get_by_role("searchbox", name="Search conversations")


def test_search_shows_matching_chats_with_the_match_highlighted(page, app_url):
    open_app(page, app_url)
    send(page, "tell me about quokkas")
    page.get_by_role("button", name="New chat").click()
    send(page, "tell me about cats")
    open_sidebar(page)
    search_box(page).fill("quokk")
    result = page.locator(".result")
    expect(result).to_have_count(1)
    expect(result.locator("strong")).to_have_text("tell me about quokkas")
    expect(result.locator("mark")).to_have_text("quokkas")  # the matched word, as the last-word prefix
    expect(page.locator("#conversations h2")).to_have_count(0)  # the dated list is replaced


def test_clicking_a_result_opens_that_chat_and_clearing_restores_the_list(page, app_url):
    open_app(page, app_url)
    send(page, "tell me about quokkas")
    page.get_by_role("button", name="New chat").click()
    send(page, "tell me about cats")
    open_sidebar(page)
    search_box(page).fill("quokkas")
    page.locator(".result").click()
    expect(page.locator(".msg.user .body")).to_have_text("tell me about quokkas")
    search_box(page).fill("")
    expect(page.locator(".conv a:not(.result)")).to_have_count(2)


def test_no_match_says_so(page, app_url):
    open_app(page, app_url)
    send(page, "hello there")
    open_sidebar(page)
    search_box(page).fill("zzzz")
    expect(page.locator("#conversations")).to_contain_text("No chats match.")


def test_a_snippet_is_text_not_html(page, app_url):
    open_app(page, app_url)
    send(page, "an xss <b>bold</b> test")
    open_sidebar(page)
    search_box(page).fill("bold")
    expect(page.locator(".result span")).to_contain_text("<b>")
    expect(page.locator(".result b")).to_have_count(0)


def test_export_links_in_settings_download_the_chat(page, app_url):
    open_app(page, app_url)
    page.get_by_role("button", name="Chat settings").click()
    expect(page.locator("#settings-dialog")).to_be_visible()
    expect(page.locator("#export-row")).to_be_hidden()  # nothing to export in a new chat
    page.keyboard.press("Escape")
    send(page, "hello export")
    page.get_by_role("button", name="Chat settings").click()
    expect(page.locator("#export-row")).to_be_visible()
    with page.expect_download() as download:
        page.get_by_role("link", name="Markdown").click()
    assert download.value.suggested_filename.endswith(".md")
    text = open(download.value.path()).read()
    assert "## You\n\nhello export" in text


def test_the_note_says_when_the_context_was_compacted(page, app_url):
    open_app(page, app_url)
    send(page, "compactme")
    expect(page.locator(".msg.assistant .note")).to_have_text("Earlier messages were compacted to save context.")
    page.reload()
    expect(page.locator(".msg.assistant .note")).to_have_text("Earlier messages were compacted to save context.")
