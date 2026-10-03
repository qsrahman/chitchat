"""The UI is ES modules with no build step, so nothing checks imports until a browser loads the page. This does:
every imported name is exported by the module it comes from, every module is used, and there are no import cycles
(a cycle only works while nothing at the top level uses the other side, which is easy to break by accident)."""
import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "app" / "static"
MODULES = {p.stem: p.read_text() for p in STATIC.glob("*.js")}
IMPORT = re.compile(r'import\s*(?:\{([^}]*)\}\s*from\s*)?"\./([\w-]+)\.js";')
EXPORT = re.compile(r"^export\s+(?:async\s+)?(?:const|let|function|class)\s+([\w$]+)", re.M)


def imports(source):
    return [(sorted(n.strip() for n in names.split(",") if n.strip()) if names else [], module)
            for names, module in IMPORT.findall(source)]


def test_every_imported_name_is_exported_by_its_module():
    for name, source in MODULES.items():
        for names, module in imports(source):
            assert module in MODULES, f"{name}.js imports ./{module}.js, which does not exist"
            exported = set(EXPORT.findall(MODULES[module]))
            for n in names:
                assert n in exported, f"{name}.js imports {n} from ./{module}.js, which does not export it"


def test_there_are_no_import_cycles():
    graph = {name: {m for _, m in imports(src)} for name, src in MODULES.items()}
    done, visiting = set(), []

    def visit(name):
        assert name not in visiting, "import cycle: " + " -> ".join([*visiting[visiting.index(name):], name])
        if name in done:
            return
        visiting.append(name)
        for dep in graph[name]:
            visit(dep)
        visiting.pop()
        done.add(name)

    for name in graph:
        visit(name)


def test_every_module_is_reachable_from_the_entry_point():
    graph = {name: {m for _, m in imports(src)} for name, src in MODULES.items()}
    seen, todo = set(), ["app"]
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo.extend(graph[name])
    assert seen == set(MODULES), f"not loaded by app.js: {sorted(set(MODULES) - seen)}"


def test_the_page_loads_only_the_entry_point_as_a_module():
    html = (STATIC / "index.html").read_text()
    assert re.findall(r'<script type="module" src="([^"]+)"', html) == ["app.js"]


def test_an_imported_name_is_used_in_the_importing_module():
    for name, source in MODULES.items():
        body = IMPORT.sub("", source)
        for names, _module in imports(source):
            for n in names:
                # not part of a longer name, and not a property of something else (a.n), but a spread (...n) counts
                used = re.search(rf"(?<![\w$])(?<![^.]\.){re.escape(n)}(?![\w$])", body)
                assert used, f"{name}.js imports {n} but never uses it"
