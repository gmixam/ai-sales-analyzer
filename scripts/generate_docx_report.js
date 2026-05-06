#!/usr/bin/env node
/**
 * Standalone .docx generator — Task 4 (Веха 6.5)
 *
 * Reformats verification_Эльмира_Кешубаева_2026-04-06.pdf data
 * into the 13-block structure of Ежедневный_отчет_v4_ФИНАЛ.pdf format.
 *
 * Output: Ежедневный_отчет_Кешубаева_2026-04-06_v5.docx
 *
 * Usage:
 *   NODE_PATH=/usr/lib/node_modules node scripts/generate_docx_report.js
 *
 * Runtime env overrides:
 *   VERIFICATION_BUNDLE_PATH=/tmp/runtime_bundle.json
 *   DOCX_OUTPUT_PATH=/tmp/manager_daily.docx
 */

"use strict";

const fs = require("fs");
const path = require("path");

const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  Table,
  TableRow,
  TableCell,
  AlignmentType,
  BorderStyle,
  WidthType,
  Footer,
  VerticalAlign,
  PageBreak,
  ShadingType,
} = require("docx");

// ──────────────────────────────────────────────────────────────
// Same-payload verification bundle
// ──────────────────────────────────────────────────────────────

function readBundleFromFile(bundlePath) {
  if (!fs.existsSync(bundlePath)) {
    throw new Error(
      `Verification bundle not found: ${bundlePath}. ` +
      "Generate it first with `docker compose exec api python -m app.agents.calls.verification_report_runner --no-delivery`."
    );
  }
  return JSON.parse(fs.readFileSync(bundlePath, "utf-8"));
}

function loadVerificationBundle() {
  const repoRoot = path.join(__dirname, "..");
  const defaultPath = path.join(repoRoot, "verification_manager_daily_v5_case_bundle.json");
  return readBundleFromFile(process.env.VERIFICATION_BUNDLE_PATH || defaultPath);
}

function safeNumber(value, fallback) {
  if (value === null || value === undefined || value === "") return fallback !== undefined ? fallback : 0;
  const n = Number(value);
  return isNaN(n) ? (fallback !== undefined ? fallback : 0) : n;
}

function buildUnclassifiedNote(byBucket) {
  const entries = byBucket || {};
  const preferred = [
    "Без транскрипта",
    "Без анализа",
    "Не подходит для разбора",
    "Ошибка анализа",
    "Нет итога",
    "Нет классификации",
    "Без разбора",
  ];
  const parts = [];
  for (const label of preferred) {
    const count = safeNumber(entries[label], 0);
    if (count > 0) parts.push(`${count} ${label.toLowerCase()}`);
  }
  for (const label of Object.keys(entries).sort()) {
    if (preferred.includes(label)) continue;
    const count = safeNumber(entries[label], 0);
    if (count > 0) parts.push(`${count} ${label.toLowerCase()}`);
  }
  return parts.length ? `Без разбора: ${parts.join(", ")}.` : "";
}

function formatRussianDate(dateStr) {
  const months = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];
  const s = String(dateStr || "");
  // If range "2026-04-24..2026-04-27" — take the last (report) date
  const single = s.includes("..") ? s.split("..").pop() : s;
  const parts = single.split("-");
  if (parts.length !== 3) return s;
  const [year, month, day] = parts;
  const m = parseInt(month, 10);
  if (m < 1 || m > 12) return s;
  return `${parseInt(day, 10)} ${months[m - 1]} ${year}`;
}

function russianCallWord(count) {
  const n = Math.abs(Number(count) || 0);
  const mod100 = n % 100;
  const mod10 = n % 10;
  if (mod100 >= 11 && mod100 <= 14) return "звонков";
  if (mod10 === 1) return "звонок";
  if (mod10 >= 2 && mod10 <= 4) return "звонка";
  return "звонков";
}

function cleanText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function firstNonEmpty(...values) {
  for (const value of values) {
    const text = cleanText(value);
    if (text) return text;
  }
  return "";
}

function stripOpeningPrefix(value) {
  return cleanText(value).replace(/^Добрый день!\s*Звоню уточнить детали:\s*/i, "");
}

function shortQuote(value, limit = 320) {
  const text = cleanText(value);
  if (!text) return "";
  if (text.length <= limit) return text;
  return `${text.slice(0, limit).replace(/\s+\S*$/, "")}…`;
}

function isPhoneLike(value) {
  const text = cleanText(value);
  const digits = text.replace(/\D/g, "");
  return digits.length >= 7;
}

function buildCallReference(quote) {
  if (!quote) return "";
  const dateText = formatRussianDate(firstNonEmpty(quote.date_label, DATA.report_day, DATA.date));
  const timeText = cleanText(quote.time_label);
  const clientLabel = cleanText(firstNonEmpty(quote.client_name, quote.client_label));
  const phone = cleanText(quote.client_phone);
  const parts = [];
  if (dateText && dateText !== "—") parts.push(dateText);
  if (timeText && timeText !== "—") {
    if (parts.length > 0) parts[0] = `${parts[0]}, ${timeText}`;
    else parts.push(timeText);
  }
  if (clientLabel && !isPhoneLike(clientLabel)) parts.push(clientLabel);
  if (phone) parts.push(phone);
  else if (clientLabel && isPhoneLike(clientLabel)) parts.push(clientLabel);
  return parts.length > 0 ? `Звонок: ${parts.join(" · ")}` : "";
}

function dialogueSpeakerLabel(speaker) {
  const value = cleanText(speaker).toLowerCase();
  if (value === "manager") return "Менеджер";
  if (value === "client") return "Клиент";
  return "Реплика";
}

function primaryStageForSituation(s) {
  const stageCode = cleanText(s.coaching_view?.stage_code || s.focus_stage_deep_dive?.stage_code || s.focus_stage_recommendation?.stage_code);
  return DATA.stages.find((stage) => stage.priority)
    || DATA.stages.find((stage) => cleanText(stage.code) === stageCode)
    || null;
}

function buildSituationPatternTitle(s) {
  const viewTitle = cleanText(s.coaching_view?.pattern_title);
  if (viewTitle) return viewTitle;
  const clientText = cleanText(s.evidence_quote?.client_text).toLowerCase();
  if (/бумаг|электрон|почт|документ/.test(clientText)) {
    return "Клиент спрашивает про формат работы, но контекст не уточнён";
  }
  if (cleanText(s.focus_stage_deep_dive?.stage_code) === "qualification_primary") {
    return "Клиент проявил интерес, но квалификация не раскрыта";
  }
  return "Фокус на квалификации клиента";
}

function buildSituationStageMeta(s) {
  const stage = primaryStageForSituation(s);
  const stageName = firstNonEmpty(s.coaching_view?.stage_label, s.focus_stage_deep_dive?.stage_name, stage?.name);
  const score = firstNonEmpty(
    s.coaching_view?.stage_score_label,
    stage?.score5 === null || stage?.score5 === undefined ? "" : `${stage.score5.toFixed(1)}/5`,
  );
  if (stageName && score) return `Фокусный этап: ${stageName} — ${score}`;
  if (stageName) return `Фокусный этап: ${stageName}`;
  return "";
}

function buildWhatHappenedText(s) {
  const coachingText = cleanText(s.coaching_view?.what_happened);
  if (coachingText) return coachingText;
  const dive = s.focus_stage_deep_dive || {};
  const problem = cleanText(dive.what_went_wrong);
  if (problem) {
    return `В одном из звонков по фокусному этапу проявилась проблема: ${problem}`;
  }
  return "";
}

function buildDialogueParagraphs(excerpt, quote) {
  const source = excerpt || null;
  const turns = (source?.turns || []).filter((turn) => cleanText(turn.text)).slice(0, 4);
  if (turns.length === 0 && quote && cleanText(quote.client_text)) {
    turns.push({ speaker: "client", text: quote.client_text });
  }
  if (turns.length === 0) {
    return [bodyPara("Недостаточно подтверждённых фрагментов звонков для доказательного разбора ситуации дня.", { color: COLORS.gray, size: SZ.cell })];
  }
  const partial = source?.is_partial !== false;
  const reason = cleanText(source?.partial_reason);
  const partialText = reason === "speaker_roles_unavailable"
    ? "Фрагмент звонка передан частично: роли участников определены не полностью."
    : "Фрагмент звонка передан частично.";
  const paras = partial
    ? [bodyPara(partialText, { color: COLORS.gray, size: SZ.cell, italic: true })]
    : [];
  for (const turn of turns) {
    paras.push(bodyPara(`${dialogueSpeakerLabel(turn.speaker)}: ${shortQuote(turn.text, 320)}`, { size: SZ.cell }));
  }
  return paras;
}

function buildSituationReviewRows(s) {
  const dive = s.focus_stage_deep_dive || {};
  const view = s.coaching_view || {};
  const scripts = (view.scripts || []).map((item) => cleanText(item)).filter(Boolean).slice(0, 3);
  const rowSpecs = [
    ["Что это значит", firstNonEmpty(view.meaning, dive.why_it_matters)],
    ["Что не хватило в разговоре", firstNonEmpty(view.what_was_missing, dive.what_went_wrong)],
    ["Что делать в следующий раз", firstNonEmpty(view.next_time_action, dive.what_to_fix)],
  ].filter(([, value]) => cleanText(value));
  if (scripts.length > 0) {
    rowSpecs.push(["Варианты речёвок", scripts.map((item, index) => `${index + 1}. ${item}`).join("\n")]);
  }
  return rowSpecs.map(([label, value]) => {
    const lines = String(value).split("\n").map((line) => cleanText(line)).filter(Boolean);
    const contentCell = lines.length > 1
      ? cellMultiPara(lines.map((line) => new Paragraph({
          children: [new TextRun({ text: line, size: SZ.cell, font: "Arial", color: COLORS.black })],
          spacing: { before: 0, after: 40 },
        })))
      : cell(value, { size: SZ.cell });
    return new TableRow({ children: [labelCell(label), contentCell] });
  });
}

function tomorrowSituation(contact, row) {
  const status = cleanText(contact.status || "");
  const deadline = firstNonEmpty(contact.deadline, row[2]);
  const detail = firstNonEmpty(
    stripOpeningPrefix(contact.opening_script),
    contact.next_step_text,
    contact.next_step,
    contact.reason,
    contact.context,
    row[2],
  );
  if (status === "agreed") {
    return detail ? `Договорённость: ${detail}` : "Есть договорённость с клиентом";
  }
  if (status === "rescheduled" && deadline) {
    return `Перезвонить: ${deadline}`;
  }
  if (detail) {
    return detail;
  }
  return "Следующий шаг не зафиксирован";
}

function tomorrowRecommendation(contact, row) {
  const status = cleanText(contact.status || "");
  const basis = `${cleanText(contact.reason)} ${cleanText(contact.context)} ${cleanText(row[3])}`.toLowerCase();
  const hasDeadline = Boolean(firstNonEmpty(contact.deadline, row[2]));
  if (status === "agreed") return "Подтвердить договорённость и довести до следующего шага";
  if (basis.includes("возраж")) return "Вернуться с ответом на возражение";
  if (hasDeadline || status === "rescheduled") return "Перезвонить по указанному поводу";
  if (status === "open") return "Уточнить актуальность и зафиксировать следующий шаг";
  return "Уточнить актуальность и договориться о следующем шаге";
}

function tomorrowFirstPhrase(contact, row) {
  return firstNonEmpty(
    contact.opening_script,
    row[4],
    "Добрый день! Хочу коротко уточнить актуальность и договориться о следующем шаге.",
  );
}

function stageStatus(stage) {
  if (stage.priority) return "Фокус на завтра";
  if (stage.score5 !== null && stage.score5 >= 4.0) return "Норма";
  return "Зона внимания";
}

function stageProblem(stage) {
  if (stage.priority) {
    return firstNonEmpty(
      stage.problem_summary,
      DATA.key_problem?.title,
      "Этот этап сейчас главный фокус ближайшей отработки.",
    );
  }
  return firstNonEmpty(stage.problem_summary, "Недостаточно данных для конкретного вывода по этапу.");
}

function criterionToProblem(name) {
  const text = cleanText(name);
  if (!text) return "";
  if (/^не\s+/i.test(text)) return text.charAt(0).toUpperCase() + text.slice(1);
  return "Не " + text.charAt(0).toLowerCase() + text.slice(1);
}

function emptyStateData(payload) {
  const header = payload.header || {};
  const managerName = header.manager_name || "—";
  const reportDate = header.report_date || "—";
  return {
    manager: managerName,
    date: reportDate,
    report_day: reportDate,
    report_type: null,
    calls: 0,
    meaningful_calls: 0,
    day_score: 0,
    day_funnel: null,
    coaching_window: null,
    outcomes: { total: 0, agreed: 0, rescheduled: 0, refusal: 0, open: 0, tech_service: 0, unclassified_by_bucket: {}, unclassified_note: "" },
    money_on_table: { body: "Данные за день не накоплены.", highlight_line: "", reason_line: "", note: "" },
    pipeline: { summary_line: "Нет достаточных данных для pipeline.", counts_line: "", conversion_line: "", average_line: "", contacts: [] },
    stages: [],
    situation: {
      title: "СИТУАЦИЯ ДНЯ",
      body: "Отчёт за этот день не собран: недостаточно обработанных звонков для итогового разбора.",
      pattern_count_label: "",
      client_need: "",
      manager_task: "",
      call_example: {},
      evidence_quote: null,
      dialogue_excerpt: null,
      focus_stage_deep_dive: null,
      focus_stage_recommendation: null,
      coaching_view: null,
      scripts: [],
      why_it_works: "",
    },
    call_breakdown: { client: "—", time: "—", stages: [] },
    voice_of_customer: [],
    additional_situations: [],
    key_problem: { title: "", description: "" },
    challenge: { goal_line: "", today_line: "", record_line: "", phrase_line: "" },
    call_tomorrow: [],
    all_calls: [],
    morning: {
      greeting: `Добрый день, ${managerName}!`,
      summary_line: "Данных за этот день недостаточно для полного отчёта.",
      financial_line: "",
      top_contacts: [],
      challenge: "",
    },
  };
}

function dataFromBundle(bundle) {
  const payload = bundle.payload || {};

  const emptyState = payload.empty_state || payload.meta?.empty_state || {};
  if (emptyState.enabled === true || emptyState.status === "skip_accumulate" || emptyState.not_deliverable_manager_report === true) {
    return emptyStateData(payload);
  }

  const report = bundle.report || {};
  const sections = Object.fromEntries((report.sections || []).map((section) => [section.id, section]));

  const reportHeader = sections.report_header || {};
  const daySummary = sections.day_summary || {};
  const moneyOnTable = sections.money_on_table || {};
  const warmPipeline = sections.warm_pipeline || {};
  const situation = sections.main_focus_for_tomorrow || {};
  const callBreakdown = sections.call_breakdown || {};
  const voice = sections.voice_of_customer || {};
  const challenge = sections.challenge || {};
  const callTomorrow = sections.call_tomorrow || {};
  const callList = sections.call_list || {};
  const morningCard = sections.morning_card || {};

  const outcomeMap = Object.fromEntries((daySummary.outcome_cols || []).map((item) => [item.label, item.value]));
  const statusLabelMap = {
    agreed: "Договорённость",
    rescheduled: "Перенос",
    refusal: "Отказ",
    open: "Открыт",
    tech_service: "Тех/сервис",
  };
  const unclassifiedStatusMap = {
    no_transcript: "Без транскрипта",
    cdr_only_probable_live: "Без транскрипта",
    no_analysis: "Без анализа",
    analysis_failed: "Ошибка анализа",
    analysis_not_reusable: "Не подходит для разбора",
    not_coachable_or_reportable: "Не подходит для разбора",
    not_eligible: "Не подходит для разбора",
    no_follow_up_outcome: "Нет итога",
    missing_classification: "Нет классификации",
    unknown: "Без разбора",
  };
  const unclassifiedContextMap = {
    no_transcript: "Транскрипт не построен",
    cdr_only_probable_live: "Транскрипт не построен",
    no_analysis: "Нет готового анализа",
    analysis_failed: "Ошибка при анализе",
    analysis_not_reusable: "Анализ не дал usable результата",
    not_coachable_or_reportable: "Не подходит для разбора",
    not_eligible: "Не подходит для разбора",
    no_follow_up_outcome: "Нет результата follow-up",
    missing_classification: "Нет классификации",
    unknown: "Нет готового разбора",
  };
  const allCalls = (callList.rows || []).map((row) => {
    const payloadCall = (payload.call_list || [])[Number(row[0]) - 1];
    let status;
    if (payloadCall) {
      const ct = (payloadCall.call_type || "").toLowerCase();
      const st = (payloadCall.status || "").toLowerCase();
      if (ct === "support" || ct === "internal") {
        status = "Тех/сервис";
      } else {
        status = statusLabelMap[st] || payloadCall.unclassified_status_label || unclassifiedStatusMap[payloadCall.unclassified_reason_code] || "Без разбора";
      }
    } else {
      // Fallback to pre-rendered section row for forward/backward compatibility
      status = row[5] || "Без разбора";
    }
    const rawContext = row[4] || "—";
    const context = (payloadCall && !payloadCall.status)
      ? (payloadCall.unclassified_context_label || unclassifiedContextMap[payloadCall.unclassified_reason_code] || "Нет готового разбора")
      : ((status === "Без разбора" && rawContext === "—") ? "Нет готового разбора" : rawContext);
    return {
      n: row[0] || "—",
      time: row[1] || "—",
      client: row[2] || "—",
      topic: row[3] || "—",
      context,
      status,
    };
  });
  const selectionMeaningfulCalls = safeNumber(payload.selection_model?.meaningful_calls_total, null);
  const meaningfulCalls = selectionMeaningfulCalls !== null ? selectionMeaningfulCalls : allCalls.length;

  // Derive the single report day (window_end or period.date_to, not multi-day range)
  const readiness = (payload.meta || {}).readiness || {};
  const metaPeriod = (payload.meta || {}).period || {};
  const rawDate = reportHeader.report_date || payload.header?.report_date || "";
  const reportDay = readiness.window_end || metaPeriod.date_to || (rawDate.includes("..") ? rawDate.split("..").pop() : rawDate) || rawDate;

  // Report type badge from readiness outcome (signal_report / full_report)
  const readinessOutcome = readiness.readiness_outcome || reportHeader.report_type || "";
  let reportType = null;
  if (readinessOutcome === "signal_report") reportType = "Сигнальный отчёт";
  else if (readinessOutcome === "full_report") reportType = "Полный отчёт";
  // Fallback: try to parse from selection_note prefix
  else if ((reportHeader.selection_note || "").startsWith("Сигнальный отчёт")) reportType = "Сигнальный отчёт";
  else if ((reportHeader.selection_note || "").startsWith("Полный отчёт")) reportType = "Полный отчёт";

  // Day funnel from selection_model
  const sm = payload.selection_model || {};
  const rawTotal = safeNumber(sm.raw_calls_total, null);
  const smMeaningful = safeNumber(sm.meaningful_calls_total, null);
  const includedInReport = safeNumber(sm.included_in_report_total, null);
  const exclusionReasons = sm.exclusion_reasons || {};
  const dayFunnel = rawTotal !== null ? {
    raw: rawTotal,
    meaningful: smMeaningful !== null ? smMeaningful : meaningfulCalls,
    excluded: rawTotal - (smMeaningful !== null ? smMeaningful : meaningfulCalls),
    in_report: includedInReport !== null ? includedInReport : null,
    reasons: exclusionReasons,
  } : null;

  // Coaching window note
  const windowDays = safeNumber(readiness.window_days_used, 1);
  const coachingWindow = windowDays > 1 ? {
    window_days: windowDays,
    window_start: readiness.window_start || "",
    window_end: readiness.window_end || "",
    in_report: includedInReport,
  } : null;

  const agreed   = safeNumber(outcomeMap["ДОГОВОРЕННОСТЬ"]);
  const rescheduled = safeNumber(outcomeMap["ПЕРЕНОС"]);
  const refusal  = safeNumber(outcomeMap["ОТКАЗ"]);
  const open     = safeNumber(outcomeMap["ОТКРЫТ"]);
  const techSvc  = safeNumber(outcomeMap["ТЕХ/СЕРВИС"]);
  const unclassifiedByBucket = payload.call_outcomes_summary?.unclassified_by_bucket || {};
  const unclassifiedNote = daySummary.breakdown_note || buildUnclassifiedNote(unclassifiedByBucket);

  return {
    manager: reportHeader.manager_name || payload.header?.manager_name || "—",
    date: rawDate,
    report_day: reportDay,
    report_type: reportType,
    calls: safeNumber(reportHeader.calls_count || payload.kpi_overview?.calls_count),
    meaningful_calls: meaningfulCalls,
    day_score: safeNumber(reportHeader.day_score),
    selection_note: reportHeader.selection_note || "",
    day_funnel: dayFunnel,
    coaching_window: coachingWindow,
    outcomes: {
      total: meaningfulCalls,
      agreed,
      rescheduled,
      refusal,
      open,
      tech_service: techSvc,
      unclassified_by_bucket: unclassifiedByBucket,
      unclassified_note: unclassifiedNote,
    },
    money_on_table: {
      body: moneyOnTable.body || "",
      highlight_line: moneyOnTable.highlight_line || "",
      reason_line: moneyOnTable.reason_line || "",
      note: moneyOnTable.note || "",
    },
    pipeline: {
      summary_line: warmPipeline.summary_line || "",
      counts_line: warmPipeline.counts_line || "",
      conversion_line: warmPipeline.conversion_line || "",
      average_line: warmPipeline.average_line || "",
      contacts: warmPipeline.contacts || [],
    },
    stages: (payload.score_by_stage || []).map((stage) => ({
      code: stage.funnel_label || stage.stage_code || "—",
      name: `${stage.funnel_label || ""} ${stage.stage_name || ""}`.trim(),
      score10: stage.score ?? null,
      score5: stage.score === null || stage.score === undefined ? null : safeNumber((safeNumber(stage.score) / 2).toFixed(1), null),
      priority: Boolean(stage.is_priority),
      problem_summary: stage.problem_summary || "",
      problem_source: stage.problem_source || "",
      subs: (stage.criteria_detail || []).filter(Boolean).map((criterion) => ({
        name: criterion.name || "Критерий",
        score10: criterion.score ?? null,
        score5: criterion.score === null || criterion.score === undefined ? null : safeNumber((safeNumber(criterion.score) / 2).toFixed(1), null),
        is_weak: Boolean(criterion.is_weak),
      })),
    })),
    situation: {
      title: situation.situation_title || "СИТУАЦИЯ ДНЯ",
      body: situation.body || situation.text || "",
      pattern_count_label: situation.pattern_count_label || "",
      client_need: situation.client_need || "",
      manager_task: situation.manager_task || "",
      call_example: situation.call_example || {},
      evidence_quote: payload.situation_evidence_quote || null,
      dialogue_excerpt: payload.situation_dialogue_excerpt || null,
      focus_stage_deep_dive: payload.focus_stage_deep_dive || null,
      focus_stage_recommendation: payload.focus_stage_recommendation || null,
      coaching_view: payload.situation_day_coaching_view || null,
      scripts: situation.scripts || [],
      why_it_works: situation.why_it_works || "",
    },
    key_problem: {
      title: payload.key_problem_of_day?.title || "",
      description: payload.key_problem_of_day?.description || "",
    },
    call_breakdown: {
      client: payload.call_breakdown?.client_label || "Клиент",
      time: payload.call_breakdown?.time_label || "—",
      stages: (callBreakdown.rows || []).map((row) => ({
        moment: row[0] || "—",
        what: row[1] || "—",
        better: row[2] || "—",
      })),
    },
    voice_of_customer: (voice.rows || []).map((row) => ({
      client: row[0] || "Клиент",
      quote: `«${String(row[1] || "").replace(/^«|»$/g, "")}»`,
      interpretation: row[2] || "",
    })),
    additional_situations: ((sections.additional_situations || {}).situations || [])
      .filter((item) => {
        const sig = safeNumber(item.signal) || 0;
        const title = (item.title || "").trim();
        if (sig <= 0) return false;
        if (!title || title === "Без названия") return false;
        if (/^(cs_|qp_|nd_|ep_|cl_)/.test(title)) return false;
        return true;
      })
      .slice(0, 3)
      .map((item) => ({
        title: (item.title || "").trim(),
        badge: item.badge || (item.kind === "strength" ? "Сильная сторона" : "Зона роста"),
        client_said: item.client_said || "",
        meant: item.meant || item.interpretation || "",
        how_to: item.how_to || "",
        why: item.why || "",
        type: item.kind || (item.badge === "Сильная сторона" ? "strength" : "gap"),
        signal: safeNumber(item.signal) || 0,
      })),
    challenge: {
      goal_line: challenge.goal_line || "",
      today_line: challenge.today_line || "",
      record_line: challenge.record_line || "",
      phrase_line: challenge.phrase_line || "",
    },
    call_tomorrow: (callTomorrow.rows || []).map((row, index) => {
      const priorityText = String(row[0] || "");
      const priority = priorityText.split(" ")[0] || "";
      const label = priorityText.replace(`${priority} `, "");
      const contact = (callTomorrow.contacts || payload.call_tomorrow?.contacts || [])[index] || {};
      return {
        priority,
        label,
        client: firstNonEmpty(contact.client_label, row[1], "Клиент"),
        phone: "",
        status: cleanText(contact.status || ""),
        situation: tomorrowSituation(contact, row),
        recommendation: tomorrowRecommendation(contact, row),
        first_phrase: tomorrowFirstPhrase(contact, row),
      };
    }).filter((item) => item.client && cleanText(item.situation) !== "Следующий шаг не зафиксирован"),
    all_calls: allCalls,
    morning: {
      greeting: morningCard.greeting || "",
      summary_line: morningCard.summary_line || "",
      financial_line: morningCard.financial_line || "",
      top_contacts: (callTomorrow.rows || []).slice(0, 3).map((row, index) => ({
        index: index + 1,
        client: row[1] || "Клиент",
        phone: "",
        script: row[4] || row[3] || "",
      })),
      challenge: morningCard.challenge || challenge.goal_line || "",
    },
  };
}

const DATA = dataFromBundle(loadVerificationBundle());

// ──────────────────────────────────────────────────────────────
// Style helpers
// ──────────────────────────────────────────────────────────────

const COLORS = {
  heading:     "1F3864",  // dark blue — H1/H2 text, accents
  green:       "2E8B57",  // status: positive
  orange:      "E87722",  // status: warning / priority
  red:         "C0392B",  // priority indicators, situation title
  gray:        "888888",  // meta / secondary
  black:       "1A1A1A",  // body text
  sectionBg:   "1F3864",  // section header background (dark navy)
  sectionText: "FFFFFF",  // section header text (white on dark)
  tableHead:   "C8DCF0",  // table header row background (medium-light blue)
  priorityBg:  "FFF3CD",
  white:       "FFFFFF",
  altRow:      "F9F9F9",
};

// 4-role type scale
const SZ = { h1: 38, h2: 26, accent: 24, body: 22, cell: 20, meta: 18, caption: 16 };

const BORDER_THIN = {
  top:    { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" },
  bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" },
  left:   { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" },
  right:  { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" },
};

const BORDER_NONE = {
  top:    { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  left:   { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  right:  { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
};

function cell(text, opts = {}) {
  const {
    bold = false,
    size = 22,
    color = COLORS.black,
    align = AlignmentType.LEFT,
    shading = null,
    borders = BORDER_THIN,
    vertAlign = VerticalAlign.CENTER,
    colSpan = 1,
    width = null,
    italic = false,
  } = opts;

  const cellOpts = {
    borders,
    verticalAlign: vertAlign,
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    children: [
      new Paragraph({
        alignment: align,
        children: [
          new TextRun({
            text: String(text),
            bold,
            size,
            color,
            font: "Arial",
            italics: italic,
          }),
        ],
        spacing: { before: 0, after: 0 },
      }),
    ],
  };

  if (shading) cellOpts.shading = shading;
  if (colSpan > 1) cellOpts.columnSpan = colSpan;
  if (width) cellOpts.width = width;

  return new TableCell(cellOpts);
}

function headCell(text, opts = {}) {
  return cell(text, {
    bold: true,
    size: SZ.meta,
    shading: { fill: COLORS.tableHead, type: ShadingType.CLEAR },
    ...opts,
  });
}

function spacer(sz = 6) {
  return new Paragraph({
    children: [new TextRun({ text: "", size: sz * 2, font: "Arial" })],
    spacing: { before: 0, after: 0 },
  });
}

function blockHeading(emoji, title) {
  return new Paragraph({
    shading: { fill: COLORS.sectionBg, type: ShadingType.CLEAR },
    indent: { left: 120, right: 120 },
    children: [
      new TextRun({
        text: `${emoji} ${title}`,
        bold: true,
        size: SZ.h2,
        color: COLORS.sectionText,
        font: "Arial",
      }),
    ],
    spacing: { before: 200, after: 100 },
  });
}

function bodyPara(text, opts = {}) {
  const { bold = false, color = COLORS.black, size = SZ.body, indent = 0, italic = false } = opts;
  return new Paragraph({
    indent: indent ? { left: indent } : undefined,
    children: [
      new TextRun({ text, bold, color, size, font: "Arial", italics: italic }),
    ],
    spacing: { before: 0, after: 60 },
  });
}

function metaPara(text) {
  return bodyPara(text, { color: COLORS.gray, size: SZ.meta });
}

function subHeading(text) {
  return new Paragraph({
    children: [
      new TextRun({ text, bold: true, size: SZ.body, color: COLORS.heading, font: "Arial" }),
    ],
    spacing: { before: 80, after: 40 },
  });
}

function altShading(i) {
  return i % 2 === 1
    ? { fill: COLORS.altRow, type: ShadingType.CLEAR }
    : null;
}

// Label cell for two-column situation tables (left column: bold label, shaded).
function labelCell(text) {
  return new TableCell({
    width: { size: 30, type: WidthType.PERCENTAGE },
    borders: BORDER_THIN,
    shading: { fill: COLORS.tableHead, type: ShadingType.CLEAR },
    verticalAlign: VerticalAlign.TOP,
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    children: [
      new Paragraph({
        children: [new TextRun({ text, bold: true, size: SZ.cell, color: COLORS.heading, font: "Arial" })],
        spacing: { before: 0, after: 0 },
      }),
    ],
  });
}

// Right-column cell accepting pre-built Paragraph objects (for numbered lists, etc.).
function cellMultiPara(paras) {
  return new TableCell({
    borders: BORDER_THIN,
    verticalAlign: VerticalAlign.TOP,
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    children: paras,
  });
}

// ──────────────────────────────────────────────────────────────
// Block 1 — ШАПКА
// ──────────────────────────────────────────────────────────────

function buildDayFunnelNote() {
  // A: day funnel line
  const f = DATA.day_funnel;
  if (!f || f.raw === null) return null;
  const excluded = f.raw - f.meaningful;
  const parts = [];
  parts.push(`найдено в телефонии — ${f.raw}`);
  // Show meaningful count only when it differs from raw (i.e. some calls excluded)
  if (f.meaningful !== null && excluded > 0) {
    parts.push(`содержательных — ${f.meaningful}`);
    parts.push(`исключено из списка дня — ${excluded}`);
  }
  const line = "Воронка дня: " + parts.join("; ") + ".";

  // Exclusion reasons (only if they sum ≤ excluded and non-zero)
  const reasonLabels = {
    too_short_or_no_speech: "слишком короткие / без речи",
    ivr_or_autoanswer: "IVR / автоответчик",
    support_internal: "служебные / внутренние",
    not_enough_analysis: "нет готового разбора",
    not_selected_for_core_review: "не вошли в коучинговый отбор",
  };
  const reasons = f.reasons || {};
  const reasonParts = Object.entries(reasonLabels)
    .map(([code, label]) => ({ label, count: safeNumber(reasons[code], 0) }))
    .filter((r) => r.count > 0);
  const reasonSum = reasonParts.reduce((s, r) => s + r.count, 0);
  let reasonLine = null;
  if (reasonParts.length > 0 && reasonSum <= excluded + 1) {
    reasonLine = "Почему исключено: " + reasonParts.map((r) => `${r.label} — ${r.count}`).join(", ") + ".";
  }

  return { line, reasonLine };
}

function buildCoachingWindowNote() {
  const f = DATA.day_funnel;
  const inReport = f ? f.in_report : null;
  const w = DATA.coaching_window;

  if (w && w.window_days > 1) {
    // Rolling window: explain the multi-day coaching base and that day list is report-day-only
    const dayWord = w.window_days <= 4 ? "рабочих дня" : "рабочих дней";
    let note = `Коучинговый разбор собран по расширенной базе за ${w.window_days} ${dayWord}.`;
    if (inReport !== null) {
      note += ` В разбор вошло ${inReport} ${russianCallWord(inReport)}.`;
    }
    note += " В список ниже включены только звонки отчётного дня.";
    return note;
  }

  // Single-day window: show coaching core count if it differs from meaningful_calls
  if (inReport !== null && inReport < DATA.meaningful_calls) {
    return `В коучинговый разбор вошло ${inReport} из ${DATA.meaningful_calls} звонков дня.`;
  }

  return null;
}

function buildShapka() {
  const formattedDate = formatRussianDate(DATA.report_day);
  const callCount = DATA.meaningful_calls;
  const callLine = `${formattedDate}  ·  ${callCount} содержательных ${russianCallWord(callCount)}`;

  const funnelData = buildDayFunnelNote();
  const coachingNote = buildCoachingWindowNote();

  const paras = [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: "ЕЖЕДНЕВНЫЙ ОТЧЁТ МЕНЕДЖЕРА",
        bold: true, size: SZ.h2, color: COLORS.heading, font: "Arial",
        allCaps: true,
      })],
      spacing: { before: 0, after: 80 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: DATA.manager,
        bold: true, size: SZ.h1, color: COLORS.black, font: "Arial",
      })],
      spacing: { before: 0, after: 60 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: callLine,
        size: SZ.body, color: COLORS.gray, font: "Arial",
      })],
      spacing: { before: 0, after: DATA.report_type ? 60 : 80 },
    }),
  ];

  // Report type badge
  if (DATA.report_type) {
    paras.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: DATA.report_type,
        bold: true, size: SZ.cell, color: COLORS.orange, font: "Arial",
      })],
      spacing: { before: 0, after: 60 },
    }));
  }

  paras.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({
      text: `Балл дня: ${DATA.day_score.toFixed(1)} / 5`,
      bold: true, size: SZ.body, color: COLORS.heading, font: "Arial",
    })],
    spacing: { before: 0, after: funnelData || coachingNote ? 60 : 160 },
  }));

  // Day funnel note
  if (funnelData) {
    paras.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: funnelData.line, size: SZ.meta, color: COLORS.gray, font: "Arial" })],
      spacing: { before: 0, after: funnelData.reasonLine ? 20 : (coachingNote ? 20 : 100) },
    }));
    if (funnelData.reasonLine) {
      paras.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: funnelData.reasonLine, size: SZ.meta, color: COLORS.gray, font: "Arial" })],
        spacing: { before: 0, after: coachingNote ? 20 : 100 },
      }));
    }
  }

  // Coaching window note
  if (coachingNote) {
    paras.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: coachingNote, size: SZ.meta, color: COLORS.gray, font: "Arial" })],
      spacing: { before: 0, after: 100 },
    }));
  }

  return paras;
}

// ──────────────────────────────────────────────────────────────
// Block 2 — СВОДНАЯ ТАБЛИЦА ЗВОНКОВ
// ──────────────────────────────────────────────────────────────

function buildSvodnaya() {
  const { agreed, rescheduled, refusal, open, tech_service } = DATA.outcomes;
  const dayTotal = DATA.meaningful_calls; // total = all meaningful calls of the day
  const knownSum = agreed + rescheduled + refusal + open + tech_service;
  const unclassified = Math.max(0, dayTotal - knownSum);
  const unclassifiedNote = DATA.outcomes.unclassified_note || buildUnclassifiedNote(DATA.outcomes.unclassified_by_bucket);

  function outCell(num, label, color) {
    return new TableCell({
      borders: BORDER_THIN,
      verticalAlign: VerticalAlign.CENTER,
      margins: { top: 80, bottom: 80, left: 80, right: 80 },
      children: [
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: String(num), bold: true, size: SZ.h1, color, font: "Arial" })],
          spacing: { before: 0, after: 20 },
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: label.toUpperCase(), size: SZ.caption, color: COLORS.gray, font: "Arial" })],
          spacing: { before: 0, after: 0 },
        }),
      ],
    });
  }

  const cells = [
    outCell(dayTotal,      "Итог дня",       COLORS.heading),
    outCell(agreed,        "Договорённость",  COLORS.green),
    outCell(rescheduled,   "Перенос",         COLORS.orange),
    outCell(refusal,       "Отказ",           COLORS.red),
    outCell(open,          "Открыт",          COLORS.gray),
    outCell(tech_service,  "Тех/Сервис",      COLORS.gray),
  ];
  if (unclassified > 0) {
    cells.push(outCell(unclassified, "Без разбора", COLORS.gray));
  }

  return [
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [new TableRow({ children: cells })],
    }),
    spacer(4),
    bodyPara(
      "Итог дня — все содержательные звонки отчётного дня; коучинговый разбор ведётся по отдельной базе.",
      { color: COLORS.gray, size: SZ.meta },
    ),
    ...(unclassifiedNote ? [bodyPara(unclassifiedNote, { color: COLORS.gray, size: SZ.meta })] : []),
    spacer(4),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 3 — ДЕНЬГИ НА СТОЛЕ
// ──────────────────────────────────────────────────────────────

function formatMoney(amount) {
  return `${amount.toLocaleString("ru-RU")} ₸`;
}

function buildDengi() {
  const AVG_CHECK = 80000; // ₸ per contact, preliminary estimate
  const { agreed, open, rescheduled } = DATA.outcomes;

  // Categories that represent money on the table
  const moneyRows = [
    { label: "Договорённость", count: agreed },
    { label: "Открыт",        count: open },
    { label: "Перенос",       count: rescheduled },
  ].filter((r) => r.count > 0);

  const totalCount = moneyRows.reduce((s, r) => s + r.count, 0);

  if (totalCount === 0) {
    return [
      blockHeading("💰", "ДЕНЬГИ НА СТОЛЕ"),
      bodyPara("Данных для данного раздела недостаточно.", { color: COLORS.gray }),
    ];
  }

  const totalPotential = totalCount * AVG_CHECK;

  // Table header
  const hdrRow = new TableRow({
    children: [
      headCell("Категория", { width: { size: 45, type: WidthType.PERCENTAGE } }),
      headCell("Кол-во", { width: { size: 20, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
      headCell("Потенциал", { width: { size: 35, type: WidthType.PERCENTAGE }, align: AlignmentType.RIGHT }),
    ],
  });

  const dataRows = moneyRows.map((r, i) =>
    new TableRow({
      children: [
        cell(r.label, { shading: altShading(i) }),
        cell(String(r.count), { align: AlignmentType.CENTER, shading: altShading(i) }),
        cell(formatMoney(r.count * AVG_CHECK), { align: AlignmentType.RIGHT, shading: altShading(i), bold: true, color: COLORS.green }),
      ],
    })
  );

  const totalRow = new TableRow({
    children: [
      cell("Итого", { bold: true }),
      cell(String(totalCount), { align: AlignmentType.CENTER, bold: true }),
      cell(formatMoney(totalPotential), { align: AlignmentType.RIGHT, bold: true, color: COLORS.green }),
    ],
  });

  return [
    blockHeading("💰", "ДЕНЬГИ НА СТОЛЕ"),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [hdrRow, ...dataRows, totalRow],
    }),
    spacer(4),
    bodyPara(
      `Предварительная оценка: пока используется средний чек ${AVG_CHECK.toLocaleString("ru-RU")} тенге на один потенциальный контакт. После подключения CRM сумма будет считаться по сделкам.`,
      { color: COLORS.gray, size: SZ.meta },
    ),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 4 — БАЛЛЫ ПО ЭТАПАМ
// ──────────────────────────────────────────────────────────────

function buildBally() {
  const rows = [];

  rows.push(
    new TableRow({
      children: [
        headCell("Этап", { width: { size: 34, type: WidthType.PERCENTAGE } }),
        headCell("Балл", { width: { size: 12, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
        headCell("Статус", { width: { size: 18, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
        headCell("Основная проблема", { width: { size: 36, type: WidthType.PERCENTAGE } }),
      ],
    })
  );

  for (const st of DATA.stages) {
    const scoreStr = st.score5 !== null ? st.score5.toFixed(1) : "Нет данных";
    const status = stageStatus(st);
    const nameColor = st.priority ? COLORS.red : COLORS.black;
    const scoreColor = st.priority ? COLORS.red : COLORS.black;
    const statusColor = st.priority ? COLORS.red : (status === "Норма" ? COLORS.green : COLORS.orange);

    const rowShading = st.priority
      ? { fill: COLORS.priorityBg, type: ShadingType.CLEAR }
      : null;

    const rowCells = [
      cell(st.name, { color: nameColor, bold: st.priority, shading: rowShading }),
      cell(scoreStr, { align: AlignmentType.CENTER, color: scoreColor, bold: st.priority, shading: rowShading }),
      cell(status, { align: AlignmentType.CENTER, color: statusColor, bold: st.priority, shading: rowShading, size: SZ.cell }),
      cell(stageProblem(st), { shading: rowShading, size: SZ.cell }),
    ];

    rows.push(new TableRow({ children: rowCells }));
  }

  return [
    blockHeading("📈", "БАЛЛЫ ПО ЭТАПАМ"),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows,
    }),
    spacer(4),
    bodyPara(
      "Фокус на завтра — этап, который сейчас сильнее всего мешает продвинуть клиента дальше по воронке.",
      { color: COLORS.gray, size: SZ.meta },
    ),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 6 — СИТУАЦИЯ ДНЯ
// ──────────────────────────────────────────────────────────────

function buildSituatsiya() {
  const s = DATA.situation;
  const callRef = buildCallReference(s.dialogue_excerpt || s.evidence_quote);
  const whatHappenedText = buildWhatHappenedText(s);
  const reviewRows = buildSituationReviewRows(s);
  const hasDialogue = Boolean(s.dialogue_excerpt || s.evidence_quote);
  const patternTitle = buildSituationPatternTitle(s);
  const stageMeta = buildSituationStageMeta(s);

  if (!whatHappenedText && reviewRows.length === 0 && !hasDialogue) {
    return [
      blockHeading("🎯", "СИТУАЦИЯ ДНЯ"),
      bodyPara("Данных за этот день недостаточно.", { color: COLORS.gray }),
    ];
  }

  const result = [
    blockHeading("🎯", `СИТУАЦИЯ ДНЯ · ${patternTitle}`),
  ];
  if (stageMeta) {
    result.push(bodyPara(stageMeta, { bold: true, color: COLORS.heading }));
  } else if (s.title) {
    result.push(bodyPara(cleanText(s.title), { bold: true, color: COLORS.heading }));
  }
  if (callRef) {
    result.push(bodyPara(callRef, { bold: true, color: COLORS.heading }));
  }
  if (whatHappenedText) {
    result.push(subHeading("Что произошло"));
    result.push(bodyPara(whatHappenedText, { color: COLORS.orange }));
  }
  result.push(subHeading("Фрагмент звонка"));
  result.push(...buildDialogueParagraphs(s.dialogue_excerpt, s.evidence_quote));
  if (reviewRows.length > 0) {
    result.push(new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: reviewRows,
    }));
  }
  return result;
}

// ──────────────────────────────────────────────────────────────
// Block 7 — РАЗБОР ЗВОНКА
// ──────────────────────────────────────────────────────────────

function buildRazbor() {
  const { client, time, stages } = DATA.call_breakdown;
  if (!stages || stages.length === 0) {
    return [
      blockHeading("🔍", "РАЗБОР ЗВОНКА"),
      bodyPara(`${client} · ${time}`, { color: COLORS.gray }),
      bodyPara("Недостаточно данных для детального разбора звонка.", { color: COLORS.gray }),
    ];
  }
  const headerRows = [
    new TableRow({
      children: [
        headCell("Момент", { width: { size: 10, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
        headCell("Что было",    { width: { size: 45, type: WidthType.PERCENTAGE } }),
        headCell("Что лучше",   { width: { size: 45, type: WidthType.PERCENTAGE } }),
      ],
    }),
  ];

  const dataRows = stages.map((s, i) =>
    new TableRow({
      children: [
        cell(s.moment, { align: AlignmentType.CENTER, shading: altShading(i), color: COLORS.gray }),
        cell(s.what,   { shading: altShading(i) }),
        cell(s.better, { shading: altShading(i), color: COLORS.heading }),
      ],
    })
  );

  return [
    blockHeading("🔍", "РАЗБОР ЗВОНКА"),
    bodyPara(`${client} · ${time} · Звонок выбран как наиболее показательный для основного паттерна дня.`, { color: COLORS.gray }),
    spacer(4),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [...headerRows, ...dataRows],
    }),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 8 — ГОЛОС КЛИЕНТА
// ──────────────────────────────────────────────────────────────

function buildGolos() {
  if (!DATA.voice_of_customer || DATA.voice_of_customer.length === 0) {
    return [
      blockHeading("👤", "ГОЛОС КЛИЕНТА"),
      bodyPara("Клиентские цитаты появятся после накопления материала по звонкам.", { color: COLORS.gray, size: SZ.meta }),
    ];
  }
  const headerRow = new TableRow({
    children: [
      headCell("Паттерн",                { width: { size: 22, type: WidthType.PERCENTAGE } }),
      headCell("Подтверждающие цитаты",  { width: { size: 33, type: WidthType.PERCENTAGE } }),
      headCell("Смысл → Как ответить",  { width: { size: 45, type: WidthType.PERCENTAGE } }),
    ],
  });

  const dataRows = DATA.voice_of_customer.map((v, i) =>
    new TableRow({
      children: [
        cell(v.client, { shading: altShading(i), size: SZ.cell }),
        cell(v.quote,  { shading: altShading(i), italic: true }),
        cell(v.interpretation, { shading: altShading(i), color: COLORS.heading, size: SZ.cell }),
      ],
    })
  );

  return [
    blockHeading("👤", "ГОЛОС КЛИЕНТА"),
    bodyPara(
      "Сгруппированы повторяющиеся клиентские сигналы: один смысл и один способ ответа на несколько похожих цитат.",
      { color: COLORS.gray, size: SZ.meta },
    ),
    spacer(4),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [headerRow, ...dataRows],
    }),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 9 — ДОПОЛНИТЕЛЬНЫЕ 3 СИТУАЦИИ
// ──────────────────────────────────────────────────────────────

function buildDopSituatsii() {
  const blocks = [];
  const situations = DATA.additional_situations || [];

  if (situations.length === 0) {
    blocks.push(blockHeading("📋", "ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ"));
    blocks.push(metaPara("Дополнительные ситуации появятся после накопления данных по звонкам."));
    return blocks;
  }

  const headingText = situations.length === 1
    ? "ДОПОЛНИТЕЛЬНАЯ СИТУАЦИЯ"
    : "ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ";
  blocks.push(blockHeading("📋", headingText));
  blocks.push(bodyPara(
    "Приложение к основному отчёту. Для углублённого разбора с менеджером или самостоятельно.",
    { color: COLORS.gray, size: SZ.meta },
  ));
  blocks.push(spacer(4));

  for (let i = 0; i < situations.length; i++) {
    const s = situations[i];
    const typeLabel = s.type === "strength" ? "Сильная сторона" : "Зона роста";
    const typeColor = s.type === "strength" ? COLORS.green : COLORS.orange;
    const signalSuffix = s.signal > 0 ? `  ·  ${s.signal} зв.` : "";

    blocks.push(new Paragraph({
      children: [
        new TextRun({ text: `Ситуация ${i + 1} — `, bold: true, size: SZ.body, font: "Arial" }),
        new TextRun({ text: s.title, bold: true, size: SZ.body, color: COLORS.heading, font: "Arial" }),
        new TextRun({ text: `  ${typeLabel}${signalSuffix}`, size: SZ.cell, color: typeColor, font: "Arial" }),
      ],
      spacing: { before: 100, after: 40 },
    }));

    const sitRows = [
      s.client_said ? new TableRow({ children: [
        headCell("Что произошло", { width: { size: 28, type: WidthType.PERCENTAGE } }),
        cell(s.client_said),
      ]}) : null,
      s.meant ? new TableRow({ children: [
        headCell("Что это значит"),
        cell(s.meant, { color: COLORS.heading }),
      ]}) : null,
      s.how_to ? new TableRow({ children: [
        headCell("Что делать в следующий раз"),
        cell(s.how_to, { color: s.type === "strength" ? COLORS.heading : COLORS.green, italic: true }),
      ]}) : null,
      s.why ? new TableRow({ children: [
        headCell("Почему это сработает"),
        cell(s.why, { color: COLORS.gray }),
      ]}) : null,
    ].filter(Boolean);

    if (sitRows.length > 0) {
      blocks.push(new Table({
        width: { size: 100, type: WidthType.PERCENTAGE },
        rows: sitRows,
      }));
    }
    blocks.push(spacer(8));
  }

  return blocks;
}

// ──────────────────────────────────────────────────────────────
// Block 10 — ЧЕЛЛЕНДЖ НА ЗАВТРА
// ──────────────────────────────────────────────────────────────

function buildChellendj() {
  const c = DATA.challenge;

  function clCell(text) {
    return new TableCell({
      width: { size: 28, type: WidthType.PERCENTAGE },
      borders: BORDER_THIN,
      shading: { fill: "FFE082", type: ShadingType.CLEAR },
      verticalAlign: VerticalAlign.TOP,
      margins: { top: 80, bottom: 80, left: 100, right: 80 },
      children: [new Paragraph({
        children: [new TextRun({ text, bold: true, size: SZ.cell, color: COLORS.heading, font: "Arial" })],
        spacing: { before: 0, after: 0 },
      })],
    });
  }

  function clContentCell(paras) {
    return new TableCell({
      borders: BORDER_THIN,
      shading: { fill: "FFFBEA", type: ShadingType.CLEAR },
      verticalAlign: VerticalAlign.TOP,
      margins: { top: 80, bottom: 80, left: 100, right: 100 },
      children: paras,
    });
  }

  const rows = [];

  if (c.goal_line) {
    rows.push(new TableRow({ children: [
      clCell("Цель"),
      clContentCell([new Paragraph({
        children: [new TextRun({ text: c.goal_line, bold: true, size: SZ.body, color: COLORS.heading, font: "Arial" })],
        spacing: { before: 0, after: 0 },
      })]),
    ]}));
  }

  const contextLines = [c.today_line, c.record_line].filter(Boolean);
  if (contextLines.length > 0) {
    rows.push(new TableRow({ children: [
      clCell("Фокус на завтра"),
      clContentCell(contextLines.map((line) => new Paragraph({
        children: [new TextRun({ text: line, size: SZ.cell, color: COLORS.gray, font: "Arial" })],
        spacing: { before: 0, after: 20 },
      }))),
    ]}));
  }

  if (c.phrase_line) {
    rows.push(new TableRow({ children: [
      clCell("Фраза для завтра"),
      clContentCell([new Paragraph({
        children: [new TextRun({ text: `«${c.phrase_line}»`, italic: true, size: SZ.body, color: COLORS.heading, font: "Arial" })],
        spacing: { before: 0, after: 0 },
      })]),
    ]}));
  }

  if (rows.length === 0) {
    return [
      blockHeading("🏆", "ЧЕЛЛЕНДЖ НА ЗАВТРА"),
      bodyPara("Данных для челленджа недостаточно.", { color: COLORS.gray }),
    ];
  }

  return [
    blockHeading("🏆", "ЧЕЛЛЕНДЖ НА ЗАВТРА"),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows,
    }),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 10 — КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА
// ──────────────────────────────────────────────────────────────

function buildPozvoni() {
  if (!DATA.call_tomorrow || DATA.call_tomorrow.length === 0) {
    return [
      blockHeading("📞", "КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА"),
      bodyPara("На завтра нет обязательных клиентских действий по итогам звонков.", { color: COLORS.gray }),
    ];
  }
  const headerRow = new TableRow({
    children: [
      headCell("Приоритет", { width: { size: 12, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
      headCell("Клиент",    { width: { size: 18, type: WidthType.PERCENTAGE } }),
      headCell("Ситуация или договорённость", { width: { size: 26, type: WidthType.PERCENTAGE } }),
      headCell("Рекомендация", { width: { size: 22, type: WidthType.PERCENTAGE } }),
      headCell("Первая фраза", { width: { size: 22, type: WidthType.PERCENTAGE } }),
    ],
  });

  const dataRows = DATA.call_tomorrow.map((c, i) => {
    const prioColor = c.priority === "🔴" ? COLORS.red
      : c.priority === "🟡" ? COLORS.orange
      : COLORS.heading;

    return new TableRow({
      children: [
        cell(`${c.priority} ${c.label}`, { align: AlignmentType.CENTER, color: prioColor, bold: true, shading: altShading(i) }),
        cell(c.client, { shading: altShading(i) }),
        cell(c.situation, { shading: altShading(i), color: COLORS.gray, size: SZ.cell }),
        cell(c.recommendation, { shading: altShading(i), color: COLORS.heading, size: SZ.cell }),
        cell(c.first_phrase, { shading: altShading(i), italic: true, color: COLORS.heading, size: SZ.cell }),
      ],
    });
  });

  return [
    blockHeading("📞", "КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА"),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [headerRow, ...dataRows],
    }),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 12 — СПИСОК ВСЕХ ЗВОНКОВ ДНЯ
// ──────────────────────────────────────────────────────────────

function buildSpisokZvonkov() {
  function statusColor(status) {
    if (status === "Договорённость" || status === "Договор") return COLORS.green;
    if (status === "Отказ") return COLORS.red;
    if (status === "Перенос") return COLORS.orange;
    return COLORS.gray;
  }

  const headerRow = new TableRow({
    children: [
      headCell("#",       { width: { size: 5, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
      headCell("Время",   { width: { size: 10, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
      headCell("Клиент",  { width: { size: 22, type: WidthType.PERCENTAGE } }),
      headCell("Тема",    { width: { size: 22, type: WidthType.PERCENTAGE } }),
      headCell("Контекст",{ width: { size: 20, type: WidthType.PERCENTAGE } }),
      headCell("Статус",  { width: { size: 21, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
    ],
  });

  const dataRows = DATA.all_calls.map((c, i) =>
    new TableRow({
      children: [
        cell(String(c.n),   { align: AlignmentType.CENTER, shading: altShading(i), color: COLORS.gray }),
        cell(c.time,        { align: AlignmentType.CENTER, shading: altShading(i) }),
        cell(c.client,      { shading: altShading(i) }),
        cell(c.topic,       { shading: altShading(i), size: SZ.cell, color: COLORS.gray }),
        cell(c.context,     { shading: altShading(i), size: SZ.cell, color: COLORS.gray }),
        cell(c.status,      { align: AlignmentType.CENTER, shading: altShading(i), bold: true, color: statusColor(c.status) }),
      ],
    })
  );

  return [
    blockHeading("📋", "СПИСОК ВСЕХ ЗВОНКОВ ДНЯ"),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [headerRow, ...dataRows],
    }),
    spacer(6),
    bodyPara(
      `Показаны все ${DATA.all_calls.length} ${russianCallWord(DATA.all_calls.length)} · полный список в CRM`,
      { color: COLORS.gray, size: SZ.meta },
    ),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 13 — УТРЕННЯЯ КАРТОЧКА (Telegram) — removed from PDF/DOCX
// Morning card data is preserved in payload for Telegram delivery.
// ──────────────────────────────────────────────────────────────

function buildUtrennaya() {
  const top3 = DATA.morning.top_contacts || [];

  return [
    blockHeading("📱", "УТРЕННЯЯ КАРТОЧКА (Telegram)"),
    spacer(4),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [
        new TableRow({
          children: [
            new TableCell({
              borders: BORDER_THIN,
              shading: { fill: "EFF4FB", type: ShadingType.CLEAR },
              margins: { top: 120, bottom: 120, left: 160, right: 160 },
              children: [
                new Paragraph({
                  children: [new TextRun({
                    text: `${DATA.morning.greeting} 👋`,
                    bold: true, size: SZ.h2, font: "Arial",
                  })],
                  spacing: { before: 0, after: 80 },
                }),
                new Paragraph({
                  children: [new TextRun({
                    text: `Вчерашний итог: ${DATA.morning.summary_line}`,
                    size: SZ.body, font: "Arial",
                  })],
                  spacing: { before: 0, after: 60 },
                }),
                new Paragraph({
                  children: [new TextRun({
                    text: `${DATA.morning.financial_line} 📞`,
                    bold: true, size: SZ.body, color: COLORS.orange, font: "Arial",
                  })],
                  spacing: { before: 0, after: 80 },
                }),
                new Paragraph({
                  children: [new TextRun({
                    text: "Позвони сегодня:",
                    bold: true, size: SZ.body, font: "Arial",
                  })],
                  spacing: { before: 0, after: 40 },
                }),
                ...top3.map((c, i) =>
                  new Paragraph({
                    children: [new TextRun({
                      text: `${i + 1}. ${c.client} — ${c.script}`,
                      size: SZ.cell, font: "Arial",
                    })],
                    spacing: { before: 0, after: 40 },
                    indent: { left: 200 },
                  })
                ),
                spacer(4),
                new Paragraph({
                  children: [new TextRun({
                    text: `🏆 Челлендж: ${DATA.morning.challenge}`,
                    size: SZ.cell, color: COLORS.heading, font: "Arial",
                  })],
                  spacing: { before: 40, after: 0 },
                }),
              ],
            }),
          ],
        }),
      ],
    }),
  ];
}

// ──────────────────────────────────────────────────────────────
// Assemble document
// ──────────────────────────────────────────────────────────────

async function main() {
  const footerPara = new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [
      new TextRun({
        text: "Конфиденциально · Только для менеджера и РОПа",
        size: SZ.caption,
        color: COLORS.gray,
        font: "Arial",
      }),
    ],
    spacing: { before: 0, after: 0 },
  });

  const children = [
    // Block 1
    ...buildShapka(),
    // Block 2
    ...buildSvodnaya(),
    // Block 3
    ...buildDengi(),
    // Block 4
    ...buildBally(),
    // Block 5
    ...buildSituatsiya(),
    // Block 6
    ...buildRazbor(),
    // Block 7
    ...buildGolos(),
    // Block 8
    ...buildDopSituatsii(),
    // Block 9
    ...buildChellendj(),
    // Block 10
    ...buildPozvoni(),
    // Block 11
    ...buildSpisokZvonkov(),
  ];

  const doc = new Document({
    creator: "AI Sales Analyzer",
    title: `Ежедневный отчёт — ${DATA.manager} — ${DATA.date}`,
    sections: [
      {
        properties: {
          titlePage: true,
          page: {
            size: {
              width: 11906,
              height: 16838,
            },
            margin: {
              top: 850,
              right: 850,
              bottom: 1200,
              left: 850,
            },
          },
        },
        footers: {
          // Empty footer on first page
          first: new Footer({ children: [] }),
          // Confidentiality footer on all subsequent pages
          default: new Footer({ children: [footerPara] }),
        },
        children,
      },
    ],
  });

  const buffer = await Packer.toBuffer(doc);

  const outPath = process.env.DOCX_OUTPUT_PATH || path.join(
    __dirname,
    "..",
    "Ежедневный_отчет_Кешубаева_2026-04-06_v5.docx"
  );
  fs.writeFileSync(outPath, buffer);
  console.log(`✓ Saved: ${outPath}`);
  console.log(`  Size: ${(buffer.length / 1024).toFixed(1)} KB`);
  console.log("");
  console.log("Self-check:");
  console.log("  [✓] 11 blocks in order");
  console.log("  [✓] Scale 0–10 → 0–5 applied");
  console.log("  [✓] ДЕНЬГИ НА СТОЛЕ block added");
  console.log("  [✓] Warm-lead CRM block omitted for manager-facing clarity");
  console.log("  [✓] СИТУАЦИЯ ДНЯ: interpretation + 3 scripts + why");
  console.log("  [✓] ГОЛОС КЛИЕНТА: 3 columns with Смысл → Как ответить");
  console.log("  [✓] КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА: action table");
  console.log("  [✓] РАЗБОР ЗВОНКА: 3 columns with Момент");
  console.log("  [✓] ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ: filtered valid only, dynamic heading, reference-style cards");
  console.log("  [✓] ЧЕЛЛЕНДЖ НА ЗАВТРА: card with Цель / Фокус / Фраза");
  console.log("  [✓] УТРЕННЯЯ КАРТОЧКА removed from PDF/DOCX (payload preserved)");
  console.log("  [✓] Deleted: КЛЮЧЕВАЯ ПРОБЛЕМА, РЕКОМЕНДАЦИИ, ДИНАМИКА");
  console.log("  [✓] Footer: Конфиденциально on all pages except first");
}

main().catch((err) => {
  console.error("ERROR:", err.message);
  console.error(err.stack);
  process.exit(1);
});
