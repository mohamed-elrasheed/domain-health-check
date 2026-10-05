"""Loading the home page in a real browser, so we can photograph it while it is open.

The page is loaded once, at phone width, exactly as a visitor's browser would load it (with its images,
styles and scripts), through the same browser path the report uses (domain_health_check/browser.py).
Everything after that works on the page already in memory: the phone screenshot, a close-up of the fault we
found, and a 1280-wide screenshot taken by widening the window, which re-lays the page out without requesting
it again.

A screenshot of a business's own live site printing raw template code ends an argument no
paragraph can. Screenshots go under sweep-output/<lead-id>/, which is gitignored, and never into either
repository's history except the private previews repository.

Playwright is optional (pip install -e ".[sweep]", then playwright install chromium).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..browser import DESKTOP, ON_SCREEN, PHONE, BrowserUnavailable, NavigationFailed, Session, displayed_text
from .load import LoadFailure, check_status
from .models import Fault, Page

__all__ = ["Browser", "BrowserUnavailable", "Opened", "ON_SCREEN"]


class Opened:
    """A loaded page, still open, so it can be photographed after it has been read."""

    def __init__(self, tab, page: Page):
        self._tab = tab
        self.page = page

    def on_screen(self, text: str) -> bool:
        """Whether a visitor can see text, at phone width or, failing that, at desktop width."""
        try:
            if self._tab.evaluate(ON_SCREEN, text):
                return True
            self._tab.set_viewport_size(DESKTOP)
            self._tab.wait_for_timeout(300)
            return bool(self._tab.evaluate(ON_SCREEN, text))
        except Exception:  # a page we cannot measure has not shown us anything
            return False
        finally:
            self._tab.set_viewport_size(PHONE)
            self._tab.wait_for_timeout(300)

    def capture(self, folder: Path, fault: Fault | None) -> list[str]:
        """phone.png (390 by 844, as first seen), evidence.png (the fault in view, at phone width, when we
        can find it on screen) and desktop.png (1280 wide, the whole page). Returns the files written."""
        folder.mkdir(parents=True, exist_ok=True)
        written: list[str] = []

        def shot(name: str, **options) -> None:
            try:
                self._tab.screenshot(path=str(folder / name), **options)
                written.append(name)
            except Exception:  # a page that fights screenshots costs us a picture, not the verdict
                pass

        self._tab.evaluate("window.scrollTo(0, 0)")
        shot("phone.png")
        if fault and fault.on_screen:
            try:
                if self._tab.evaluate(ON_SCREEN, fault.quote):  # scrolls to the copy a visitor can see
                    shot("evidence.png")
            except Exception:  # the phone shot still stands
                pass
        elif fault and fault.selector:
            try:
                self._tab.locator(fault.selector).first.scroll_into_view_if_needed(timeout=3000)
                shot("evidence.png")
            except Exception:  # not on screen; the phone shot still stands
                pass
        self._tab.set_viewport_size(DESKTOP)
        self._tab.wait_for_timeout(800)
        self._tab.evaluate("window.scrollTo(0, 0)")
        shot("desktop.png", full_page=True, scale="css")  # one pixel per CSS pixel; a long page at 2x is huge
        return written


class Browser:
    def __enter__(self) -> Browser:
        self._session = Session(hint=", or pass --no-browser to sweep without screenshots").__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self._session.__exit__(*exc)

    @contextmanager
    def open(self, url: str) -> Iterator[Opened]:
        """Navigate once to url at phone width. Raises LoadFailure like load.fetch_page."""
        try:
            with self._session.tab(url) as (tab, response):
                check_status(response.status, response.url, response.headers.get("retry-after", ""))
                chain = []
                hop = response.request.redirected_from
                while hop is not None:
                    answer = hop.response()
                    chain.insert(0, (hop.url, answer.status if answer else 0))
                    hop = hop.redirected_from
                page = Page(url, response.url, response.status, chain, tab.content(), rendered=True,
                            visible_text=displayed_text(tab))
                yield Opened(tab, page)
        except NavigationFailed as failure:
            raise LoadFailure(failure.kind, failure.message) from None
