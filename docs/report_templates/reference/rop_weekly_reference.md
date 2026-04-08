# Report Template References

## rop_weekly_reference.md

Status: reference pack for Codex / visual source of truth
Reference type: semantic + visual contract
Target artifact: final PDF report for weekly ROP run
Primary visual source: `Еженедельный отчет для РОП.pdf`

### 1. Purpose

This file is the repo-friendly visual and structural source of truth for the `rop_weekly` report.

Codex should **not redesign the weekly report**. The goal is to reproduce the existing management-report format as closely as possible using stable template assets and PDF rendering.

### 2. Reference source

Base reference: `Еженедельный отчет для РОП.pdf`

Observed target characteristics from the reference:

* multi-page portrait management report
* strong first page with large title and `Что внутри` block
* heavy use of dark blue section bars
* dashboard and trend tables are key blocks, not optional
* risk managers are rendered as separate manager cards
* top/anti-top and next-week actions are managerial decision blocks
* final CRM business-results block is present even when data is missing

### 3. Audience and tone

Audience:

* ROP and leadership only
* explicitly not for managers

Tone:

* managerial
* concise, decisive, action-oriented
* no motivational language for reps
* should prioritize where to intervene this week

Footer style:

* for ROP and leadership
* not for manager distribution

### 4. Global layout rules

#### 4.1 Page structure

* portrait orientation
* repeated top metadata line
* footer with confidentiality and page number
* dense report, but highly structured

#### 4.2 Primary visual language

* dark blue bars for main numbered sections
* green for best / positive / support
* red for risk / urgent / decline
* amber for observation / medium priority
* teal for CRM/business-results section
* pastel card backgrounds
* table headers in dark blue

#### 4.3 What must not be redesigned

* do not remove numbered section bars
* do not replace dashboard table with narrative text
* do not remove trend table
* do not merge risk managers into one paragraph
* do not replace ROP action table with bullets only
* do not hide CRM placeholder block if business data is absent

### 5. Required section order

1. top metadata line
2. large weekly title page
3. subtitle line
4. `ЧТО ВНУТРИ`
5. department/team coverage line
6. `1. ДАШБОРД НЕДЕЛИ`
7. dashboard interpretation note
8. `2. ДИНАМИКА: НЕДЕЛЯ К НЕДЕЛЕ`
9. best / worrying dynamics mini-lists
10. `3. ЗОНЫ РИСКА — РЕАКЦИЯ ДО КОНЦА НЕДЕЛИ`
11. per-manager risk cards
12. `4. СИСТЕМНЫЕ ПРОБЛЕМЫ КОМАНДЫ`
13. system issue cards
14. `5. ТОП И АНТИТОП ПЕРИОДА`
15. best-period / attention-needed paired cards
16. `6. ЗАДАЧИ РОПа НА СЛЕДУЮЩУЮ НЕДЕЛЮ`
17. action table
18. `7. БИЗНЕС-РЕЗУЛЬТАТЫ ПЕРИОДА`
19. CRM placeholder or filled table
20. final footer / confidentiality

### 6. Block-by-block visual contract

#### 6.1 Top metadata line

Content:

* weekly report
* week number
* period range
* department / direction
* confidentiality

Visual form:

* thin, muted line above the main content on every page

#### 6.2 Large title page

Purpose:

* make the artifact look like a formal managerial weekly report

Content:

* huge title `ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ`
* short subtitle like `Качество звонков · Зоны риска · Задачи на неделю`
* line with department / week / date range

Visual form:

* oversized title
* generous white space
* thin divider line
* not a dashboard yet

#### 6.3 `ЧТО ВНУТРИ`

Purpose:

* orient the reader before the analytical pages

Content:

* bullet list of major sections
* short team composition line below

Visual form:

* dark blue filled box with white text
* compact bullet structure
* should visually anchor the first page

#### 6.4 `1. ДАШБОРД НЕДЕЛИ`

Purpose:

* 30-second status scan of the whole team

Columns:

* manager
* department
* calls
* average score
* trend
* % strong
* % problematic
* stop flags
* signal

Visual form:

* large wide table
* dark blue header row
* score cells and signal cells color-coded
* trend text/sign remains visible
* signal column must visually stand out

Rules:

* this table is mandatory
* do not turn it into cards or bullets

#### 6.5 Dashboard interpretation note

Purpose:

* explain how to read the signal colors/statuses

Visual form:

* pale note box under dashboard table
* short paragraph, not long text

#### 6.6 `2. ДИНАМИКА: НЕДЕЛЯ К НЕДЕЛЕ`

Purpose:

* compare current week vs previous week

Content:

* manager
* previous period score
* current period score
* delta
* trend
* stage-by-stage deltas

Visual form:

* big matrix table
* dark blue header row
* green positive deltas
* red negative deltas
* neutral grey for flat values

Rules:

* keep it tabular
* compact numeric presentation is acceptable
* do not replace with a chart-only block

#### 6.7 Best / worrying dynamics mini-lists

Purpose:

* summarize who improved and who regressed

Content:

* short list of strongest positive dynamics
* short list of worrying dynamics

Visual form:

* two side-by-side text clusters below trend tables
* green for best
* red/orange for worrying

#### 6.8 `3. ЗОНЫ РИСКА — РЕАКЦИЯ ДО КОНЦА НЕДЕЛИ`

Purpose:

* identify who requires immediate managerial reaction

Visual form:

* strong red section bar
* one intro sentence about number of managers in risk

##### Risk manager card structure

Each card must include:

* manager name
* department
* calls
* average score
* `Проблема` summary
* `Действие для РОПа`
* `Этапы П2` row with compact stage values

Card visual form:

* pale tinted card with left red accent border
* two-column content:

  * problem/identity on left
  * action for ROP on right
* mini stage strip at bottom

Rules:

* one manager = one card
* keep cards scannable and repeatable
* this is not free-form prose

#### 6.9 `4. СИСТЕМНЫЕ ПРОБЛЕМЫ КОМАНДЫ`

Purpose:

* highlight issues that are team-wide, not individual

Each system issue card includes:

* count `X из Y менеджеров`
* issue title
* why it matters / quantitative sign
* `Действие`

Visual form:

* stacked cards with large count column on the left
* each card has its own tint/accent color
* title in dark blue
* action line emphasized

Rules:

* keep count visually large
* action must be explicit, not hidden in paragraph text

#### 6.10 `5. ТОП И АНТИТОП ПЕРИОДА`

Purpose:

* create clear management contrast between best and most problematic case

Content:

* left card: best period / best manager
* right card: requires attention / worst case

Visual form:

* two side-by-side cards
* green best card
* red attention card
* recommendation line for ROP below each card

Rules:

* retain side-by-side comparison if page width allows
* if stacked, still keep visual pairing obvious

#### 6.11 `6. ЗАДАЧИ РОПа НА СЛЕДУЮЩУЮ НЕДЕЛЮ`

Purpose:

* convert analysis into a weekly action plan

Columns:

* manager
* priority
* weekly task
* how to verify
* deadline

Visual form:

* full table
* dark blue header row
* priority text color-coded by urgency

Rules:

* table is mandatory
* this is the main action output of the weekly report

#### 6.12 `7. БИЗНЕС-РЕЗУЛЬТАТЫ ПЕРИОДА`

Purpose:

* connect quality analysis to CRM outcomes when available

Content:

* intro note that section is filled from CRM if data exists
* table with business metrics

Visual form:

* teal section bar
* light cyan/teal note box
* CRM table below

Rules:

* if CRM values are absent, keep the block and show placeholders
* do not silently remove it

### 7. Semantic contract for data filling

The renderer should fill a stable managerial template, not generate a new report shape each time.

Mandatory semantic blocks:

* title page
* dashboard
* weekly dynamics
* best/worrying dynamics summary
* risk-zone manager cards
* system problems
* top/anti-top
* next-week ROP tasks
* CRM/business-results section

Optional / bounded blocks:

* richer synthesis text
* LLM-composed managerial summary paragraphs
* additional narrative context when data quality allows

Placeholder behavior:

* keep the section
* use placeholders or explanatory note
* do not remove core management blocks

### 8. Mapping hints for Codex

* team aggregates -> dashboard table
* previous/current week comparison -> dynamics matrix
* risk signal managers -> zone-risk cards
* widespread criterion failures -> system-problem cards
* strongest / weakest manager or period -> top/anti-top cards
* planned coaching actions -> ROP task table
* CRM metrics -> business-results section

### 9. Allowed simplifications

Allowed only in bounded form:

* slightly simplified typography
* CSS-based rendering instead of exact desktop layout
* reduced decorative icons if not essential

Not allowed:

* removing numbered sections
* turning dashboard into plain bullets
* removing per-manager risk cards
* dropping the ROP task table
* dropping CRM placeholder area

### 10. Acceptance criteria

The result is acceptable only if:

* the PDF clearly reads as a formal weekly management report
* page 1 contains big title + `Что внутри` orientation block
* dashboard table exists and is color-coded
* week-to-week dynamics matrix exists
* risk section uses repeated manager cards
* system issues use repeated count/action cards
* top/anti-top comparison exists
* ROP next-week tasks remain a real table
* CRM/business-results block is present even with placeholders
* output feels like the same report family as the source PDF, not a generic analytics export

### 11. Versioning recommendation

Recommended active template id:

* `rop_weekly_template_v1`

If a separate layout spec is needed, use:

* `rop_weekly_layout_v1`
* `rop_weekly_content_contract_v1`
