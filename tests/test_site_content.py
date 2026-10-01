import pytest

from domain_health_check.checks.site import content
from domain_health_check.models import Status
from site_helpers import edited, with_body

TITLE = "<title>Mizan Group LLC · Centreville, Virginia</title>"
H1 = "<h1>Professional service, delivered personally"
DESCRIPTION = ("Computers, networks and websites for homes and small businesses in Northern Virginia. Fixed prices in "
               "writing and one point of contact, from the first call to the final invoice.")


# ---------- Page title

def test_mizan_title_passes(mizan_page):
    [result] = content.check_title(mizan_page)
    assert result.status is Status.PASS
    assert "39 characters" in result.summary


def test_svg_title_in_the_body_is_not_the_page_title(mizan_page):
    # The page has a second <title> inside an SVG. Without the head one, there is no page title.
    [result] = content.check_title(edited(mizan_page, TITLE, ""))
    assert result.status is Status.FAIL


@pytest.mark.parametrize("title, status, phrase", [
    ("", Status.FAIL, "no title"),
    ("Home", Status.WARN, "very short"),
    ("www.mizangroupllc.com", Status.WARN, "just your web address"),
    ("mizangroupllc.com", Status.WARN, "just your web address"),
    ("Mizan Group LLC, computers, networks and websites for homes and businesses in Virginia", Status.WARN,
     "cut it off"),
])
def test_title_problems(mizan_page, title, status, phrase):
    [result] = content.check_title(edited(mizan_page, TITLE, f"<title>{title}</title>"))
    assert result.status is status and phrase in result.summary


# ---------- Meta description

def test_mizan_description_is_too_long(mizan_page):
    # A real finding on Mizan's own site.
    [result] = content.check_description(mizan_page)
    assert result.status is Status.WARN
    assert "177 characters" in result.summary
    assert "70 to 160" in result.fix


def test_description_missing(mizan_page):
    [result] = content.check_description(edited(mizan_page, ' name="description"', ""))
    assert result.status is Status.WARN and "no meta description" in result.summary


def test_description_of_good_length_passes(mizan_page):
    shorter = "Computers, networks and websites for homes and small businesses in Northern Virginia, at fixed prices."
    [result] = content.check_description(edited(mizan_page, DESCRIPTION, shorter))
    assert result.status is Status.PASS


# ---------- Main heading

def test_mizan_main_heading_passes(mizan_page):
    [result] = content.check_main_heading(mizan_page)
    assert result.status is Status.PASS
    assert "Professional service, delivered personally" in result.summary


def test_second_h1_warns(mizan_page):
    [result] = content.check_main_heading(with_body(mizan_page, "<h1>Contact</h1>"))
    assert result.status is Status.WARN and "2 main headings" in result.summary


def test_no_h1_warns(mizan_page):
    page = edited(edited(mizan_page, "<h1>", "<h2>"), "</h1>", "</h2>")
    [result] = content.check_main_heading(page)
    assert result.status is Status.WARN and "no main heading" in result.summary


def test_h1_that_is_only_a_logo_counts_its_alt_text(mizan_page):
    page = edited(mizan_page, H1, '<h1><img src="logo.png" alt="Mizan Group">')
    [result] = content.check_main_heading(page)
    assert result.status is Status.PASS and "Mizan Group" in result.summary


def test_empty_h1_warns(mizan_page):
    page = edited(mizan_page, H1, '<h1><img src="logo.png">')
    assert "empty" in content.check_main_heading(page)[0].summary


# ---------- Heading order

def test_mizan_heading_order_passes(mizan_page):
    [result] = content.check_heading_order(mizan_page)
    assert result.status is Status.PASS and "22 headings" in result.summary


def test_every_skip_is_counted(mizan_page):
    page = with_body(mizan_page, "<h4>Fine print</h4><h2>Back up</h2><h5>Deep</h5>")
    [result] = content.check_heading_order(page)
    assert result.status is Status.WARN and "2 places" in result.summary
    assert any("h4 directly after an h2" in d for d in result.details)
    assert any("h5 directly after an h2" in d for d in result.details)


@pytest.mark.parametrize("levels, skips", [
    ([1, 2, 3, 2, 3], 0),
    ([2, 3], 0),       # starting at h2 skips nothing; the missing h1 is the main heading check's finding
    ([3, 2], 1),       # an h3 before any h2
    ([1, 3], 1),
    ([1, 2, 3, 4, 1, 2], 0),
])
def test_heading_order_rule(levels, skips):
    result = content.evaluate_heading_order(levels)
    assert (result.status is Status.WARN) == bool(skips)


def test_no_headings_did_not_run():
    result = content.evaluate_heading_order([])
    assert not result.ran


# ---------- Image alt text

def test_mizan_images_pass_counting_lazy_ones(mizan_page):
    [result] = content.check_alt_text(mizan_page)
    assert result.status is Status.PASS
    assert "2 of the 2" in result.summary
    assert any("only load when a visitor scrolls" in d for d in result.details)


@pytest.mark.parametrize("alt, useful", [
    ("Technician fixing a router", True),
    ("", False),
    (None, False),
    ("   ", False),
    ("IMG_1234.jpg", False),
    ("hero-banner.webp", False),
    ("IMG_1234", False),  # same as the file name without its extension
])
def test_useful_alt(alt, useful):
    assert content.useful_alt(alt, "https://cdn.test/uploads/IMG_1234.jpg") is useful


def test_images_without_alt_warn_and_are_listed(mizan_page):
    page = with_body(mizan_page, '<img src="https://cdn.test/team.jpg"><img src="https://cdn.test/van.jpg" alt="van.jpg">')
    [result] = content.check_alt_text(page)
    assert result.status is Status.WARN and "2 of the 4" in result.summary
    assert "No useful alt text: https://cdn.test/team.jpg" in result.details


def test_noscript_copies_are_not_counted(mizan_page):
    page = with_body(mizan_page, '<noscript><img src="https://cdn.test/a.jpg"></noscript>')
    assert "2 of the 2" in content.check_alt_text(page)[0].summary


def test_ninety_percent_passes():
    images = [(f"https://cdn.test/{i}.jpg", "A photo") for i in range(9)] + [("https://cdn.test/x.jpg", "")]
    assert content.evaluate_alt_text(images).status is Status.PASS
    assert content.evaluate_alt_text(images[1:]).status is Status.WARN  # 8 of 9


def test_no_images_did_not_run():
    assert not content.evaluate_alt_text([]).ran
