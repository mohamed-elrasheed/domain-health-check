"""A Proposal as HTML. Pure: takes the proposal and the date, returns page text.

string.Template.substitute raises on any value it is not given, so a page can never ship with a slot left
unfilled: the same fault sweep reports on other people's sites.
"""

from __future__ import annotations

import html
import re
from datetime import date
from importlib import resources
from string import Template

from .content import Hours, Proposal


def _t(name: str) -> Template:
    return Template(resources.files(__package__).joinpath("templates", name).read_text(encoding="utf-8"))


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def _tel(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"+1{digits}" if len(digits) == 10 else digits


def _long_date(day: date) -> str:
    return f"{day.day} {day.strftime('%B')} {day.year}"


def numbers(p: Proposal, css: str = "number") -> str:
    if not p.numbers:
        return '    <p class="none">No rating on file yet.</p>'
    return "\n".join(f'    <div class="{css}"><b>{esc(big)}</b><span>{esc(small)}</span></div>'
                     for big, small in p.numbers)


def hours_list(h: Hours | None, empty: str) -> str:
    if h is None:
        return f'<p class="empty">{esc(empty)}</p>'
    rows = "".join(f"<li><span>{esc(days)}</span><span>{esc(times)}</span></li>" for days, times in h.rows)
    note = f'<p class="hours-note">{esc(h.note)}</p>' if h.note else ""
    return f'<ul class="hours">{rows}</ul>{note}'


def proposal_page(p: Proposal, photographed: date) -> str:
    return _t("proposal.html").substitute(
        name=esc(p.display_name),
        current_host=esc(p.current_host),
        photographed=_long_date(photographed),
        numbers=numbers(p),
        trade=esc(p.trade),
        phone=esc(p.phone) if p.phone else '<span class="empty">Not on file</span>',
        address=esc(p.address) if p.address else '<span class="empty">Not on file</span>',
        hours=hours_list(p.hours, "Not confirmed yet. We fill these in with you."),
    )


def site_page(p: Proposal, today: date) -> str:
    tel = _tel(p.phone)
    call_button = f'<a class="btn btn-call" href="tel:{esc(tel)}">Call {esc(p.phone)}</a>' if p.phone else ""
    call_small = f'<a class="call-small" href="tel:{esc(tel)}">Call</a>' if p.phone else ""
    directions = p.maps_url and not p.comes_to_you
    map_button = f'<a class="btn btn-map" href="{esc(p.maps_url)}">Get directions</a>' if directions else ""
    map_link = f'<a href="{esc(p.maps_url)}">Get directions</a>' if directions else ""
    proof = "" if not p.numbers else (
        '<section aria-label="Reviews"><div class="proof">\n' + numbers(p, css="figure") + "\n</div></section>")
    street, _, rest = p.address.partition(", ")
    address_lines = f"{esc(street)}<br>{esc(rest)}" if rest else esc(p.address)
    area_line = f"Based in {esc(p.town)}{f', {esc(p.state)}' if p.state else ''}" if p.town else ""
    # Templates for trades that usually come to the customer carry one contact slot, filled either way.
    if p.comes_to_you:
        contact_section = (f'<section class="contact" aria-labelledby="contact-title">\n'
                           f'  <h2 id="contact-title">Get in touch</h2>\n'
                           f'  <p>{area_line}</p>\n  {call_button}\n</section>')
    else:
        contact_section = (f'<section class="contact visit" aria-labelledby="visit-title">\n'
                           f'  <h2 id="visit-title">Find us</h2>\n'
                           f'  <address>{address_lines}</address>\n  {map_link}\n</section>')
    return _t(f"{p.template}/site.html").substitute(
        name=esc(p.display_name),
        display_name=esc(p.display_name),
        trade=esc(p.trade),
        town=esc(p.town),
        state_suffix=f", {esc(p.state)}" if p.state else "",
        call_small=call_small,
        call_button=call_button,
        map_button=map_button,
        proof=proof,
        site_hours=hours_list(p.hours, f"Hours will be listed here once {p.who} confirms them."),
        address_lines=address_lines,
        map_link=map_link,
        area_line=area_line,
        contact_section=contact_section,
        year=today.year,
    )


PREVIEW_BASE = "https://preview.mizangroupllc.com"

# The files every previews site carries, whatever leads are in it. The second Disallow is covered by the first
# and is there to say so: the screenshots under /_shots/ are never to be crawled.
ROBOTS_TXT = "User-agent: *\nDisallow: /\nDisallow: /_shots/\n"
HEADERS = "/*\n  X-Robots-Tag: noindex, nofollow\n  Referrer-Policy: no-referrer\n"
# The root lists nothing: a preview's link goes to that business and nobody else.
REDIRECTS = "/ https://www.mizangroupllc.com/ 302\n"
ROOT_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Mizan Group LLC</title>
<style>
body{margin:0;padding:48px 16px;background:#f6f3ee;color:#10201f;font:17px/1.5 system-ui,sans-serif;text-align:center}
</style>
</head>
<body><p>Nothing to see here. <a href="https://www.mizangroupllc.com/">Mizan Group LLC</a></p></body>
</html>
"""


def shared_files() -> dict[str, str]:
    """public/<name>: text, for every file the previews site carries whatever leads are in it."""
    return {"robots.txt": ROBOTS_TXT, "_headers": HEADERS, "_redirects": REDIRECTS, "index.html": ROOT_PAGE}
