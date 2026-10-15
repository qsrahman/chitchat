from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, send


def copy_button(page, message):
    return message.locator(".actions").get_by_role("button", name="Copy", exact=True)


def clipboard(page):
    return page.evaluate("navigator.clipboard.readText()")


def test_every_message_has_its_own_copy_button_that_copies_only_that_message(page, app_url):
    open_app(page, app_url)
    send(page, "first question")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    send(page, "second question")
    expect(page.locator(".msg.assistant").nth(1)).to_contain_text("Reply #2")
    expect(page.locator(".msg.assistant").nth(1).locator(".actions button").first).to_be_visible()  # saved
    users, replies = page.locator(".msg.user"), page.locator(".msg.assistant")
    expect(page.locator(".msg .actions").get_by_role("button", name="Copy", exact=True)).to_have_count(4)

    copy_button(page, users.nth(0)).click()
    assert clipboard(page) == "first question"
    copy_button(page, replies.nth(0)).click()
    assert clipboard(page) == "Reply #1 to **first question**"  # the raw markdown, not the second reply too
    copy_button(page, users.nth(1)).click()
    assert clipboard(page) == "second question"
    copy_button(page, replies.nth(1)).click()
    assert clipboard(page) == "Reply #2 to **second question**"


def test_copy_on_your_message_confirms_like_the_others(page, app_url):
    open_app(page, app_url)
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    user = page.locator(".msg.user")
    copy_button(page, user).click()
    expect(user.locator(".actions").get_by_role("button", name="Copied", exact=True)).to_be_visible()
    expect(copy_button(page, user)).to_be_visible()


def test_copy_keeps_the_text_exactly_including_line_breaks(page, app_url):
    open_app(page, app_url)
    page.get_by_label("Message", exact=True).fill("line one")
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("line two")
    page.keyboard.press("Enter")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    copy_button(page, page.locator(".msg.user")).click()
    assert clipboard(page) == "line one\nline two"


def test_copy_is_still_there_after_a_reload(page, app_url):
    open_app(page, app_url)
    send(page, "remember me")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    page.reload()
    expect(page.locator(".msg.user")).to_be_visible()
    copy_button(page, page.locator(".msg.user")).click()
    assert clipboard(page) == "remember me"


def test_a_message_with_only_an_attachment_has_no_copy_button(page, app_url):
    from tests.helpers import PNG

    open_app(page, app_url)
    page.locator("#file-input").set_input_files({"name": "cat.png", "mimeType": "image/png", "buffer": PNG})
    expect(page.locator(".chip")).to_have_count(1)
    expect(page.locator("#send")).to_be_enabled(timeout=10_000)
    page.locator("#send").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(page.locator(".msg.assistant").locator(".actions button").first).to_be_visible()  # saved
    expect(copy_button(page, page.locator(".msg.user"))).to_have_count(0)
    expect(copy_button(page, page.locator(".msg.assistant"))).to_have_count(1)


# ---- when the clipboard API will not do it ----

# What the page copies by selecting text, as the old way does: recorded, and still really done.
RECORD_OLD_COPY = """
window.__copied = []
const real = document.execCommand.bind(document)
document.execCommand = (command) => {
  const ok = real(command)
  if (command === 'copy') window.__copied.push(document.getSelection().toString() || document.activeElement?.value)
  return ok
}
"""
REFUSED = "navigator.clipboard.writeText = () => Promise.reject(new DOMException('denied', 'NotAllowedError'))"
ABSENT = "Object.defineProperty(navigator, 'clipboard', { value: undefined })"  # as on http://192.168...
CODE = "for i in range(3):\n    print(i)"


def test_the_code_copy_button_works_when_the_browser_refuses_the_clipboard_api(page, app_url):
    page.add_init_script(REFUSED + RECORD_OLD_COPY)
    open_app(page, app_url)
    send(page, "show code")
    button = page.locator(".code .code-copy")
    button.click()
    expect(button).to_have_accessible_name("Copied")
    assert page.evaluate("window.__copied") == [CODE]


def test_the_code_copy_button_works_on_a_page_that_has_no_clipboard_api(page, app_url):
    page.add_init_script(ABSENT + ";" + RECORD_OLD_COPY)
    open_app(page, app_url)
    send(page, "show code")
    button = page.locator(".code .code-copy")
    button.click()
    expect(button).to_have_accessible_name("Copied")
    assert page.evaluate("window.__copied") == [CODE]


def test_a_message_copy_button_works_without_the_clipboard_api_and_keeps_the_focus(page, app_url):
    page.add_init_script(ABSENT + ";" + RECORD_OLD_COPY)
    open_app(page, app_url)
    send(page, "hello there")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    expect(copy_button(page, page.locator(".msg.user").first)).to_be_visible()
    button = page.locator(".msg.user").first.locator(".actions button").first  # still the one when it is renamed
    button.click()
    expect(button).to_have_accessible_name("Copied")
    assert page.evaluate("window.__copied") == ["hello there"]
    expect(button).to_be_focused()  # selecting the copy did not take the focus away


def test_when_nothing_can_copy_the_buttons_say_so_instead_of_doing_nothing(page, app_url):
    page.add_init_script(REFUSED + ";document.execCommand = () => false")
    open_app(page, app_url)
    send(page, "show code")
    button = page.locator(".code .code-copy")
    button.click()
    expect(button).to_have_accessible_name("Couldn't copy")
    expect(button).to_have_accessible_name("Copy code")  # and is itself again a moment later
    expect(page.locator("#composer-note")).to_be_hidden()
    expect(page.locator(".msg.assistant")).to_contain_text("print")
    copy_button(page, page.locator(".msg.user").first).click()
    expect(page.locator("#composer-note")).to_contain_text("Couldn't copy")
