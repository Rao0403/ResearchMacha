# ResearchMacha interface audit and design system

This document is the implementation reference for the ResearchMacha product UI. It describes the current interface, the target visual direction, and the rules that future screens must follow.

## Product and audience

ResearchMacha is a local-first research workspace for students and researchers who need to discover papers, inspect evidence, read PDFs, compare findings, and preserve cited outputs. The interface should feel like a quiet research tool: dense enough for repeated work, calm enough for long reading sessions, and explicit about evidence and degraded AI output.

The product is an application, not a marketing site. Primary actions and current work should appear before explanatory copy.

## Screen inventory

| Route | Current screen | Classification | Primary purpose | Important states |
| --- | --- | --- | --- | --- |
| `/` | `ResearchWorkflowPage` | Primary | Turn a question into selected papers and a cited brief | empty, discovering, awaiting approval, importing, analyzing, blocked, synthesizing, done, degraded |
| `/reader` | `ReaderPage` | Primary | Upload or open a PDF | empty, uploading, processing, ready, degraded, failed |
| `/reader/:paperId` | `ReaderPage` | Primary | Read a paper with generated notes, highlights, citations, and chat | loading, processing, ready, degraded, failed, reanalyzing |
| `/batch-summary` | `BatchSummaryPage` | Primary | Upload and compare multiple papers | empty, uploading, processing, mixed failure, summarizing, ready, degraded |
| `/papers/:paperId` | `ReaderPage` | Compatibility alias | Open an existing reader link | same as canonical reader route |
| `/debug/library` | `LibraryPage` | Promote later | Browse saved papers | loading, empty, populated, error |
| `/debug/projects` | `ProjectListPage` | Replace later | Browse persisted projects | loading, empty, populated, error |
| `/debug/projects/:projectId` | `ProjectWorkspacePage` | Legacy | Older step-by-step project workflow | draft through synthesized |
| `/debug/discover` | `SearchPage` | Legacy | Standalone arXiv search/import | empty, searching, results, importing, error |
| not routed | `PaperWorkspacePage` | Obsolete candidate | Older paper workspace | processing, ready, error |

## Shared component inventory

- `PdfViewer`: PDF rendering, paging, zoom, loading, and errors.
- `GenerationNotice`: generation-mode and degraded-result disclosure.
- `ResearchCitationLink`: cross-paper citation provenance and reader deep linking.
- `useSingleFlightPolling`: request-scoped background status polling.
- Global CSS controls: buttons, inputs, panels, status pills, tabs, tables, empty states, and page containers.

The current component layer lacks shared page headers, alerts, loading skeletons, reusable status components, and consistent form primitives. Similar presentation is consequently repeated inside individual pages.

## Current visual issues

### Structure and proportions

- The fixed 300px sidebar consumes too much laptop width and contains persistent promotional copy unrelated to the current task.
- General pages and the reader share one container model even though the reader needs substantially more horizontal space.
- Large introductory headers delay access to the actual workflow.
- Reader, batch, workflow, and legacy pages use overlapping but different panel conventions.
- The 2,000-line global stylesheet makes page-specific behavior and obsolete selectors difficult to distinguish.

### Typography and spacing

- Heading sizes and serif usage vary by selector grouping rather than semantic level.
- Large radii, shadows, padding, and pill buttons make dense research content feel inflated.
- Long abstracts, findings, warnings, and citations do not share a predictable reading width.
- Tables and cards use different spacing systems.

### Color and states

- The warm cream, brown, orange, gradients, and background grid dominate the content.
- Status colors are not consistently accompanied by text or icons.
- Loading, empty, warning, blocked, degraded, and failed states use inconsistent structures.
- Focus treatment exists for text fields but is incomplete for links, tabs, citation controls, and icon buttons.

### Workflow presentation

- Technical trace detail competes with the human workflow in the research screen.
- Candidate comparison is dense but not easy to scan on common laptop widths.
- Batch output is a large text table rather than an evidence-oriented comparison.
- Generated notes, source highlights, warnings, and researcher-authored content do not yet have a complete visual taxonomy.

## Target visual direction

The target is a restrained research workstation with cool neutral surfaces, compact controls, clear evidence provenance, and minimal decoration.

### Color tokens

| Token | Value | Use |
| --- | --- | --- |
| `--color-canvas` | `#f6f7f9` | Application background |
| `--color-surface` | `#ffffff` | Primary panels and controls |
| `--color-surface-subtle` | `#f0f3f7` | Secondary grouping and hover states |
| `--color-surface-strong` | `#e7ebf1` | Selected and pressed neutral states |
| `--color-text` | `#172033` | Primary text |
| `--color-text-muted` | `#637083` | Secondary text |
| `--color-text-subtle` | `#7d8898` | Metadata and placeholders |
| `--color-border` | `#d9e0e8` | Default borders |
| `--color-border-strong` | `#bcc7d4` | Emphasized boundaries |
| `--color-accent` | `#315bd6` | Primary action and active navigation |
| `--color-accent-hover` | `#2448b8` | Primary action hover |
| `--color-accent-soft` | `#e9efff` | Selected and informational backgrounds |
| `--color-success` | `#237a57` | Ready and successful states |
| `--color-warning` | `#9a5b13` | Warnings and degraded states |
| `--color-danger` | `#b42318` | Failure and destructive states |
| `--color-focus` | `#6b8cff` | Focus ring |

Color must never be the only status signal. Every state includes a text label and, when helpful, an icon.

### Typography

- Application font: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`.
- Research-title font: `Charter, "Iowan Old Style", Georgia, serif`.
- Base size: 16px with 1.5 line height.
- UI metadata: 12px or 13px; never below 12px.
- Body and control text: 14px to 16px.
- Section heading: 20px to 24px.
- Page heading: 28px to 32px, with no viewport-scaled typography.
- Comfortable prose width: 68 to 76 characters.

### Spacing, shape, and elevation

- Spacing scale: 4, 8, 12, 16, 24, 32, 48, and 64px.
- Radius scale: 4px for compact controls, 8px for controls/cards, 12px for major surfaces.
- Standard control height: 40px; compact control height: 34px.
- Shadows are reserved for overlays or truly elevated surfaces. Bordered surfaces are the default.
- Avoid cards inside cards. Use dividers, headings, and whitespace within a primary surface.

### Layout widths

- Desktop navigation: 224px.
- Standard content: maximum 1120px.
- Comparison content: maximum 1440px.
- Reader: full available width with 24px outer gutters.
- Desktop reader split at 1200px and above: 68% PDF / 32% side panel.
- Reader split from 1100px through 1199px: 62% PDF / 38% side panel.
- Below 1100px: PDF first, side panel second so the document never becomes a narrow preview beside the desktop navigation.
- Page gutters: 32px desktop, 24px compact laptop, 16px mobile.

### Responsive breakpoints

- `1200px`: wide reader and comparison layout.
- `1100px`: stacked reader threshold.
- `960px`: compact navigation threshold.
- `720px`: mobile navigation and single-column forms.
- `480px`: icon-only primary navigation with accessible labels.

Primary verification viewports are 1440x900, 1280x800, 1024x768, and 390x844.

## Shared component vocabulary

- `PageHeader`: compact title, description, metadata, and actions.
- `Button`: primary, secondary, ghost, and danger variants; regular and compact sizes.
- `Field`: label, control, help text, and validation message.
- `Surface`: default, subtle, and inset groupings.
- `StatusBadge`: semantic status text with an optional icon.
- `Alert`: information, warning, danger, and success messages.
- `EmptyState`: brief explanation plus at most one primary and one secondary action.
- `Skeleton`: layout-preserving loading placeholder.
- `Tabs`: keyboard-operable view switching.
- `ProgressSteps`: human-readable workflow progression.
- `CitationChip`: compact source page; expands or links to provenance.

Components must expose semantic HTML and accessible names. Visual variants must not encode business behavior.

## Page composition

### Application shell

- Compact navigation containing Research, Reader, Compare, and Library.
- Remove the persistent promotional card.
- Standard pages use the centered 1120px container.
- Reader opts into the wide layout.
- Mobile uses a compact top navigation rather than retaining the fixed sidebar.

### Research workflow

- Question input is the first actionable element.
- A four-step progress model communicates Discover, Select, Analyze, and Synthesize.
- Candidate cards emphasize identity, relevance, rationale, and selection.
- Technical trace details remain available inside a collapsed disclosure.
- Findings use consistent evidence blocks rather than generic AI prose cards.

### PDF reader

- PDF is visually dominant.
- Side panel contains AI Notes, Highlights, Chat, and later My Notes.
- Summary sections share one hierarchy and citation treatment.
- Processing overlays preserve layout and previous successful notes.
- Chat input remains visible without reducing the PDF to a narrow column.

### Batch comparison

- Dimensions form rows and papers form columns.
- Paper headers and the dimension column remain visible while scrolling.
- Agreements and differences appear before detailed comparison.
- Citation provenance stays within the relevant comparison cell.

### Library and projects

- Prefer compact lists over promotional cards.
- Search, filters, status, timestamps, and the next action remain visible.
- Empty states explain the first productive action.

## Interaction and accessibility rules

- All workflows must be completable with a keyboard.
- Every interactive element receives a visible `:focus-visible` ring.
- Background status changes use polite live regions.
- Loading indicators retain the final layout dimensions where practical.
- Errors identify what failed and provide a recovery action when available.
- Motion is subtle and disabled under `prefers-reduced-motion`.
- Content reflows without page-level horizontal scrolling; only intentional comparison regions may scroll horizontally.
- Tabs follow standard tab/tabpanel keyboard and ARIA behavior.
- Icon-only controls always have an accessible name and tooltip only when the label is otherwise unavailable.

## Compatibility and cleanup strategy

- Introduce new tokens and primitives behind compatibility aliases first.
- Migrate primary screens one at a time with their tests.
- Promote Library and Projects only in their scheduled commits.
- Preserve `/papers/:paperId` as a compatibility route until the final integration pass.
- Remove legacy/debug pages and obsolete selectors only after canonical replacements are verified.
- Do not add a full UI template, Tailwind, shadcn, or a component framework during this redesign.
