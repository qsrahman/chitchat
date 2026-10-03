from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, send


def test_reasoning_streams_open_then_collapses_and_can_be_expanded(page, app_url):
    open_app(page, app_url)
    send(page, "ponder this")
    details = page.locator(".msg.assistant details.reasoning")
    expect(details).to_have_attribute("open", "")  # live while the model is thinking
    expect(details.locator("summary")).to_have_text("Thinking…")
    expect(details.locator(".reasoning-body strong")).to_have_text("Weighing options.")
    expect(page.locator(".dots")).to_have_count(0)  # the reasoning block is the progress indicator

    expect(page.locator(".msg.assistant .body")).to_have_text("The answer is 42.")
    expect(details).not_to_have_attribute("open", "")  # collapsed once the answer starts
    expect(details.locator("summary")).to_have_text("Reasoning")

    details.locator("summary").click()
    expect(details.locator(".reasoning-body")).to_contain_text("Checking the sums.")


def test_token_usage_is_not_shown_under_the_reply(page, app_url):
    open_app(page, app_url)
    send(page, "ponder this")
    expect(page.locator(".msg.assistant")).to_contain_text("The answer is 42.")
    expect(page.locator(".msg.assistant > .note")).to_be_hidden()


def test_reasoning_survives_a_reload(page, app_url):
    open_app(page, app_url)
    send(page, "ponder this")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()  # the reply is done and saved
    page.reload()
    details = page.locator(".msg.assistant details.reasoning")
    expect(details).not_to_have_attribute("open", "")
    expect(details.locator("summary")).to_have_text("Reasoning")
    details.locator("summary").click()
    expect(details.locator(".reasoning-body")).to_contain_text("Weighing options.")
    expect(page.locator(".msg.assistant > .note")).to_be_hidden()


def test_a_plain_reply_has_no_reasoning_block_or_usage_line(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    expect(page.locator("details.reasoning")).to_have_count(0)
    expect(page.locator(".msg.assistant > .note")).to_be_hidden()


def test_a_failed_reply_drops_its_reasoning_block(page, app_url):
    open_app(page, app_url)
    send(page, "ponder broken")
    expect(page.locator(".msg.error")).to_contain_text("model fell over")
    expect(page.locator("details.reasoning")).to_have_count(0)
