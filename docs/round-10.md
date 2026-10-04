# Round 10

Two loose ends from the defaults for new chats (`docs/settings-dialog.md`), in one commit.

## The defaults are in the backup
Export (the JSON, and the zip with files) now carries `defaults`: `{model, reasoning_effort, tools}`. Import takes them only if none are chosen on this machine, like the custom instructions (a restore never overwrites): tools this version doesn't have are dropped, and a bad effort, an empty model or a value that isn't an object is ignored, with the import still succeeding. The import answer has a new `defaults` (true when taken), the dialog says "defaults for new chats added", and the page takes them at once instead of at the next reload: the Settings controls, the header's "Default (...)" and the tools of a new chat on screen. Before, restoring on a new machine lost them.

Tests: `tests/test_backup_files.py` (the round trip, never overwriting, the odd values, a retired tool) and `tests/ui/test_backup_ui.py` (the message, and the page following without a reload).

## Titles follow the default model on a custom endpoint
With `OPENAI_BASE_URL` set and no `TITLE_MODEL`, titles were written by `OPENAI_MODEL`. Once a different default can be chosen in Settings, that could be a model the endpoint no longer runs. `Settings.title_model_for(main_model)` now takes the default in force (the one chosen in Settings, else `OPENAI_MODEL`); the Server tab shows the same. Not changed: on OpenAI titles still come from a small fixed model whatever the default is, `TITLE_MODEL` still wins, and a chat that picks its own model still gets its title from the default, not from its own model (as before).

Tests: `tests/test_settings.py`, `tests/test_config_api.py`.

## Browser tests and the host's network
The two failing runs in an earlier load sweep were `net::ERR_NETWORK_CHANGED`: the Mac's network changed during the run, and every browser test running then failed with console errors or a page that never became ready. Re-running the sweep would only have shown whether it happens again, so instead those failures are now recognised and the tests run again, and nothing else is. What it does and how it is tested: `docs/development.md`.
