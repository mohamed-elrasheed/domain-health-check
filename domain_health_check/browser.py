"""The one way this tool loads a page in a real browser. Both modes use it, and it imports neither.

sweep loads every home page this way so it can photograph it. The report fetches with httpx and comes here
only when the delivered page is an empty shell that scripts fill in. The page is loaded at phone width with the
browser's own User-Agent plus ours, waits for the load event and then for the network to settle, and anything
read afterwards is read from the page already in memory: widening the window re-lays it out without
requesting it again.

What counts as on screen is the same here for both modes: visible by CSS, a box of at least one pixel each
way, and inside the page rather than parked off-canvas. sweep adds one more test for text it quotes (the
element must be the topmost thing at its own centre, so not covered by another section).

Playwright is optional (pip install -e ".[sweep]", then playwright install chromium).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from .identity import USER_AGENT

PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 800}
LOAD_SECONDS = 30
SETTLE_MS = 5000  # after load, how long to wait for late content before reading the page

# Chromium's network errors, as the failure kinds sweep records.
NET_ERRORS = {
    "ERR_NAME_NOT_RESOLVED": "nxdomain", "ERR_CERT_": "certificate", "ERR_TIMED_OUT": "timeout",
    "ERR_CONNECTION_": "connection", "ERR_ADDRESS_UNREACHABLE": "connection", "ERR_TOO_MANY_REDIRECTS": "redirects",
    "ERR_SSL_": "certificate",
}
HIDDEN = "data-dhc-hidden"  # the attribute mark_hidden puts on elements that are not on screen

# Elements whose visibility a finding depends on: headings, images, links, and anything holding text of its own.
# Wrappers are judged by what they hold, never on their own box: a zero-height wrapper around floated or
# absolutely placed children is not hidden, and marking it would hide everything inside.
_JUDGE = """
(el) => {
  if (el.checkVisibility && !el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return false;
  const left = r.left + scrollX, top = r.top + scrollY;
  const width = document.documentElement.scrollWidth, height = document.documentElement.scrollHeight;
  return left + r.width > 0 && top + r.height > 0 && left < width && top < height;
}
"""
_CANDIDATES = """
() => Array.from(document.body ? document.body.querySelectorAll("*") : []).filter(el =>
  /^(H[1-6]|IMG|A)$/.test(el.tagName) ||
  Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim()))
"""
SEEN = "data-dhc-seen"
# Scroll the whole page the way a visitor would, pausing so scroll-triggered reveals and lazy images can run,
# and note every judged element that is on screen at some point. Builders commonly hold sections at opacity 0
# until they scroll into view; judged only at the top of the page, they would all count as hidden. On the last
# pass, every element never seen is marked hidden. Returns how many were marked (0 on the first pass).
MARK_HIDDEN = f"""
async (last) => {{
  const onScreen = {_JUDGE};
  const pause = ms => new Promise(done => setTimeout(done, ms));
  const note = () => ({_CANDIDATES})().forEach(el => {{ if (!el.hasAttribute("{SEEN}") && onScreen(el))
    el.setAttribute("{SEEN}", ""); }});
  const step = Math.max(200, Math.floor(innerHeight * 0.6));
  for (let y = 0; y <= 60000; y += step) {{
    scrollTo(0, y);
    await pause(250);
    note();
    if (y + innerHeight >= document.documentElement.scrollHeight) break;
  }}
  scrollTo(0, 0);
  await pause(250);
  note();
  if (!last) return 0;
  let marked = 0;
  ({_CANDIDATES})().forEach(el => {{
    if (!el.hasAttribute("{SEEN}")) {{ el.setAttribute("{HIDDEN}", ""); marked++; }}
  }});
  document.querySelectorAll("[{SEEN}]").forEach(el => el.removeAttribute("{SEEN}"));
  return marked;
}}
"""

# Whether some text is on screen for a visitor, and not covered: the first element holding it that passes the
# on-screen test above, scrolled into view, and is the topmost thing at its own centre. Leaves the window
# scrolled to it when found.
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


class NavigationFailed(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


def displayed_text(tab) -> str:
    """The text the browser displays (innerText leaves out anything hidden), at phone width and then at desktop
    width, since a menu collapsed on a phone is shown on a desktop."""
    read = "document.body ? document.body.innerText : ''"
    phone = tab.evaluate(read)
    tab.set_viewport_size(DESKTOP)
    tab.wait_for_timeout(300)
    desktop = tab.evaluate(read)
    tab.set_viewport_size(PHONE)
    tab.wait_for_timeout(300)
    return f"{phone}\n{desktop}"


def mark_hidden(tab) -> int:
    """Put data-dhc-hidden on every judged element that is on screen at no point while a visitor scrolls the
    page, at phone width or at desktop width, so its HTML can be read afterwards with what a visitor cannot see
    left out. Returns how many were marked."""
    tab.evaluate(MARK_HIDDEN, False)
    tab.set_viewport_size(DESKTOP)
    tab.wait_for_timeout(300)
    marked = tab.evaluate(MARK_HIDDEN, True)
    tab.set_viewport_size(PHONE)
    tab.wait_for_timeout(300)
    return marked


class Session:
    """One Chromium for a run. hint is what to tell the operator when Playwright is missing."""

    def __init__(self, hint: str = "", offline: bool = False):
        self.hint = hint
        self.offline = offline  # tests load local files with the network switched off

    def __enter__(self) -> Session:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserUnavailable('Playwright is not installed. Run pip install -e ".[sweep]" and then '
                                     f"playwright install chromium{self.hint}.") from None
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
    def tab(self, url: str) -> Iterator[tuple[object, object]]:
        """Navigate once to url at phone width and let it settle. Yields (tab, response). Raises
        NavigationFailed when the browser could not load it at all."""
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        context = self._browser.new_context(
            viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True,
            user_agent=self.user_agent, service_workers="block", offline=self.offline)
        try:
            tab = context.new_page()
            try:
                response = tab.goto(url, wait_until="load", timeout=LOAD_SECONDS * 1000)
            except PlaywrightTimeout:
                raise NavigationFailed("timeout", f"the page did not finish loading within {LOAD_SECONDS} "
                                                  "seconds") from None
            except PlaywrightError as exc:
                message = str(exc).splitlines()[0]
                raise NavigationFailed(next((k for marker, k in NET_ERRORS.items() if marker in message), "error"),
                                       message) from None
            if response is None:
                raise NavigationFailed("error", "the browser got no response")
            try:
                tab.wait_for_load_state("networkidle", timeout=SETTLE_MS)
            except PlaywrightTimeout:
                pass  # a page that never goes quiet (chat widgets, analytics) is still loaded
            yield tab, response
        finally:
            context.close()
