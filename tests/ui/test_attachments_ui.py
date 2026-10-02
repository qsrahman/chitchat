import re

from playwright.sync_api import expect

from tests.helpers import PNG, make_pdf
from tests.ui.test_chat_ui import open_app, open_sidebar, saved_messages, send

NOTES = ("notes.txt", b"remember the milk", "text/plain")
PIC = ("pic.png", PNG, "image/png")
DOC = ("doc.pdf", make_pdf("Hello PDF world"), "application/pdf")


def attach(page, *files):
    page.set_input_files("#file-input", [{"name": n, "mimeType": m, "buffer": b} for n, b, m in files])


def chips(page):
    return page.locator("#chips .chip")


def sent_button(page):
    return page.locator("#send")


def wait_uploaded(page):
    expect(page.locator('#chips .chip[aria-busy="true"]')).to_have_count(0)


def test_attach_button_opens_the_file_chooser_and_files_become_chips(page, app_url):
    open_app(page, app_url)
    expect(page.locator("#chips")).to_be_hidden()
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="Attach files").click()
    chooser.value.set_files([{"name": n, "mimeType": m, "buffer": b} for n, b, m in (PIC, NOTES)])
    expect(chips(page)).to_have_count(2)
    wait_uploaded(page)
    image, text = chips(page).nth(0), chips(page).nth(1)
    expect(image.locator("img")).to_have_attribute("alt", "pic.png")
    expect(image.locator("img")).to_have_attribute("src", re.compile("^blob:"))  # a local preview
    expect(text).to_contain_text("notes.txt")
    expect(text).to_contain_text("17B")


def test_a_message_can_be_just_attachments_and_they_are_shown_and_sent(page, app_url):
    open_app(page, app_url)
    expect(sent_button(page)).to_be_disabled()
    attach(page, PIC, NOTES, DOC)
    wait_uploaded(page)
    expect(sent_button(page)).to_be_enabled()  # no text needed
    sent_button(page).click()

    user = page.locator(".msg.user")
    expect(user.locator(".tile-image img")).to_have_attribute("alt", "pic.png")
    expect(user.locator(".tile-file .chip-name")).to_have_text(["notes.txt", "doc.pdf"])
    expect(user.locator(".body")).to_be_hidden()  # no empty bubble
    expect(page.locator(".msg.assistant")).to_contain_text("[files=pic.png,notes.txt,doc.pdf]")
    expect(page.locator("#chips")).to_be_hidden()  # moved from the composer into the message
    expect(page.locator("#title")).to_have_text("pic.png, notes.txt, doc.pdf")  # titled from the file names


def test_text_and_attachments_together(page, app_url):
    open_app(page, app_url)
    attach(page, NOTES)
    wait_uploaded(page)
    send(page, "summarize this")
    expect(page.locator(".msg.user .body")).to_have_text("summarize this")
    expect(page.locator(".msg.user .tile-file")).to_have_count(1)
    expect(page.locator(".msg.assistant")).to_contain_text("[files=notes.txt]")


def test_removing_a_chip_keeps_it_out_of_the_message(page, app_url):
    open_app(page, app_url)
    attach(page, PIC, NOTES)
    wait_uploaded(page)
    page.get_by_role("button", name="Remove pic.png").click()
    expect(chips(page)).to_have_count(1)
    send(page, "just the notes")
    expect(page.locator(".msg.assistant")).to_contain_text("[files=notes.txt]")
    expect(page.locator(".msg.user .tile-image")).to_have_count(0)


def test_removing_the_last_chip_disables_send_again(page, app_url):
    open_app(page, app_url)
    attach(page, PIC)
    wait_uploaded(page)
    expect(sent_button(page)).to_be_enabled()
    page.get_by_role("button", name="Remove pic.png").click()
    expect(page.locator("#chips")).to_be_hidden()
    expect(sent_button(page)).to_be_disabled()


def test_unsupported_files_show_why_and_are_not_sent(page, app_url, expected_console_errors):
    open_app(page, app_url)
    expected_console_errors.append("415")  # the browser logs the rejected upload
    attach(page, ("tool.zip", b"PK\x03\x04" + b"\x00" * 300, "application/zip"), NOTES)
    wait_uploaded(page)
    bad = chips(page).nth(0)
    expect(bad).to_have_class(re.compile("is-error"))
    expect(bad).to_contain_text("Unsupported file type")
    send(page, "hello")
    expect(page.locator(".msg.assistant")).to_contain_text("[files=notes.txt]")
    expect(page.locator(".msg.user .tile-file")).to_have_count(1)  # only the good one went


def test_too_many_files_are_refused_with_a_message(page, app_url):
    open_app(page, app_url)
    attach(page, *[(f"{i}.txt", b"hi", "text/plain") for i in range(6)])
    expect(chips(page)).to_have_count(6)
    expect(chips(page).last).to_contain_text("up to 5 files")
    wait_uploaded(page)
    send(page, "go")
    expect(page.locator(".msg.user .tile-file")).to_have_count(5)


def test_send_waits_for_uploads_to_finish(page, app_url):
    open_app(page, app_url)
    held = []

    def hold_uploads(route):
        held.append(route) if route.request.method == "POST" else route.continue_()

    page.route("**/api/attachments", hold_uploads)
    attach(page, NOTES)
    expect(page.locator('#chips .chip[aria-busy="true"]')).to_have_count(1)
    page.get_by_label("Message", exact=True).fill("text is ready")
    expect(sent_button(page)).to_be_disabled()  # the file is still uploading
    page.keyboard.press("Enter")  # and Enter doesn't sneak past it
    expect(page.locator(".msg.user")).to_have_count(0)
    held[0].continue_()
    wait_uploaded(page)
    expect(sent_button(page)).to_be_enabled()
    page.keyboard.press("Enter")
    expect(page.locator(".msg.assistant")).to_contain_text("[files=notes.txt]")


def test_a_failed_upload_says_so(page, app_url, expected_console_errors):
    open_app(page, app_url)
    expected_console_errors.append("net::ERR_FAILED")

    def fail_uploads(route):
        route.abort() if route.request.method == "POST" else route.continue_()

    page.route("**/api/attachments", fail_uploads)
    attach(page, NOTES)
    expect(chips(page).first).to_contain_text("Couldn't reach the server")


def test_dropping_files_on_the_page_attaches_them(page, app_url):
    open_app(page, app_url)
    drag = """(type) => {
      const dt = new DataTransfer();
      dt.items.add(new File(["dropped words"], "dropped.txt", { type: "text/plain" }));
      document.dispatchEvent(new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true }));
    }"""
    page.evaluate(drag, "dragenter")
    expect(page.locator("#drop")).to_be_visible()
    page.evaluate(drag, "drop")
    expect(page.locator("#drop")).to_be_hidden()
    expect(chips(page)).to_have_count(1)
    expect(chips(page).first).to_contain_text("dropped.txt")
    wait_uploaded(page)
    send(page, "read it")
    expect(page.locator(".msg.assistant")).to_contain_text("[files=dropped.txt]")


def test_dragging_something_that_is_not_a_file_does_nothing(page, app_url):
    open_app(page, app_url)
    page.evaluate("""() => {
      const dt = new DataTransfer(); dt.setData("text/plain", "just text");
      document.dispatchEvent(new DragEvent("dragenter", { dataTransfer: dt, bubbles: true }));
    }""")
    expect(page.locator("#drop")).to_be_hidden()


def test_pasting_an_image_attaches_it_but_pasting_text_is_left_alone(page, app_url):
    open_app(page, app_url)
    paste = """([bytes, asFile]) => {
      const dt = new DataTransfer();
      if (asFile) dt.items.add(new File([new Uint8Array(bytes)], "shot.png", { type: "image/png" }));
      else dt.setData("text/plain", "some text");
      const event = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true });
      document.getElementById("input").dispatchEvent(event);
      return event.defaultPrevented;
    }"""
    assert page.evaluate(paste, [list(PNG), False]) is False  # left to the browser
    expect(page.locator("#chips")).to_be_hidden()
    assert page.evaluate(paste, [list(PNG), True]) is True
    expect(chips(page)).to_have_count(1)
    expect(chips(page).first.locator("img")).to_have_attribute("alt", "shot.png")


def test_attachments_survive_a_reload_and_open_or_download(page, app_url):
    open_app(page, app_url)
    attach(page, PIC, NOTES)
    wait_uploaded(page)
    send(page, "look")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    page.reload()
    image = page.locator(".msg.user .tile-image")
    expect(image.locator("img")).to_have_js_property("naturalWidth", 1)  # the file is really served
    expect(image).to_have_attribute("target", "_blank")
    expect(image).to_have_attribute("rel", "noopener")
    file_link = page.locator(".msg.user .tile-file")
    response = page.request.get(f"{app_url}{file_link.get_attribute('href')}")
    assert response.text() == "remember the milk"
    assert response.headers["content-disposition"].startswith("attachment")


def test_file_names_are_shown_as_text_not_markup(page, app_url):
    open_app(page, app_url)
    nasty = "<b>bold<img src=x onerror=window.__xss=1>.txt"
    attach(page, (nasty, b"hi", "text/plain"))
    expect(chips(page).first).to_contain_text(nasty)
    wait_uploaded(page)
    send(page, "hello")
    expect(page.locator(".msg.user .tile-file .chip-name")).to_have_text(nasty)
    expect(page.locator("#chips img, .attachments img")).to_have_count(0)
    assert page.evaluate("window.__xss") is None


def test_retry_after_a_send_that_never_arrived_resends_the_attachments(page, app_url, expected_console_errors):
    open_app(page, app_url)
    expected_console_errors.append("net::ERR_FAILED")
    first = []

    def kill_first(route):
        if first:
            route.continue_()
        else:
            first.append(1)
            route.abort()

    page.route("**/api/conversations/*/chat", kill_first)
    attach(page, NOTES)
    wait_uploaded(page)
    send(page, "read this")
    expect(page.locator(".msg.error")).to_contain_text("Couldn't get a reply")
    page.get_by_role("button", name="Retry").click()
    expect(page.locator(".msg.assistant")).to_contain_text("[files=notes.txt]")
    saved = saved_messages(page)
    assert [a["name"] for a in saved[0]["meta"]["attachments"]] == ["notes.txt"]
    assert len(saved) == 2


def test_retry_after_a_model_error_replies_to_the_same_attachments(page, app_url):
    open_app(page, app_url)
    attach(page, NOTES)
    wait_uploaded(page)
    send(page, "please fail")
    expect(page.locator(".msg.error")).to_contain_text("simulated failure")
    page.get_by_role("button", name="Retry").click()
    expect(page.locator(".msg.assistant")).to_contain_text("[files=notes.txt]")
    assert len(saved_messages(page)) == 2


def test_regenerate_and_edit_keep_the_attachments(page, app_url):
    open_app(page, app_url)
    attach(page, NOTES)
    wait_uploaded(page)
    send(page, "first words")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    page.get_by_role("button", name="Regenerate").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #2")
    expect(page.locator(".msg.assistant")).to_contain_text("[files=notes.txt]")
    page.get_by_role("button", name="Edit").click()
    page.get_by_label("Edit your message").fill("reworded")
    page.get_by_role("button", name="Save").click()
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #3")
    expect(page.locator(".msg.assistant")).to_contain_text("[files=notes.txt]")
    expect(page.locator(".msg.user .tile-file")).to_have_count(1)


def test_switching_conversations_clears_the_composer_chips(page, app_url):
    open_app(page, app_url)
    send(page, "first chat")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    attach(page, NOTES)
    wait_uploaded(page)
    expect(chips(page)).to_have_count(1)
    open_sidebar(page)
    page.get_by_role("button", name="New chat").click()
    expect(page.locator("#chips")).to_be_hidden()
    expect(sent_button(page)).to_be_disabled()


def test_deleting_the_conversation_deletes_its_files(page, app_url):
    open_app(page, app_url)
    attach(page, PIC)
    wait_uploaded(page)
    send(page, "keep this")
    expect(page.locator(".msg.assistant")).to_contain_text("Reply #1")
    href = page.locator(".msg.user .tile-image").get_attribute("href")
    assert page.request.get(f"{app_url}{href}").status == 200
    open_sidebar(page)
    page.get_by_role("button", name=re.compile('^Delete "')).click()
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()
    assert page.request.get(f"{app_url}{href}").status == 404


def test_the_composer_stays_tidy_with_chips_on_a_phone(page, app_url):
    page.set_viewport_size({"width": 375, "height": 700})
    open_app(page, app_url)
    attach(page, PIC, NOTES, DOC, ("a-rather-long-file-name-for-a-phone-screen.txt", b"hi", "text/plain"))
    wait_uploaded(page)
    composer = page.locator(".composer").bounding_box()
    assert composer["x"] >= 0 and composer["x"] + composer["width"] <= 375
    for i in range(4):
        box = chips(page).nth(i).bounding_box()
        assert box["x"] + box["width"] <= composer["x"] + composer["width"] + 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
