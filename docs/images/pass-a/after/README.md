# Pass A — isolated synthetic data, after-only captures

Captured by Chromium against the production Turbopack build on `127.0.0.1:3185`.
All API/session responses in these images are synthetic Playwright fixtures; no production
incident, user session or cloud-provider data is shown. No before baseline was available.

- `roster-{390,768,1280,1440}.png`: complete-history roster with 75 synthetic cases,
  readable source/state filters and contained horizontal table scrolling.
- `overview-*.png`, `intake-*.png`, `workbench-*.png`, `architecture-*.png`: the same four widths.
  Architecture width captures use its accessible structured text view.
- `saved-authorization-1440.png`: saved authorization actor/time, execution and verification separately.
- `historical-metrics-1440.png`: evidence observation time and unavailable latest sample time.
- `navigation-open-{390,768}.png`: all destinations, account and sign out in the disclosure menu.
- `architecture-keyboard-1440.png`: Space-selected BFF node, visible keyboard focus,
  synchronized inspector and emphasized connected edges (captured before pointer selection).
- `observations-{390,768,1280,1440}.json`: document width equals viewport on all five pages.

All 25 PNGs passed signature, chunk checksum, compressed-pixel and dimension validation.
Representative mobile, desktop, authorization, metrics and keyboard captures were visually inspected.
Full-page roster and structured architecture captures are deliberately tall; open at native width to read.
