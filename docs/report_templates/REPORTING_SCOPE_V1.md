# REPORTING_SCOPE_V1

Status: current implementation scope note for Codex / repo-local development  
Purpose: make the current step readable without reopening roadmap and PDF every time.

## 1. Current project phase

Current project phase:
- MVP-1 transition to `Manual Reporting Pilot`

Roadmap position:
- after `Delivery Ready`
- before future automation settings / reporting loop automation

## 2. Stage tasks and statuses

- `Delivery Ready` - closed
- `Manual Output Validation` - closed
- documentation alignment for `Manual Reporting Pilot` - closed
- `Manual Reporting Pilot` operating model - agreed
- first bounded implementation step for `Manual Reporting Pilot` - current active step
- automation readiness / scheduler / retries / beat / full reporting loop - out of scope for this step

## 3. What the current step is

Current step:
- design and implement the first bounded version of manual reporting launch and report assembly

Target outputs in this phase:
- `manager_daily`
- `rop_weekly`

`rop_monthly`:
- reference only
- not in current implementation slice

## 4. What must be true in v1

The first implementation must support:
- manual operator trigger
- launch via `report_preset + period + filters`
- presets:
  - `manager_daily`
  - `rop_weekly`
- modes:
  - `build_missing_and_report`
  - `report_from_ready_data_only`
- reuse-first artifact logic
- no unnecessary full rerun
- email-only delivery
- configurable recipient resolution through Bitrix data
- optional bounded report-composer layer above existing artifacts

## 5. Delivery rules

Current delivery mode:
- email only

Every report should go to:
- main recipient
- monitoring copy: `sales@dogovor24.kz`

Recipient resolution rules:
- manager email from Bitrix employee card
- weekly ROP report to sales head from Bitrix org structure
- this must be configurable logic, not hardcoded branching

## 6. Reuse and recompute rules

If still valid, reuse:
- transcript
- card
- checklist
- intermediate analysis outputs
- report inputs

Recompute only when the effective version of a truly relevant dependency changed.

Triggers that may require recomputation:
- prompt version
- report logic version
- checklist version
- card format version
- model-dependent report step version

Important:
- changing model does NOT mean full pipeline rerun by default
- selective rerun of model-dependent step is allowed

## 7. Explicit non-goals

Do NOT implement in this step:
- scheduler
- retries
- beat
- cron / standing automation
- full reporting loop
- monthly report implementation
- broad analyzer redesign
- approved analyzer contract changes
- broad extractor / intake refactor
- new provider adapters only for this step

## 8. Repo-local sources of truth for report formats

Use these files as the main implementation references for report shapes:
- `docs/report_templates/MANAGER_DAILY_REFERENCE.md`
- `docs/report_templates/ROP_WEEKLY_REFERENCE.md`
- `docs/report_templates/ROP_MONTHLY_REFERENCE.md`

Interpretation:
- daily and weekly = active implementation references
- monthly = future-facing reference only

## 9. Development principle

Separate three concerns:
1. selection / reuse / build logic
2. normalized report payload contract
3. rendering / delivery

Do not couple visual rendering too tightly with computation logic.

## 10. Practical implication for Codex

When you receive a task for this phase:
- do not rely on PDF directly;
- rely on repo-local markdown references;
- keep the solution bounded;
- preserve approved analyzer flow;
- optimize for a useful operator-driven reporting pilot, not for automation completeness.
