"""Phase 8 in the browser: searching chats, exporting one, and the compaction note."""
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_sidebar, send


def search_box(page):
    return page.get_by_role("searchbox", name="Search conversations")


def test_search_shows_matching_chats_with_the_match_highlighted(page, app_url):
    open_app(page, app_url)
    send(page, "tell me about quokkas")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()  # saved, not cut off
    page.get_by_role("button", name="New chat").click()
    send(page, "tell me about cats")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    open_sidebar(page)
    search_box(page).fill("quokk")
    result = page.locator(".result")
    expect(result).to_have_count(1)
    expect(result.locator("strong")).to_have_text("tell me about quokkas")
    # the prefix matched the word, in the title and in the snippet
    expect(result.locator("mark")).to_have_text(["quokkas", "quokkas"])
    expect(page.locator("#conversations h2")).to_have_count(0)  # the dated list is replaced


def test_clicking_a_result_opens_that_chat_and_clearing_restores_the_list(page, app_url):
    open_app(page, app_url)
    send(page, "tell me about quokkas")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()  # saved, not cut off
    page.get_by_role("button", name="New chat").click()
    send(page, "tell me about cats")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
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
    assert page.locator("#export-md").get_attribute("href") is None  # so no link can ask for a conversation named null
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


def seed_chats(page, app_url, n):
    for i in range(n):
        cid = page.request.post(f"{app_url}/api/conversations").json()["id"]
        page.request.patch(f"{app_url}/api/conversations/{cid}", data={"title": f"chat {i:03d}"})


def test_a_long_list_loads_a_page_and_show_more_loads_the_rest(page, app_url):
    seed_chats(page, app_url, 120)
    open_app(page, app_url)
    open_sidebar(page)
    links = page.locator(".conv a:not(.result)")
    expect(links).to_have_count(50)
    expect(links.first).to_have_text("chat 119")  # newest first
    page.get_by_role("button", name="Show more").click()
    expect(links).to_have_count(100)
    page.get_by_role("button", name="Show more").click()
    expect(links).to_have_count(120)
    expect(page.get_by_role("button", name="Show more")).to_have_count(0)  # nothing older


def test_a_short_list_has_no_show_more(page, app_url):
    seed_chats(page, app_url, 3)
    open_app(page, app_url)
    open_sidebar(page)
    expect(page.locator(".conv a:not(.result)")).to_have_count(3)
    expect(page.get_by_role("button", name="Show more")).to_have_count(0)


def test_a_chat_beyond_the_first_page_opens_with_its_title_and_stays_loaded_on_refresh(page, app_url):
    seed_chats(page, app_url, 60)
    open_app(page, app_url)
    open_sidebar(page)
    page.get_by_role("button", name="Show more").click()
    page.get_by_role("link", name="chat 000").click()
    expect(page.locator("#title")).to_have_text("chat 000")
    page.get_by_role("button", name='Rename "chat 001"').click()
    page.locator("#rename-input").fill("renamed one")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("link", name="renamed one")).to_be_visible()
    expect(page.locator(".conv a:not(.result)")).to_have_count(60)  # a refresh keeps what was loaded
    expect(page.locator("#title")).to_have_text("chat 000")
    page.get_by_role("button", name="New chat").first.click()
    expect(page.locator("#title")).to_have_text("New chat")


def test_mod_k_focuses_search_and_mod_shift_o_starts_a_new_chat(page, app_url):
    open_app(page, app_url)
    send(page, "tell me about quokkas")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    page.keyboard.press("Control+k")
    expect(search_box(page)).to_be_focused()
    expect(page.locator("body")).to_have_class(re.compile("nav-open"))
    page.keyboard.press("Control+Shift+O")
    expect(page.locator(".msg")).to_have_count(0)
    expect(page.locator("#title")).to_have_text("New chat")
    expect(page.locator("#input")).to_be_focused()


def test_the_shortcuts_are_ignored_while_a_dialog_is_open_and_without_the_modifier(page, app_url):
    open_app(page, app_url)
    page.keyboard.press("k")  # plain letters belong to the message box
    expect(page.locator("#input")).to_have_value("k")
    page.get_by_role("button", name="Chat settings").click()
    page.keyboard.press("Control+k")
    expect(page.locator("body")).not_to_have_class(re.compile("nav-open"))  # nothing opened behind the dialog


def test_the_shortcuts_are_in_the_tooltips(page, app_url):
    open_app(page, app_url)
    open_sidebar(page)
    expect(page.locator("#new-chat")).to_have_attribute("title", re.compile(r"New chat \((⌘|Ctrl\+)Shift\+O\)"))
    expect(search_box(page)).to_have_attribute("title", re.compile(r"Search chats \((⌘|Ctrl\+)K\)"))


# ---- undo for delete ----

def delete_chat(page, title):
    open_sidebar(page)
    page.get_by_role("button", name=f'Delete "{title}"').click()
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()


def chat_exists(page, app_url, cid):
    return page.request.get(f"{app_url}/api/conversations/{cid}").status == 200


def test_undo_brings_back_the_open_chat_with_its_messages(page, app_url):
    open_app(page, app_url)
    send(page, "tell me about quokkas")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    cid = page.url.split("#")[1]
    delete_chat(page, "tell me about quokkas")
    expect(page.get_by_role("status")).to_contain_text('Deleted "tell me about quokkas"')
    expect(page.get_by_text("Your conversations will show up here.")).to_be_visible()  # hidden at once
    expect(page.locator(".msg")).to_have_count(0)
    page.get_by_role("button", name="Undo").click()
    expect(page.locator(".msg.user .body")).to_have_text("tell me about quokkas")
    expect(page.locator("#conversations a")).to_have_text("tell me about quokkas")
    expect(page.locator("#toast")).to_be_hidden()
    assert chat_exists(page, app_url, cid)


def test_undo_for_a_chat_that_was_not_open_only_restores_the_list(page, app_url):
    open_app(page, app_url)
    send(page, "first chat")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    page.get_by_role("button", name="New chat").first.click()
    send(page, "second chat")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    delete_chat(page, "first chat")
    expect(page.locator("#conversations a")).to_have_count(1)
    expect(page.locator("#conversations a")).to_have_text("second chat")
    expect(page.locator(".msg.user .body")).to_have_text("second chat")  # still where it was
    page.get_by_role("button", name="Undo").click()
    expect(page.locator("#conversations a")).to_have_text(["second chat", "first chat"])
    expect(page.locator(".msg.user .body")).to_have_text("second chat")


def test_the_delete_becomes_final_after_the_wait(page, app_url):
    page.clock.install()
    open_app(page, app_url)
    send(page, "doomed chat")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    cid = page.url.split("#")[1]
    delete_chat(page, "doomed chat")
    assert chat_exists(page, app_url, cid)  # not yet
    with page.expect_response(lambda r: r.request.method == "DELETE"):
        page.clock.fast_forward(11_000)
    expect(page.locator("#toast")).to_be_hidden()
    assert not chat_exists(page, app_url, cid)


def test_deleting_a_second_chat_makes_the_first_delete_final(page, app_url):
    seed_chats(page, app_url, 2)
    open_app(page, app_url)
    ids = [c["id"] for c in page.request.get(f"{app_url}/api/conversations").json()]
    delete_chat(page, "chat 001")
    with page.expect_response(lambda r: r.request.method == "DELETE"):
        page.get_by_role("button", name='Delete "chat 000"').click()
        page.get_by_role("dialog").get_by_role("button", name="Delete").click()
    expect(page.get_by_role("status")).to_contain_text('Deleted "chat 000"')
    assert not chat_exists(page, app_url, ids[0])  # chat 001, the first one
    assert chat_exists(page, app_url, ids[1])  # chat 000 can still be undone


def test_a_chat_waiting_to_be_deleted_is_not_in_search_results(page, app_url):
    open_app(page, app_url)
    send(page, "tell me about quokkas")
    expect(page.locator(".msg.assistant .actions button").first).to_be_visible()
    delete_chat(page, "tell me about quokkas")
    search_box(page).fill("quokkas")
    expect(page.get_by_text("No chats match.")).to_be_visible()
