# ROP_MONTHLY_REFERENCE

Status: approved repo-local extracted reference from `Ежемесячный отчет для РОП.pdf`  
Purpose: preserve monthly format as future reference only. This file is not an implementation scope signal for the current v1.

## 1. Current scope status

`rop_monthly` is reference-only for now.

It is NOT part of:
- current `Manual Reporting Pilot` v1 implementation;
- current `manager_daily` / `rop_weekly` implementation slice.

This file exists so that:
- weekly and daily contracts can be designed in an extensible way;
- future monthly implementation does not need to start from the PDF again.

## 2. What this report is

`rop_monthly` is a strategic management report for one month.

Compared with weekly:
- weekly = who needs action now;
- monthly = what needs to change in approach / standards next month.

The PDF positions it as:
- confidential;
- for ROP and management;
- not for managers.

## 3. Canonical section order from the PDF

1. Header / cover
2. What is inside
3. Month summary
4. Four-week trends
5. Monthly manager ranking
6. Team stage profile
7. Systemic patterns - what does not change
8. Decisions for next month
9. Business results of the month
10. Leader memo / interpretation
11. Footer

## 4. Main structural differences vs weekly

Monthly is:
- more strategic;
- less operationally urgent;
- more trend-based;
- more focused on standards, patterns and management decisions;
- less focused on immediate weekly coaching tasks.

Weekly asks:
- who needs reaction this week?

Monthly asks:
- what should change in scripts, standards, coaching approach and team management next month?

## 5. Main section notes

## 5.1 Month summary
The PDF uses high-level team metrics:
- team average score for the month;
- delta vs previous month;
- count of managers with growth;
- count of managers with decline;
- short month conclusion.

## 5.2 Four-week trends
Weekly values are shown across four weeks with:
- trend sparkline / direction;
- monthly average;
- month delta;
- trend label;
- short stable-growth / stable-decline notes.

## 5.3 Monthly manager ranking
Managers are ranked by:
- average score;
- dynamics;
- strong/problematic share;
- verdict label.

Examples of verdict-like labels in the PDF:
- `Эталон`
- `Растёт`
- `Наблюдение`
- `Зона риска`

This is more layered than weekly top/anti-top.

## 5.4 Team stage profile
The PDF shows stage averages across the team and per manager, including:
- stage values;
- arrows vs previous month;
- team average by stage;
- interpretation of strongest and weakest stages.

## 5.5 Systemic patterns
This section looks for recurring multi-month problems.
For each pattern, the PDF includes:
- pattern title;
- explanation;
- root cause;
- proposed solution;
- how many months it has persisted;
- how many managers are affected.

Examples:
- opening without value/purpose
- client answers are not converted into value
- call does not end with a concrete agreement
- sustained decline without reversal

## 5.6 Decisions for next month
This is a prioritised action table with fields like:
- level (`systemic`, `individual`, `reference/mentor`);
- task;
- success metric;
- owner;
- deadline

This is more strategic than weekly tasking.

## 5.7 Business results
CRM-dependent placeholder block:
- calls
- agreements
- reschedules
- refusals
- conversion
- deals
- amount

The PDF also suggests linking call-quality improvement to business outcomes.

## 5.8 Leader memo
The monthly memo explains:
- how monthly differs from weekly;
- task levels;
- score scale;
- when to escalate;
- warning patterns such as:
  - decline 3+ weeks in a row
  - plateau 4 weeks
  - stop-flags not improving
  - transitions < 1.0

## 6. Why this matters for current implementation

Even though monthly is out of scope now, weekly/daily schemas should be designed so that future monthly can reuse:
- shared manager summary primitives;
- stage profile blocks;
- trend structures;
- problem card structures;
- CRM placeholder conventions;
- memo / legend conventions.

## 7. Explicit non-signal

Do not treat this file as a request to implement monthly now.
Current v1 scope remains:
- `manager_daily`
- `rop_weekly`
- manual parameterized launch
- email-first delivery
- reuse-first execution

PDF is the visual reference.
This markdown file is the future-facing reference.
