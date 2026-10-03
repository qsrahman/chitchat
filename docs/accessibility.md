# Accessibility

## The bar
`tests/ui/test_a11y_ui.py` runs [axe-core](https://github.com/dequelabs/axe-core) (vendored for tests only in `tests/ui/assets/`, tracked in `scripts/vendor.toml`) over every state of the page, in the light and the dark theme, and on a phone: the home screen, a conversation with every kind of content (headings, links, lists, a table, a quote, code with every token type, math, reasoning, tool calls, notes, an error), content wider than the column, the sidebar with and without search results, both menus, attachments ready and failed, the drop overlay, each dialog, a reply mid-stream, thinking effort and search switched on, and right-to-left text. **Zero violations** is the bar: a new one means a change made something less accessible. The tests wait for entrance fades to finish first, because contrast is read from the colors on screen.

The audit's own sensitivity is tested (`test_the_audit_does_notice...`): taking away a focus stop makes it fail. The test page injects axe with the Content-Security-Policy bypassed for that context only; the policy itself is tested in `test_csp_ui.py`.

## What the first audit found, and the fixes
No contrast problems anywhere except one, and three structural ones:
- **Syntax-highlight string color** was 4.46:1 in light mode (needs 4.5:1); darkened to `#177043` (5.4:1). The first sample had no string in it and passed; the scenario now has every token type, and putting the old color back fails the audit.
- **No level-one heading** on the home screen: the greeting was an `h2` and the real `h1` (the chat title) is hidden there. The greeting is the `h1` now; there is exactly one visible `h1` at a time (tested).
- **The menus and the drop overlay sat outside any landmark**: moved inside `<main>` (they render in the top layer, so layout is unchanged).
- **Scrolling regions a keyboard could not reach:** a formula, a code block, a table or a long reasoning block wider or taller than its box scrolls, and a keyboard can only scroll what it can focus. They now have `tabindex="0"` (set in `markdown.js` and `messages.js`), and a test focuses each one and scrolls it with the arrow keys. axe only reports this when the content actually overflows, so a scenario with overflowing content is part of the audit.

## What is already in place
Native `<dialog>` (focus trapped, Escape closes, focus returns), the Popover API for menus, real `<button>`s and labels on every control, visible focus rings, a skip-free single column, `lang="en"`, a page title, text sizes in `rem`, reduced motion respected, 44px touch targets on touch screens, `dir="auto"` for right-to-left text, and live status for tool calls (`aria-busy` on a running call). The sidebar's open state is `aria-expanded`.

## What automated checks can't judge (not done)
axe finds roughly a third of accessibility problems. These need a person with the tools:
- **A screen reader pass** (VoiceOver, NVDA): above all how a streaming reply is announced. The message area is `role="log"` and the reply is re-rendered as it streams, so some readers may repeat text. `aria-busy` is set on the thread while streaming; whether that is enough is not verified.
- **Reading order and focus order** in each state.
- **Zoom to 200% and 400%**, and very narrow windows (reflow).
- **Windows high-contrast / forced-colors mode.**
- Whether the wording of labels and notes is clear to someone who cannot see the screen.
