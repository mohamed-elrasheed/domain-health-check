"""Loading the home page in a real browser, so we can photograph it while it is open.

The page is loaded once, at phone width, exactly as a visitor's browser would load it (with its images,
styles and scripts). Everything after that works on the page already in memory: the phone screenshot, a
close-up of the fault we found, and a 1280-wide screenshot taken by widening the window, which re-lays the
page out without requesting it again.

A screenshot of a business's own live site printing raw template code ends an argument no
paragraph can. Screenshots go under sweep-output/<lead-id>/, which is gitignored, and never into either
repository's history except the private previews repository.

Playwright is optional (pip install -e ".[sweep]", then playwright install chromium).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..identity import USER_AGENT
from .load import TOTAL_SECONDS, LoadFailure, check_status
from .models import Fault, Page

PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 800}
SETTLE_MS = 5000  # after load, how long to wait for late content before reading the page

# Chromium's network errors, by the failure kind load.py records.
NET_ERRORS = {
    "ERR_NAME_NOT_RESOLVED": "nxdomain", "ERR_CERT_": "certificate", "ERR_TIMED_OUT": "timeout",
    "ERR_CONNECTION_": "connection", "ERR_ADDRESS_UNREACHABLE": "connection", "ERR_TOO_MANY_REDIRECTS": "redirects",
    "ERR_SSL_": "certificate",
}


def _displayed_text(tab) -> str:
    """The text the browser actually displays (innerText leaves out anything hidden), at phone width and
    then at desktop width, since a menu collapsed on a phone is shown on a desktop. Widening the window
    re-lays the page out; it does not request it again."""
    read = "document.body ? document.body.innerText : ''"
    phone = tab.evaluate(read)
    tab.set_viewport_size(DESKTOP)
    tab.wait_for_timeout(300)
    desktop = tab.evaluate(read)
    tab.set_viewport_size(PHONE)
    tab.wait_for_timeout(300)
    return f"{phone}\n{desktop}"


# Whether some text is on screen for a visitor: the first element holding it that is visible by CSS, has a
# size, can be scrolled into view, and is the topmost thing at its own centre, so not covered by another
# section, not clipped away and not parked off-canvas. Leaves the window scrolled to it when found.
ON_SCREEN = """
(needle) => {
  const lower = needle.toLowerCase();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (!node.textContent.toLowerCase().includes(lower)) continue;
    const el = node.parentElement;
    if (!el) continue;
    if (el.checkVisibility && !el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
    el.scrollIntoView({block: "center", inline: "center"});
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
    const top = document.elementFromPoint(x, y);
    if (top && (top === el || el.contains(top) || top.contains(el))) return true;
  }
  return false;
}
"""


class BrowserUnavailable(RuntimeError):
    pass


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
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserUnavailable(
                'Playwright is not installed. Run pip install -e ".[sweep]" and then playwright install '
                "chromium, or pass --no-browser to sweep without screenshots.") from None
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch()
        except Exception as exc:
            self._playwright.stop()
            raise BrowserUnavailable(f"Could not start Chromium ({exc}). Run playwright install chromium.") from exc
        probe = self._browser.new_page()
        # The browser's own User-Agent, so sites serve what they serve a visitor, with ours added so anyone
        # reading their logs can see who it was and why.
        self.user_agent = f"{probe.evaluate('navigator.userAgent')} {USER_AGENT}"
        probe.close()
        return self

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._playwright.stop()

    @contextmanager
    def open(self, url: str) -> Iterator[Opened]:
        """Navigate once to url at phone width. Raises LoadFailure like load.fetch_page."""
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        context = self._browser.new_context(
            viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True,
            user_agent=self.user_agent, service_workers="block")
        try:
            tab = context.new_page()
            try:
                response = tab.goto(url, wait_until="load", timeout=TOTAL_SECONDS * 1000)
            except PlaywrightTimeout:
                raise LoadFailure("timeout", f"the page did not finish loading within {TOTAL_SECONDS} seconds") \
                    from None
            except PlaywrightError as exc:
                message = str(exc).splitlines()[0]
                kind = next((k for marker, k in NET_ERRORS.items() if marker in message), "error")
                raise LoadFailure(kind, message) from None
            if response is None:
                raise LoadFailure("error", "the browser got no response")
            check_status(response.status, response.url)
            try:
                tab.wait_for_load_state("networkidle", timeout=SETTLE_MS)
            except PlaywrightTimeout:
                pass  # a page that never goes quiet (chat widgets, analytics) is still loaded
            chain = []
            hop = response.request.redirected_from
            while hop is not None:
                answer = hop.response()
                chain.insert(0, (hop.url, answer.status if answer else 0))
                hop = hop.redirected_from
            page = Page(url, response.url, response.status, chain, tab.content(), rendered=True,
                        visible_text=_displayed_text(tab))
            yield Opened(tab, page)
        finally:
            context.close()
