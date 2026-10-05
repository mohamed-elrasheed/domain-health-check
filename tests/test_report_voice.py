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
                                               "runner.py", "pricelist.py"))])
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
