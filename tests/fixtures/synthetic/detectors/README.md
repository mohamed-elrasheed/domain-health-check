# Detector fixtures

Handwritten home pages for the three detectors that look past the page's own markup: broken links, mixed
content and the browser tab icon. Each has one page that passes and one that fails. Every business, name and
domain is invented; the `.test` and `example.com` addresses cannot belong to anyone.

The tests serve these pages and answer every link and icon request from a local transport, so nothing here is
ever requested from the internet.

| Page | What it is for |
|---|---|
| `links-pass.html` | Every link, on the site and off it, answers 200. |
| `links-fail.html` | One link on the site is gone (404), one loops, one link to another site is gone. |
| `mixed-pass.html` | Every image, script, stylesheet, font and frame loads over https. |
| `mixed-fail.html` | Seven assets over plain http, more than the five a report lists. |
| `favicon-pass.html` | Names its own icon. |
| `favicon-fail.html` | Names no icon, and the site has no /favicon.ico. |
| `favicon-default.html` | Names the standard icon of an invented builder, listed only in the test config `../platforms/default-icons.yaml`. |
