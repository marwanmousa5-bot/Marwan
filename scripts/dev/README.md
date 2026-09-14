# Development helpers

Small Node scripts that drive the bundled headless Chromium against the
`web-demo` build. They are not part of the product; they exist so that every UI
change is verified by looking at it rather than by assuming it worked.

Serve the build first:

```
python3 -m http.server 8099 --directory web-demo/public
```

Then, from the repository root:

| Script | What it does |
| --- | --- |
| `node scripts/dev/shot.mjs <url> <out.png> [waitMs]` | One screenshot, plus the page's console output. |
| `node scripts/dev/tour.mjs "Alerts" "Dispatch" …` | Clicks each navigation entry in turn, screenshots it, and reports any JavaScript error raised on that page. |
| `node scripts/dev/probe.mjs` | Boots the app and prints statistics about the seeded world (trip counts, date span, distances) straight out of `window.__fb`. |
| `node scripts/dev/debug.mjs` | Ad-hoc page instrumentation while chasing a specific bug. |

Screenshots are written under the session scratch directory referenced inside
each script; change the `OUT` constant if you want them elsewhere.
