# Plugins for the whole test suite (a top-level conftest is where pytest allows this): the rerun of a browser test that
# failed because the host's network changed (tests/network_changed.py), and pytest's own `pytester`, which tests that.
pytest_plugins = ["tests.network_changed", "pytester"]
