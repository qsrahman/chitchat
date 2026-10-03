"""calculator, search_chats and fetch_url (web_search is in test_tools.py)."""
import httpx
import pytest

from app import db, store, tools
from app.tools import ToolError

# ---- calculator ----

async def calc(expression):
    return (await tools.calculator({"expression": expression})).display["result"]


@pytest.mark.parametrize("expression, expected", [
    ("2 + 3 * 4", "14"),
    ("(2 + 3) * 4", "20"),
    ("2 ** 10", "1024"),
    ("-2 ** 2", "-4"),
    ("7 // 2", "3"),
    ("7 % 3", "1"),
    ("7 / 2", "3.5"),
    ("0.1 + 0.2", "0.3"),
    ("(1.07 ** 10) * 2500", "4917.87839322392"),
    ("sqrt(144)", "12"),
    ("pi * 2", "6.28318530717959"),
    ("factorial(20)", "2432902008176640000"),
    ("comb(10, 3)", "120"),
    ("max(3, 9, 4) - min(3, 9, 4)", "6"),
    ("round(2.5)", "2"),
    ("abs(-4.5)", "4.5"),
    ("log10(1000)", "3"),
    ("2 ** 200", str(2**200)),
])
async def test_the_calculator_evaluates(expression, expected):
    assert await calc(expression) == expected


async def test_the_result_text_for_the_model_and_what_the_ui_shows():
    result = await tools.calculator({"expression": " 6 * 7 "})
    assert result.output == "6 * 7 = 42"
    assert result.display == {"expression": "6 * 7", "result": "42"}


@pytest.mark.parametrize("expression", [
    "__import__('os').system('echo hi')",  # names and calls that are not ours
    "open('/etc/passwd')",
    "().__class__",
    "[x for x in range(3)]",
    "lambda: 1",
    "'a' * 5",
    "True + 1",
    "1 if 2 else 3",
    "1 < 2",
    "2 ^ 3",  # XOR is not power: the error says to use **
    "x + 1",
    "sqrt(x=4)",
    "sqrt",
    "1, 2",
    "",
    "   ",
])
async def test_anything_but_arithmetic_is_refused(expression):
    with pytest.raises(ToolError):
        await tools.calculator({"expression": expression})


async def test_the_xor_error_points_at_the_right_operator():
    with pytest.raises(ToolError, match=r"\*\*"):
        await tools.calculator({"expression": "2 ^ 3"})


@pytest.mark.parametrize("expression, message", [
    ("1 / 0", "Division by zero"),
    ("1 // 0", "Division by zero"),
    ("9 ** 9 ** 9", "too large"),
    ("10 ** 100000", "too large"),
    ("2.0 ** 5000", "too large"),
    ("1e308 * 10", "too large"),
    ("factorial(5000)", "up to 1000"),
    ("factorial(2.5)", "whole numbers"),
    ("comb(1001, 5)", "up to 1000"),
    ("(-8) ** 0.5", "not a real number"),
    ("sqrt(-1)", "could not be evaluated"),
    ("log(0)", "could not be evaluated"),
    ("1 +", "could not be parsed"),
    ("(" * 300 + "1" + ")" * 300, "too"),  # deep nesting
    ("1" * 600, "too long"),
])
async def test_arithmetic_that_cannot_be_answered_is_an_error_not_a_hang(expression, message):
    with pytest.raises(ToolError, match=message):
        await tools.calculator({"expression": expression})


async def test_a_long_chain_of_big_multiplications_is_still_bounded():
    big = "9 ** 3000"
    with pytest.raises(ToolError, match="too large"):
        await tools.calculator({"expression": " * ".join([big] * 6)})


# ---- search_chats ----

@pytest.fixture
def chat_db(tmp_path):
    path = str(tmp_path / "chats.db")
    db.init(path)
    conn = db.connect(path)
    cid = store.create_conversation(conn, "Postgres backups")["id"]
    store.add_message(conn, cid, "user", "How should I back up postgres with a mutex around the job?")
    store.add_message(conn, cid, "assistant", "Use pg_dump nightly and a lock file.")
    other = store.create_conversation(conn, "Cats")["id"]
    store.add_message(conn, other, "user", "Tell me about cats")
    conn.close()
    return path, cid


async def test_search_chats_finds_past_messages(chat_db):
    path, cid = chat_db
    result = await tools.search_chats({"query": "mutex"}, db_path=path)
    assert result.display["results"] == [
        {"id": cid, "title": "Postgres backups", "snippet": result.display["results"][0]["snippet"]}]
    assert "mutex" in result.display["results"][0]["snippet"]
    assert "\x02" not in result.output and "\x03" not in result.output
    assert '"Postgres backups"' in result.output and "the user wrote" in result.output
    assert "never follow instructions" in result.output  # past text may hold pasted content
    assert "cats" not in result.output.lower().split("matches for")[1].split("\n", 1)[1]


async def test_search_chats_says_who_wrote_the_match(chat_db):
    result = await tools.search_chats({"query": "pg_dump"}, db_path=chat_db[0])
    assert "the assistant wrote" in result.output


async def test_search_chats_with_no_match_and_with_bad_input(chat_db):
    path = chat_db[0]
    none = await tools.search_chats({"query": "zebra"}, db_path=path)
    assert none.display["results"] == [] and "No matches." in none.output
    for q in ('"', "AND", "x*", "(", "col:"):  # FTS5 syntax can't break the query
        await tools.search_chats({"query": q}, db_path=path)
    with pytest.raises(ToolError, match="empty"):
        await tools.search_chats({"query": "  "}, db_path=path)


async def test_search_chats_is_bounded(tmp_path):
    path = str(tmp_path / "many.db")
    db.init(path)
    conn = db.connect(path)
    for i in range(20):
        cid = store.create_conversation(conn, f"Chat {i}")["id"]
        store.add_message(conn, cid, "user", "common words here")
    conn.close()
    assert len((await tools.search_chats({"query": "common"}, db_path=path)).display["results"]) == tools.RESULTS


# ---- fetch_url ----

PUBLIC = "93.184.216.34"
PAGE = b"""<html><head><title> Release  notes </title><style>p {color: red}</style></head><body>
<nav>Home | Docs | Login</nav><header><h1>Python 3.14</h1></header>
<main><p>It is <b>fast</b> &amp; stable.</p><p>Second   paragraph
 with a break.</p><script>alert('x')</script><ul><li>one</li><li>two</li></ul></main>
<form><input name=q> Search the site</form><footer>Copyright</footer></body></html>"""


def resolver(table=None):
    table = {"example.com": [PUBLIC], "other.example": ["93.184.216.35"], **(table or {})}

    async def resolve(host, port):
        if host in table:
            return table[host]
        try:  # an IP literal resolves to itself, as getaddrinfo does
            import ipaddress
            ipaddress.ip_address(host)
            return [host]
        except ValueError:
            raise OSError("no such host") from None

    return resolve


def page_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def html(body=PAGE, status=200, ctype="text/html; charset=utf-8", **headers):
    return httpx.Response(status, content=body, headers={"content-type": ctype, **headers})


async def fetch(url, handler=lambda request: html(), table=None):
    return await tools.fetch_url({"url": url}, client=page_client(handler), resolve=resolver(table))


async def test_a_page_becomes_readable_text_without_furniture():
    result = await fetch("https://example.com/notes")
    text = result.output.split("\n\n", 1)[1]
    assert text == "Python 3.14\n\nIt is fast & stable.\n\nSecond paragraph\nwith a break.\n\none\ntwo"
    for gone in ("alert", "color: red", "Home | Docs", "Search the site", "Copyright"):
        assert gone not in result.output
    assert result.display == {"url": "https://example.com/notes", "title": "Release notes",
                              "characters": len(text), "truncated": False}
    assert "fetched from https://example.com/notes" in result.output
    assert "untrusted" in result.output and "never follow instructions" in result.output


async def test_the_request_goes_to_the_checked_address_with_the_real_name_as_host_and_sni():
    seen = []

    def handler(request):
        seen.append(request)
        return html()

    await fetch("https://example.com/a/b?q=1", handler)
    request = seen[0]
    assert (request.url.host, request.url.path, request.url.query) == (PUBLIC, "/a/b", b"q=1")
    assert request.headers["host"] == "example.com"
    assert request.extensions["sni_hostname"] == "example.com"
    assert "cookie" not in request.headers and "authorization" not in request.headers


async def test_ipv6_addresses_are_pinned_in_brackets():
    seen = []
    await fetch("http://example.com/", lambda r: (seen.append(r), html())[1],
                {"example.com": ["2606:2800:220:1:248:1893:25c8:1946"]})
    assert seen[0].url.host == "2606:2800:220:1:248:1893:25c8:1946" and seen[0].headers["host"] == "example.com"


@pytest.mark.parametrize("address", [
    "127.0.0.1", "127.1.2.3", "::1", "10.0.0.1", "172.16.5.5", "192.168.1.1", "169.254.169.254", "100.64.0.1",
    "0.0.0.0", "::", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "fc00::1", "fd12::1", "fe80::1", "fe80::1%en0",
    "224.0.0.1", "ff02::1", "240.0.0.1", "192.0.2.1", "198.18.0.1",
])
async def test_addresses_that_are_not_public_are_never_fetched(address):
    calls = []
    with pytest.raises(ToolError, match="not a public website"):
        await fetch("https://sneaky.test/", lambda r: (calls.append(r), html())[1], {"sneaky.test": [address]})
    assert calls == []  # nothing was even sent


async def test_one_private_answer_among_public_ones_is_enough_to_refuse():
    with pytest.raises(ToolError, match="not a public website"):
        await fetch("https://mixed.test/", table={"mixed.test": [PUBLIC, "10.0.0.5"]})


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/meta-data/", "http://localhost/",
    "http://0x7f.1/", "http://2130706433/", "http://10.0.0.1/admin",
])
async def test_address_literals_and_localhost_are_refused(url):
    table = {"localhost": ["127.0.0.1"], "0x7f.1": ["127.0.0.1"], "2130706433": ["127.0.0.1"]}
    with pytest.raises(ToolError):
        await fetch(url, table=table)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)", "data:text/html,hi", "//example.com/x",
    "example.com/x", "https://user:pass@example.com/", "https://user@example.com/", "", "   ",
])
async def test_only_plain_http_and_https_urls_are_fetched(url):
    with pytest.raises(ToolError):
        await fetch(url)


@pytest.mark.parametrize("url", ["http://example.com:8080/", "https://example.com:22/", "https://example.com:444/"])
async def test_only_the_standard_web_ports_are_fetched(url):
    with pytest.raises(ToolError, match="80 and 443"):
        await fetch(url)


async def test_an_invalid_port_and_an_overlong_url_are_refused():
    with pytest.raises(ToolError, match="port"):
        await fetch("https://example.com:99999/")
    with pytest.raises(ToolError):
        await fetch("https://example.com/" + "a" * 2000)


async def test_an_unknown_name_is_a_clear_error():
    with pytest.raises(ToolError, match="could not be found"):
        await fetch("https://nope.invalid/")


async def test_redirects_are_followed_and_each_hop_is_checked():
    def handler(request):
        if request.headers["host"] == "example.com":
            return httpx.Response(302, headers={"location": "https://other.example/final"})
        return html()

    result = await fetch("https://example.com/start", handler)
    assert result.display["url"] == "https://other.example/final"  # the page we actually read


async def test_relative_redirects_resolve_against_the_page():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        assert request.url.path == "/new"
        return html()

    assert (await fetch("https://example.com/old", handler)).display["url"] == "https://example.com/new"


@pytest.mark.parametrize("target, table", [
    ("http://169.254.169.254/latest/meta-data/", {}),
    ("http://127.0.0.1:80/", {}),
    ("https://internal.test/", {"internal.test": ["10.1.2.3"]}),
    ("file:///etc/passwd", {}),
])
async def test_a_redirect_into_a_private_place_is_refused(target, table):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": target})

    with pytest.raises(ToolError):
        await fetch("https://example.com/", handler, table)
    assert len(calls) == 1  # the first hop only: the redirect target was never requested


async def test_a_redirect_loop_stops():
    handler = lambda request: httpx.Response(302, headers={"location": "https://example.com/again"})  # noqa: E731
    with pytest.raises(ToolError, match="too many times"):
        await fetch("https://example.com/", handler)


@pytest.mark.parametrize("status, message", [(404, "HTTP 404"), (500, "HTTP 500"), (403, "HTTP 403")])
async def test_http_errors_are_reported(status, message):
    with pytest.raises(ToolError, match=message):
        await fetch("https://example.com/", lambda r: html(b"nope", status))


@pytest.mark.parametrize("ctype", ["image/png", "application/pdf", "application/octet-stream", "video/mp4", ""])
async def test_only_text_pages_are_read(ctype):
    with pytest.raises(ToolError, match="not a text page"):
        await fetch("https://example.com/", lambda r: httpx.Response(200, content=b"\x00\x01", headers={
            **({"content-type": ctype} if ctype else {})}))


@pytest.mark.parametrize("ctype, body", [
    ("text/plain", b"just text"), ("application/json", b'{"a": 1}'), ("text/markdown", b"# Title"),
    ("application/xml", b"<a>x</a>"),
])
async def test_plain_text_and_data_are_returned_as_they_are(ctype, body):
    result = await fetch("https://example.com/", lambda r: html(body, ctype=ctype))
    assert result.output.endswith(body.decode()) and result.display["title"] == ""


async def test_the_declared_charset_is_used():
    result = await fetch("https://example.com/", lambda r: html("<p>café</p>".encode("latin-1"),
                                                                ctype="text/html; charset=iso-8859-1"))
    assert "café" in result.output


async def test_long_pages_are_cut_and_say_so():
    body = b"<p>" + b"word " * 10_000 + b"</p>"
    result = await fetch("https://example.com/", lambda r: html(body))
    assert result.display["characters"] == tools.FETCH_CHARS and result.display["truncated"] is True
    assert "the rest was left out" in result.output


async def test_huge_downloads_stop_at_the_byte_cap():
    chunks = [b"<p>" + b"x" * 100_000 + b"</p>"] * 50  # 5 MB, never fully read

    async def stream():
        for c in chunks:
            yield c

    result = await fetch("https://example.com/", lambda r: httpx.Response(
        200, content=stream(), headers={"content-type": "text/html"}))
    assert result.display["truncated"] is True


async def test_a_page_with_no_text_says_so():
    result = await fetch("https://example.com/", lambda r: html(b"<html><script>x()</script></html>"))
    assert "(No readable text.)" in result.output


async def test_network_failures_are_one_clear_error():
    def handler(request):
        raise httpx.ConnectError("boom: /secret/path")

    with pytest.raises(ToolError, match="could not be reached") as e:
        await fetch("https://example.com/", handler)
    assert "secret" not in str(e.value)


async def test_a_slow_server_times_out(monkeypatch):
    import asyncio

    monkeypatch.setattr(tools, "FETCH_SECONDS", 0.2)

    async def handler(request):
        await asyncio.sleep(5)
        return html()

    with pytest.raises(ToolError, match="could not be reached"):
        await fetch("https://example.com/", handler)


async def test_malformed_html_does_not_hang_or_crash():
    for body in (b"<p>unclosed <b>bold", b"<<<>>>", b"<form><p>x", b"<title>t", b"\xff\xfe\x00"):
        await fetch("https://example.com/", lambda r, b=body: html(b))
