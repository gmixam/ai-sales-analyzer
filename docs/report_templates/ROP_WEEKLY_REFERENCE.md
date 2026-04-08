# ROP_WEEKLY_REFERENCE

Status: approved repo-local extracted reference from `Еженедельный отчет для РОП.pdf`  
Purpose: give Codex a text-native source of truth for the `rop_weekly` output shape without depending on PDF access.

## 1. What this report is

`rop_weekly` is a weekly management report for the sales head / ROP.

It is not a manager-facing coaching note.
It is a team-level operational control report for one selected weekly period.

Its job is to answer:
- who is stable, growing, regressing or in a risk zone;
- where immediate reaction is needed this week;
- which problems are systemic vs individual;
- what exactly the ROP should do next week;
- what business-result placeholders should later connect from CRM.

## 2. Audience and tone

Primary audience:
- ROP;
- sales leadership / management.

Tone:
- managerial;
- direct;
- prioritised;
- action-oriented;
- less motivational than `manager_daily`;
- suitable for internal control, not for forwarding to managers unchanged.

The PDF explicitly positions this report as:
- confidential;
- for ROP and management;
- not for direct sharing with managers.

## 3. Visual / structural intent from the PDF

The report is built as a structured management pack:
1. cover page / intro;
2. weekly dashboard table;
3. week-over-week dynamics;
4. risk-zone manager cards;
5. systemic team problems;
6. top / anti-top of the period;
7. next-week ROP tasks table;
8. business-results placeholder block;
9. leader memo / legend.

The flow moves from:
- quick entry,
- to diagnosis,
- to action plan,
- to optional business context,
- to memo / interpretation reference.

## 4. Canonical report order

Recommended section order for implementation:

1. Header / cover
2. What is inside
3. Dashboard of the week
4. Week-over-week dynamics
5. Risk zones - reaction this week
6. Systemic team problems
7. Top and anti-top of the period
8. ROP tasks for next week
9. Business results of the period
10. Leader memo / legend
11. Footer / generation note

## 5. Required sections and fields

## 5.1 Header / cover
Required:
- report_title = "Еженедельный отчёт" or equivalent
- subtitle explaining report purpose
- department / business context
- week label
- date range

Optional:
- confidentiality marker
- audience note

## 5.2 What is inside
Required:
- a short list of included sections

This is packaging but useful for readability.

## 5.3 Dashboard of the week
Required:
- one row per manager
- fields:
  - manager_name
  - department
  - calls_count
  - average_score
  - trend_label
  - strong_calls_pct
  - problematic_calls_pct
  - stop_flags_pct or equivalent
  - status_signal

Status signal vocabulary from the PDF:
- `Эталон`
- `Растёт`
- `Стабильно`
- `Наблюдение`
- `Зона риска`

This section is the 30-second entry point.

## 5.4 Week-over-week dynamics
Required:
- previous period score
- current period score
- delta
- trend
- stage-level deltas

The PDF shows stage columns:
- E1 primary / opening
- E2 qualification
- E3 discovery
- E4 proposal
- E5 objections
- E6 closing
- transitions

Also required:
- short summary block:
  - best dynamics of the period
  - alarming dynamics of the period

This section is more diagnostic than the dashboard.

## 5.5 Risk zones - reaction this week
Required:
- dedicated cards for managers requiring action this week
- each card should include:
  - manager name
  - department
  - calls_count
  - average_score
  - core problem statement
  - action for the ROP
  - stage profile snapshot

Important:
- this section should be selective, not all managers
- focus on those with real weekly priority

The PDF examples include:
- Antон
- Аскар
- Ибрагим
- Толеген

## 5.6 Systemic team problems
Required:
- problems that affect many managers
- for each item include:
  - how many managers are affected
  - problem title
  - short explanation
  - recommended systemic action
  - timing / follow-up note if available

Examples seen in the PDF:
- no opening value / purpose
- no link from client answer to benefit
- call ends without fixed next step
- weak transitions between stages

This section is explicitly about team-wide issues where individual coaching alone is insufficient.

## 5.7 Top and anti-top of the period
Required:
- one "best period" block
- one "requires attention" / anti-top block

Each block should contain:
- manager
- supporting metrics
- short interpretation
- one recommendation to the ROP

This section is compact and executive-friendly.

## 5.8 ROP tasks for next week
Required:
- one action table
- fields:
  - manager
  - priority
  - task for next week
  - how to verify
  - deadline

Priority vocabulary from the PDF:
- `Критично`
- `Высокий`
- `Средний`
- `Поддержка`

This is one of the most important sections.
The report should end not with diagnosis only, but with a concrete action list.

## 5.9 Business results of the period
Required in contract:
- section placeholder must exist

Preferred fields:
- manager
- calls_count
- agreed_count
- rescheduled_count
- refusal_count
- conversion_pct
- deal_amount or equivalent

Important:
- in first implementation this section may remain placeholder / partially filled
- the PDF clearly marks it as CRM-dependent and fillable when data is available

## 5.10 Leader memo / legend
Required:
- status signal explanation
- trend explanation
- score scale
- action-priority explanation

This section is reference material for reading the report correctly.

## 6. Data dependencies

Likely data sources for `rop_weekly`:
- all analyzed calls within weekly period
- manager and department mapping
- checklist and stage scores
- stop flags / percentages
- derived trend calculations
- optional CRM conversion / deal data

Model-dependent blocks:
- cover subtitle wording
- best/alarming dynamics commentary
- problem descriptions
- risk-zone narratives
- top / anti-top interpretation
- task wording if produced by report-composer

Deterministic / non-model blocks:
- dashboard rows
- calculated deltas
- stage averages
- affected-manager counts
- priority tables
- legend blocks

## 7. First implementation slice

Must be included in v1:
- header
- dashboard
- week-over-week dynamics
- selective risk zones section
- systemic team problems
- top / anti-top block
- next-week tasks table
- business-results placeholder
- leader memo

Can be simplified in v1:
- "what is inside" may be short
- risk-zone cards may be limited to top N
- business-results section may stay placeholder if CRM data is missing
- some narrative text may be bounded report-composer output over deterministic payload

## 8. Important implementation warnings

- Do not make it manager-facing in tone.
- Do not make it as long or strategic as monthly.
- Keep a strong distinction between:
  - team-level systemic issues;
  - manager-specific urgent issues.
- Ranking and prioritisation must be explicit.
- The report should help the ROP decide whom to coach this week and how.
- Weekly is an operational management pack, not a broad retrospective essay.

## 9. Suggested renderer mapping

For email-first implementation:
- dashboard and tasks should be HTML tables;
- risk zones and top/anti-top should be visually separated cards/blocks;
- systemic problems may be stacked cards;
- business-results block may be rendered as placeholder table;
- memo stays at the end.

PDF is the visual reference.
This markdown file is the implementation reference.
