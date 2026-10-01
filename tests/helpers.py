"""Shared test helpers, imported by both the API tests and the browser tests' server."""
import json


def parse_sse(text):
    return [json.loads(f[6:]) for f in text.split("\n\n") if f.startswith("data: ")]


async def new_conv(client):
    return (await client.post("/api/conversations")).json()["id"]