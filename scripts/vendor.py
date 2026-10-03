"""Check and update the third-party files in app/static/vendor/ against the official npm packages.

    uv run python scripts/vendor.py check              # are they unmodified? is there a newer release?
    uv run python scripts/vendor.py update NAME [VER]  # replace one library (latest unless VER is given)

What was copied from where, and the version, is in scripts/vendor.toml. Needs the network (the npm registry), so it
is run by hand, not by the tests. See docs/vendor.md.
"""
import argparse
import fnmatch
import io
import re
import sys
import tarfile
import tomllib
from pathlib import Path
from urllib.parse import quote

import httpx

MANIFEST = Path(__file__).with_name("vendor.toml")
VENDOR = Path(__file__).parent.parent / "app" / "static" / "vendor"
REGISTRY = "https://registry.npmjs.org"
IGNORED = {".DS_Store"}


def _woff2_only(css: str) -> str:
    """KaTeX's stylesheet lists woff2, woff and ttf for every font. Every current browser takes woff2, so the other
    two are dropped from the stylesheet (and not shipped), which is the only change made to any vendored file."""
    return re.sub(r',url\(fonts/[\w-]+\.woff\) format\("woff"\),url\(fonts/[\w-]+\.ttf\) format\("truetype"\)', "", css)


TRANSFORMS = {"woff2-only": lambda data: _woff2_only(data.decode()).encode()}


def load_manifest(path: Path = MANIFEST) -> dict:
    return tomllib.loads(path.read_text())


def _package_url(package: str, version: str) -> str:
    return f"{REGISTRY}/{quote(package, safe='@')}/{version}"


def latest_version(http: httpx.Client, package: str) -> str:
    return http.get(_package_url(package, "latest")).raise_for_status().json()["version"]


def package_files(http: httpx.Client, package: str, version: str) -> dict[str, bytes]:
    """Every file of an npm package version, by its path inside the package. Read in memory, never extracted."""
    meta = http.get(_package_url(package, version)).raise_for_status().json()
    tarball = http.get(meta["dist"]["tarball"]).raise_for_status().content
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        return {m.name.split("/", 1)[1]: tar.extractfile(m).read() for m in tar if m.isfile()}


def expected(entry: dict, files: dict[str, bytes]) -> dict[str, bytes]:
    """The vendored files (path under vendor/ -> bytes) that this package version should give."""
    out = {}
    for target, source in entry["files"].items():
        if target.endswith("/"):  # a set of files: a glob inside the package
            matched = {p: d for p, d in files.items() if fnmatch.fnmatchcase(p, source)}
            if not matched:
                raise ValueError(f"nothing in {entry['package']} matches {source}")
            out.update({target + p.rsplit("/", 1)[1]: d for p, d in matched.items()})
        elif source in files:
            out[target] = files[source]
        else:
            raise ValueError(f"{entry['package']} has no {source}")
    for target, name in entry.get("transforms", {}).items():
        out[target] = TRANSFORMS[name](out[target])
    return out


def check(manifest: dict, http: httpx.Client, vendor: Path = VENDOR, out=print) -> int:
    """Print a line per library. Returns 1 if a file differs from the official one, is missing, or isn't in the
    manifest (that needs a look), 0 otherwise; a newer release is only information."""
    bad, known = 0, set()
    for name, entry in manifest.items():
        want = expected(entry, package_files(http, entry["package"], entry["version"]))
        known |= set(want)
        differs = [t for t, data in want.items() if not (vendor / t).is_file() or (vendor / t).read_bytes() != data]
        latest = latest_version(http, entry["package"])
        files = f"{len(want)} files match the official package" if not differs else f"CHANGED: {', '.join(differs)}"
        news = "up to date" if latest == entry["version"] else f"newer release: {latest}"
        out(f"{name:12} {entry['version']:9} {files}; {news}")
        bad += bool(differs)
    unknown = sorted(p.relative_to(vendor).as_posix() for p in vendor.rglob("*")
                     if p.is_file() and p.name not in IGNORED and p.relative_to(vendor).as_posix() not in known)
    if unknown:
        out(f"NOT IN THE MANIFEST: {', '.join(unknown)}")
    return int(bool(bad or unknown))


def update(manifest_path: Path, name: str, version: str | None, http: httpx.Client, vendor: Path = VENDOR,
           out=print) -> None:
    manifest = load_manifest(manifest_path)
    if name not in manifest:
        raise SystemExit(f"unknown library {name!r}; the manifest has: {', '.join(manifest)}")
    entry = manifest[name]
    version = version or latest_version(http, entry["package"])
    old = expected(entry, package_files(http, entry["package"], entry["version"]))
    new = expected(entry, package_files(http, entry["package"], version))
    for target, data in new.items():
        path = (vendor / target).resolve()
        if not path.is_relative_to(vendor.resolve()):
            raise SystemExit(f"refusing to write outside the vendor directory: {target}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    lines = manifest_path.read_text().split("\n")
    section = lines.index(f"[{name}]")
    line = next(i for i in range(section, len(lines)) if lines[i].startswith("version = "))
    lines[line] = f'version = "{version}"'
    manifest_path.write_text("\n".join(lines))
    out(f"{name}: {entry['version']} -> {version}, {len(new)} files written")
    if gone := sorted(set(old) - set(new)):
        out(f"no longer in the package, delete by hand if unused: {', '.join(gone)}")
    out("Now read the release notes, run the tests (uv run pytest), and look at the page.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    up = commands.add_parser("update")
    up.add_argument("name")
    up.add_argument("version", nargs="?")
    args = parser.parse_args(argv)
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        if args.command == "check":
            return check(load_manifest(), http)
        update(MANIFEST, args.name, args.version, http)
        return 0


if __name__ == "__main__":
    sys.exit(main())
