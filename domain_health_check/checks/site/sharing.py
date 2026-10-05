"""How the home page looks when someone shares a link to it.

Open Graph tags (og:title, og:description, og:image) set the title, summary
and picture in the preview card on Facebook, LinkedIn, iMessage and most chat
apps. Without them, the app guesses.
"""

from __future__ import annotations

from ...fetcher import PageContext
from ...models import SITE, CheckResult, Status
from ._html import meta, parse

SOCIAL_PREVIEW = "Social preview"
REQUIRED = {"og:title": "title", "og:description": "description", "og:image": "image"}

EXPLANATION = (
    "When someone shares your website in a text message or on Facebook or LinkedIn, these settings control the "
    "title, description and picture in the preview. Without them, the preview may be blank or show a random "
    "image from the page."
)


def evaluate_social_preview(tags: dict[str, str]) -> CheckResult:
    """tags is {og property: content} for whatever the page has."""
    missing = [plain for prop, plain in REQUIRED.items() if not tags.get(prop)]
    details = [f"{prop}: {tags[prop]}" for prop in REQUIRED if tags.get(prop)]
    if not missing:
        return CheckResult(SITE, SOCIAL_PREVIEW, Status.PASS,
                           "Your home page has a title, description and image for link previews.", EXPLANATION,
                           details=details)
    fix = (
        "In your website builder, open the home page settings and look for \"social sharing\" or \"Open Graph\". "
        "Fill in the title, description and image. A picture of 1200 by 630 pixels works well everywhere."
    )
    if len(missing) == len(REQUIRED):
        summary = "Your home page has no link preview settings, so shared links may show no picture or description."
    else:
        summary = f"Your home page link preview is missing its {' and '.join(missing)}."
    return CheckResult(SITE, SOCIAL_PREVIEW, Status.WARN, summary, EXPLANATION, fix,
                       details + [f"Missing: og:{plain}" for plain in missing],
                       measure=(len(REQUIRED) - len(missing)) / len(REQUIRED))  # the share of the three present


def check_social_preview(page: PageContext) -> list[CheckResult]:
    # The apps that draw link previews read the page as delivered and run no scripts, so this is judged on what
    # the server sent even when the page was also rendered: a tag that scripts add never reaches a preview.
    tree = parse(page.as_delivered)
    tags = {}
    for prop in REQUIRED:
        # The standard is property="og:...", but name="og:..." is common and every major app reads it.
        found = meta(tree, prop, "property") + meta(tree, prop, "name")
        tags[prop] = next((value for value in found if value), "")
    return [evaluate_social_preview(tags)]
