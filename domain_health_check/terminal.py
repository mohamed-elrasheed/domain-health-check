"""Coloured summary for the terminal, using standard ANSI escape codes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TextIO

from .models import DomainReport, Status

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
COLOR = {Status.PASS: "\033[32m", Status.WARN: "\033[33m", Status.FAIL: "\033[31m"}  # green, yellow, red
NOT_CHECKED = "----"  # same width as PASS, so the columns line up


def _enable_windows_ansi() -> bool:
    """Older Windows consoles need 'virtual terminal processing' switched on to understand ANSI codes."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (AttributeError, OSError):
        return False


def use_color(stream: TextIO, disabled: bool = False) -> bool:
    # NO_COLOR is a common convention: https://no-color.org
    if disabled or os.environ.get("NO_COLOR") or not stream.isatty():
        return False
    return _enable_windows_ansi() if os.name == "nt" else True


def format_summary(report: DomainReport, color: bool, report_path: Path | None = None) -> str:
    def paint(text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if color else text

    width = max(len(r.name) for r in report.results) if report.results else 0
    lines = ["", paint(report.domain, BOLD)]
    for r in report.results:
        label = paint(r.status.value, COLOR[r.status]) if r.ran else paint(NOT_CHECKED, DIM)
        lines.append(f"  {label}  {r.name.ljust(width)}  {r.summary}")

    counts = ", ".join(
        paint(f"{report.count(s)} {s.value.lower()}", COLOR[s]) for s in (Status.PASS, Status.WARN, Status.FAIL)
    )
    if report.not_checked:
        counts += f", {len(report.not_checked)} not checked"
    lines.append(f"  {counts}")
    if report_path:
        lines.append(paint(f"  Report: {report_path}", DIM))
    return "\n".join(lines)
