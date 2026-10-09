"""The Appearance setting (Settings, General): System follows the operating system, Light and Dark override it, and
the choice is remembered."""
from playwright.sync_api import expect

from tests.ui.test_chat_ui import open_app, open_prefs

LIGHT, DARK = "rgb(236, 235, 229)", "rgb(19, 20, 23)"  # the page background (--bg, the desk behind the sheet)


def appearance(page):
    return page.get_by_label("Appearance")


def test_it_starts_on_system_and_light_and_dark_override_it(page, app_url):
    page.emulate_media(color_scheme="dark")
    open_app(page, app_url)
    open_prefs(page)
    expect(appearance(page)).to_have_value("system")
    expect(page.locator("body")).to_have_css("background-color", DARK)
    appearance(page).select_option("light")
    expect(page.locator("body")).to_have_css("background-color", LIGHT)  # against the system's dark
    appearance(page).select_option("dark")
    expect(page.locator("body")).to_have_css("background-color", DARK)
    page.emulate_media(color_scheme="light")
    expect(page.locator("body")).to_have_css("background-color", DARK)  # a choice stays when the system changes
    appearance(page).select_option("system")
    expect(page.locator("body")).to_have_css("background-color", LIGHT)  # and system follows it again


def test_the_choice_survives_a_reload_and_system_forgets_it(page, app_url):
    page.emulate_media(color_scheme="light")
    open_app(page, app_url)
    open_prefs(page)
    appearance(page).select_option("dark")
    page.reload()
    expect(page.locator("body")).to_have_css("background-color", DARK)
    open_prefs(page)
    expect(appearance(page)).to_have_value("dark")  # the setting shows what is in force
    appearance(page).select_option("system")
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
    open_prefs(page)
    appearance(page).select_option("dark")
    assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == "dark"
    shadow = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--shadow-color').trim()")
    assert shadow == "220 20% 2%"
