"""Shared test helpers, imported by both the API tests and the browser tests' server."""
import base64
import json


def parse_sse(text):
    return [json.loads(f[6:]) for f in text.split("\n\n") if f.startswith("data: ")]


async def new_conv(client):
    return (await client.post("/api/conversations")).json()["id"]


# ---- file fixtures for attachment tests ----
# A real 1x1 PNG (decodes, so browsers can show it) ...
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)
# ... and bare magic numbers for the types the server only sniffs.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 300
GIF = b"GIF89a" + b"\x00" * 300
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 300


def make_pdf(text: str | None) -> bytes:
    """A valid one-page PDF showing `text` (None = a page with no text, like a scan)."""
    stream = f"BT /F1 18 Tf 10 50 Td ({text}) Tj ET".encode() if text else b""
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n%s\nendstream" % (len(stream), stream),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    return out + b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref)


async def upload(client, name, data):
    return await client.post("/api/attachments", files={"file": (name, data)})
