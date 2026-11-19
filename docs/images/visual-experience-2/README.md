# Visual Experience 2 implementation captures

These screenshots show the actual Next.js production implementation. Every image
is visibly labeled **synthetic UI fixtures**. The browser intercepts all API requests;
no live model, database or connector is contacted for these captures. Live end-to-end
tests are separately recorded in `docs/PROGRESS.md`.

Reproduce after a production build: `cd apps/web && pnpm build && pnpm smoke:mock`
(or `pnpm test:visual2`). The suite refuses an occupied port 3199 and cleans up its
own server. It supplies an explicit minimal process environment. Desktop is 1440 px;
mobile is 390 px. Captures start at the document top after fonts and hydration settle,
with reduced motion. `verification.json` lists executed checks and page errors.

| Area | Desktop | Mobile |
| --- | --- | --- |
| Intake | [Home](home-desktop.png) | [Home](home-mobile.png) |
| Investigation | [Workbench](workbench-desktop.png) | [Workbench](workbench-mobile.png) |
| Incident roster | [Roster](roster-desktop.png) | [Roster](roster-mobile.png) |
| Integrations | [Catalog](integrations-desktop.png) | [Catalog](integrations-mobile.png) |
| Source evidence | [Inspector](evidence-desktop.png) | In workbench mobile capture |
| Read-only | [Uploaded evidence](readonly-desktop.png) | Same responsive workbench |
| Blocked proposals | [Blocked](blocked-desktop.png) | Same responsive workbench |
| Verified simulator outcome | [Completed](completed-desktop.png) | Same responsive workbench |
| Architecture | [Explorer](architecture-desktop.png) | Existing pan/zoom and text tree retained |
| Safety | [Approval boundary](safety-desktop.png) | Responsive sequence in source |
| Guide | Technical detail tested in browser | [Guide](guide-mobile.png) |
| Backend unavailable | [Unavailable](unavailable-desktop.png) | Same responsive intake |

Baseline v0.7.x captures are preserved in [the prior redesign directory](../redesign/).
See [before/after hierarchy and limitations](../../design/VISUAL_EXPERIENCE_2.md).
Rendered hierarchy and visual-density judgments are subjective; no measured
operator-performance or percentage text-reduction claim is made.
