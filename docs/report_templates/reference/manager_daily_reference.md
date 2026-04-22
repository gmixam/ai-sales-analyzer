# Report Template References

## manager_daily_reference.md

Status: reference pack for Codex / visual source of truth
Reference type: semantic + visual contract
Target artifact: final PDF report for manager daily run
Primary visual source: `Ежедневный отчет для менеджера.pdf`

### 1. Purpose

This file is the repo-friendly visual and structural source of truth for the `manager_daily` report.

Codex should **not invent a new layout**. The goal is to reproduce the existing reference style as closely as possible using stable template assets and PDF rendering.

### 2. Reference source

Base reference: `Ежедневный отчет для менеджера.pdf`

Observed target characteristics from the reference:

* report is multi-page, portrait, A4-like
* every page has a light header line with period / manager / department context
* major sections use dark blue horizontal title bars
* the document mixes metric tiles, highlight banners, two-column analysis blocks, recommendation cards, a tabular call summary, and a final memo/reference page

### 3. Document role and tone

Audience:

* primary: manager
* secondary: ROP

Tone:

* supportive but direct
* coaching-oriented, not bureaucratic
* concise, readable, action-driven
* strengths are acknowledged, but the document clearly pushes one main focus for the next day

Confidentiality footer style:

* confidential
* only for manager and ROP

### 4. Global layout rules

#### 4.1 Page structure

* portrait orientation
* white or very light neutral background
* top thin metadata line on every page
* footer line on every page with confidentiality note and page number
* visually dense but still readable
* generous section spacing, but not a slide deck style

#### 4.2 Primary visual language

* dark blue section bars for primary headings
* green used for positive signals and strong results
* warm yellow / amber used for caution / focus / development
* red used for main problem / critical issue
* pale tinted backgrounds inside cards
* large bold numbers for day metrics
* strong headline hierarchy

#### 4.3 What must not be redesigned

* do not replace the report with a plain text dump
* do not collapse everything into one long narrative
* do not remove metric tiles and banners
* do not replace recommendation cards with a generic bullet list
* do not move the call table to the beginning
* do not remove the memo page

### 5. Required section order

1. top metadata line
2. hero header block
3. `ИТОГ ДНЯ`
4. short executive narrative
5. `Сигнал дня`
6. `ГЛАВНЫЙ ФОКУС НА ЗАВТРА`
7. `РАЗБОР`

   * `Что сработало`
   * `Над чем работать`
8. `КЛЮЧЕВАЯ ПРОБЛЕМА ДНЯ`
9. `РЕКОМЕНДАЦИИ`
10. `ИТОГИ ЗВОНКОВ`
11. call list table
12. note `Показаны первые N из N...`
13. `ДИНАМИКА ПО ФОКУСНОМУ КРИТЕРИЮ`
14. short interpretation paragraph
15. `ПАМЯТКА`
16. explanatory mini-reference blocks

### 6. Block-by-block visual contract

#### 6.1 Top metadata line

Content:

* report short name
* manager name
* exact date
* department
* product / direction

Visual form:

* thin line near page top
* small muted text
* not a dominant title

#### 6.2 Hero header block

Purpose:

* immediately identify report type and day context

Content:

* main title: daily call review
* manager name
* human-readable date
* short focus-of-week line

Visual form:

* large dark blue banner
* white title text
* secondary text inside same block
* compact lightning / accent style for focus line is acceptable

#### 6.3 `ИТОГ ДНЯ`

Purpose:

* fast top-level reading in 10 seconds

Content tiles:

* total calls
* average score
* % strong calls
* % basic
* % problematic

Visual form:

* horizontal row of 4–5 tiles
* each tile has a large numeric value and a short label
* tile background tint differs by meaning
* average score and good shares visually stand out

#### 6.4 Executive narrative

Purpose:

* interpret the day, not just state numbers

Content:

* 1 paragraph summarizing the day quality
* 1 progress line vs period average with delta
* must contain both numeric comparison and human-readable meaning

Visual form:

* light tinted box under metric tiles
* progress line highlighted inline

#### 6.5 `Сигнал дня`

Purpose:

* surface one positive concrete example

Content:

* best call / strongest observed pattern
* exact time and client reference when available
* short explanation why this is the correct model behavior

Visual form:

* green positive banner/card
* starts with checkmark-style emphasis

#### 6.6 `ГЛАВНЫЙ ФОКУС НА ЗАВТРА`

Purpose:

* one dominant next-day behavior

Content:

* only one main behavioral instruction
* short imperative phrasing
* ideally one sentence plus one short reinforcement sentence

Visual form:

* yellow / warm highlighted banner
* visually prominent
* should feel like the main coaching takeaway

#### 6.7 `РАЗБОР`

Purpose:

* split the day into strengths vs growth areas

Structure:

* left column: `Что сработало`
* right column: `Над чем работать`

Visual form:

* two-column block under one dark blue section header
* positive list in green
* problem list in red/orange
* each bullet contains metric score and short explanation

Rules:

* left column shorter and cleaner
* right column more detailed and more action-oriented
* do not turn into paragraphs only

#### 6.8 `КЛЮЧЕВАЯ ПРОБЛЕМА ДНЯ`

Purpose:

* name the central issue in one sentence and explain it

Content:

* short red headline
* 1 paragraph explaining why this is the main blocker
* should connect several symptoms into one core problem

Visual form:

* red-tinted warning box
* strong title in red + dark blue emphasis allowed

#### 6.9 `РЕКОМЕНДАЦИИ`

Purpose:

* concrete coaching actions from the day

Expected volume:

* usually up to 5 recommendations

Each recommendation card contains:

* numbered title
* priority tag (`Сделай завтра` or `На неделе`)
* short context with a real call example when available
* `Как звучало`
* `Как лучше`
* `Почему это работает`

Visual form:

* stacked cards across pages
* pale background card
* vertical colored accent line at left
* title in dark blue
* small priority pill/tag on the right
* two side-by-side quote/example boxes for “as was” vs “better way”

Rules:

* `Как звучало` and `Как лучше` should remain visually separated
* `Почему это работает` must stay as its own line, not buried in the body
* recommendations are day-level coaching, not generic sales theory

#### 6.10 `ИТОГИ ЗВОНКОВ`

Purpose:

* summarize dispositions and expose open-call issue

Content:

* count of `Договорились`
* `Перенесли`
* `Отказ`
* `Открыт`
* one short explanation about why open status matters

Visual form:

* 4 compact metric counters
* open status visually marked with warning emphasis

#### 6.11 Call list table

Purpose:

* give a compact operational list of the day

Columns:

* time
* client
* duration
* type
* status
* next step
* deadline

Visual form:

* grid table with dark blue header row
* status cells use semantic fills:

  * green = agreed
  * amber = postponed
  * red = refusal
  * peach/light orange = open
* multiple pages are allowed if needed

Rules:

* table should stay readable in PDF
* use compact row height
* if too many rows, show first N and add note about full list in CRM

#### 6.12 `ДИНАМИКА ПО ФОКУСНОМУ КРИТЕРИЮ`

Purpose:

* show whether the target skill is improving

Content:

* selected criterion name
* comparison of 2 periods
* simple mini-chart or bars
* inline stage comparisons for adjacent key stages

Visual form:

* teal / blue-green section header
* compact chart area with short numeric labels
* short explanatory paragraph below

Rules:

* this is not a huge analytics chart
* it is a narrow confirmation block for the day focus

#### 6.13 `ПАМЯТКА`

Purpose:

* make the report self-explanatory without external instructions

Sub-blocks in memo page:

* call level definitions (`Сильный`, `Базовый`, `Проблемный`)
* call status definitions (`Договорились`, `Перенёс`, `Отказ`, `Открыт`)
* evaluation stages
* recommendation priority meanings

Visual form:

* simple explanatory page
* two-column or grouped text blocks
* lower visual intensity than first pages
* acts like appendix/reference

### 7. Semantic contract for data filling

The renderer should fill the template, not compose a brand new document.

Mandatory semantic blocks:

* day summary numbers
* human-readable narrative
* one positive signal
* one main focus for tomorrow
* strengths list
* weaknesses list
* one core problem statement
* recommendations with examples
* call outcome counters
* call table
* focus criterion dynamics
* memo block

Optional / bounded blocks:

* model-dependent richer phrasing
* polished synthesis paragraphs
* exact example quotes if available

Placeholder behavior:

* keep the block
* show bounded placeholder / fallback text
* do not silently drop key sections

### 8. Mapping hints for Codex

* summary metrics -> top tiles
* narrative summary -> executive narrative box
* best call / positive example -> `Сигнал дня`
* main coaching focus -> `ГЛАВНЫЙ ФОКУС НА ЗАВТРА`
* stage strengths -> `Что сработало`
* stage gaps -> `Над чем работать`
* synthesized root cause -> `КЛЮЧЕВАЯ ПРОБЛЕМА ДНЯ`
* recommendation payload -> recommendation cards
* call outcomes -> counters + call table
* period comparison -> dynamics block

### 9. Allowed simplifications

Allowed only if exact visual reproduction is too expensive for the current bounded step:

* slightly simpler typography
* fewer decorative accents
* CSS-based PDF instead of exact desktop publishing reproduction

Not allowed:

* removing whole sections
* collapsing recommendation cards into bullets only
* replacing the table with a plain list
* replacing the memo page with a one-line footer note

### 10. Acceptance criteria

The result is acceptable only if:

* the final PDF clearly looks like the same class of document as the reference
* the section order is preserved
* the top metrics area is tile-based
* the review block remains two-column
* recommendations are card-based with `Как звучало / Как лучше / Почему это работает`
* the call list remains a real table
* the focus dynamics block is preserved
* the memo page is present
* the output feels like a finished manager report, not an AI-generated text export

### 11. Versioning recommendation

Recommended active template id:

* `manager_daily_template_v2`

If a separate layout spec is needed, use:

* `manager_daily_layout_v1`
* `manager_daily_content_contract_v1`
