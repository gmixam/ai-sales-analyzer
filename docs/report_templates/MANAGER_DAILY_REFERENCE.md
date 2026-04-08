# MANAGER_DAILY_REFERENCE

Status: approved repo-local extracted reference from `Ежедневный отчет для менеджера.pdf`  
Purpose: give Codex a text-native source of truth for the `manager_daily` output shape without depending on PDF access.

## 1. What this report is

`manager_daily` is a manager-facing daily coaching report for one manager over one selected day.

It is not a single-call card and not a team report.
It aggregates the calls of one manager for the day and turns them into:
- a quick summary of the day;
- one main focus for tomorrow;
- concrete recommendations with examples from real calls;
- call outcome summary;
- a short call list;
- a small dynamics block;
- a short memo / legend.

## 2. Audience and tone

Primary audience:
- the manager;
- optionally the manager's direct lead in copy.

Tone:
- supportive and coaching-oriented;
- direct but not punitive;
- specific, practical, business-readable;
- should explain both "what to do" and "why it matters".

The report should feel:
- concise at the top;
- practical in the middle;
- reference-like at the bottom.

## 3. Visual / structural intent from the PDF

The PDF shows a strong hierarchy:
1. report header with manager name, date, department, product/context;
2. top summary block with KPI cards;
3. narrative interpretation of the day;
4. highlighted "signal of the day";
5. highlighted "main focus for tomorrow";
6. analysis split into:
   - what worked;
   - what to improve;
7. one explicitly named "key problem of the day";
8. recommendations section with cards;
9. call outcomes summary;
10. calls table;
11. focus-criterion dynamics;
12. memo / legend.

This does not need to be copied pixel-for-pixel in implementation, but the information hierarchy should stay similar.

## 4. Canonical report order

Recommended section order for first implementation:

1. Header
2. Focus-of-the-week line
3. Day summary / KPI overview
4. Narrative day conclusion
5. Signal of the day
6. Main focus for tomorrow
7. Analysis:
   - what worked
   - what to improve
8. Key problem of the day
9. Recommendations
10. Call outcomes summary
11. Call list / per-call short table
12. Focus criterion dynamics
13. Memo / legend
14. Footer / generation note

## 5. Required sections and fields

## 5.1 Header
Required:
- report_title = "Ежедневный разбор звонков" or equivalent
- manager_name
- report_date
- department_name
- product_or_business_context if available

Optional:
- team / segment label
- confidentiality label

## 5.2 Focus of the week
Required:
- short current focus sentence

Notes:
- may come from external operator input or config
- if unavailable, allow placeholder or omit in first version

## 5.3 Day summary / KPI overview
Required:
- calls_count
- average_score
- strong_calls_pct
- baseline_calls_pct
- problematic_calls_pct

Useful optional fields:
- score_vs_period_avg
- delta_vs_period_avg
- interpretation_label

This block should answer in 10 seconds:
- how many calls there were;
- how strong the day was overall;
- whether this day is better or worse than the recent average.

## 5.4 Narrative day conclusion
Required:
- short synthesized paragraph:
  - what the day looked like overall;
  - strongest stable zone;
  - main problem area;
  - short progress interpretation

This is a good candidate for bounded report-composer text.

## 5.5 Signal of the day
Required:
- one positive example / standout call
- why it is a model example

Prefer fields:
- call_time
- client_or_phone_mask
- short evidence description
- reason_this_matters

## 5.6 Main focus for tomorrow
Required:
- one sentence only
- highly actionable
- tied to the main problem of the day

This is one of the most important blocks in the whole report.

## 5.7 Analysis: what worked
Required:
- 3 to 5 items
- each item should include:
  - label / criterion name
  - score or strength signal
  - short interpretation

Example types seen in PDF:
- tone and contact
- question depth
- proposal quality
- time management

## 5.8 Analysis: what to improve
Required:
- 3 to 5 items
- each item should include:
  - label / criterion name
  - score or weakness signal
  - short interpretation

Example types seen in PDF:
- introduction / self-presentation
- next-step fixation
- remaining questions check
- objection handling

## 5.9 Key problem of the day
Required:
- explicit problem title
- explanatory paragraph:
  - what is going wrong;
  - how often it occurs;
  - why it matters operationally

This section should be singular and focused.
Only one main problem should be highlighted.

## 5.10 Recommendations
Required:
- up to 5 recommendation cards
- each recommendation should contain:
  - priority tag (`do_tomorrow` or `this_week`)
  - short title
  - reason / context
  - "how it sounded"
  - "better phrasing"
  - why this works

This section is central.
Do not collapse it into generic bullets.
Each recommendation should be concrete and speech-oriented.

Recommended priority vocabulary:
- `Сделай завтра`
- `На неделе`

## 5.11 Call outcomes summary
Required:
- agreed_count
- rescheduled_count
- refusal_count
- open_count

Optional:
- short explanation of what "open" means

The PDF explicitly explains that "open" means the call happened but the next step was not fixed.

## 5.12 Call list / short table
Required:
- a compact per-call list or table
- fields:
  - time
  - client / phone
  - duration
  - call_type
  - status
  - next_step
  - deadline

Important:
- first implementation may limit rows
- if truncated, explicitly state that only the first N calls are shown and the full list stays in CRM

## 5.13 Focus criterion dynamics
Required:
- focus_criterion_name
- current_period_value
- previous_period_value
- delta

Optional:
- nearby stage deltas to provide context

The PDF uses this to reinforce the selected focus and to show whether the issue is improving or degrading.

## 5.14 Memo / legend
Required:
- call level legend:
  - strong
  - baseline
  - problematic
- call status legend:
  - agreed
  - rescheduled
  - refusal
  - open
- recommendation priority legend

Optional:
- evaluation stages list

This is reference material, not the main insight.

## 6. Data dependencies

Likely data sources for `manager_daily`:
- analyzed calls for selected manager and date
- checklist / scores
- intermediate analysis outputs
- per-call status / next step / deadline
- optionally CRM or persisted delivery fields
- optional focus-of-week config

Model-dependent blocks:
- narrative day conclusion
- signal-of-the-day wording
- main focus wording
- recommendation wording
- key problem explanation

Non-model / deterministic blocks:
- KPI summary
- counts
- table rows
- score deltas
- legends

## 7. First implementation slice

Must be included in v1:
- header
- KPI summary
- short narrative conclusion
- signal of the day
- main focus for tomorrow
- what worked
- what to improve
- up to 5 recommendations
- call outcomes summary
- compact calls table
- minimal legend

Can be simplified in v1:
- focus-of-the-week source can be manual/configurable
- dynamics block can be one criterion only
- memo can be short
- calls table can be truncated

## 8. Important implementation warnings

- Do not turn this into a raw JSON dump or technical debug report.
- Do not make it too long at the top; summary must be skimmable.
- Recommendations must be phrased as coaching actions, not generic analytics comments.
- The report is day-based and manager-based, not team-based.
- Keep one main focus only.
- "What worked" should be shorter than "what to improve".
- This report should feel useful to the manager the next morning.

## 9. Suggested renderer mapping

For email-first implementation:
- preserve section order;
- top KPI block may be rendered as compact cards or inline metrics;
- recommendations should remain visually separated;
- calls table may be HTML table;
- memo may be collapsed into the end of the email.

PDF is the visual reference.
This markdown file is the implementation reference.
