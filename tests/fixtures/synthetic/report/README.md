# Golden report fixtures

One handwritten home page per site archetype, each with an `expected.json` beside it listing every finding the
report must emit for it, and nothing else. They reproduce the markup patterns of each platform (Webflow's
`w-` classes, WordPress lazy-load placeholders, Wix's script payloads, Squarespace's `data-src` images, GoDaddy's
builder markup, a single-page app's empty shell). No real business, site or page is copied; every name and
domain is invented.

`expected.json`: `headers` are the response headers the page is served with; `findings` lists
`{"check", "status", "says"}` for every result that is not a pass (`NOT_CHECKED` for a check that could not
run), where `says` is a phrase the summary must contain. `findings_without_render` (js-spa only) is what the
report says when the page cannot be rendered in a browser.
