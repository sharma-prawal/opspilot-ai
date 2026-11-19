---
name: OpsPilot AI
description: Incident Forensics Lab — precise evidence, inspectable decisions.
colors:
  bg: "#fbfbf8"
  panel: "#ffffff"
  panel-2: "#f4f3ec"
  panel-3: "#eceae1"
  border: "#e2dfd5"
  border-strong: "#c8c4b7"
  text: "#1c2529"
  text-muted: "#4a525d"
  muted: "#626b74"
  accent: "#ad4d1c"
  accent-hover: "#9c4217"
  accent-soft: "rgba(192, 86, 33, 0.12)"
  success: "#047857"
  success-soft: "rgba(4, 120, 87, 0.12)"
  warn: "#965209"
  warn-soft: "rgba(217, 119, 6, 0.12)"
  danger: "#b91c1c"
  danger-soft: "rgba(185, 28, 28, 0.12)"
  info: "#1e3a8a"
  info-soft: "rgba(30, 58, 138, 0.12)"
  purple: "#6d28d9"
  purple-soft: "rgba(109, 40, 217, 0.12)"
typography:
  page-heading:
    fontFamily: "Georgia, Cambria, Times New Roman, Times, serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: "2rem"
    letterSpacing: "-0.025em"
  panel-heading:
    fontFamily: "Georgia, Cambria, Times New Roman, Times, serif"
    fontSize: "1rem"
    fontWeight: 700
    lineHeight: "1.5rem"
    letterSpacing: "-0.025em"
  report-body:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif"
    fontSize: "0.875rem"
    lineHeight: 1.65
  control:
    fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif"
    fontSize: "0.75rem"
    lineHeight: "1rem"
  exhibit-label:
    fontFamily: "Geist Mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
    fontSize: "0.72rem"
    fontWeight: 700
    letterSpacing: "0.05em"
rounded:
  badge: "3px"
  control: "4px"
  field: "5px"
  panel: "6px"
  intake: "8px"
spacing:
  base: "4px"
  tight: "8px"
  grouped: "12px"
  regular: "16px"
  panel: "20px"
  section: "24px"
  generous: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "34px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "34px"
  button-danger:
    backgroundColor: "{colors.danger-soft}"
    textColor: "{colors.danger}"
    rounded: "{rounded.control}"
    height: "34px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    height: "34px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    height: "34px"
  filter-field:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.field}"
    padding: "9px 10px"
  badge-neutral:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.text-muted}"
    rounded: "{rounded.badge}"
    padding: "2px 8px"
  dossier-panel:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.panel}"
    padding: "20px"
  navigation-active:
    backgroundColor: "{colors.text}"
    textColor: "{colors.bg}"
    rounded: "{rounded.control}"
    padding: "6px 10px"
---

# Design System: OpsPilot AI

## Overview

**Creative North Star: "Incident Forensics Lab"**

OpsPilot AI uses warm ivory paper, deep ink, editorial headings and compact operational controls. It feels like an organized investigation dossier: calm, exact and ready for inspection. Evidence IDs, source labels and measured values carry the detail; brand expression stays concentrated in the convergence mark and serif headings.

The world is evidence-first. Quiet rules and tonal paper layers organize dense information without making every item a card. Context, reports and audit detail can expand when needed. The guide favors reading; operational surfaces favor finding a case, inspecting records and making a decision. These are expressions of one visual system, not separate identities.

**Key Characteristics:**

- Warm paper and ink with restrained burnt amber selection.
- Editorial serif headings, familiar sans controls and precise monospace data.
- Flat bordered dossiers with compact, labeled evidence semantics.
- Inspectable charts with explicit units, provenance and uncertainty.

This document records implemented values from `apps/web/app/globals.css`, `apps/web/components/{ui,nav,brand,visuals}.tsx` and the incident roster. `docs/design/BRAND.md` owns asset usage; `docs/design/VISUAL_EXPERIENCE_2.md` owns surface strategy. Frontmatter values describe the light theme. The existing dark override in `globals.css` preserves these roles with ink surfaces, light text and brighter semantic accents; use the CSS variables so components inherit that mapping.

## Colors

The palette combines archival neutrals with sparse operational color; frontmatter names match the implemented CSS custom properties.

### Primary

- **Burnt Amber** (`accent`): primary actions, selected modes, linked evidence references and focus outlines. `accent-hover` darkens the action; `accent-soft` provides its quiet selected surface.

### Secondary

- **Evidence Emerald** (`success` / `success-soft`): supporting evidence, verified simulator recovery and successful states, always paired with a label.
- **Contradiction Rose** (`danger` / `danger-soft`): contradictions, blocked proposals, errors and destructive review controls.
- **Attention Ochre** (`warn` / `warn-soft`): caution and pending review.
- **Telemetry Indigo** (`info` / `info-soft`): connected telemetry, read-only boundaries and informational state.
- **Upload Violet** (`purple` / `purple-soft`): uploaded evidence and categorical distinction.

### Neutral

- **Ivory Ground** (`bg`): the page canvas.
- **White Paper** (`panel`): dossier panels and form fields.
- **Warm Stone** (`panel-2`) and **Layered Stone** (`panel-3`): nested context, selection and chart tracks.
- **Fine Rule** (`border`) and **Strong Rule** (`border-strong`): quiet separation and interactive boundaries.
- **Deep Ink** (`text`): primary reading and active navigation; **Secondary Ink** (`text-muted`) carries supporting prose; **Muted Ink** (`muted`) carries metadata.

**The Labeled Color Rule.** Color supplements visible state, source or relationship text. A green line alone never means proof or approval.

## Typography

**Display Font:** Georgia, with Cambria, Times New Roman, Times and serif fallbacks.
**Body Font:** Geist, with platform sans fallbacks.
**Label/Mono Font:** Geist Mono, with system monospace fallbacks.

**Character:** The serif establishes editorial authority without turning controls into artwork. Sans text supports quick scanning; monospace distinguishes exact identifiers, timestamps, measurements and code. Tabular numerals are enabled globally.

### Hierarchy

- **Page heading:** the frontmatter page-heading role grows to `1.875rem` / `2.25rem` from the small breakpoint. It anchors a surface above a fine rule.
- **Panel heading:** the frontmatter panel-heading role labels a dossier section.
- **Report heading:** serif first and second levels (`1.35rem` and `1.15rem`); deeper headings use sans (`0.95rem`).
- **Body:** report text uses the report-body role; compact UI uses `0.75rem`–`0.875rem` with supporting text muted. Conclusion prose is capped at `70ch` in its implemented component.
- **Label:** exhibit labels are uppercase mono; ordinary navigation and controls use sentence case. Badges use `11px` mono with semibold weight; evidence chips and exact source chronology use `0.65rem`.

**The Exact Data Rule.** Use monospace for record identity and exact values; retain explanatory prose in sans so metadata does not compete with the conclusion.

## Layout

The application shell centers content in a `max-w-7xl` container (`80rem`). Gutters are `16px`, increasing to `24px` at the `640px` breakpoint; the main area has `24px` vertical padding. Shared panel bodies use the panel spacing token. The shell header remains sticky; the document reserves `140px` scroll padding for anchored sections.

Use the established four-pixel rhythm and fine rules to group related content. The intake desk uses the approved asymmetric composition with a `1fr 2.3fr` grid, `28px` gap and `24px` padding. It stacks at `800px` with an `18px` gap; padding reduces to `20px` below `480px`. Incident facts move from four columns to two at that breakpoint; five-stage decision and boundary sequences stack vertically.

Navigation scrolls horizontally below `640px`. The roster keeps an `820px` minimum width inside its labeled horizontal scroller; capability tables use `600px` and the evidence map `560px`. Do not squeeze exact data into unreadable columns. Below `480px`, panel horizontal padding reduces to `16px`, filter text inputs become `16px`, intake controls stack and source chronology narrows its time column. Use the existing responsive behavior instead of hiding record identity or state.

## Elevation & Depth

Dossier panels are flat at rest: the later stylesheet override sets their shadow to none. White paper, warm stone, fine rules and spacing establish hierarchy. Small control shadows remain on buttons and selected navigation. React Flow controls and minimap retain a compact utility shadow (`0 2px 8px rgba(0, 0, 0, 0.08)`) to remain legible over the canvas. This limited depth vocabulary is structural rather than atmospheric.

**The Paper Rule.** Organize dossier content with tone, rules and space before introducing elevation.

## Shapes

Corners are restrained and mostly rectangular: compact badges use the badge radius, ordinary buttons the control radius, filter fields the field radius, dossiers the panel radius and intake the intake radius. Fine borders are `1px`; verification stamps use `2px`. Circular dots and pins indicate status or source observations, rather than becoming decorative shapes.

The original evidence-convergence mark joins three paths at an open observation lens. Follow the light/dark exports, minimum size, clear space and no-distortion rules in `docs/design/BRAND.md`. Signal icons are original `28`-unit vectors with `1.6`-unit strokes; they represent capabilities, not provider endorsement.

## Components

### Buttons

Compact and familiar. The shared medium button uses the frontmatter dimensions and a `150ms` transition. Small buttons are `28px` tall; large buttons are `40px`. Primary is amber with white text, secondary white paper with ink, danger a rose tint that fills on hover, ghost transparent with muted text, and outline transparent with a visible rule. Disabled buttons reduce opacity to `0.4`; preserve the disabled native state. Primary and secondary focus treatments add an accent ring; the global keyboard focus outline is `2px` with `2px` offset. Text links underline on hover.

### Chips

Badges combine text, a compact mono label and a semantic tint or neutral stone surface. Source badges explicitly distinguish simulator, uploaded evidence, connected telemetry and unavailable source. Evidence links use small bordered chips with visible “supports” or “contradicts” text. Selected hypotheses use a stone surface and fine outline; selection remains operable with a button and `aria-pressed`.

### Cards / Containers

Dossier panels use the frontmatter panel treatment and no panel shadow. Optional headers have a bottom rule, `20px` horizontal padding and `14px` vertical padding. Supporting context opens through a native disclosure. Reduce horizontal padding to the established mobile value; use rows and dividers inside a panel rather than nesting dossiers for every fact.

### Inputs / Fields

Toolbar fields use the frontmatter filter-field treatment, a strong fine rule and `0.8rem` text. Login fields are a separate observed variant: `36px` tall, stone background, `8px` corners, `12px` horizontal padding and accent border on focus. Retain visible or accessible labels. Errors use a labeled alert with rose tint and border; unavailable data remains explicit rather than becoming a numeric zero.

### Navigation

Compact sentence-case links use ink on ivory when active, muted text at rest and a stone hover surface. Active links expose `aria-current="page"`. At narrow widths, the strip scrolls without wrapping its links. The skip link appears on keyboard focus and leads to main content.

### Evidence Visuals

Metric bars compare persisted baseline, extreme and current summaries with independent scales and units; they are not a time series. Source chronology uses valid `observed_at` times and opens the corresponding record. Workflow chronology stays in the audit context. Hypothesis maps use emerald solid support edges and rose dashed contradiction edges, with relationship labels and selectable evidence. These are model associations, not proven causes; confidence is explicitly uncalibrated.

Native SVG/CSS handles these small visuals; the established React Flow canvas handles architecture. Counts describe returned records. Unknown, unavailable and empty each remain distinct. Read-only upload and connector investigations expose advisory results; simulator approval controls require an explicit simulator source.

Motion remains subordinate to state: short control transitions and active status pulses. The reduced-motion rule disables animations and transitions globally. Keep textual values and labels available when motion is absent.

## Do's and Don'ts

### Do:

- **Do** use the semantic CSS variables so light and dark themes preserve meaning.
- **Do** pair semantic color with visible labels, exact values and source references.
- **Do** preserve compact sans controls, serif section headings and monospace exact data.
- **Do** use fine rules, quiet paper layers and progressive disclosure for dense evidence.
- **Do** keep units, independent metric scales, source chronology and uncalibrated confidence explicit.
- **Do** keep upload and connector analysis visibly read-only and planned providers visibly planned.

### Don't:

- **Don't** turn persisted summary values into an invented trend or time series.
- **Don't** present model evidence associations or temporal proximity as causal proof.
- **Don't** turn missing data into zero or unknown provenance into simulator authorization.
- **Don't** distort the convergence mark, add glow or imply provider implementation through an icon.
- **Don't** add decorative chart effects or panel shadows that obscure evidence hierarchy.


## Final focused refinement

Pending simulator action controls precede the forensic detail in Analysis. Both
review links reveal that tab and focus the current approval control (or the review
form for a viewer), without submitting a decision. Rationale and exact parameters
remain visible; plan history and blocked-proposal explanations expand on demand.
Metric labels, units and provenance captions use 12 px text, with larger evidence
map labels and an explicit mobile scrolling hint.

Integrations begins with compact implemented-source rows and a separate planned
group. A provider expands its configuration and connection-test controls. Capability
comparison and the complete technical catalog are secondary disclosures. Safety
keeps the five-stage boundary visible and presents seven short, individually
expandable gate summaries with their original technical criteria intact.
