"""The proposal generator, on an invented lead. No real business appears here."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from selectolax.parser import HTMLParser

from domain_health_check.preview import cli, content, render

PROPOSAL_LINE = "A proposal for Example Garage & Sons (Fuel), prepared by Mizan Group LLC. Not an official site."
LEAD = {
    "id": "example-garage", "n": "Example Garage & Sons (Fuel)", "cat": "auto", "town": "Springfield",
    "addr": "100 Main St, Springfield, VA 22150", "ph": "555-010-0100", "rating": "42 reviews (Yelp)",
    "links": [["Site", "https://examplegarage.wixsite.com/home"],
              ["Maps", "https://www.google.com/maps/search/?api=1&query=Example+Garage"],
              ["Yelp", "https://www.yelp.com/biz/example-garage"]],
}
TODAY = date(2026, 10, 4)


def visible(page: str) -> str:
    tree = HTMLParser(page)
    tree.strip_tags(["style", "script"])
    text = " ".join(tree.body.text(separator=" ").split())
    return re.sub(r"\s+([,.])", r"\1", text)  # inline tags are not word breaks


# ---------- reading the lead

@pytest.mark.parametrize("rating, numbers", [
    ("42 reviews (Yelp)", [("42", "reviews on Yelp")]),
    ("4.9 / 39 (Carfax)", [("4.9", "stars on Carfax"), ("39", "reviews on Carfax")]),
    ("30 reviews (Yelp) / 4.6 / 21 (Birdeye)",
     [("30", "reviews on Yelp"), ("4.6", "stars on Birdeye"), ("21", "reviews on Birdeye")]),
    ("1.0 / 1 (Yelp)", [("1.0", "stars on Yelp"), ("1", "review on Yelp")]),
    ("120 reviews (aggregated)", [("120", "reviews")]),
    ("rating not found", []),
])
def test_rating_numbers(rating, numbers):
    assert content.rating_numbers(rating) == numbers


def test_numbers_on_the_lead_override_the_rating():
    p = content.proposal({**LEAD, "numbers": [["1992", "family owned since"]]})
    assert p.numbers == [("1992", "family owned since")]


def test_hours_group_days_with_the_same_times():
    h = content.hours({"mon": [["08:00", "18:00"]], "tue": [["08:00", "18:00"]], "wed": [["08:00", "18:00"]],
                       "thu": [["08:00", "18:00"]], "fri": [["08:00", "18:00"]], "sat": [["08:00", "12:00"]],
                       "sun": [], "note": "Walk-ins welcome", "checked": "2026-10-04"})
    assert h.rows == [("Monday to Friday", "8:00 am to 6:00 pm"), ("Saturday", "8:00 am to noon"),
                      ("Sunday", "Closed")]
    assert h.note == "Walk-ins welcome" and h.complete


def test_a_split_day_and_a_missing_day():
    h = content.hours({"mon": [["09:00", "12:00"], ["13:00", "17:30"]], "wed": [["09:00", "17:30"]]})
    assert h.rows == [("Monday", "9:00 am to noon, 1:00 pm to 5:30 pm"), ("Wednesday", "9:00 am to 5:30 pm")]
    assert not h.complete  # Tuesday is unknown, not closed


@pytest.mark.parametrize("record", [None, {}, {"checked": "2026-10-04"}])
def test_no_hours_yet_is_none(record):
    assert content.hours(record) is None


@pytest.mark.parametrize("record", [{"mon": [["8am", "6pm"]]}, {"monday": []}, {"mon": "8 to 6"}])
def test_malformed_hours_are_refused(record):
    with pytest.raises(content.LeadError):
        content.hours(record)


def test_a_trade_without_a_template_is_refused():
    with pytest.raises(content.LeadError, match="no template for trade"):
        content.proposal({**LEAD, "cat": "plumbing"})


def test_the_name_is_theirs_or_ours_unchanged_never_trimmed():
    assert content.proposal(LEAD).display_name == "Example Garage & Sons (Fuel)"  # ours, exactly
    assert content.proposal(LEAD, read_name="Example Fuel").display_name == "Example Fuel"  # read from their page
    lead = {**LEAD, "display_name": "Example Fuel Garage"}
    assert content.proposal(lead, read_name="Example Fuel").display_name == "Example Fuel Garage"  # the lead wins


@pytest.mark.parametrize("lead, read, note", [
    ({**LEAD, "display_name": "Example Fuel", "display_name_source": "their site header"}, ("", ""),
     'Name "Example Fuel" is from their site header. Confirm it on the call.'),
    ({**LEAD, "display_name": "Example Fuel", "display_name_confirmed": True}, ("", ""), ""),
    (LEAD, ("Example Fuel", "their site footer (copyright line)"),
     'Name "Example Fuel" was read from their site footer (copyright line). Confirm it on the call.'),
    (LEAD, ("", ""), 'No name read from their site; the pages use our lead name "Example Garage & Sons (Fuel)". '
                     "Confirm it on the call."),
])
def test_an_unconfirmed_name_is_called_out(lead, read, note):
    assert cli.name_note(lead, read) == note


# ---------- the pages

@pytest.fixture
def pages():
    p = content.proposal(LEAD, "examplegarage.wixsite.com")
    return render.proposal_page(p, TODAY), render.site_page(p, TODAY)


def test_every_page_says_it_is_a_proposal_first(pages):
    for page in pages:
        text = visible(page)
        assert text.startswith(PROPOSAL_LINE), text[:120]
        assert '<meta name="robots" content="noindex, nofollow">' in page


def test_no_slot_is_left_unfilled(pages):
    for page in pages:
        assert "${" not in page and "{{" not in page and not re.search(r"\$[a-z_]+", page)


def test_values_are_escaped(pages):
    proposal_page, _ = pages
    assert "Example Garage &amp; Sons (Fuel)" in proposal_page and "& Sons" not in proposal_page.replace("&amp;", "")


def test_the_proposal_page_holds_the_comparison_numbers_and_details_and_nothing_else(pages):
    proposal_page, _ = pages
    text = visible(proposal_page)
    assert "examplegarage.wixsite.com, photographed 4 October 2026" in text
    assert '<img src="current.png"' in proposal_page and '<iframe src="site.html"' in proposal_page
    assert "42 reviews on Yelp" in text
    for label in ("Business", "Trade", "Phone", "Address", "Hours"):
        assert f"<dt>{label}</dt>" in proposal_page
    assert "Not confirmed yet. We fill these in with you." in text
    assert "<script" not in proposal_page  # nothing runs, nothing tracks


def test_the_proposed_site_carries_their_name_and_honest_gaps(pages):
    _, site = pages
    text = visible(site)
    assert "© 2026 Example Garage &amp; Sons" in site.replace("&copy;", "©")
    assert 'href="tel:+15550100100"' in site
    assert "Hours will be listed here once the shop confirms them." in text
    assert "Auto repair in Springfield, Virginia" in text


def test_ten_digit_numbers_dial_with_the_country_code():
    p = content.proposal({**LEAD, "ph": "703-555-0100"})
    assert 'href="tel:+17035550100"' in render.site_page(p, TODAY)


def test_hours_render_when_known():
    p = content.proposal({**LEAD, "hours": {"mon": [["08:00", "18:00"]], "sun": []}})
    site = render.site_page(p, TODAY)
    assert "<li><span>Monday</span><span>8:00 am to 6:00 pm</span></li>" in site
    assert "<li><span>Sunday</span><span>Closed</span></li>" in site


def test_no_rating_on_file_says_so():
    p = content.proposal({**LEAD, "rating": "rating not found"})
    assert "No rating on file yet." in visible(render.proposal_page(p, TODAY))
    assert 'aria-label="Reviews"' not in render.site_page(p, TODAY)


CONTRACTIONS = ("n't", "'re", "'ll", "'ve", "'d ", "'m ")


def test_our_copy_follows_the_voice_rules(pages):
    for page in pages:
        text = visible(page)
        assert "—" not in text and "!" not in text, text
        assert not any(c in text for c in CONTRACTIONS), text


# ---------- writing into the previews repository

@pytest.fixture
def previews(tmp_path) -> Path:
    repo = tmp_path / "mizan-previews"
    (repo / ".git").mkdir(parents=True)
    return repo


@pytest.fixture
def screenshot(tmp_path) -> Path:
    path = tmp_path / "sweep-output" / "example-garage" / "phone.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x89PNG not really")
    return path


def test_write_produces_the_folder_and_the_shared_files(previews, screenshot):
    folder = cli.write(LEAD, screenshot, previews, TODAY)
    assert sorted(p.name for p in folder.iterdir()) == ["current.png", "index.html", "site.html"]
    public = previews / "public"
    assert (public / "robots.txt").read_text() == "User-agent: *\nDisallow: /\n"
    assert "X-Robots-Tag: noindex, nofollow" in (public / "_headers").read_text()
    assert (public / "_redirects").read_text().startswith("/ https://www.mizangroupllc.com/")
    assert "example-garage" not in (public / "index.html").read_text()  # the root lists no lead


def test_a_new_generation_replaces_the_old_folder(previews, screenshot):
    folder = cli.write(LEAD, screenshot, previews, TODAY)
    (folder / "old-draft.html").write_text("stale")
    cli.write(LEAD, screenshot, previews, TODAY)
    assert not (folder / "old-draft.html").exists()


def test_write_refuses_without_a_repository_or_a_screenshot(tmp_path, screenshot, previews):
    with pytest.raises(content.LeadError, match="not a git repository"):
        cli.write(LEAD, screenshot, tmp_path / "nowhere", TODAY)
    with pytest.raises(content.LeadError, match="run domain-health-check-sweep"):
        cli.write(LEAD, tmp_path / "missing.png", previews, TODAY)


def test_the_command_reads_the_lead_list_and_never_writes_to_it(tmp_path, previews, screenshot, capsys):
    leads = tmp_path / "leads.json"
    leads.write_text(json.dumps([LEAD]), encoding="utf-8")
    before = leads.read_bytes()
    assert cli.main(["example-garage", "--leads", str(leads), "--previews", str(previews),
                     "--screenshots", str(tmp_path / "sweep-output")], today=TODAY) == 0
    assert leads.read_bytes() == before
    assert "Hours are not on the lead yet" in capsys.readouterr().out
    assert cli.main(["nobody", "--leads", str(leads), "--previews", str(previews)]) == 2


# ---------- every trade's template

TRADE_CODES = ["auto", "barber", "clean", "land", "food"]


@pytest.mark.parametrize("trade", TRADE_CODES)
@pytest.mark.parametrize("hours", [None, {"mon": [["09:00", "17:00"]], "sun": []}])
def test_every_template_keeps_the_rules(trade, hours):
    lead = {**LEAD, "cat": trade, "hours": hours}
    site = render.site_page(content.proposal(lead), TODAY)
    text = visible(site)
    assert text.startswith(PROPOSAL_LINE)
    assert '<meta name="robots" content="noindex, nofollow">' in site and "<script" not in site
    assert "${" not in site and "{{" not in site
    assert "—" not in text and "!" not in text and not any(c in text for c in CONTRACTIONS)
    assert "© 2026 Example Garage &amp; Sons (Fuel)" in site.replace("&copy;", "©")
    assert 'href="tel:+15550100100"' in site and "42" in text
    assert "<img" not in site  # typographic: no stock photography, no pictures at all


@pytest.mark.parametrize("trade, comes_to_you", [("auto", False), ("barber", False), ("food", False),
                                                 ("clean", True), ("land", True)])
def test_a_business_that_comes_to_you_shows_its_town_not_its_street(trade, comes_to_you):
    site = visible(render.site_page(content.proposal({**LEAD, "cat": trade}), TODAY))
    assert ("100 Main St" in site) is not comes_to_you
    assert ("Get directions" in site) is not comes_to_you
    assert ("Based in Springfield, Virginia" in site) is comes_to_you


def test_a_lead_can_say_it_has_a_storefront():
    lead = {**LEAD, "cat": "clean", "visits": "storefront"}  # a dry cleaner files under cleaning
    assert "100 Main St" in visible(render.site_page(content.proposal(lead), TODAY))
    with pytest.raises(content.LeadError, match="visits"):
        content.proposal({**LEAD, "visits": "sometimes"})


@pytest.mark.parametrize("trade, who", [("auto", "the shop"), ("barber", "the shop"), ("food", "the restaurant"),
                                        ("clean", "the business"), ("land", "the business")])
def test_the_empty_hours_line_names_the_business_the_right_way(trade, who):
    site = visible(render.site_page(content.proposal({**LEAD, "cat": trade}), TODAY))
    assert f"Hours will be listed here once {who} confirms them." in site
