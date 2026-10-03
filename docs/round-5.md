# Round 5

Three changes: a sweep for flaky tests, a render time budget, and branching. Each is its own commit.

## 1. Flaky-test sweep
**Method.** The suite ran 12 times in a row with six CPU-burning processes competing for the machine (`yes > /dev/null`), then again after each round of fixes (10, 14, 18 and 20 runs). Every failure was read, not retried. Normal runs of 844 tests had been green for weeks; under load 3 of the first 12 runs failed, and the failures were different tests, all UI tests, all with the same shape: the test acted before the page or the server was ready.

**What was wrong, and the fix for each:**
- **The page was "open" before its scripts had run.** `open_app` waited for the heading, which is plain HTML. The module scripts are deferred, so under load a `fill` or an Enter could land on a page with no handlers yet (the message was never sent, the search never ran). `app.js` now sets `data-ready` on `<body>` once everything is attached, and the test `page` fixture waits for it after every `goto` and `reload` (also `open_app` and the axe pages). This was the root of several failures (`test_stop_button_keeps_partial_reply`, `test_no_match_says_so`).
- **"The reply is there" was not "the reply is saved".** 44 places waited for `Reply #N` to appear and then navigated, searched or reloaded; the text shows before the server has saved the message, so a quick enough next step aborted the stream (Stop semantics) or searched before the chat existed. Each now also waits for the message's action buttons, which appear when the reply is saved. Three search tests waited for the assistant's placeholder, which exists before the request does; they wait for the title or the saved reply now.
- **A disabled button.** The web search toggle is disabled until the page knows which tools exist; one test focused and pressed it too early.
- **Enter went to a link.** After clicking a chat in the sidebar the message box is focused last; the draft test pressed Enter once its text was there but before the focus, so Enter activated the link.
- **Five `sleep(0.1)`s** in the API tests (fixed in round 4: the fake model now says when it is hanging).

**Result:** 20 runs in a row under the same load, 844 passed each time. That is not proof there are none left: the rate before was about 1 failed run in 4, so 20 clean runs make a flake at that rate very unlikely, but a rarer one could still be there. The sweep script is not in the repository (a shell loop with `yes` burners); the method above is all it is.
