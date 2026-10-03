"""The theme button: System follows the operating system, Light and Dark override it, and the choice is remembered."""
import re

from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_sidebar

LIGHT, DARK = "rgb(252, 251, 250)", "rgb(27, 26, 25)"  # the page background (--surface)


def theme_button(page):
    return page.get_by_role("button", name=re.compile("^Theme: "))


def test_it_starts_on_system_and_cycles_system_light_dark(page, app_url):
    page.emulate_media(color_scheme="dark")
    open_app(page, app_url)
    open_sidebar(page)
    expect(theme_button(page)).to_have_text("Theme: System")
    expect(page.locator("body")).to_have_css("background-color", DARK)
    theme_button(page).click()
    expect(theme_button(page)).to_have_text("Theme: Light")
    expect(page.locator("body")).to_have_css("background-color", LIGHT)  # against the system's dark
    theme_button(page).click()
    expect(theme_button(page)).to_have_text("Theme: Dark")
    expect(page.locator("body")).to_have_css("background-color", DARK)
    page.emulate_media(color_scheme="light")
    expect(page.locator("body")).to_have_css("background-color", DARK)  # a choice stays when the system changes
    theme_button(page).click()
    expect(theme_button(page)).to_have_text("Theme: System")
    expect(page.locator("body")).to_have_css("background-color", LIGHT)  # and system follows it again


def test_the_choice_survives_a_reload_and_system_forgets_it(page, app_url):
    page.emulate_media(color_scheme="light")
    open_app(page, app_url)
    open_sidebar(page)
    theme_button(page).click()
    theme_button(page).click()  # Dark
    page.reload()
    open_sidebar(page)
    expect(theme_button(page)).to_have_text("Theme: Dark")
    expect(page.locator("body")).to_have_css("background-color", DARK)
    theme_button(page).click()  # System
    assert page.evaluate("localStorage.getItem('theme')") is None
    assert page.evaluate("document.documentElement.dataset.theme") is None


def test_the_saved_theme_is_set_before_the_page_script_runs(page, app_url):
    """Otherwise the page would paint in the system theme first and flash."""
    page.emulate_media(color_scheme="light")
    page.add_init_script("localStorage.setItem('theme', 'dark')")
    seen = []
    page.expose_function("seen", lambda theme: seen.append(theme))
    page.add_init_script(
        "document.addEventListener('DOMContentLoaded', () => seen(document.documentElement.dataset.theme))")
    open_app(page, app_url)
    assert seen == ["dark"]


def test_a_dark_choice_on_a_light_system_gives_the_dark_color_scheme_and_shadows(page, app_url):
    page.emulate_media(color_scheme="light")
    open_app(page, app_url)
    open_sidebar(page)
    theme_button(page).click()
    theme_button(page).click()
    assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == "dark"
    shadow = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--shadow-color').trim()")
    assert shadow == "30 20% 2%"
