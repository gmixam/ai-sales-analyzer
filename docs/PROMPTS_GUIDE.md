# PROMPTS_GUIDE

## Purpose
This document defines how prompt assets should be organized and how prompt instructions must be split between permanent project policies and task-specific requests.

Prompt files are product assets and versioned contracts, not disposable text snippets and not content that should be re-explained in every task prompt.

## 1. Permanent Prompt Policies

These rules are stable by default and should live in prompt assets, source documents, or standing docs.

### 1.1 Prompt asset ownership
- Keep prompts in dedicated markdown files under the relevant agent.
- Treat prompt files as source assets, not inline code literals.
- Do not hardcode production prompt text in runtime code.

### 1.2 Contract and schema stability
- Preserve the output JSON contract even when wording changes.
- Prompt revisions must not change downstream schema unless there is an explicitly planned breaking migration.
- Schema constraints belong in prompt assets and source-of-truth docs, not in repeated task prompts.

### 1.3 Versioning
- Every production prompt change must be traceable to a version label or release note.
- Track prompt changes together with `instruction_version` in persisted analysis records.
- If prompt experiments are introduced later, each analysis row must retain the exact `instruction_version` used.

### 1.4 Stable behavior rules
- Language expectations should live in prompt assets or policy docs when they are stable for a stage or artifact class.
- Output behavior rules should live in prompt assets or policy docs when they are stable for a stage or artifact class.
- Restrictions against hallucinated fields, free-form drift, or schema-breaking output should live in prompt assets or source docs when they are persistent requirements.
- Examples must stay concise and aligned with the active schema.

## 2. What Must Not Be Repeated In Every Task Prompt

The following belong in source prompt assets and/or project docs unless the current task is explicitly changing them:
- language expectations for stable artifact classes;
- business-output localization rules;
- output formatting behavior that is already approved;
- JSON schema and field constraints;
- prompt versioning expectations;
- general anti-hallucination and structured-output guardrails;
- default stage policies that already live in a stage spec.

## 3. What Task Prompts Should Still Contain

Task prompts should contain only the variable part of the current step:
- current stage, if it matters for the task;
- current step and objective;
- exact artifact or case under work;
- concrete scope boundaries for this task;
- expected output for this task;
- explicit local restrictions or temporary exceptions.

If a task prompt starts re-listing stable language, output, and schema rules that already exist in source assets or docs, it is probably too long.

## 4. Authoring Checklist For Prompt Changes

Use this checklist when editing prompt assets:
- Define the task clearly.
- Define required output fields explicitly if the prompt owns them.
- Reference stable language/output policies instead of duplicating them.
- Keep examples short and contract-aligned.
- Preserve backward-compatible behavior unless a planned change says otherwise.
- Update related docs when the change affects standing project understanding.

## 5. Operational Notes
- Prompt files in `core/app/agents/calls/prompts/` are source assets.
- Long-term prompt metadata should also be persisted in the `prompts` table.
- Task prompts are for step-specific intent, not for re-documenting the entire prompt contract.
- If a stable prompt rule changes, update the source prompt asset first and then sync the relevant project docs if needed.

## 6. Manual Reporting Pilot Prompt Boundary

For `Manual Reporting Pilot`, prompt changes must stay explicitly bounded:
- do not treat report-composer prompts as analyzer-contract prompts by default;
- keep daily/weekly reporting synthesis prompts separate from the approved core call-analysis contract;
- preserve reuse-first behavior: changing a reporting prompt must not imply a full pipeline rerun unless that reporting step actually depends on the changed prompt output;
- model experiments for reporting should target only the model-dependent reporting step when possible;
- prompt assets for `manager_daily` and `rop_weekly` should be organized around `report_preset + period + filters`, not around implicit scheduler assumptions.
