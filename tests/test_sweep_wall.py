"""The wall between sweep (our prospecting) and report (a deliverable, consent only).

sweep must not be able to reach the report path. If anything sweep imports, directly or through another
module, is registry, DNS, TLS, report, PDF, mail or report-fetch code, these tests fail. They work on an
allow-list rather than a deny-list, so a new report module is outside the wall without anyone having to
remember to add it here.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

PACKAGE = Path(__file__).parent.parent / "domain_health_check"

# Everything sweep may reach inside this package: itself, the User-Agent, and the robots.txt parser it
# needs in order to honor robots.txt.
ALLOWED = {"domain_health_check", "domain_health_check.identity", "domain_health_check.robots"}
# Outside libraries sweep has no business importing: DNS lookups, raw TLS and sockets, mail, PDFs.
FORBIDDEN_LIBRARIES = {"dns", "ssl", "socket", "smtplib", "email", "weasyprint", "whois"}


def module_file(name: str) -> Path | None:
    parts = name.split(".")[1:]
    candidate = PACKAGE.joinpath(*parts)
    if candidate.is_dir() and (candidate / "__init__.py").exists():
        return candidate / "__init__.py"
    if candidate.with_suffix(".py").exists():
        return candidate.with_suffix(".py")
    return None


def imports_of(name: str) -> set[str]:
    """Every module name one of our modules imports, anywhere in the file, with relative imports resolved."""
    path = module_file(name)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = ".".join(base[:len(base) - node.level + 1])
                base = f"{base}.{node.module}" if node.module else base
            else:
                base = node.module
            found.add(base)
            for alias in node.names:  # from . import hosts names a module; from .x import Y names a symbol
                if module_file(f"{base}.{alias.name}") and base.startswith("domain_health_check"):
                    found.add(f"{base}.{alias.name}")
    return found


def closure(start: set[str]) -> tuple[set[str], set[str]]:
    """(our modules reachable from start, outside top-level packages they import)."""
    ours, outside, todo = set(), set(), list(start)
    while todo:
        name = todo.pop()
        if name in ours:
            continue
        ours.add(name)
        for imported in imports_of(name):
            if imported.startswith("domain_health_check"):
                if module_file(imported):
                    todo.append(imported)
            else:
                outside.add(imported.split(".")[0])
    return ours, outside


def sweep_modules() -> set[str]:
    """Every prospecting module: sweep, and preview, which writes the proposal pages."""
    return {f"domain_health_check.{package}.{p.stem}" if p.stem != "__init__" else f"domain_health_check.{package}"
            for package in ("sweep", "preview") for p in (PACKAGE / package).glob("*.py")}


def test_sweep_reaches_nothing_outside_the_wall():
    ours, _ = closure(sweep_modules())
    outside_wall = {m for m in ours if m not in ALLOWED and not m.startswith(("domain_health_check.sweep",
                                                                              "domain_health_check.preview"))}
    assert not outside_wall, f"sweep can reach report-path code: {sorted(outside_wall)}"


def test_sweep_imports_no_dns_tls_mail_or_pdf_library():
    _, outside = closure(sweep_modules())
    assert not outside & FORBIDDEN_LIBRARIES, sorted(outside & FORBIDDEN_LIBRARIES)


def test_the_report_path_cannot_reach_sweep():
    ours, _ = closure({"domain_health_check.cli", "domain_health_check.runner"})
    assert not {m for m in ours if m.startswith(("domain_health_check.sweep", "domain_health_check.preview"))}


def test_the_closure_would_catch_a_wiring_mistake():
    """Guard the guard: a sweep module that imported the runner must show up as outside the wall."""
    ours, _ = closure({"domain_health_check.cli"})
    assert "domain_health_check.runner" in ours and "domain_health_check.checks.rdap" in ours
    assert "domain_health_check.mailer" in ours and "domain_health_check.fetcher" in ours


RUN_A_SWEEP = textwrap.dedent("""
    import json, sys
    from pathlib import Path
    import httpx
    from domain_health_check.sweep import cli

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\\nAllow: /\\n")
        return httpx.Response(200, html="<html><head><title>x</title></head><body><p>Hello</p></body></html>")

    out = Path(sys.argv[1])
    leads = out / "leads.json"
    leads.write_text(json.dumps([
        {"id": "a", "n": "A", "cat": "auto", "links": [["Site", "https://www.example.com/"]]},
        {"id": "b", "n": "B", "cat": "food", "links": [["Facebook", "https://www.facebook.com/b"]]},
    ]))
    code = cli.main([str(leads), "-o", str(out / "sweep-output"), "--no-browser"],
                    transport=httpx.MockTransport(handler))
    loaded = sorted(m for m in sys.modules if m.startswith("domain_health_check") or
                    m.split(".")[0] in ("dns", "smtplib", "weasyprint"))
    print(json.dumps({"code": code, "loaded": loaded}))
""")


def test_a_real_sweep_run_never_loads_report_code(tmp_path):
    """The static check reads imports; this one runs a sweep in a fresh interpreter and looks at what was
    actually loaded. A lazy import inside a function would get past neither."""
    result = subprocess.run([sys.executable, "-c", RUN_A_SWEEP, str(tmp_path)], capture_output=True, text=True,
                            timeout=120, cwd=PACKAGE.parent)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["code"] == 0
    outside = [m for m in report["loaded"] if m not in ALLOWED and not m.startswith("domain_health_check.sweep")]
    assert outside == [], f"a sweep run loaded: {outside}"

    written = sorted(p.relative_to(tmp_path / "sweep-output").as_posix()
                     for p in (tmp_path / "sweep-output").rglob("*") if p.is_file())
    assert written == ["a/result.json", "b/result.json", written[-1]] and written[-1].startswith("sweep-")
    assert not any(p.suffix in (".pdf", ".md", ".eml") for p in tmp_path.rglob("*"))

