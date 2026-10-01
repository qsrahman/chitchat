async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


async def test_serves_index(client):
    r = await client.get("/")
    assert r.status_code == 200 and "ChitChat" in r.text
