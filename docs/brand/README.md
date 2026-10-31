# Brand assets

The Sensibility mark (Oct 2026): a silver coin with a deep green serif S
(`#053C32`) and a serif wordmark. `ASSETS-PREVIEW.png` shows them all.

The files the site uses are in `frontend/public/`. They are the favicons, the app icons,
`site.webmanifest`, and `wordmark.svg`, which is the wordmark cut out of
`logo.svg` so the header can fill it with `--ink`. The redesign spec's
*Brand* section (`docs/superpowers/specs/2026-10-26-frontend-redesign-design.md`)
describes how the app uses them.

This folder keeps the rest of the set for later use (emails, social cards, print).
None of it is served:

- `logo.png`, `logo-on-dark.png`: the coin and the wordmark (3020×1030,
  transparent background; the dark version has a white wordmark). These are
  the closest match to the original design.
- `coin.png`: the coin alone (1024², transparent).
- `logo.svg`, `coin.svg`: vector *recreations*, close to the PNGs but not
  exact traces. The type is outlined, so no font is needed.
- `icon-light-512.png`, `icon-dark-1024.png`: square presentation icons.
- `favicon-{16,32,48,64}.png`: the favicon art as PNGs (`favicon.ico` holds
  the same sizes).

The design came from a generated image, not an editable vector master, so
the PNGs have a fixed resolution. A designer would need to redraw the vectors
for large print or a trademark.
