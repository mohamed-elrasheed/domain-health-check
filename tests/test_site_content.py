import pytest
from site_helpers import edited, with_body

from domain_health_check.checks.site import content
from domain_health_check.models import Status

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
    assert result.status is Status.WARN and "no title" in result.summary


@pytest.mark.parametrize("title, status, phrase", [
    ("", Status.WARN, "no title"),
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
    ([3, 2], 0),       # no h1: the first heading is not judged against the missing one (the main heading finding)
    ([1, 3, 2], 1),    # with an h1, an h3 straight after it skips the h2
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
    assert result.summary == "2 of 2 images on your home page have a description."
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
    assert result.status is Status.WARN and result.summary.startswith(
        "1 of 4 images on your home page has no description, and 1 is described only by a file name or the word "
        "'logo'.")
    assert "Not described: https://cdn.test/team.jpg: no description" in result.details
    assert "Not described: https://cdn.test/van.jpg: described only as 'van.jpg'" in result.details


def test_noscript_copies_are_not_counted(mizan_page):
    page = with_body(mizan_page, '<noscript><img src="https://cdn.test/a.jpg"></noscript>')
    assert content.check_alt_text(page)[0].summary.startswith("2 of 2 images")


def test_ninety_percent_passes():
    # No alt attribute at all: not marked as decoration, so it counts against the share.
    images = [(f"https://cdn.test/{i}.jpg", "A photo") for i in range(9)] + [("https://cdn.test/x.jpg", None)]
    assert content.evaluate_alt_text(images).status is Status.PASS
    assert content.evaluate_alt_text(images[1:]).status is Status.WARN  # 8 of 9


def test_no_images_did_not_run():
    assert not content.evaluate_alt_text([]).ran


# ---------- Regressions found on a real WordPress page (synthetic reproductions)

PLACEHOLDER = "data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%20600%20700%22%3E%3C/svg%3E"


def lazy_img(address: str, alt: str | None) -> str:
    """The markup a WordPress lazy-load plugin delivers: a placeholder src, the real address in data-src."""
    alt_attr = "" if alt is None else f' alt="{alt}"'
    return f'<img class="lazy" src="{PLACEHOLDER}" data-src="{address}"{alt_attr}>'


def test_file_name_alt_behind_a_lazy_placeholder_is_not_a_description(mizan_page):
    # The real page had alt="icon1" on data-src=".../icon1.png" and we counted it as described.
    images = "".join(lazy_img(f"https://www.mizangroupllc.com/uploads/icon{i}.png", f"icon{i}") for i in range(1, 6))
    [result] = content.check_alt_text(with_body(mizan_page, images))
    assert result.status is Status.WARN
    assert result.summary.startswith("5 of 7 images on your home page are described only by a file name")
    assert "Not described: https://www.mizangroupllc.com/uploads/icon1.png: described only as 'icon1'" in result.details


def test_details_name_the_real_image_not_the_placeholder(mizan_page):
    [result] = content.check_alt_text(with_body(mizan_page, lazy_img("https://www.mizangroupllc.com/uploads/team.jpg", None) * 3))
    assert not any("data:image" in d for d in result.details)
    assert "Not described: https://www.mizangroupllc.com/uploads/team.jpg: no description" in result.details


def test_wordpress_size_suffix_still_counts_as_the_file_name():
    assert not content.useful_alt("r-img1", "https://example.com/wp-content/uploads/2025/09/r-img1-300x232.jpg")
    assert content.useful_alt("Hardwood floor in a living room", "https://example.com/uploads/r-img1-300x232.jpg")


def test_a_skip_that_exists_only_because_the_main_heading_is_missing_is_not_counted_again():
    only_that = content.evaluate_heading_order([3, 3, 2, 2, 3, 2, 3])
    assert only_that.status is Status.PASS
    assert ("The page has no main heading, so its first heading (an h3) is not judged against one. The main heading "
            "finding covers that.") in only_that.details
    another = content.evaluate_heading_order([3, 3, 2, 2, 3, 2, 4])
    assert another.status is Status.WARN and another.summary == "Your home page skips a heading level in 1 place."
    assert not any("at the start of the page" in d for d in another.details)
    with_h1 = content.evaluate_heading_order([3, 1, 2])
    assert "Heading 1 of 3 is an h3 at the start of the page, before any h2" in with_h1.details


# ---------- Placeholder text from a website template (synthetic reproductions)

AUTO_SHOP = ["Example Auto Care, Springfield", "Auto repair and car service in Springfield",
             "Brakes and tyres", "Oil changes", "Engine diagnostics"]


def test_template_demo_description_is_flagged_even_at_the_right_length():
    # The real case: an auto repair shop whose description was a theme's demo copy, at a perfect length.
    demo = "Take payments online with a scalable platform that grows with your perfect business"
    result = content.evaluate_description([demo + ". Built for every shop."], AUTO_SHOP)
    assert result.status is Status.WARN and "placeholder text left over from a website template" in result.summary


def test_description_unrelated_to_the_page_is_flagged_as_maybe():
    unrelated = "Discover elegant furniture collections crafted with sustainable timber for modern living spaces today."
    result = content.evaluate_description([unrelated], AUTO_SHOP)
    assert result.status is Status.WARN and "may be placeholder text" in result.summary


def test_related_description_passes():
    real = "Family auto repair in Springfield: brakes, tyres, oil changes and engine diagnostics, at fixed prices."
    assert content.evaluate_description([real], AUTO_SHOP).status is Status.PASS


def test_too_little_context_flags_nothing():
    unrelated = "Discover elegant furniture collections crafted with sustainable timber for modern living spaces today."
    assert content.evaluate_description([unrelated], ["Home"]).status is Status.PASS


def test_demo_title_is_flagged():
    result = content.evaluate_title("Just Another WordPress Site", "https://example.com/", AUTO_SHOP)
    assert result.status is Status.WARN and "placeholder text" in result.summary


def test_plurals_and_variants_count_as_shared_words():
    assert content.terms("Flooring installers") & content.terms("Floors installed")


def test_mizan_title_and_description_are_not_placeholder(mizan_page):
    assert "placeholder" not in content.check_title(mizan_page)[0].summary
    assert "placeholder" not in content.check_description(mizan_page)[0].summary


@pytest.mark.parametrize("images, summary", [
    ([("a.jpg", "A shop front")], "1 of 1 image on your home page has a description."),
    ([("a.jpg", None)], "1 of 1 image on your home page has no description. It is not inside a link and is not a logo."),
    ([("a.jpg", None), ("b.jpg", None), ("c.jpg", "A van")],
     "2 of 3 images on your home page have no description. None of them is inside a link or is a logo."),
    ([("a.jpg", None)] + [(f"{n}.jpg", "A van") for n in range(9)],
     "1 of 10 images on your home page has no description. It is not inside a link and is not a logo."),
    ([("logo.png", None, "logo"), ("a.jpg", None, "link"), ("b.jpg", "A van")],
     "2 of 3 images on your home page have no description. 1 logo image and 1 linked image need a real description."),
])
def test_alt_text_counts_read_as_english(images, summary):
    assert content.evaluate_alt_text(images).summary == summary


def test_the_logo_and_linked_images_must_have_a_description(mizan_page):
    page = with_body(mizan_page, '<a href="/"><img class="custom-logo" src="https://cdn.test/brand.png"></a>'
                                 '<a href="/menu"><img src="https://cdn.test/menu.jpg" alt=""></a>')
    [result] = content.check_alt_text(page)
    assert result.status is Status.WARN
    assert result.summary.endswith("1 logo image and 1 linked image need a real description.")
    assert "Needs one (logo image): https://cdn.test/brand.png: no description" in result.details
    assert "Needs one (inside a link): https://cdn.test/menu.jpg: no description" in result.details


def test_a_blank_decorative_image_is_never_called_a_problem():
    images = [("https://cdn.test/swirl.png", ""), ("https://cdn.test/team.jpg", "Our crew")]
    result = content.evaluate_alt_text(images)
    assert result.status is Status.PASS
    assert result.summary == ("1 of 2 images on your home page has no description. It is not inside a link and is "
                              "not a logo.")
    assert "Left blank on purpose, which is right for decoration: https://cdn.test/swirl.png" in result.details
    assert not any(d.startswith(("Needs one", "Not described")) for d in result.details)


def test_on_wordpress_the_seo_fields_point_to_a_plugin_and_name_none():
    from domain_health_check.checks.site import sharing
    for fix in (content.evaluate_description([], editor="WordPress").fix,
                sharing.evaluate_social_preview({}, editor="WordPress").fix):
        assert "SEO plugin" in fix and "tune-up" in fix
        assert not any(name in fix for name in ("Yoast", "Rank Math", "All in One", "SEOPress"))
    assert "SEO plugin" not in content.evaluate_description([]).fix


def test_logo_images_are_counted_and_an_unreadable_linked_image_is_not_guessed_at(mizan_page):
    page = with_body(mizan_page, '<a href="/"><img class="custom-logo" src="https://cdn.test/logo.webp"></a>'
                                 '<a href="/"><img class="custom-logo" src="https://cdn.test/logo.webp" alt="logo"></a>'
                                 '<img src="https://cdn.test/footer-logo.webp">'
                                 '<a href="/quote"><img data-src=""></a>')
    [result] = content.check_alt_text(page)
    assert result.summary.endswith("3 logo images and 1 linked image need a real description.")
    assert "Needs one (logo image): https://cdn.test/logo.webp: described only as 'logo'" in result.details
    assert "Needs one (inside a link): one linked image (no readable address): no description" in result.details


def test_the_word_logo_alone_is_described_only_as_logo():
    assert content.alt_problem("logo", "https://cdn.test/brand.png") == "described only as 'logo'"
    assert content.alt_problem("Logo", "https://cdn.test/brand.png") == "described only as 'Logo'"
    assert content.alt_problem("Harbor Lane Bakery logo", "https://cdn.test/brand.png") is None


def test_heading_order_pass_sentence_without_a_main_heading():
    result = content.evaluate_heading_order([3, 3, 2, 2, 3, 2, 3])
    assert result.status is Status.PASS
    assert result.summary == ("Your headings are in order after the first one. The missing main heading is reported "
                              "under Main heading.")


def test_heading_order_pass_sentence_with_a_main_heading():
    result = content.evaluate_heading_order([1, 2, 3, 2])
    assert result.status is Status.PASS
    assert result.summary == "Your 4 headings are in order, with no levels skipped."
