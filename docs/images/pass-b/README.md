# Pass B rendered evidence

Actual production-build Chromium captures, 25 November 2026. **After-only, synthetic saved cases.**
`final-counts/` contains the two final count-correction captures: [desktop](final-counts/counts-1440.png) and [mobile](final-counts/counts-390.png). They show the actual cited/accessibility/unavailability split and supersede count wording in the earlier accepted captures. No fair same-case before capture was created. The original audit concepts remain design references,
not implementation evidence. No API, cloud, model or remediation calls are made by these browser fixtures.

| Required view | Capture |
| --- | --- |
| Desktop leading hypothesis | [workbench-1440.png](after/workbench-1440.png) |
| Contextual inspector | [inspector-1440.png](after/inspector-1440.png) |
| Coverage/provider details | [coverage-1440.png](after/coverage-1440.png) |
| Connected read-only | [connector-readonly-1440.png](after/connector-readonly-1440.png) |
| Uploaded read-only | [upload-readonly-1440.png](after/upload-readonly-1440.png) |
| Simulator authorization | [simulator-pending-1440.png](after/simulator-pending-1440.png) |
| Simulator verification | [simulator-verified-1440.png](after/simulator-verified-1440.png) |
| Tablet | [workbench-768.png](after/workbench-768.png), [inspector-768.png](after/inspector-768.png) |
| Laptop | [workbench-1280.png](after/workbench-1280.png), [inspector-1280.png](after/inspector-1280.png) |
| Mobile | [workbench-390.png](after/workbench-390.png), [inspector-390.png](after/inspector-390.png) |

The four `after/observations-*.json` files record viewport/document equality, layout bounds,
body font size and uncaught page errors. `after/accessibility-samples.json` records representative
computed contrast measurements. These are scoped checks, not an accessibility certification.

`regressions/` contains this feature build's rerun of the existing Pass A journeys; approved Pass A
captures are preserved in their original directory. `inventory.json` records PNG dimensions and SHA-256.
The browser JSON reports are under `docs/audits/pass-b*-playwright.json`.
