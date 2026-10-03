"""How this tool introduces itself to the sites it loads, in both modes.

It lands in other people's server logs, so it names Mizan and carries a URL: anyone reading their logs can
see who it was and why. fetcher.py (report) and sweep/load.py (sweep) both send exactly this; they import it
from here so that neither mode has to import the other's fetch code.
"""

USER_AGENT = "domain-health-check/0.1 (+https://www.mizangroupllc.com/digital)"
ROBOTS_TOKEN = "domain-health-check"  # the product token robots.txt groups match against
