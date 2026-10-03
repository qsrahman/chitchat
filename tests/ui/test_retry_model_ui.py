"""Try a reply again with another model: a menu next to Regenerate and Retry, for that reply only."""
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, send


def menu(page):
    return page.get_by_role("menu", name="Try again with another model")


def opener(page):
    return page.get_by_role("button", name="Try again with another model")


def done(page, count):
    expect(page.locator(".msg")).to_have_count(count)
    expect(page.locator(".msg").last.locator(".actions button").first).to_be_visible()


def test_picking_a_model_runs_the_reply_again_with_it_and_keeps_the_old_one(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    done(page, 2)
    expect(page.locator(".model-tag")).to_have_text("scripted-default")  # which model wrote it
    opener(page).click()
    expect(menu(page)).to_be_visible()
    expect(menu(page).get_by_role("menuitem")).to_have_text(
        [re.compile("^scripted-default"), re.compile("^alpha-model"), re.compile("^gpt-5-mini")])
    menu(page).get_by_role("menuitem", name=re.compile("^alpha-model")).click()
    expect(page.locator(".msg.assistant")).to_contain_text("[model=alpha-model]")
    done(page, 2)
    expect(page.locator(".model-tag")).to_have_text("alpha-model")
    expect(page.locator(".versions")).to_contain_text("2 / 2")
    page.get_by_role("button", name="Previous version").click()
    expect(page.locator(".msg.assistant")).not_to_contain_text("[model=")  # the first one, by the default model
    expect(page.locator(".model-tag")).to_have_text("scripted-default")


def test_the_conversations_own_model_does_not_change(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    done(page, 2)
    opener(page).click()
    menu(page).get_by_role("menuitem", name=re.compile("^alpha-model")).click()
    expect(page.locator(".msg.assistant")).to_contain_text("[model=alpha-model]")
    done(page, 2)
    expect(page.locator("#model-name")).to_have_text("scripted-default")
    send(page, "and now?")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("Reply #")
    expect(page.locator(".msg.assistant").nth(1)).not_to_contain_text("[model=")  # the next message: the chat's own


def test_the_model_that_wrote_a_reply_is_still_shown_after_a_reload(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    done(page, 2)
    opener(page).click()
    menu(page).get_by_role("menuitem", name=re.compile("^gpt-5-mini")).click()
    done(page, 2)
    page.reload()
    expect(page.locator(".model-tag")).to_have_text("gpt-5-mini")


def test_retry_after_a_failed_reply_can_use_another_model(page, app_url):
    open_app(page, app_url)
    send(page, "please fail")
    expect(page.locator(".msg.error")).to_be_visible()
    opener(page).click()
    menu(page).get_by_role("menuitem", name=re.compile("^alpha-model")).click()
    expect(page.locator(".msg.error")).to_have_count(0)
    expect(page.locator(".msg.assistant")).to_contain_text("[model=alpha-model]")


def test_the_menu_opens_with_the_keyboard_moves_with_arrows_and_closes_on_escape(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    done(page, 2)
    opener(page).focus()
    page.keyboard.press("Enter")
    expect(menu(page)).to_be_visible()
    expect(menu(page).get_by_role("menuitem").first).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(menu(page).get_by_role("menuitem").nth(1)).to_be_focused()
    page.keyboard.press("Escape")
    expect(menu(page)).to_be_hidden()
    expect(opener(page)).to_be_focused()  # back where it came from


def test_the_menu_stays_inside_the_window_even_for_a_button_at_the_bottom(page, app_url):
    page.set_viewport_size({"width": 390, "height": 500})
    open_app(page, app_url)
    send(page, "hello")
    done(page, 2)
    opener(page).click()
    expect(menu(page)).to_be_in_viewport(ratio=1)  # all of it (placed when the browser reports it open, so it retries)
