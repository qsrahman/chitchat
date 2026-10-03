"""Docs name files in backticks (`app/tools.py`, `docs/phase-8.md`); a renamed or deleted file must not leave a stale name."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / n for n in ("README.md", "CLAUDE.md", "PLAN.md")] + sorted((ROOT / "docs").glob("*.md"))
TOKEN = re.compile(r"`([^`\s]+)`")
# A file name is a token with an extension we have, in a directory the repo has (or a bare name at the top level).
EXTENSIONS = (".py", ".js", ".mjs", ".css", ".html", ".md", ".toml", ".json", ".sh")
# Placeholders, a library's name, and paths inside npm packages (docs/vendor.md lists those) are not files here.
NOT_FILES = {"phase-N.md", "docs/phase-N.md", "date-title-idprefix.md", "highlight.js", "marked.min.js",
             "dist/katex.min.css", "dist/katex.min.js", "dist/purify.min.js", "lib/marked.umd.js"}
LOCATIONS = ("app/static/vendor/", "app/static/vendor/katex/", "tests/ui/assets/", "", "app/", "app/static/", "docs/", "tests/", "tests/ui/", "scripts/", ".githooks/")


def names(doc):
    for token in TOKEN.findall(doc.read_text()):
        token = token.removesuffix(",").removesuffix(".").split("::")[0].split(":")[0]
        if token not in NOT_FILES and token.endswith(EXTENSIONS) and not any(c in token for c in "*<>{}$=()") and not token.startswith(("http", ".")):
            yield token


@pytest.mark.parametrize("doc", DOCS, ids=lambda d: d.name)
def test_every_file_a_doc_names_exists(doc):
    missing = sorted({n for n in names(doc) if not any((ROOT / loc / n).exists() for loc in LOCATIONS)})
    assert not missing, f"{doc.name} names files that do not exist: {missing}"
