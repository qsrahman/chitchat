import pytest

from app.main import SECURITY_HEADERS
from tests.helpers import PNG, new_conv, parse_sse, upload


@pytest.mark.parametrize("path", ["/", "/app.js", "/style.css", "/healthz", "/api/conversations", "/api/models",
                                  "/api/tools", "/nope"])
async def test_every_response_carries_the_security_headers(client, path):
    r = await client.get(path)
    for name, value in SECURITY_HEADERS.items():
        assert r.headers[name] == value, (path, name)


def test_the_policy_allows_only_what_the_app_needs():
    csp = SECURITY_HEADERS["Content-Security-Policy"]
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";") if d.strip())
    assert directives["script-src"] == "'self'"  # no inline script, no eval, no other origin
    assert directives["default-src"] == "'self'"
    assert directives["object-src"] == "'none'" and directives["frame-ancestors"] == "'none'"
    assert directives["base-uri"] == "'none'" and directives["connect-src"] == "'self'"
    assert "'unsafe-inline'" in directives["style-src"]  # KaTeX writes style attributes
    assert "https:" not in csp and "*" not in csp  # nothing from the open web


async def test_the_page_has_no_inline_script_that_the_policy_would_block(client):
    html = (await client.get("/")).text
    import re

    for tag in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in tag, tag
    assert not re.search(r"\son\w+\s*=", html)  # no inline event handlers either


async def test_an_attachment_keeps_its_own_stricter_policy(client):
    aid = (await upload(client, "pic.png", PNG)).json()["id"]
    r = await client.get(f"/api/attachments/{aid}")
    assert r.headers["content-security-policy"] == "sandbox"  # not replaced by the page policy
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


async def test_streaming_replies_have_the_headers_and_still_stream(client):
    cid = await new_conv(client)
    async with client.stream("POST", f"/api/conversations/{cid}/chat", json={"content": "hi"}) as r:
        assert r.status_code == 200
        assert r.headers["content-security-policy"] == SECURITY_HEADERS["Content-Security-Policy"]
        assert r.headers["content-type"].startswith("text/event-stream")
        body = (await r.aread()).decode()
    assert [e["type"] for e in parse_sse(body)][-2:] == ["done", "title"]


async def test_errors_from_the_api_have_the_headers_too(client):
    r = await client.get("/api/conversations/missing")
    assert r.status_code == 404 and r.headers["x-frame-options"] == "DENY"
    r = await client.post("/api/conversations/missing/chat", json={"content": "x"})
    assert r.status_code == 404 and "content-security-policy" in r.headers


async def test_the_pages_files_are_revalidated_not_reused_blindly(client):
    first = await client.get("/chat.js")
    assert first.headers["cache-control"] == "no-cache" and first.headers["etag"]
    again = await client.get("/chat.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304  # nothing is sent again when it has not changed
    assert (await client.get("/")).headers["cache-control"] == "no-cache"


async def test_the_api_is_left_to_say_for_itself(client):
    assert "cache-control" not in (await client.get("/api/models")).headers
