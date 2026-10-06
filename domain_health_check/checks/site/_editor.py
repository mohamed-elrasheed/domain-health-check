"""Where the owner makes a change: the one opening phrase every self fix uses.

The runner sets PageContext.editor from what the report recognized: a hosted builder's name (platform.detect), or
"WordPress" (platform.detect_cms). Every self fix opens with the same phrase for that platform, so no fix tells a
WordPress owner to look in a "website builder".
"""

from __future__ import annotations

ANYWHERE = "Wherever you edit your site"


def where(editor: str = "") -> str:
    """ "In Webflow", "In WordPress", or "Wherever you edit your site" when nothing was recognized."""
    return f"In {editor}" if editor else ANYWHERE
