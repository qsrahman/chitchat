"""The Sources panel and the numbered chips: read from the search and page calls a chat's replies carry."""
from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, send


def sources_btn(page):
    return page.locator("#sources-btn")


def chip(page):
    return page.locator(".msg.assistant .body a.cite")


def test_a_chat_without_searches_has_no_sources_button(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(sources_btn(page)).to_be_hidden()
    expect(page.locator("#sources")).to_be_hidden()


def test_a_search_adds_a_source_per_web_result_and_a_link_to_one_becomes_a_numbered_chip(page, app_url):
    open_app(page, app_url)
    send(page, "findweb cite")
    expect(page.locator(".msg.assistant .body")).to_contain_text("It is 3.14")
    expect(sources_btn(page)).to_contain_text("2 sources")  # the javascript: result is not a source
    expect(page.locator("#sources")).to_be_hidden()
    expect(chip(page)).to_have_text("2")
    expect(chip(page)).to_have_accessible_name("Source 2: What's new")


def test_a_link_to_a_page_that_was_not_found_stays_a_link(page, app_url):
    open_app(page, app_url)
    send(page, "findweb")
    expect(page.locator(".msg.assistant .body")).to_contain_text("per python.org")
    expect(chip(page)).to_have_count(0)
    expect(page.locator(".msg.assistant .body a")).to_have_text("python.org")


def test_the_button_opens_and_closes_the_panel_with_a_card_per_source(page, app_url):
    open_app(page, app_url)
    send(page, "findweb")
    sources_btn(page).click()
    cards = page.locator("#sources .source-card")
    expect(cards).to_have_count(2)
    expect(cards.first).to_contain_text("Python Releases")
    expect(cards.first).to_contain_text("python.org")
    expect(cards.first).to_have_attribute("href", "https://www.python.org/downloads/")
    expect(cards.first).to_have_attribute("rel", "noopener noreferrer")
    expect(sources_btn(page)).to_have_attribute("aria-expanded", "true")
    page.get_by_role("button", name="Close sources").click()
    expect(page.locator("#sources")).to_be_hidden()
    expect(sources_btn(page)).to_be_focused()


def test_a_chip_opens_the_panel_at_its_card_without_leaving_the_page(page, app_url):
    open_app(page, app_url)
    send(page, "findweb cite")
    chip(page).click()
    expect(page.locator("#sources")).to_be_visible()
    expect(page.locator("#source-2")).to_have_class("source-card is-hit")
    expect(page.locator("#source-2")).to_be_focused()
    assert page.url.startswith("http://127.0.0.1") or "localhost" in page.url
    page.keyboard.press("Escape")
    expect(page.locator("#sources")).to_be_hidden()


def test_the_sources_come_back_when_the_chat_is_opened_again_and_go_with_a_new_chat(page, app_url):
    open_app(page, app_url)
    send(page, "findweb cite")
    expect(chip(page)).to_have_text("2")
    page.reload()
    expect(sources_btn(page)).to_contain_text("2 sources")
    expect(chip(page)).to_have_text("2")
    page.get_by_role("button", name="New chat").click()
    expect(sources_btn(page)).to_be_hidden()


def test_the_panel_is_a_column_beside_the_conversation_on_a_wide_screen(page, app_url):
    open_app(page, app_url)
    send(page, "findweb")
    sources_btn(page).click()
    panel, main = page.locator("#sources").bounding_box(), page.locator("main").bounding_box()
    assert panel["x"] >= main["x"] + main["width"] - 1 and panel["width"] > 300
