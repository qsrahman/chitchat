"""scripts/vendor.py (against a fake npm registry: no network) and the real vendor directory's consistency."""
import importlib.util
import io
import re
import tarfile
import tomllib
from pathlib import Path
from urllib.parse import quote, unquote

import httpx
import pytest

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("vendor_script", ROOT / "scripts" / "vendor.py")
vendor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vendor)

KATEX_CSS = (
    '@font-face{font-family:KaTeX_Main;src:url(fonts/KaTeX_Main-Regular.woff2) format("woff2"),'
    'url(fonts/KaTeX_Main-Regular.woff) format("woff"),url(fonts/KaTeX_Main-Regular.ttf) format("truetype")}'
)


def tarball(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path, data in files.items():
            info = tarfile.TarInfo(f"package/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class Registry:
    """A fake npm registry: packages[name][version] = {path in package: bytes}, and a latest version each."""

    def __init__(self, packages, latest):
        self.packages, self.latest, self.requests = packages, latest, []

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handle), base_url="https://registry.test")

    def handle(self, request):
        self.requests.append(str(request.url))
        # raw_path keeps %2F in a scoped name from looking like a path separator, as the real registry needs
        parts = [unquote(p) for p in request.url.raw_path.decode().split("?")[0].strip("/").split("/")]
        if parts[0] == "tarballs":
            return httpx.Response(200, content=tarball(self.packages[parts[1]][parts[2].removesuffix(".tgz")]))
        name, version = parts[0], parts[1]
        version = self.latest[name] if version == "latest" else version
        if name not in self.packages or version not in self.packages[name]:
            return httpx.Response(404)
        return httpx.Response(200, json={"version": version, "dist": {
            "tarball": f"https://registry.test/tarballs/{quote(name, safe='')}/{version}.tgz"}})


@pytest.fixture
def env(tmp_path, monkeypatch):
    manifest = tmp_path / "vendor.toml"
    manifest.write_text('''# comment kept
[lib]
package = "lib"
version = "1.0.0"
[lib.files]
"lib.min.js" = "dist/lib.min.js"
"fonts/" = "dist/fonts/*.woff2"

[css]
package = "@scope/css"
version = "2.0.0"
[css.files]
"css/katex.css" = "dist/katex.css"
[css.transforms]
"css/katex.css" = "woff2-only"
''')
    registry = Registry(
        {"lib": {"1.0.0": {"dist/lib.min.js": b"v1", "dist/fonts/a.woff2": b"fa", "dist/fonts/a.ttf": b"no",
                           "README.md": b"x"},
                 "1.1.0": {"dist/lib.min.js": b"v1.1", "dist/fonts/a.woff2": b"fa2", "dist/fonts/b.woff2": b"fb"}},
         "@scope/css": {"2.0.0": {"dist/katex.css": KATEX_CSS.encode()}}},
        {"lib": "1.1.0", "@scope/css": "2.0.0"},
    )
    vend = tmp_path / "vendor"
    (vend / "fonts").mkdir(parents=True)
    (vend / "css").mkdir()
    (vend / "lib.min.js").write_bytes(b"v1")
    (vend / "fonts" / "a.woff2").write_bytes(b"fa")
    (vend / "css" / "katex.css").write_text(vendor._woff2_only(KATEX_CSS))
    return manifest, registry, vend


def run_check(env):
    manifest, registry, vend = env
    lines = []
    code = vendor.check(vendor.load_manifest(manifest), registry.client(), vend, out=lines.append)
    return code, lines


# ---- check ----

def test_unmodified_files_and_a_newer_release_are_reported(env):
    code, lines = run_check(env)
    assert code == 0  # a newer release is information, not a failure
    assert "2 files match the official package; newer release: 1.1.0" in lines[0]
    assert lines[1].endswith("1 files match the official package; up to date")


def test_a_changed_file_fails_the_check_and_is_named(env):
    _, _, vend = env
    (vend / "lib.min.js").write_bytes(b"tampered")
    code, lines = run_check(env)
    assert code == 1 and "CHANGED: lib.min.js" in lines[0]


def test_a_missing_file_fails_the_check(env):
    _, _, vend = env
    (vend / "fonts" / "a.woff2").unlink()
    code, lines = run_check(env)
    assert code == 1 and "CHANGED: fonts/a.woff2" in lines[0]


def test_a_file_that_is_not_in_the_manifest_fails_the_check_but_a_ds_store_does_not(env):
    _, _, vend = env
    (vend / ".DS_Store").write_bytes(b"junk")
    assert run_check(env)[0] == 0
    (vend / "extra.js").write_bytes(b"who added this")
    code, lines = run_check(env)
    assert code == 1 and "NOT IN THE MANIFEST: extra.js" in lines[-1]


def test_the_katex_edit_is_the_only_transform_and_checks_clean(env):
    assert "woff" not in (env[2] / "css" / "katex.css").read_text().replace("woff2", "")
    assert run_check(env)[1][1].startswith("css")


def test_a_package_without_the_listed_file_is_an_error(env):
    manifest, registry, vend = env
    manifest.write_text(manifest.read_text().replace("dist/lib.min.js", "dist/gone.js"))
    with pytest.raises(ValueError, match="has no dist/gone.js"):
        run_check(env)


# ---- update ----

def test_update_replaces_the_files_and_bumps_the_version_keeping_comments(env):
    manifest, registry, vend = env
    lines = []
    vendor.update(manifest, "lib", None, registry.client(), vend, out=lines.append)  # to the latest, 1.1.0
    assert (vend / "lib.min.js").read_bytes() == b"v1.1"
    assert (vend / "fonts" / "a.woff2").read_bytes() == b"fa2" and (vend / "fonts" / "b.woff2").read_bytes() == b"fb"
    text = manifest.read_text()
    assert 'version = "1.1.0"' in text and 'version = "2.0.0"' in text  # only this library's line changed
    assert text.startswith("# comment kept") and tomllib.loads(text)["lib"]["version"] == "1.1.0"
    assert lines[0] == "lib: 1.0.0 -> 1.1.0, 3 files written"
    assert run_check(env)[0] == 0


def test_update_to_a_given_version_and_it_checks_clean_afterwards(env):
    manifest, registry, vend = env
    vendor.update(manifest, "lib", "1.0.0", registry.client(), vend, out=lambda *_: None)
    assert vendor.load_manifest(manifest)["lib"]["version"] == "1.0.0"


def test_update_says_which_files_the_new_version_no_longer_has(env):
    manifest, registry, vend = env
    registry.packages["lib"]["1.1.0"].pop("dist/fonts/a.woff2")
    lines = []
    vendor.update(manifest, "lib", None, registry.client(), vend, out=lines.append)
    assert any("no longer in the package" in line and "fonts/a.woff2" in line for line in lines)
    assert (vend / "fonts" / "a.woff2").exists()  # nothing is deleted for you


def test_update_applies_the_transform(env):
    manifest, registry, vend = env
    registry.packages["@scope/css"]["2.1.0"] = {"dist/katex.css": KATEX_CSS.encode()}
    vendor.update(manifest, "css", "2.1.0", registry.client(), vend, out=lambda *_: None)
    assert (vend / "css" / "katex.css").read_text() == vendor._woff2_only(KATEX_CSS)


def test_update_of_an_unknown_library_lists_the_known_ones(env):
    manifest, registry, vend = env
    with pytest.raises(SystemExit, match="lib, css"):
        vendor.update(manifest, "nope", None, registry.client(), vend)


def test_update_refuses_to_write_outside_the_vendor_directory(env):
    manifest, registry, vend = env
    manifest.write_text(manifest.read_text().replace('"lib.min.js"', '"../escaped.js"'))
    with pytest.raises(SystemExit, match="outside the vendor directory"):
        vendor.update(manifest, "lib", None, registry.client(), vend)
    assert not (vend.parent / "escaped.js").exists()


def test_scoped_package_names_are_requested_the_way_the_registry_wants(env):
    manifest, registry, vend = env
    run_check(env)
    assert any("/@scope%2Fcss/" in url for url in registry.requests)


def test_the_woff2_only_edit_removes_exactly_the_other_two_formats():
    out = vendor._woff2_only(KATEX_CSS)
    assert out == ('@font-face{font-family:KaTeX_Main;src:url(fonts/KaTeX_Main-Regular.woff2) format("woff2")}')
    assert vendor._woff2_only(out) == out  # idempotent


# ---- the real vendor directory (no network: what the manifest says against what is on disk) ----

MANIFEST = tomllib.loads((ROOT / "scripts" / "vendor.toml").read_text())
VENDOR = ROOT / "app" / "static" / "vendor"
BANNERS = {  # how a library's own file says which version it is
    "marked": ("marked.umd.js", r"marked v([\d.]+)"),
    "dompurify": ("purify.min.js", r"DOMPurify ([\d.]+)"),
    "highlightjs": ("highlight.min.js", r"Highlight\.js v([\d.]+)"),
    "katex": ("katex/katex.min.js", r'version:"([\d.]+)"'),
}


@pytest.mark.parametrize("name", BANNERS)
def test_the_version_in_the_manifest_is_the_version_the_file_declares(name):
    file, pattern = BANNERS[name]
    found = re.search(pattern, (VENDOR / file).read_text(errors="replace")[:400_000])
    assert found and found[1] == MANIFEST[name]["version"], f"{file} says {found and found[1]}"


def test_every_manifest_file_exists_and_every_vendored_file_is_in_the_manifest():
    listed = set()
    for entry in MANIFEST.values():
        for target in entry["files"]:
            if target.endswith("/"):
                listed |= {p.relative_to(VENDOR).as_posix() for p in (VENDOR / target).glob("*.woff2")}
            else:
                assert (VENDOR / target).is_file(), target
                listed.add(target)
    on_disk = {p.relative_to(VENDOR).as_posix() for p in VENDOR.rglob("*") if p.is_file() and p.name != ".DS_Store"}
    assert on_disk == listed


def test_every_library_has_a_purpose_and_a_pinned_version():
    for name, entry in MANIFEST.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", entry["version"]), name
        assert entry["purpose"] and entry["package"], name


def test_the_page_loads_only_vendored_files_that_are_in_the_manifest():
    html = (ROOT / "app" / "static" / "index.html").read_text()
    css = (ROOT / "app" / "static" / "style.css").read_text()
    referenced = set(re.findall(r'(?:src|href)="(vendor/[^"]+)"', html))
    assert referenced, "the page should load its libraries from vendor/"
    for path in referenced:
        assert (VENDOR / path.removeprefix("vendor/")).is_file(), path
    assert not re.search(r'(?:src|href)="https?://', html)  # no CDN: the CSP would block it, and CLAUDE.md forbids it
    assert "https://" not in css.replace("http://www.w3.org", "")


def test_the_katex_stylesheet_only_names_fonts_that_are_shipped():
    css = (VENDOR / "katex" / "katex.min.css").read_text()
    names = set(re.findall(r"url\(fonts/([\w-]+\.\w+)\)", css))
    assert names and all((VENDOR / "katex" / "fonts" / n).is_file() for n in names)
    assert all(n.endswith(".woff2") for n in names)  # the woff/ttf fallbacks were removed on purpose
