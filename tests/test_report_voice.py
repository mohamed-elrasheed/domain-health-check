"""The report's voice rules, checked against everything it can say rather than one sample report.

REPORT-SPEC and CLAUDE.md: no em dashes, no exclamation marks, no contractions, no promise to run the checks
again. Every string literal in the modules that produce report text is checked, docstrings excepted, so a
finding that only appears on some other site cannot slip through.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parent.parent / "domain_health_check"
# Everything whose strings reach a report, the email or the terminal summary.
OUTPUT = sorted([*PACKAGE.glob("checks/*.py"), *PACKAGE.glob("checks/site/*.py"),
                 *(PACKAGE / name for name in ("layout.py", "report.py", "pdf.py", "mailer.py", "terminal.py",
                                               "runner.py", "pricelist.py", "linkcheck.py",
                                               "platform.py"))])
CONTRACTION = re.compile(r"(?i)n['’]t\b|['’](re|ll|ve|m|d)\b|\b(it|that|there|here|what|who)['’]s\b|\blet['’]s\b(?! encrypt)")
RECHECK = re.compile(r"(?i)(run|check)\w* (these checks |it )?again|at no charge|free re-?check")


def literals(path: Path) -> list[tuple[int, str]]:
    """(line, text) of every string literal that is not a docstring."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)}
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]


@pytest.mark.parametrize("path", OUTPUT, ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_no_contractions_dashes_or_exclamations(path):
    problems = [f"line {line}: {text!r}" for line, text in literals(path)
                if CONTRACTION.search(text) or "—" in text or re.search(r"\w!(\s|$)", text)]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("path", OUTPUT, ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_no_promise_to_check_again(path):
    problems = [f"line {line}: {text!r}" for line, text in literals(path) if RECHECK.search(text)]
    assert not problems, "\n".join(problems)



@pytest.mark.parametrize("path", OUTPUT + [PACKAGE / "external.py"], ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_no_lazy_plurals(path):
    """"1 mail servers" once reached a report; "mail server(s)" is the same fault, half fixed."""
    problems = [f"line {line}: {text!r}" for line, text in literals(path) if re.search(r"\w\(s\)", text)]
    assert not problems, "\n".join(problems)



# A present-tense fault about this site: "your page ... is not / has no / also loads", "this site ... lacks".
FAULT = re.compile(r"(?i)\b(your|this|the) (page|site|home page|website|domain|listing|profile)\b[^.]*"
                   r"\b(is not|isn't|does not|doesn't|has no|lacks|is missing|are missing|also loads|but it)\b")


def explanation_constants():
    """Every *EXPLANATION string in the checks. A check shows its explanation on a pass too."""
    found = []
    for path in sorted((PACKAGE / "checks").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and "EXPLANATION" in t.id
                                                    for t in node.targets):
                try:
                    value = ast.literal_eval(node.value)
                except ValueError:
                    continue
                if isinstance(value, str):
                    found.append((f"{path.name}:{node.lineno}", value))
    return found


@pytest.mark.parametrize("where, text", explanation_constants(), ids=lambda v: v if ":" in str(v) else None)
def test_no_explanation_describes_a_fault_with_this_site(where, text):
    assert not FAULT.search(text), f"{where}: {text}"


def test_the_fault_pattern_catches_the_old_mixed_content_text():
    assert FAULT.search("Your page is served securely, but it also loads some files over an insecure connection.")


def test_no_passing_result_in_a_full_run_describes_a_fault(fake_dns, monkeypatch, mizan_page):
    from datetime import datetime, timezone

    from domain_health_check import fetcher, runner
    from domain_health_check.checks import rdap, tls
    from domain_health_check.config import DomainConfig
    from domain_health_check.models import Status
    monkeypatch.setattr(tls, "fetch_tls_info", lambda d: ({"notAfter": "Jan  1 00:00:00 2027 GMT"}, "TLSv1.3"))
    monkeypatch.setattr(rdap, "fetch_rdap", lambda d: {"events": []})
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: mizan_page)
    report = runner.run_checks(DomainConfig("mizangroupllc.com"), datetime(2026, 10, 6, tzinfo=timezone.utc))
    passing = [r for r in report.results if r.ran and r.status is Status.PASS]
    assert len(passing) > 15
    assert not [(r.name, r.explanation) for r in passing if FAULT.search(r.explanation)]
