# Temporary Font Style Audit — Manager Daily Report

Status: draft for style review.

Target report inspected:

- `review_packages/role_problem_fit_2026-05-08_tolegen/manager_daily_d42e8246-772e-4a04-bbe7-2b88f45db695_2026-05-08_manager_daily_template_v2.pdf`

Primary source of truth for the current PDF:

- Active template: `manager_daily_template_v2`
- Active version map: `core/app/agents/calls/report_template_assets/active_versions.json`
- PDF build path from artifact metadata: `docx_first_pdf_delivery`
- Actual font/style source for PDF: `scripts/generate_docx_report.js`
- HTML/CSS preview source: `core/app/agents/calls/report_template_assets/manager_daily/manager_daily_template_v2/layout.css`

Important: the current delivered PDF is generated DOCX-first. The CSS preview has its own typography, but it is not the main source of truth for the PDF that goes to Telegram.

## 1. Actual Fonts Embedded In The PDF

The generator asks for `Arial`, but after LibreOffice conversion the PDF embeds these fonts:

| Embedded PDF font | Why it appears |
| --- | --- |
| `LiberationSans` | Regular text, mapped from Arial |
| `LiberationSans-Bold` | Bold text, headings, table emphasis |
| `LiberationSans-Italic` | Quotes, fragments, italic notes |
| `DejaVuSerif-Bold` | Fallback for some symbols / emoji-like glyphs |

Current risk: visually the report is not really using Arial in the final PDF. It is using Liberation Sans, which is okay for Cyrillic, but dense 8-10pt text becomes harder to read.

## 2. PDF/DOCX Type Scale

In `docx`, `TextRun.size` is stored in half-points. So `22` means `11pt`.

| Token | DOCX size | Approx pt | Current use | Readability note |
| --- | ---: | ---: | --- | --- |
| `SZ.h1` | 38 | 19pt | Manager name; large outcome numbers | Clear enough |
| `SZ.h2` | 26 | 13pt | Report title; section headers | Section headers are readable but not very large |
| `SZ.accent` | 24 | 12pt | Defined but currently not used | Candidate for future mid-level emphasis |
| `SZ.body` | 22 | 11pt | Main paragraphs, key lines, default table cells | Borderline for dense PDF tables |
| `SZ.cell` | 20 | 10pt | Compact table text, fragments, dialogue, labels | Main source of difficulty |
| `SZ.meta` | 18 | 9pt | Notes, table headers, scope notes | Too small for operational reading |
| `SZ.caption` | 16 | 8pt | Outcome labels, footer | Too small except for true footer/caption |

Source: `scripts/generate_docx_report.js`, constant `SZ`.

## 3. PDF/DOCX Reusable Text Styles

| Style helper | Font | Size | Weight/style | Color | Where used |
| --- | --- | ---: | --- | --- | --- |
| `cell()` default | Arial -> LiberationSans | 11pt | Regular | `#1A1A1A` | Default table body cells |
| `cell(..., size: SZ.cell)` | Arial -> LiberationSans | 10pt | Regular | Usually black/gray/heading | Compact table body cells |
| `cell(..., bold: true)` | Arial -> LiberationSans-Bold | 11pt | Bold | Contextual | Totals, priorities, statuses |
| `cell(..., italic: true)` | Arial -> LiberationSans-Italic | 11pt or 10pt | Italic | Contextual | Quotes, fragments, "how to" text |
| `headCell()` | Arial -> LiberationSans-Bold | 9pt | Bold | `#1A1A1A` on `#C8DCF0` | Table headers |
| `blockHeading()` | Arial -> LiberationSans-Bold | 13pt | Bold | White on dark blue | Section bars |
| `bodyPara()` default | Arial -> LiberationSans | 11pt | Regular | `#1A1A1A` | Normal paragraph text |
| `bodyPara(..., size: SZ.meta)` | Arial -> LiberationSans | 9pt | Regular | `#888888` | Notes and scope explanations |
| `bodyPara(..., italic: true)` | Arial -> LiberationSans-Italic | 10-11pt | Italic | Usually gray | Partial fragment notes |
| `subHeading()` | Arial -> LiberationSans-Bold | 11pt | Bold | `#1F3864` | "Что произошло", "Фрагмент звонка" |
| `labelCell()` | Arial -> LiberationSans-Bold | 10pt | Bold | `#1F3864` on `#C8DCF0` | Left labels in situation tables |
| Footer | Arial -> LiberationSans | 8pt | Regular | `#888888` | "Конфиденциально..." footer |

## 4. PDF/DOCX Colors Affecting Text Readability

| Token | Hex | Current role | Readability note |
| --- | --- | --- | --- |
| `COLORS.black` | `#1A1A1A` | Main body | Good contrast |
| `COLORS.heading` | `#1F3864` | Section/title emphasis | Good contrast |
| `COLORS.gray` | `#888888` | Meta, notes, secondary table text | Too light when paired with 8-10pt |
| `COLORS.orange` | `#E87722` | Warnings, problem text | Readable, but can dominate |
| `COLORS.red` | `#C0392B` | Priority/problem | Readable |
| `COLORS.green` | `#2E8B57` | Positive/status | Readable |
| `COLORS.sectionText` | `#FFFFFF` | Section header text | Good on dark blue |
| `COLORS.tableHead` | `#C8DCF0` | Table header background | Fine, but header text is only 9pt |

## 5. PDF/DOCX Block Usage

| Report area | Current font style | Source pattern | Notes |
| --- | --- | --- | --- |
| Report title "ЕЖЕДНЕВНЫЙ ОТЧЁТ МЕНЕДЖЕРА" | 13pt, bold, all caps, dark blue, centered | `SZ.h2`, `bold: true`, `allCaps: true` | Readable, but visually close to section headers |
| Manager name | 19pt, bold, black, centered | `SZ.h1` | Clear |
| Date/call count line | 11pt, regular, gray | `SZ.body`, `COLORS.gray` | Could be okay, but gray is light |
| Report type badge | 10pt, bold, orange | `SZ.cell`, `bold: true` | Small but short |
| Day score | 11pt, bold, dark blue | `SZ.body`, `bold: true` | Readable |
| Funnel/coaching notes | 9pt, regular, gray | `SZ.meta`, `COLORS.gray` | Hard to read |
| Outcome numbers | 19pt, bold, status color | `SZ.h1`, `bold: true` | Clear |
| Outcome labels | 8pt, regular, gray, uppercase | `SZ.caption` | Too small |
| Section bars | 13pt, bold, white on dark blue | `blockHeading()` | Readable, but not spacious |
| Money table headers | 9pt, bold, black on light blue | `headCell()` | Too small |
| Money table body | 11pt, regular/bold | `cell()` default | Okay |
| Money explanatory note | 9pt, gray | `bodyPara(..., SZ.meta)` | Hard to read |
| Stage score table headers | 9pt, bold | `headCell()` | Too small |
| Stage score table body | Mostly 11pt; problem column 10pt | `cell()` and `SZ.cell` overrides | Dense |
| Situation day title in section bar | 13pt, bold, white | `blockHeading("СИТУАЦИЯ ДНЯ · ...")` | Long titles wrap inside bar |
| Situation scope note | 9pt, gray | `SZ.meta` | Hard to read |
| Situation focus stage/title/example | 11pt, bold, dark blue | `bodyPara(..., bold: true)` | Okay |
| Situation "Что произошло" label | 11pt, bold, dark blue | `subHeading()` | Okay |
| Situation problem text | 11pt, orange | `bodyPara(..., COLORS.orange)` | Readable |
| Situation partial-fragment note | 10pt, italic, gray | `SZ.cell`, `italic: true` | Hard if important |
| Situation dialogue lines | 10pt, regular, black | `SZ.cell` | Dense; likely should be larger |
| Situation review table labels | 10pt, bold, dark blue on blue fill | `labelCell()` | Dense |
| Situation review table content | 10pt, regular, black | `SZ.cell` | Dense |
| Call breakdown intro | 11pt, regular, gray | `bodyPara(..., COLORS.gray)` | Light |
| Call breakdown headers | 9pt, bold | `headCell()` | Too small |
| Call breakdown "moment" | 11pt, gray, centered | `cell(..., COLORS.gray)` | Light |
| Call breakdown "what" | 11pt, black | `cell()` | Okay |
| Call breakdown fragment | 10pt, italic | `SZ.cell`, `italic: true` | Hard to read |
| Call breakdown recommendation | 11pt, dark blue | `cell(..., COLORS.heading)` | Okay |
| Voice of customer intro | 9pt, gray | `SZ.meta` | Too small |
| Voice table headers | 9pt, bold | `headCell()` | Too small |
| Voice client cell | 10pt | `SZ.cell` | Dense |
| Voice quote | 11pt, italic | `cell(..., italic: true)` | Better than call breakdown fragments |
| Voice interpretation | 10pt, dark blue | `SZ.cell`, `COLORS.heading` | Dense |
| Additional situations section title | 13pt, bold, white | `blockHeading()` | Okay |
| Additional situations intro/scope | 9pt, gray | `SZ.meta` | Hard to read |
| Additional situation inline heading | 11pt bold + 10pt colored type label | direct `TextRun` | Type label is small |
| Additional situation table headers | 9pt, bold | `headCell()` | Too small |
| Additional situation body | 11pt default, some italic | `cell()` | Mixed readability |
| Challenge labels | 10pt, bold, dark blue | custom `clCell()` | Dense |
| Challenge goal | 11pt, bold, dark blue | `SZ.body`, bold | Okay |
| Challenge context | 10pt, gray | `SZ.cell`, gray | Dense/light |
| Challenge phrase | 11pt, italic, dark blue | `SZ.body`, italic | Okay |
| Call tomorrow headers | 9pt, bold | `headCell()` | Too small |
| Call tomorrow priority | 11pt, bold, status color | `cell(..., bold: true)` | Okay |
| Call tomorrow client | 11pt, black | `cell()` | Okay |
| Call tomorrow context | 10pt, gray | `SZ.cell`, gray | Dense/light |
| Call tomorrow recommendation | 10pt, dark blue | `SZ.cell`, heading | Dense |
| All calls headers | 9pt, bold | `headCell()` | Too small |
| All calls number | 11pt, gray | `cell(..., gray)` | Light |
| All calls client | 11pt, black | `cell()` | Okay |
| All calls topic/context | 10pt, gray | `SZ.cell`, gray | Hard to scan |
| All calls status | 11pt, bold, status color | `cell(..., bold: true)` | Okay |
| Footer | 8pt, gray | `SZ.caption` | Fine only as footer |

## 6. HTML/CSS Preview Typography

This section is for `report_preview.html` / CSS preview. It does not currently control the Telegram PDF, but it is useful if we later align preview and PDF.

Global:

| Selector | Style | Where used |
| --- | --- | --- |
| `body` | Arial/Helvetica, `line-height: 1.28`, color `--ink` | Whole HTML report |
| `.meta-line`, `.footer-content` | 18px, gray | Metadata/footer |
| `.footer` | 16px, gray | Page footer |

Hero / title:

| Selector | Style | Where used |
| --- | --- | --- |
| `.hero-title` | 28px, 800 | Hero title |
| `.hero-sub` | 17px, 500 | Hero subtitle |
| `.focus-week` | 16px, 700 | Hero focus line |
| `.section-bar` | 21px, 800, uppercase, letter spacing 0.2px | Section bars |
| `.title-page h1` | 30px, letter spacing 0.02em | Title page heading |
| `.title-page .subtitle` | 17px | Title page subtitle |

Summary / outcome tiles:

| Selector | Style | Where used |
| --- | --- | --- |
| `.tile-value` | 31px, 800 | Tile numbers |
| `.tile-label` | 15px | Tile labels |
| `.outcome-value` | 28px, 800 | Outcome table numbers |
| `.outcome-label` | 13px, 600, uppercase, letter spacing 0.4px | Outcome labels |
| `.summary-box` | 18px | Summary box |
| `.summary-box .progress` | 17px | Progress line |

Situation day:

| Selector | Style | Where used |
| --- | --- | --- |
| `.situation-title` | 15px, 800 | Situation title |
| `.situation-body` | 15px | Situation body |
| `.situation-script` | 13px | Suggested script |
| `.situation-count` | 12px, italic | Situation count |
| `.situation-example` | 13px, line-height 1.5 | Example call |
| `.situation-example-label` | 11px | Example label |
| `.situation-example-contact` | 600 | Contact emphasis |
| `.situation-example-reason` | 12px | Example reason |
| `.situation-scripts` | 13px, line-height 1.7 | Script list |

Voice of customer:

| Selector | Style | Where used |
| --- | --- | --- |
| `.voice-quote` | 13px, italic | Client quote |
| `.voice-meta` | 11px | Meta line |
| `.voice-context` | 11px | Context |
| `.voice-placeholder` | 12px, italic | Empty state |

Call breakdown:

| Selector | Style | Where used |
| --- | --- | --- |
| `.bd-header` | 14px, 600 | Breakdown header |
| `.bd-stage-table` | 12px | Breakdown stage table |
| `.bd-stage-table th` | 11px | Breakdown table headers |
| `.bd-stage-score` | 600 | Stage score |
| `.bd-weak-flag` | 10px | Weak flag |
| `.bd-col` | 12px, line-height 1.6 | Worked/to-fix columns |
| `.bd-col-title` | 11px, 700 | Column labels |
| `.bd-rec` | 13px, line-height 1.5 | Recommendation box |
| `.bd-rec-label` | 11px | Recommendation label |

Stage score / review:

| Selector | Style | Where used |
| --- | --- | --- |
| `.stage-scores-table` | 16px | Stage score table base |
| `.stage-th-*` | 13px, 700, uppercase | Stage score table headers |
| `.stage-label` | 15px | Stage name |
| `.stage-funnel-label` | 14px, 700 | Funnel label |
| `.stage-score` | 16px, 700 | Stage score |
| `.crit-chip` | 10px, line-height 1.4 | Criteria chips |
| `.crit-score` | 700 | Criteria score |
| `.stage-priority-flag` | 13px, 800 | Priority flag |
| `.stage-empty` | 15px | Empty state |
| `.review-grid` | 18px | Two-column review |
| `.review-col h3` | 20px, 800 | Review column heading |

Legacy / optional HTML blocks:

| Selector | Style | Where used |
| --- | --- | --- |
| `.problem-card h3` | 20px, 800, uppercase | Problem card heading |
| `.rec-title` | 20px, 800 | Recommendation title |
| `.priority-pill` | 14px, 800 | Priority badge |
| `.rec-context` | 17px | Recommendation context |
| `.example-title` | 16px, 800 | Before/after example label |
| `.example-box p` | 15px, italic | Example quote |
| `.why-line` | 16px | Why line |
| `.call-table` | 15px | Generic call table |
| `.call-table th` | 15px | Generic call table headers |
| `.table-note` | 16px | Table note |
| `.dynamics-title` | 20px, 800 | Dynamics title |
| `.period-bars` | 15px | Period bars labels |
| `.bar-value.*` | 800 | Period bar numbers |
| `.stage-line` | 18px | Stage line |
| `.memo-card h4` | 18px | Memo heading |

Additional situations / call tomorrow:

| Selector | Style | Where used |
| --- | --- | --- |
| `.add-sit-kind-badge` | 10px, 600, uppercase, letter spacing 0.04em | Additional situation badge |
| `.add-sit-signal` | 10px | Signal count |
| `.add-sit-title` | 13px, 600 | Additional situation title |
| `.add-sit-interp` | 11px, line-height 1.4 | Additional situation interpretation |
| `.add-sit-placeholder` | 12px, italic | Empty state |
| `.ct-client` | 12px, 600 | Call tomorrow client |
| `.ct-time` | 11px | Call tomorrow time |
| `.ct-badge` | 10px, 600, uppercase, letter spacing 0.03em | Call tomorrow status badge |
| `.ct-deadline` | 10px | Call tomorrow deadline |
| `.ct-script` | 11px, italic, line-height 1.4 | Call script |
| `.ct-placeholder` | 12px, italic | Empty state |
| `.section-body table` | 13px | Generic section table |
| `.section-body th` | 12px, uppercase, letter spacing 0.03em | Generic table header |
| `.header-manager` | 28px, 800 | Generic header manager |
| `.header-score` | 18px, 700 | Generic header score |
| `.header-selection-note` | 11px, line-height 1.35 | Selection note |
| `.sub-row td` | 12px | Secondary table row |

## 7. Main Readability Problems To Fix

1. Too much meaningful content is rendered at 9-10pt:
   - table headers;
   - dialogue fragments;
   - call breakdown fragments;
   - voice interpretation;
   - call tomorrow context/recommendation;
   - all calls topic/context.

2. Gray text is both small and low-contrast:
   - `#888888` at 8-10pt is hard to read in PDF.

3. Dense tables have no explicit line-height control:
   - DOCX uses tight table paragraphs plus small cell margins.

4. Section hierarchy is compressed:
   - `h2` section headers are only 13pt, close to body emphasis.

5. There are two style systems:
   - PDF/DOCX styles in `scripts/generate_docx_report.js`;
   - HTML preview styles in `layout.css`;
   - they are not aligned, so changing only CSS will not fix the delivered PDF.

## 8. Candidate Direction For The Next Edit

Do not apply yet; this is a working proposal for discussion.

| Token / style | Current | Candidate |
| --- | ---: | ---: |
| `SZ.h1` | 19pt | 20-21pt |
| `SZ.h2` | 13pt | 14-15pt |
| `SZ.body` | 11pt | 11.5-12pt |
| `SZ.cell` | 10pt | 10.8-11pt |
| `SZ.meta` | 9pt | 10pt |
| `SZ.caption` | 8pt | 8.8-9pt |
| `COLORS.gray` | `#888888` | `#5F6368` or darker |
| Table header size | 9pt | 10pt |
| Footer | 8pt | Keep 8pt or 8.5pt |

Suggested first safe change:

- Increase `cell`, `meta`, and table headers before changing layout structure.
- Darken `COLORS.gray`.
- Keep page count under control by checking the same Толеген PDF after each change.

