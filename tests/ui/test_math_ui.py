from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, send

UNSAFE = "\\href{javascript:window.__xss=1}{click me}"  # the last formula in the scripted reply


def tex_sources(page):
    """The TeX behind every rendered formula, from KaTeX's accessible MathML."""
    return page.locator('.msg.assistant .body annotation[encoding="application/x-tex"]').all_text_contents()


def test_formulas_are_typeset_in_every_delimiter_style(page, app_url):
    open_app(page, app_url)
    send(page, "math please")
    body = page.locator(".msg.assistant .body")
    expect(body.locator(".katex").first).to_be_visible()
    safe = ["17\\cdot20 = 340", "E=mc^2", "x^2 + y^2 = z^2"]
    assert tex_sources(page) == [*safe, UNSAFE]
    # \( \) is inline; $$ inline and \[ \] are display math
    expect(body.locator(".katex-display")).to_have_count(2)
    expect(body.locator(".math-block")).to_have_count(1)
    expect(body.locator("p > .katex").first).to_be_visible()


def test_currency_and_code_are_not_treated_as_math(page, app_url):
    open_app(page, app_url)
    send(page, "math please")
    body = page.locator(".msg.assistant .body")
    expect(body).to_contain_text("It costs $5 and $10")
    expect(body.locator(":not(pre) > code")).to_have_text("\\(x\\)")
    expect(body.locator("pre code")).to_have_text("\\(y\\)")
    assert "x" not in tex_sources(page) and "y" not in tex_sources(page)


def test_unsafe_tex_is_inert(page, app_url):
    open_app(page, app_url)
    send(page, "math please")
    body = page.locator(".msg.assistant .body")
    expect(body.locator(".katex").last).to_be_visible()
    expect(body.locator("a[href^=javascript]")).to_have_count(0)  # trust is off: \href does not become a link
    assert page.evaluate("window.__xss") is None


def test_an_unfinished_formula_stays_literal_until_it_closes(page, app_url):
    open_app(page, app_url)
    send(page, "mathstream")
    body = page.locator(".msg.assistant .body")
    expect(body).to_contain_text("a^2")  # mid-formula: no closing delimiter yet
    expect(body.locator(".katex")).to_have_count(0)
    expect(body.locator(".katex")).to_have_count(1)
    assert tex_sources(page) == ["a^2 + b^2"]


def test_math_survives_a_reload(page, app_url):
    open_app(page, app_url)
    send(page, "math please")
    expect(page.locator(".msg.assistant .body .katex").first).to_be_visible()
    page.reload()
    expect(page.locator(".msg.assistant .body .katex").first).to_be_visible()
    assert len(tex_sources(page)) == 4


def test_reasoning_keeps_asterisks_and_underscores_but_still_formats_bold_and_math(page, app_url):
    open_app(page, app_url)
    send(page, "ponder stars")
    details = page.locator(".msg.assistant details.reasoning")
    expect(page.locator(".msg.assistant .body")).to_have_text("The answer is 42.")
    details.locator("summary").click()
    reasoning = details.locator(".reasoning-body")
    expect(reasoning).to_contain_text("So 17*23 = 391 and 17*20 + 17*3 = 391")
    expect(reasoning).to_contain_text("_snake_case_")
    expect(reasoning.locator("em")).to_have_count(0)
    expect(reasoning.locator("strong")).to_have_text("Plan")
    expect(reasoning.locator(".katex")).to_have_count(1)


PRIMES_FORMULAS = ["x", "\\pi(x) \\approx \\frac{x}{\\ln(x)}", "\\pi(x)", "\\ln(x)", "x", "x", "1 / \\ln(x)", "n", "n"]


def test_dollar_delimited_math_in_a_real_reply_is_typeset(page, app_url):
    open_app(page, app_url)
    send(page, "primes please")
    body = page.locator(".msg.assistant .body")
    expect(body.locator(".katex").first).to_be_visible()
    assert tex_sources(page) == PRIMES_FORMULAS
    expect(body.locator(".katex-display")).to_have_count(1)  # the $$ block
    expect(body.locator("em .katex")).to_have_count(3)  # the three formulas inside the italic sentence
    expect(body.locator(".katex-error")).to_have_count(0)


def test_prices_and_escaped_dollars_stay_text_next_to_dollar_math(page, app_url):
    open_app(page, app_url)
    send(page, "primes please")
    body = page.locator(".msg.assistant .body")
    expect(body.locator(".katex").first).to_be_visible()
    expect(body).to_contain_text("will pay $1 million to whoever proves it.")  # \$ is a plain dollar sign
    expect(body).to_contain_text("Tickets cost $5 and $10; budgets are $20,000 and $30,000.")
    assert "\\$" not in body.inner_text()


def test_a_dollar_formula_stays_literal_until_it_closes(page, app_url):
    open_app(page, app_url)
    send(page, "dollarstream")
    body = page.locator(".msg.assistant .body")
    expect(body).to_contain_text("$a^2")
    expect(body.locator(".katex")).to_have_count(0)
    expect(body.locator(".katex")).to_have_count(1)
    assert tex_sources(page) == ["a^2 + b^2"]


def test_dollar_math_survives_a_reload(page, app_url):
    open_app(page, app_url)
    send(page, "primes please")
    expect(page.locator(".msg.assistant .body .katex").first).to_be_visible()
    page.reload()
    expect(page.locator(".msg.assistant .body .katex").first).to_be_visible()
    assert tex_sources(page) == PRIMES_FORMULAS
