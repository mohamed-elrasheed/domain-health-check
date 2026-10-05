# Platform fixtures

One handwritten page per hosted website builder, each recognizable by a different kind of signal, plus two that
must not be taken for a builder. `cases.json` gives the response headers each page is served with and the
platform the report must detect (`null` for none). Every name and domain is invented.

| Page | Signal |
|---|---|
| `webflow.html` | `<meta name="generator">` and `data-wf-site` |
| `wix.html` | assets from Wix's own hosts, nothing else |
| `squarespace.html` | `server: Squarespace` response header |
| `shopify.html` | `x-shopid` response header and Shopify's asset host |
| `godaddy.html` | GoDaddy Website Builder's generator tag |
| `wordpress.html` | a WordPress generator tag: self-hosted, so not a builder that sets headers |
| `squarespace-markup-only.html` | Squarespace's markup patterns (`data-src` images, its context script) and no Squarespace header, host or generator tag: must not match, since nothing names the platform |
| `custom.html` | a hand-built site that only links to a builder's site, which is a link and not an asset |
