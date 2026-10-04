"""A browser test that failed because the host's network changed is run again, and nothing else is."""
from pathlib import Path

ROOT = Path(__file__).parent.parent
# The other plugins are left out: a sub-run has nothing to do with the browser, or the event loop.
COMMON = ("-p tests.network_changed --reruns 2 --only-rerun NetworkChanged -n 0 -p no:cacheprovider "
          "-p no:playwright -p no:asyncio -q").split()


def run(pytester, monkeypatch, source):
    pytester.makepyfile(test_it=f"""
import pathlib, pytest

def attempt():
    counter = pathlib.Path("attempts.txt")
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    return n

{source}
""")
    monkeypatch.setenv("PYTHONPATH", str(ROOT))  # so that `tests.network_changed` can be imported
    result = pytester.runpytest_subprocess(*COMMON)
    attempts = int((pytester.path / "attempts.txt").read_text())
    return result, attempts


def reruns(result):
    return result.parseoutcomes().get("rerun", 0)


def bad(result):
    """What went wrong at the end, if anything: {"failed": n} and {"error": n}."""
    return {k: v for k, v in result.parseoutcomes().items() if k in ("failed", "error")}


def test_a_failure_after_the_page_saw_the_network_change_is_run_again(pytester, monkeypatch):
    result, attempts = run(pytester, monkeypatch, """
def test_it(request):
    if attempt() == 1:
        request.node.network_changed = True  # what the page fixture does when the console says so
        assert False, "a timeout, which says nothing about why"
""")
    assert attempts == 2
    assert reruns(result) == 1 and not bad(result)


def test_an_error_that_names_the_network_change_is_run_again(pytester, monkeypatch):
    result, attempts = run(pytester, monkeypatch, """
def test_it():
    if attempt() == 1:
        raise RuntimeError("Page.goto: net::ERR_NETWORK_CHANGED at http://127.0.0.1:8000/")
""")
    assert attempts == 2
    assert reruns(result) == 1 and not bad(result)


def test_a_network_change_found_when_the_test_is_over_is_run_again(pytester, monkeypatch):
    result, attempts = run(pytester, monkeypatch, """
from tests.network_changed import NetworkChanged

@pytest.fixture
def page_like():
    first = attempt() == 1
    yield
    if first:
        raise NetworkChanged("the page's requests failed")  # the page fixture's teardown

def test_it(page_like):
    pass
""")
    assert attempts == 2
    assert reruns(result) == 1 and not bad(result)


def test_any_other_failure_is_not_run_again(pytester, monkeypatch):
    result, attempts = run(pytester, monkeypatch, """
def test_it():
    attempt()
    assert 1 == 2
""")
    assert attempts == 1
    assert reruns(result) == 0 and bad(result) == {"failed": 1}


def test_a_test_that_keeps_failing_is_reported_as_the_network_change_it_was(pytester, monkeypatch):
    result, attempts = run(pytester, monkeypatch, """
def test_it(request):
    attempt()
    request.node.network_changed = True
    assert False, "boom"
""")
    assert attempts == 3  # the first run and two more
    assert reruns(result) == 2 and bad(result) == {"failed": 1}
    result.stdout.fnmatch_lines(["*NetworkChanged: the host's network changed during the test*boom*"])
