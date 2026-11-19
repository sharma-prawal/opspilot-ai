# Visual Experience 2

Baseline: published v0.7.1; origin/main 1ee1b700, CI run 44548721335 passed.
Mode: Operate. Evolve the approved Incident Forensics Lab identity.

## Direction

An engineer opens a case to identify the affected service, compare explanations,
inspect the supporting records and decide what to do. Ivory paper, deep ink,
restrained burnt amber and precise emerald/rose evidence semantics remain.
Brand expression belongs in the mark and editorial headings; controls stay familiar.

Logo exploration: observation aperture (a segmented lens), evidence convergence
(three paths converging into one observation), and signal beacon (a pulse inside
an open ring). Select evidence convergence: distinctive at favicon size, directly
connected to the product mechanism and independent of cybersecurity conventions.
Source vector studies are in public/brand/concepts.svg. No generated raster art.

## Information hierarchy

| Surface | Before | After |
| --- | --- | --- |
| Home | Product explanation, four metrics, six scenario cards | Three-mode intake, compact status strip, recent cases, source mix |
| Workbench | Pipeline and banners before conclusions, expanded prose | Incident facts and leading hypothesis, metric comparisons, selectable hypothesis evidence map; report and audit depth on demand |
| Roster | Unfiltered table | Search, source and state filters, linked titles and exact times |
| Integrations | Architecture prose before configuration | Capability matrix and live connector configuration; implementation and connectivity kept separate |
| Safety | Philosophy essays before controls | Approval boundary sequence, expandable rationale and case study |
| Architecture | Large canvas plus long supporting text | Legible selected connections, shorter canvas, expandable reference legend |
| Guide | Long opening explanation | Visual task sequence; complete technical sections retained |

## Data and implementation contracts

Use existing React Flow for architecture; small native SVG/CSS charts add no
dependency or licensing burden. Metric comparison bars show persisted baseline,
extreme and current values, never interpolate a trend. Every metric uses its own
scale and units. Workflow event times are execution chronology, not service metrics.
Source chronology uses observed_at, and selection opens its evidence payload.
Hypothesis links show the model's support/contradiction associations, not proven
causality. Confidence remains explicitly uncalibrated. Empty and unknown differ
from zero. Source mix counts only the incidents returned by the API.

No API, database, inference, approval, authentication or startup contract changes.
Read-only investigations expose advice without execution controls. Unknown source
does not enable simulator approval controls. All essential artwork is local.

## Verification

See the final session entry in docs/PROGRESS.md for executed checks and limitations.
Screenshots under docs/images/visual-experience-2 use labeled synthetic browser
fixtures, with no calls to the running API/database or model. Visual improvements
are design judgments, not measured operator performance or model quality gains.


## Executed verification and review

`make lint` passed; `make test` passed (396 Python, 68 web; 3 opt-in live-model
tests skipped). The seven existing live Playwright journeys passed against the
test database, including both read-only intake flows and simulator approval through
verified recovery. After final localized keyboard fixes, frontend unit tests,
production build and the 15-check production browser smoke suite passed. The
smoke suite records zero page errors and captures desktop/mobile implementation
screenshots using explicit synthetic fixtures. Independent visual review: two P2
focus/navigation findings fixed, scoped verdict **ship** with both resolved.

Design improvements in the table above are qualitative judgments. Test outcomes
are objective checks; no task-completion-time study, measured text reduction,
statistical calibration or new model-performance evaluation is claimed.

The primary interface remains light. Dark logo exports are provided, without a new
theme toggle. Summary metrics do not support a historical operational trend chart;
no backend series endpoint was added. Future adapters remain planned.
