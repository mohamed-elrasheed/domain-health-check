"""preview: a proposal page for one prospect, written into the private mizan-previews repository.

Prospecting, like sweep, and walled off from the report the same way (tests/test_sweep_wall.py). It reads a
lead record and the phone screenshot sweep took, and writes a folder of static HTML that Cloudflare Pages
serves at preview.mizangroupllc.com/<lead-id>/.

The rules every page follows:

  * "A proposal for <business>, prepared by Mizan Group LLC. Not an official site." sits at the top of
    every page, above the fold, never in a footer. A page carrying a real business's name can be taken for
    their own site; that line and our subdomain are what prevent it.
  * Every page carries <meta name="robots" content="noindex, nofollow">, every response carries the same as
    an X-Robots-Tag header, and robots.txt disallows everything.
  * The business's own facts carry the page: rating and review count, name, phone, address, hours, trade.
    No stock photography, no invented services, no testimonials, nothing we cannot stand behind.
  * A fact we do not have is shown as missing, never guessed. Hours stay empty until the sales call.

Nothing here writes into this repository. The screenshot of their current site only ever goes to the
private previews repository.
"""
