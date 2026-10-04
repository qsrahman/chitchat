"""A host whose network changes in the middle of a run (Wi-Fi, a VPN, sleep) makes Chromium fail requests, even to
127.0.0.1, with net::ERR_NETWORK_CHANGED, and every browser test running at that moment fails with errors that say
nothing about the app (console errors, a page that never became ready, timeouts). A real failure of the app never
looks like that, so these are named for what they are and the test is run again (`--only-rerun NetworkChanged` in
pyproject.toml, from pytest-rerunfailures): nothing else is ever run twice. docs/development.md."""
import pytest

MARK = "ERR_NETWORK_CHANGED"


class NetworkChanged(Exception):
    """The host's network changed while the test was running (Chromium said net::ERR_NETWORK_CHANGED)."""


def seen(errors) -> bool:
    return any(MARK in str(e) for e in errors)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """A test that failed after its page saw the network change failed because of it: say so, and let it be rerun."""
    try:
        return (yield)
    except NetworkChanged:
        raise
    except Exception as e:
        if getattr(item, "network_changed", False) or MARK in str(e):
            raise NetworkChanged(f"the host's network changed during the test ({MARK}); the failure was: {e!r}") from e
        raise
