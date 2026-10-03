"""Each sweep detector against a handwritten page that has its fault, and a clean page that has none."""

from __future__ import annotations

from pathlib import Path

import pytest
from selectolax.parser import HTMLParser

from domain_health_check.sweep import faults
from domain_health_check.sweep.models import Page, Robots, Visit

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
YEAR = 2026


def page(name: str, url: str = "https://www.example.com/", rendered: bool = False) -> Page:
    return Page(url, url, 200, [], (SYNTHETIC / name).read_text(encoding="utf-8"), rendered)


def found(name: str, url: str = "https://www.example.com/", rendered: bool = False) -> list[faults.Fault]:
    return faults.evaluate_page(page(name, url, rendered), YEAR)


def codes(name: str, **kw) -> list[str]:
    return [f.code for f in found(name, **kw)]


def test_a_clean_page_has_no_fault():
    # Template code inside script and style, a lazy-loaded image, a search form with an empty action,
    # a form that posts somewhere real, and a theme copyright older than the business's own: all fine.
    assert found("good.html") == []


def test_placeholders_quote_the_code_and_count_it():
    [fault] = found("placeholders.html")
    assert fault.code == "placeholder"
    assert fault.quote == "{{placeholder_hero_banner}}"
    assert '"{{placeholder_hero_banner}}" and "{{placeholder_intro_copy}}", in 5 places in all' in fault.sentence


def test_vendor_labels_count_in_text_and_in_alt_text():
    [fault] = found("vendor-labels.html")
    assert fault.code == "placeholder"
    assert '"Cat-Landing" and "Core Page"' in fault.sentence
    tree = HTMLParser('<body><img src="a.jpg" alt="Main Dish Image"></body>')
    assert faults.placeholders(tree, rendered=False).quote == "Main Dish Image"


def test_vendor_labels_match_the_whole_string_only():
    tree = HTMLParser("<body><p>Send us a shop photo and we will quote the job.</p></body>")
    assert faults.placeholders(tree, rendered=False) is None


def test_lorem_ipsum_is_a_placeholder():
    [fault] = found("lorem.html")
    assert fault.code == "placeholder" and "Lorem ipsum dolor sit amet" in fault.sentence


def test_client_side_templates_are_not_placeholders_before_rendering():
    # A framework fills these in the browser. Read as delivered, they are not evidence of anything.
    assert codes("client-template.html") == []
    # Still there after the browser rendered the page, they are what visitors see.
    assert codes("client-template.html", rendered=True) == ["placeholder"]


def test_copyright_two_years_behind():
    [fault] = found("stale-copyright.html")
    assert fault.code == "stale-copyright"
    assert fault.sentence == 'The copyright line on the home page reads "Copyright © 2014".'


@pytest.mark.parametrize("text, stale", [
    ("© 2025 Example", False),  # one year behind is not two
    ("© 2024 Example", True),
    ("Copyright 2010 - 2026 Example", False),  # a range counts by its last year
    ("© 2023 Theme Co. © 2026 Example", False),  # the latest line decides
    ("All rights reserved.", False),  # no year says nothing either way
    ("(c) 2019", True),
])
def test_copyright_years(text, stale):
    assert (faults.stale_copyright(text, YEAR) is not None) is stale


@pytest.mark.parametrize("url, builder", [
    ("https://examplebarbers.wixsite.com/examplebarbers", True),
    ("https://example-auto.mechanicnet.com/", True),
    ("https://example.business.site/", True),
    ("https://example.godaddysites.com/", True),
    ("https://example-shop.squarespace.com/", True),
    ("https://sites.google.com/view/example", True),
    ("https://www.wix.com/", False),
    ("https://www.squarespace.com/", False),
    ("https://www.example.com/", False),
])
def test_builder_host(url, builder):
    fault = faults.builder_host(url)
    assert (fault is not None) is builder
    if fault:
        assert fault.quote in fault.sentence and "not on a domain of their own" in fault.sentence


def test_builder_host_is_found_on_the_live_address():
    assert codes("builder-host.html", url="https://examplebarbers.wixsite.com/examplebarbers") == ["builder-host"]


def test_theme_vendor_demo_images():
    [fault] = found("demo-images.html")
    assert fault.code == "demo-images"
    assert "3 of its 4 images served from cleaning.sometheme.example" in fault.sentence


def test_builder_stock_images_resolve_the_real_source():
    # The first image's src is a lazy-load placeholder; its real address is in data-srcset.
    [fault] = found("stock-images.html")
    assert fault.code == "demo-images"
    assert fault.sentence.startswith("3 of the 3 images on the home page are the website builder's stock pictures")


def test_own_uploads_are_not_stock():
    tree = HTMLParser('<body><img src="/wp-content/uploads/2024/stockton-office.jpg"></body>')
    assert faults.demo_images(tree, "https://www.example.com/") is None


def test_staging_link_names_the_link_and_the_host():
    [fault] = found("staging-link.html")
    assert fault.code == "staging-link"
    assert fault.sentence == ('The "Order Online" link on the home page points at abc.xyz.temporary.site, a '
                              'temporary development address, not their live site.')
    assert fault.selector == 'a[href*="abc.xyz.temporary.site"]'


@pytest.mark.parametrize("url, staging", [
    ("https://abc.xyz.temporary.site/", True),
    ("https://example.mystagingwebsite.com/", True),
    ("https://staging.example.com/", True),
    ("http://localhost:8080/", True),
    ("https://example.local/", True),
    ("https://dev.to/article", False),  # a two-label host that starts with dev. is just a site
    ("https://www.example.com/", False),
])
def test_staging_hosts(url, staging):
    assert (faults.staging_host(url) is not None) is staging


def test_dead_contact_form():
    # The newsletter form also posts to "#", but a known form tool submits it with a script.
    [fault] = found("contact-form.html")
    assert fault.code == "contact-form"
    assert fault.quote == 'action="#"'


@pytest.mark.parametrize("form, dead", [
    ("<form><textarea></textarea></form>", True),  # no action at all
    ('<form action=""><input type="email"></form>', True),
    ('<form action="/" method="get"><textarea></textarea></form>', True),  # the same page, by GET
    ('<form action="/" method="post"><textarea></textarea></form>', False),  # server-side, a normal pattern
    ('<form action="https://forms.example.net/f/123"><textarea></textarea></form>', False),
    ('<form action="#" class="wpforms-form"><textarea></textarea></form>', False),
    ('<form action="#" onsubmit="send(event)"><textarea></textarea></form>', False),
    ('<form action="#"><input type="text" name="q"></form>', False),  # not a contact form
    # A Webflow form: no action, method get, submitted by Webflow's script. The wrapper says so.
    ('<div class="w-form"><form method="get" data-name="Contact"><textarea></textarea></form></div>', False),
    ('<form method="get" data-wf-page-id="1" data-wf-element-id="2"><textarea></textarea></form>', False),
])
def test_contact_forms(form, dead):
    tree = HTMLParser(f"<body>{form}</body>")
    assert (faults.dead_contact_form(tree, "https://www.example.com/") is not None) is dead


def test_no_viewport():
    [fault] = found("no-viewport.html")
    assert fault.code == "no-viewport" and "shrunk to fit" in fault.sentence


def test_an_empty_shell_is_not_a_missing_viewport():
    assert faults.missing_viewport(HTMLParser("<html><body><div id=root></div></body></html>")) is None


# ---------- robots.txt and the listed address

def robots(name_or_text: str, status: int = 200) -> Robots:
    path = SYNTHETIC / name_or_text
    text = path.read_text(encoding="utf-8") if name_or_text and path.exists() else name_or_text
    return Robots("https://www.example.com/robots.txt", status, text)


def test_robots_server_error():
    [fault] = faults.evaluate_robots(robots("", 500))
    assert fault.code == "robots-error" and "(HTTP 500)" in fault.sentence


def test_robots_429_counts_as_a_server_error():
    assert [f.code for f in faults.evaluate_robots(robots("", 429))] == ["robots-error"]


def test_disallow_that_covers_the_home_page():
    [fault] = faults.evaluate_robots(robots("robots-disallow-home.txt"))
    assert fault.code == "google-blocked" and fault.quote == "Disallow: /"


def test_disallow_aimed_at_googlebot_alone():
    [fault] = faults.evaluate_robots(robots("robots-disallow-google-home.txt"))
    assert fault.quote == "Disallow: /$"


def test_disallow_aimed_only_at_us_is_not_a_fault_for_them():
    assert faults.evaluate_robots(robots("robots-disallow-us-only.txt")) == []


def test_a_missing_robots_file_is_no_rules():
    assert faults.evaluate_robots(robots("", 404)) == []


def test_nxdomain_names_the_listed_address():
    [fault] = faults.evaluate_visit(Visit("https://www.example-listed.com/", failure="nxdomain"), YEAR)
    assert fault.code == "nxdomain" and "www.example-listed.com, does not exist" in fault.sentence


def test_certificate_error_in_plain_words():
    visit = Visit("https://www.example.com/", failure="certificate", detail="certificate has expired")
    [fault] = faults.evaluate_visit(visit, YEAR)
    assert fault.sentence.endswith("because its certificate has expired.")


def test_faults_come_most_damaging_first():
    html = (SYNTHETIC / "no-viewport.html").read_text(encoding="utf-8").replace("2026", "2019")
    visit = Visit("https://www.example.com/", robots=robots("", 500),
                  page=Page("https://www.example.com/", "https://www.example.com/", 200, [], html))
    assert [f.code for f in faults.evaluate_visit(visit, YEAR)] == ["robots-error", "no-viewport",
                                                                    "stale-copyright"]


def test_a_page_that_forwards_to_a_platform_is_not_judged():
    visit = Visit("https://www.example.com/", page=Page(
        "https://www.example.com/", "https://www.facebook.com/example", 200, [], "<html><body>x</body></html>"))
    assert faults.evaluate_visit(visit, YEAR) == []


CONTRACTIONS = ("n't", "'re", "'ll", "'ve", "'d ", "'m ")


def test_every_sentence_follows_the_voice_rules():
    sentences = [f.sentence for path in SYNTHETIC.glob("*.html") for f in found(path.name, rendered=True)]
    sentences += [faults.nxdomain("https://a.example/").sentence,
                  faults.certificate("https://a.example/", "self-signed certificate").sentence,
                  faults.evaluate_robots(robots("", 503))[0].sentence,
                  faults.evaluate_robots(robots("robots-disallow-home.txt"))[0].sentence,
                  faults.builder_host("https://a.wixsite.com/a").sentence]
    assert len(sentences) >= 12
    for sentence in sentences:
        assert "—" not in sentence and "!" not in sentence, sentence
        assert not any(c in sentence for c in CONTRACTIONS), sentence
        assert " I " not in f" {sentence} ", sentence
        assert sentence.endswith(".") and ". " not in sentence.replace("Co. ", ""), sentence  # one sentence
