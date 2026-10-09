"""The owner-cost ladder: what a problem costs the business, from most to least.

One list, read by two places so they cannot drift apart: layout.py orders the report by it, and scoring.py
weights the score by it. A missing main heading costs a business more than a missing DKIM record, so it both
comes first and moves the number more.
"""

from __future__ import annotations

LADDER = [
    # 1. Customers cannot reach the site, or reach you. A phone number that differs between the website and the
    # Google listing sends some callers to a number nobody expects.
    ["Search engine blocking", "SSL certificate", "Domain registration", "Profile phone number", "Tap to call",
     "Contact form"],
    # 2. Google cannot understand the site.
    ["Main heading", "Meta description", "Page title", "Image alt text", "Heading order", "Canonical tag",
     "Sitemap and robots", "Structured data matches the page", "Social preview"],
    # 3. Customers cannot find the business locally.
    ["Google Business Profile", "Profile completeness", "Profile website link", "Reviews"],
    # 4. The site is slow enough that people leave.
    ["Real-world loading speed", "Mobile speed", "Page weight", "Mobile viewport", "Redirect chain", "Accessibility",
     "Broken links", "Mixed content"],
    # 5. Email can be spoofed.
    ["DMARC (anti-spoofing policy)", "SPF (approved senders)", "DKIM (email signatures)", "Mail servers (MX)"],
    # 6. Hardening.
    ["HSTS (always use HTTPS)", "Content Security Policy", "X-Content-Type-Options", "DNSSEC", "TLS version",
     "Nameservers", "Best practices", "Links to other sites", "Favicon"],
]
TIER_WEIGHT = {1: 5, 2: 4, 3: 3, 4: 2, 5: 1, 6: 1}
# Checks whose place in the order and weight in the score were set separately. The three ways a customer reaches
# the business (the listed phone, tapping to call, the contact form) lead the report with tier 1, but weigh 2: a
# number can differ on purpose, and a form we cannot submit is a reason to check, not proof it is broken.
WEIGHT_OVERRIDE = {"Profile phone number": 2, "Tap to call": 2, "Contact form": 2}
CUSTOMER_FACING = 4  # tiers 1 to 4 cost customers; 5 and 6 are behind the scenes

TIER = {name: (tier, position) for tier, names in enumerate(LADDER, start=1) for position, name in enumerate(names)}
