"""sweep: our own prospecting research. It is not the report.

For each local business on our lead list, sweep looks at the address listed for it, loads that home page
once the way any visitor would, and returns a verdict (none, weak, unver or good) with one specific flaw
quoted from the page. The result goes to us and never to the business.

The wall between sweep and the report is enforced in code and proved in tests/test_sweep_wall.py:

  * sweep imports nothing from the report path: no registry, DNS or TLS checks, no report fetcher (which
    also opens the sitemap), no runner, no report, PDF or mailer. From the rest of the package it uses
    only identity.py (the User-Agent) and robots.py (a pure parser, needed to honor robots.txt).
  * It never writes a report or a PDF and never sends anything. Its only output is a verdict file and
    screenshots under sweep-output/, which is gitignored.
  * Its footprint is one visit: robots.txt, then the home page. No sitemap, no second page, no probing.
"""
