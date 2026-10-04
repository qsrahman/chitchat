"""Backup and import from the sidebar."""
import json

from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_prefs, open_sidebar, row_action, send

CHAT_ID = "ab" * 16


def chat_file(title="Imported wombats", cid=CHAT_ID, **extra):
    return {"conversations": [{"id": cid, "title": title, "messages": [
        {"role": "user", "content": "where do wombats sleep?"},
        {"role": "assistant", "content": "In burrows, mostly.", **extra}]}]}


def as_upload(data, name="chats.json"):
    body = data if isinstance(data, bytes) else json.dumps(data).encode()
    return {"name": name, "mimeType": "application/json", "buffer": body}


def open_backup(page):
    """Settings, Data controls: where the exports and the import are."""
    return open_prefs(page, "Data controls")


def test_the_sidebar_has_a_backup_button_that_opens_the_dialog(page, app_url):
    open_app(page, app_url)
    dialog = open_backup(page)
    expect(dialog.get_by_role("link", name="Export all chats")).to_have_attribute("href", "/api/export?format=json")
    expect(dialog.get_by_role("link", name="Export with attachments")).to_have_attribute(
        "href", "/api/export?format=full")
    expect(dialog.get_by_role("link", name="Export as Markdown")).to_have_attribute("href", "/api/export?format=md")
    expect(dialog.get_by_label("Import chats from a file")).to_be_visible()
    expect(dialog.locator("#backup-status")).to_be_hidden()
    dialog.get_by_role("button", name="Close").click()
    expect(dialog).to_be_hidden()


def test_settings_is_in_the_icon_rail_too(page, app_url):
    open_app(page, app_url)  # the sidebar starts closed, as a rail of icons
    expect(page.get_by_role("button", name="Settings", exact=True)).to_be_visible()


def test_exporting_downloads_a_file_with_the_chats_in_it(page, app_url):
    open_app(page, app_url)
    send(page, "hello export")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    dialog = open_backup(page)
    with page.expect_download() as download:
        dialog.get_by_role("link", name="Export all chats").click()
    name = download.value.suggested_filename
    assert name.startswith("chitchat-") and name.endswith(".json")
    data = json.load(open(download.value.path()))
    assert data["format"] == "chitchat-backup"
    assert data["conversations"][0]["messages"][0]["content"] == "hello export"
    with page.expect_download() as zipped:
        dialog.get_by_role("link", name="Export as Markdown").click()
    assert zipped.value.suggested_filename.endswith(".zip")


def test_importing_a_file_adds_the_chat_to_the_list_and_it_opens(page, app_url):
    open_app(page, app_url)
    dialog = open_backup(page)
    dialog.get_by_label("Import chats from a file").set_input_files(as_upload(chat_file()))
    expect(dialog.locator("#backup-status")).to_have_text("Imported 1 chat.")
    dialog.get_by_role("button", name="Close").click()
    open_sidebar(page)
    page.locator("#conversations").get_by_role("link", name="Imported wombats").click()
    expect(page.locator(".msg.user .body")).to_have_text("where do wombats sleep?")
    expect(page.locator(".msg.assistant .body")).to_have_text("In burrows, mostly.")


def test_importing_the_same_file_again_says_nothing_is_new(page, app_url):
    open_app(page, app_url)
    dialog = open_backup(page)
    upload = dialog.get_by_label("Import chats from a file")
    upload.set_input_files(as_upload(chat_file()))
    expect(dialog.locator("#backup-status")).to_have_text("Imported 1 chat.")
    upload.set_input_files(as_upload(chat_file()))  # the same file chosen again still counts
    expect(dialog.locator("#backup-status")).to_have_text("Nothing new: 1 chat already here.")
    assert page.locator("#conversations .conv").count() == 1


def test_a_partly_new_file_says_how_many_of_each(page, app_url):
    open_app(page, app_url)
    dialog = open_backup(page)
    upload = dialog.get_by_label("Import chats from a file")
    upload.set_input_files(as_upload(chat_file()))
    expect(dialog.locator("#backup-status")).to_have_text("Imported 1 chat.")
    both = {"conversations": [*chat_file()["conversations"], *chat_file("Another", "cd" * 16)["conversations"]]}
    upload.set_input_files(as_upload(both))
    expect(dialog.locator("#backup-status")).to_have_text("Imported 1 chat; 1 already here.")


def test_a_file_that_is_not_an_export_says_why_and_adds_nothing(page, app_url, expected_console_errors):
    expected_console_errors.append("422")  # the browser logs the refusals it is meant to get
    open_app(page, app_url)
    dialog = open_backup(page)
    upload = dialog.get_by_label("Import chats from a file")
    upload.set_input_files(as_upload(b"this is not json", "notes.json"))
    status = dialog.locator("#backup-status")
    expect(status).to_contain_text("isn't JSON")
    expect(status).to_have_class("is-error")
    wrong_role = {"conversations": [{"title": "t", "messages": [{"role": "robot", "content": "x"}]}]}
    upload.set_input_files(as_upload(wrong_role))
    expect(status).to_contain_text("doesn't look like a ChitChat export")
    dialog.get_by_role("button", name="Close").click()
    expect(page.locator("#conversations")).to_contain_text("Your conversations will show up here.")


def test_when_the_server_cannot_be_reached_it_says_so(page, app_url, expected_console_errors):
    expected_console_errors.append("net::ERR_FAILED")
    open_app(page, app_url)
    dialog = open_backup(page)
    page.route("**/api/import", lambda route: route.abort())
    dialog.get_by_label("Import chats from a file").set_input_files(as_upload(chat_file()))
    expect(dialog.locator("#backup-status")).to_have_text("Couldn't reach the server.")


def test_the_status_clears_when_the_dialog_is_opened_again(page, app_url):
    open_app(page, app_url)
    dialog = open_backup(page)
    dialog.get_by_label("Import chats from a file").set_input_files(as_upload(chat_file()))
    expect(dialog.locator("#backup-status")).to_be_visible()
    dialog.get_by_role("button", name="Close").click()
    open_backup(page)
    expect(page.locator("#backup-status")).to_be_hidden()


def test_a_hostile_file_cannot_run_script_or_break_the_chat(page, app_url):
    """Markup in the title and the reply, a tool call whose details are the wrong shape, a javascript: link."""
    evil = "<img src=x onerror=window.__xss=1><script>window.__xss=1</script>"
    data = {"conversations": [{"id": CHAT_ID, "title": evil, "messages": [
        {"role": "user", "content": evil},
        {"role": "assistant", "content": f"{evil} [x](javascript:window.__xss=1)", "meta": {"tools": [
            {"id": "c1", "name": "calculator", "status": "done", "display": {"expression": 1}},
            {"id": "c2", "name": "search_chats", "status": "done", "display": {"query": "q", "results": "nope"}},
            {"id": "c3", "name": "fetch_url", "status": "done", "display": {"url": "javascript:window.__xss=1"}},
            {"id": "c4", "name": "web_search", "status": "done", "display": {}},
        ]}}]}]}
    open_app(page, app_url)
    dialog = open_backup(page)
    dialog.get_by_label("Import chats from a file").set_input_files(as_upload(data))
    expect(dialog.locator("#backup-status")).to_have_text("Imported 1 chat.")
    page.goto(f"{app_url}/#{CHAT_ID}")
    expect(page.locator(".msg.assistant")).to_be_visible()
    assert page.locator(".msg.user .body").text_content() == evil  # as text
    expect(page.locator(".msg.assistant img")).to_have_count(0)
    expect(page.locator(".tool-call")).to_have_count(4)  # every call is there, and the chat opened
    summaries = page.locator(".tool-call summary").all_text_contents()
    assert summaries[3] == "Used web_search"  # details that make a line throw fall back to a plain one
    assert all("<" not in text or "script" not in text for text in summaries)
    assert page.evaluate("window.__xss") is None
    assert page.locator(".msg.assistant a[href^='javascript']").count() == 0


def test_a_backup_with_attachments_brings_the_pictures_back(page, app_url):
    from tests.ui.test_attachments_ui import PIC, attach, wait_uploaded
    from tests.ui.test_chat_ui import finish_delete
    open_app(page, app_url)
    attach(page, PIC)
    wait_uploaded(page)
    send(page, "keep this picture")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    dialog = open_backup(page)
    with page.expect_download() as download:
        dialog.get_by_role("link", name="Export with attachments").click()
    assert download.value.suggested_filename.endswith("-with-files.zip")
    zipped = download.value.path()
    dialog.get_by_role("button", name="Close").click()
    open_sidebar(page)
    row_action(page, "keep this picture", "Delete…")  # gone, files and all
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()
    expect(page.get_by_text("Your conversations will show up here.")).to_be_visible()
    finish_delete(page)
    dialog = open_backup(page)
    dialog.get_by_label("Import chats from a file").set_input_files(
        {"name": "backup.zip", "mimeType": "application/zip", "buffer": open(zipped, "rb").read()})
    expect(dialog.locator("#backup-status")).to_have_text("Imported 1 chat with 1 file.")
    dialog.get_by_role("button", name="Close").click()
    page.locator("#conversations").get_by_role("link", name="keep this picture").click()
    image = page.locator(".msg.user .tile-image img")
    expect(image).to_be_visible()
    page.wait_for_function("(el) => el.complete && el.naturalWidth > 0", arg=image.element_handle())  # it loads


def test_importing_a_chat_you_just_deleted_brings_it_back_and_it_stays(page, app_url):
    """The delete waits ten seconds for Undo; an import in that time must not be hidden by it or deleted by it."""
    page.clock.install()
    open_app(page, app_url)
    send(page, "tell me about quokkas")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    cid = page.url.split("#")[1]
    backup = page.request.get(f"{app_url}/api/export").body()
    open_sidebar(page)
    row_action(page, "tell me about quokkas", "Delete…")
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()
    expect(page.locator("#toast")).to_be_visible()
    dialog = open_backup(page)
    dialog.get_by_label("Import chats from a file").set_input_files(as_upload(backup))
    expect(dialog.locator("#backup-status")).to_have_text("Imported 1 chat.")
    dialog.get_by_role("button", name="Close").click()
    quokkas = page.locator("#conversations").get_by_role("link", name="tell me about quokkas")
    expect(quokkas).to_be_visible()  # not hidden
    page.clock.fast_forward(11_000)
    expect(page.locator("#conversations").get_by_role("link", name="tell me about quokkas")).to_be_visible()
    assert page.request.get(f"{app_url}/api/conversations/{cid}").status == 200  # and not deleted again


def test_an_import_says_when_it_took_the_defaults_for_new_chats(page, app_url):
    open_app(page, app_url)
    dialog = open_backup(page)
    document = {**chat_file(), "defaults": {"model": "alpha-model", "tools": ["web_search"]}}
    dialog.get_by_label("Import chats from a file").set_input_files(as_upload(document))
    expect(dialog.locator("#backup-status")).to_contain_text("defaults for new chats added")
    dialog.get_by_role("tab", name="General").click()  # the page takes them at once, not after a reload
    expect(dialog.get_by_label("Model", exact=True)).to_have_value("alpha-model")
    expect(dialog.get_by_role("switch", name="Web search")).to_be_checked()
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Web search")).to_have_attribute("aria-pressed", "true")  # the new chat
