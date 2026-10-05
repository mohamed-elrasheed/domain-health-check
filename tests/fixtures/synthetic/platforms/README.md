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
| `custom.html` | a hand-built site that only links to a builder's site, which is a link and not an asset |
