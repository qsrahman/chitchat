"""One command that says whether the project is in a state to commit:

    uv run python scripts/check.py

It runs the Python lint (ruff), the type checker (pyright, on `app/`), the JavaScript lint (eslint, when Node is
installed: a missing import in the UI only shows when that line runs, and nothing else here would find it), tsc
(the UI's types, from JSDoc) and the whole test suite, in parallel. Stops at the first step that fails. The network
is not needed once eslint and tsc have been fetched once. See docs/development.md.
"""
import shutil
import subprocess
import sys
import time

STEPS = [
    ("ruff", ["uv", "run", "ruff", "check", "."]),
    ("pyright", ["uv", "run", "pyright"]),
    ("eslint", ["npx", "--yes", "eslint@10", "app/static"]),
    ("tsc", ["npx", "--yes", "-p", "typescript@7", "tsc", "-p", "jsconfig.json"]),
    ("tests", ["uv", "run", "pytest", "-q"]),
]


def main() -> int:
    started = time.monotonic()
    for name, command in STEPS:
        if command[0] == "npx" and not shutil.which("npx"):
            print(f"-- {name}: skipped (Node is not installed)")
            continue
        print(f"-- {name}", flush=True)
        step = time.monotonic()
        if subprocess.run(command).returncode:
            print(f"-- {name} FAILED")
            return 1
        print(f"-- {name} ok ({time.monotonic() - step:.0f}s)")
    print(f"all checks passed ({time.monotonic() - started:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
