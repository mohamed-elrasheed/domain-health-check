"""Reading what a business calls itself from its own header or footer."""

from __future__ import annotations

import pytest

from domain_health_check.sweep.names import display_name

LEAD = "Example Garage Auto Care (Fuel)"


@pytest.mark.parametrize("html, found", [
    ('<header><a href="/">Example Fuel</a><nav>Home Services</nav></header>',
     ("Example Fuel", "their site header")),
    ('<div class="site-header"><img src="logo.png" alt="Example Garage"></div>',
     ("Example Garage", "their site header (logo description)")),
    ("<header><nav>Home Menu</nav></header><footer>Copyright © 2015-2026 Example Garage LLC. All rights reserved.</footer>",
     ("Example Garage LLC", "their site footer (copyright line)")),
])
def test_their_own_name(html, found):
    assert display_name(f"<html><body>{html}</body></html>", LEAD) == found


@pytest.mark.parametrize("html", [
    "<header><nav>Home Services Contact</nav></header>",  # nothing that names them
    "<footer>Copyright © 2000-26 Vendor Software Group, Inc</footer>",  # the vendor, not them
    "<header><p>Welcome to Example Garage, serving the county with honest repairs for over thirty years "
    "and counting</p></header>",  # a sentence, not a name
    "<main><h1>Example Garage</h1></main>",  # not the header or the footer
])
def test_no_name_rather_than_a_guess(html):
    assert display_name(f"<html><body>{html}</body></html>", LEAD) is None


def test_hidden_header_text_does_not_count():
    html = '<html><body><header><span class="sr">Example Fuel</span></header></body></html>'
    assert display_name(html, LEAD, shown="Home Services") is None
    assert display_name(html, LEAD, shown="Example Fuel Home") == ("Example Fuel", "their site header")


def test_a_lead_name_with_nothing_distinctive_reads_nothing():
    assert display_name("<header>Auto Care</header>", "Auto Care Service Center") is None
