"""Settings, Data controls, Storage: what is kept, unused files, and deleting old archived chats."""
import os
import sqlite3

from playwright.sync_api import expect

from tests.ui.test_chat_ui import conv_id, open_app, open_prefs, send

LONG_AGO = "2000-01-01T00:00:00+00:00"


def storage(page):
    return open_prefs(page, "Data controls")


def age_chat(tmp_path, cid):
    """Archive-time is not activity, so a chat is made 'old' by its last message's time."""
    with sqlite3.connect(tmp_path / "ui.db") as conn:
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (LONG_AGO, cid))


def archive(page, app_url, cid):
    assert page.request.patch(f"{app_url}/api/conversations/{cid}", data={"archived": True}).ok


def finished_chat(page, text):
    """Send a message in a new chat and wait until the reply is saved; returns the chat's id."""
    send(page, text)
    expect(page.locator(".msg.assistant").last.locator(".actions button").first).to_be_visible()
    return conv_id(page)


def test_it_says_what_is_kept_and_has_nothing_to_delete_at_first(page, app_url):
    open_app(page, app_url)
    d = storage(page)
    expect(d.locator("#storage-summary")).to_contain_text("Database")
    expect(d.locator("#storage-summary")).to_contain_text("0 files. 0 chats, 0 archived.")
    expect(d.locator("#unused-note")).to_have_text("None: every file belongs to a chat.")
    expect(d.get_by_role("button", name="Delete unused files")).to_be_disabled()
    expect(d.locator("#archived-note")).to_have_text("No archived chats are that old.")
    expect(d.get_by_role("button", name="Delete archived chats")).to_be_disabled()


def test_the_numbers_follow_the_chats(page, app_url):
    open_app(page, app_url)
    finished_chat(page, "hello")
    expect(storage(page).locator("#storage-summary")).to_contain_text("1 chat, 0 archived.")


def test_unused_files_can_be_deleted(page, app_url, tmp_path):
    open_app(page, app_url)
    folder = tmp_path / "files"
    folder.mkdir(exist_ok=True)
    stray = folder / ("a" * 32)
    stray.write_bytes(b"left behind")
    os.utime(stray, (0, 0))
    d = storage(page)
    expect(d.locator("#unused-note")).to_contain_text("1 file")
    d.get_by_role("button", name="Delete unused files").click()
    expect(d.locator("#storage-status")).to_have_text("Deleted 1 unused file, 11B.")
    assert not stray.exists()
    expect(d.locator("#unused-note")).to_have_text("None: every file belongs to a chat.")
    expect(d.get_by_role("button", name="Delete unused files")).to_be_disabled()


def test_old_archived_chats_are_deleted_after_a_confirmation_and_the_open_one_is_left(page, app_url, tmp_path):
    open_app(page, app_url)
    old = finished_chat(page, "an old one")  # the chat on screen is the one that will go
    archive(page, app_url, old)
    age_chat(tmp_path, old)
    page.get_by_role("button", name="New chat").click()
    kept = finished_chat(page, "a new one")
    archive(page, app_url, kept)  # archived, but not old

    d = storage(page)
    expect(d.locator("#archived-note")).to_have_text("1 archived chat not used for 90 days or more.")
    d.get_by_role("button", name="Delete archived chats").click()
    confirm = page.get_by_role("dialog", name="Delete old archived chats?")
    expect(confirm).to_contain_text("1 archived chat not used for 90 days or more will be deleted for good")
    confirm.get_by_role("button", name="Keep them").click()
    assert page.request.get(f"{app_url}/api/conversations/{old}").ok  # cancelled: nothing happened

    d.get_by_role("button", name="Delete archived chats").click()
    confirm.get_by_role("button", name="Delete for good").click()
    expect(d.locator("#storage-status")).to_have_text("Deleted 1 chat.")
    assert page.request.get(f"{app_url}/api/conversations/{old}").status == 404
    assert page.request.get(f"{app_url}/api/conversations/{kept}").ok
    expect(d.locator("#archived-note")).to_have_text("No archived chats are that old.")
    expect(d.locator("#storage-summary")).to_contain_text("1 chat, 1 archived.")


def test_the_chat_on_screen_is_closed_when_it_is_one_of_the_deleted(page, app_url, tmp_path):
    open_app(page, app_url)
    cid = finished_chat(page, "about to go")
    archive(page, app_url, cid)
    age_chat(tmp_path, cid)
    d = storage(page)
    d.get_by_role("button", name="Delete archived chats").click()
    confirm = page.get_by_role("dialog", name="Delete old archived chats?")
    confirm.get_by_role("button", name="Delete for good").click()
    expect(d.locator("#storage-status")).to_have_text("Deleted 1 chat.")
    page.keyboard.press("Escape")
    expect(page.get_by_role("heading", name="What are you working on?")).to_be_visible()
    assert "#" not in page.url  # and the address no longer names the deleted chat


def test_a_longer_age_leaves_chats_that_are_not_that_old(page, app_url, tmp_path):
    open_app(page, app_url)
    cid = finished_chat(page, "somewhat old")
    archive(page, app_url, cid)
    with sqlite3.connect(tmp_path / "ui.db") as conn:  # 60 days ago
        conn.execute("UPDATE conversations SET updated_at = datetime('now', '-60 days') WHERE id = ?", (cid,))
    d = storage(page)
    expect(d.locator("#archived-note")).to_have_text("No archived chats are that old.")  # the default is 90 days
    d.locator("#archived-age").select_option("30")
    expect(d.locator("#archived-note")).to_have_text("1 archived chat not used for 30 days or more.")


def test_a_failed_delete_says_so_and_keeps_the_chat(page, app_url, tmp_path, expected_console_errors):
    open_app(page, app_url)
    cid = finished_chat(page, "stays")
    archive(page, app_url, cid)
    age_chat(tmp_path, cid)
    expected_console_errors.append("net::ERR_FAILED")
    page.route(
        "**/api/storage/archived*",
        lambda route: route.abort() if route.request.method == "DELETE" else route.continue_(),
    )
    d = storage(page)
    d.get_by_role("button", name="Delete archived chats").click()
    confirm = page.get_by_role("dialog", name="Delete old archived chats?")
    confirm.get_by_role("button", name="Delete for good").click()
    expect(d.locator("#storage-status")).to_contain_text("Couldn't delete them")
    assert page.request.get(f"{app_url}/api/conversations/{cid}").ok
