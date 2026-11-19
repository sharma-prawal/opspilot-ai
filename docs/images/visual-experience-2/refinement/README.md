# Final UX refinement captures

Actual production Next.js implementation, using visibly labeled synthetic browser
fixtures. The original approved screenshots remain one directory above. This is a
focused refinement of 0a734f3; the original brand geometry and assets are unchanged.

- [Homepage desktop](home-desktop.png)
- [Workbench desktop](workbench-desktop.png)
- [Workbench mobile](workbench-mobile.png)
- [Integrations desktop](integrations-desktop.png)
- [Integrations mobile](integrations-mobile.png)
- [Safety desktop](safety-desktop.png)
- [Original symbol at native 16/24/32 px, light and dark](brand-legibility.png)

Reproduce: `cd apps/web && pnpm build && pnpm test:visual2` (or `pnpm smoke:mock`).
The suite starts its own production frontend on free port 3199 with a minimal
environment; all API responses are intercepted synthetic fixtures. It stops only
its own server. Desktop is 1440 px; mobile is 390 px. Captures start at document
top after fonts/hydration settle. Reduced motion is enabled. The symbol board
shows existing SVGs at their native display sizes and has no operational data.

`verification.json` records the browser checks, including direct approval-button
focus/viewport assertions on desktop and mobile, keyboard source-node navigation,
per-connector controls, secondary capability comparison, keyboard contract selection,
and full gate criteria on expansion. These are interaction checks and rendered
design evidence, not a model-quality or operator-performance evaluation.
