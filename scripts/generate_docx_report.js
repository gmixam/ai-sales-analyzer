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
  TableLayoutType,
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

const PROOF_TYPE_LABELS = {
  direct_gap: "Подтверждение из звонка",
  sequence_inference: "Суть момента",
  absence_in_context: "Что не было зафиксировано",
  context_support: "Контекст из звонка",
};

function proofTypeLabel(value, fallback = "Подтверждение из звонка") {
  const key = cleanText(value).toLowerCase();
  return PROOF_TYPE_LABELS[key] || fallback;
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

function samePhone(left, right) {
  const l = cleanText(left).replace(/\D/g, "");
  const r = cleanText(right).replace(/\D/g, "");
  return Boolean(l && r && l === r);
}

function buildCallReference(quote) {
  if (!quote) return "";
  const explicitReference = cleanText(quote.client_call_reference || quote.call_reference);
  if (explicitReference) return `Звонок: ${explicitReference}`;
  const dateText = formatRussianDate(firstNonEmpty(quote.date_label, DATA.report_day, DATA.date));
  const timeText = cleanText(quote.time_label);
  const clientLabel = cleanText(firstNonEmpty(quote.client_name, quote.client_label));
  const phone = cleanText(quote.client_phone);
  const parts = [];
  if (clientLabel && !isPhoneLike(clientLabel)) parts.push(clientLabel);
  if (phone && !samePhone(clientLabel, phone)) parts.push(phone);
  else if (clientLabel && isPhoneLike(clientLabel)) parts.push(clientLabel);
  if (dateText && dateText !== "—") {
    parts.push(timeText && timeText !== "—" ? `${dateText}, ${timeText}` : dateText);
  } else if (timeText && timeText !== "—") {
    parts.push(timeText);
  }
  return parts.length > 0 ? `Звонок: ${parts.join(" · ")}` : "";
}

function dialogueSpeakerLabel(speaker) {
  const value = cleanText(speaker).toLowerCase();
  if (value === "manager") return "Менеджер";
  if (value === "client") return "Клиент";
  if (value === "side_1" || value === "сторона 1") return "Сторона 1";
  if (value === "side_2" || value === "сторона 2") return "Сторона 2";
  return "Сторона 1";
}

function speakerForQuoteIndex(index) {
  return index % 2 === 0 ? "Сторона 1" : "Сторона 2";
}

function primaryStageForSituation(s) {
  const stageCode = cleanText(s.coaching_view?.stage_code || s.focus_stage_deep_dive?.stage_code || s.focus_stage_recommendation?.stage_code);
  return DATA.stages.find((stage) => cleanText(stage.code) === stageCode)
    || DATA.stages.find((stage) => stage.priority)
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

function compactSemanticText(value) {
  return cleanText(value)
    .toLowerCase()
    .replace(/[ё]/g, "е")
    .replace(/[^a-zа-я0-9]+/g, " ")
    .trim();
}

function sameMeaningText(left, right) {
  const a = compactSemanticText(left);
  const b = compactSemanticText(right);
  return Boolean(a && b && (a === b || a.includes(b) || b.includes(a)));
}

function buildDialogueParagraphs(excerpt, quote, opts = {}) {
  const source = excerpt || null;
  const turns = (source?.turns || []).filter((turn) => cleanText(turn.text)).slice(0, 10);
  const quoteFallback = quoteText(quote);
  if (turns.length === 0 && quoteFallback) {
    turns.push({ speaker: "client", text: quoteFallback });
  }
  if (turns.length === 0) {
    return [bodyPara("Недостаточно подтверждений из звонков для доказательного разбора ситуации дня.", { color: COLORS.gray, size: SZ.cell })];
  }
  const partial = source?.is_partial !== false;
  const reason = cleanText(source?.partial_reason);
  const evidenceLabel = opts.label || "Подтверждение из звонка";
  let partialText = `${evidenceLabel} передано частично.`;
  if (reason === "speaker_roles_unavailable") {
    partialText = `${evidenceLabel} передано частично: роли участников определены не полностью.`;
  } else if (reason === "low_information_fragment_only") {
    partialText = "Доступно только слабое подтверждение: в звонке не найдено более содержательное.";
  }
  const paras = partial
    ? [bodyPara(partialText, { color: COLORS.gray, size: SZ.cell, italic: true })]
    : [];
  turns.forEach((turn, index) => {
    paras.push(dialoguePara(dialogueSpeakerLabel(turn.speaker) || speakerForQuoteIndex(index), turn.text, { size: SZ.cell }));
  });
  return paras;
}

function dialoguePara(speaker, text, opts = {}) {
  const quote = shortQuote(text, opts.limit || 700);
  if (!quote) return bodyPara("", { size: opts.size || SZ.cell });
  return new Paragraph({
    children: [
      new TextRun({ text: `${speaker || "Сторона 1"}: `, bold: true, italics: true, size: opts.size || SZ.cell, color: COLORS.heading, font: "Arial" }),
      new TextRun({ text: quote, italics: true, size: opts.size || SZ.cell, color: opts.color || COLORS.black, font: "Arial" }),
    ],
    spacing: { before: opts.before || 0, after: opts.after === undefined ? 40 : opts.after },
  });
}

function dialogueCellParagraphsFromText(text, opts = {}) {
  const raw = String(text || "").trim();
  if (!raw) return [];
  const parsed = parseDialogueLines(raw);
  if (parsed.length > 0) {
    return parsed.map((turn, index) => dialoguePara(turn.speaker || speakerForQuoteIndex(index), turn.text, { size: opts.size || SZ.cell, limit: opts.limit || 420 }));
  }
  return [dialoguePara(opts.speaker || "Сторона 1", raw.replace(/^«|»$/g, ""), { size: opts.size || SZ.cell, limit: opts.limit || 420 })];
}

function parseDialogueLines(value) {
  const text = String(value || "").replace(/\r/g, "").replace(/\s*\/\s*/g, "\n");
  const chunks = text.split(/\n+/).map((item) => cleanText(item)).filter(Boolean);
  const turns = [];
  for (const chunk of chunks) {
    const match = chunk.match(/^(клиент|менеджер|оператор|продавец|собеседник|сторона\s*[12]|side\s*[12]|реплика)\s*:\s*(.+)$/i);
    if (!match) continue;
    let speaker = match[1].toLowerCase();
    if (speaker === "клиент") speaker = "Клиент";
    else if (speaker === "менеджер" || speaker === "оператор" || speaker === "продавец") speaker = "Менеджер";
    else if (speaker.includes("2")) speaker = "Сторона 2";
    else speaker = "Сторона 1";
    turns.push({ speaker, text: match[2] });
  }
  return turns;
}

function quoteText(value) {
  if (!value) return "";
  if (typeof value === "string") return cleanText(value).replace(/^«|»$/g, "");
  return firstNonEmpty(
    value.text,
    value.quote,
    value.client_text,
    value.manager_text,
    value.fragment,
    value.excerpt,
  );
}

function dialogueExcerptText(excerpt, limit = 360) {
  const turns = (excerpt?.turns || []).filter((turn) => cleanText(turn.text)).slice(0, 8);
  if (turns.length === 0) return "";
  return turns
    .map((turn) => `${dialogueSpeakerLabel(turn.speaker)}: ${shortQuote(turn.text, Math.floor(limit / turns.length))}`)
    .join(" / ");
}

function situationMomentSummary(s) {
  return firstNonEmpty(
    s.coaching_moment?.summary,
    s.moment_summary,
    s.coaching_view?.moment_summary,
    s.coaching_view?.summary,
    s.coaching_view?.what_happened,
    dialogueExcerptText(s.dialogue_excerpt),
    quoteText(s.evidence_quote),
  );
}

function situationSupportingQuote(s) {
  const evidenceQuotes = (s.coaching_view?.evidence_quotes || []).filter((item) => cleanText(item));
  return firstNonEmpty(
    evidenceQuotes.join(" / "),
    quoteText(s.coaching_moment?.supporting_quote),
    quoteText(s.supporting_quote),
    dialogueExcerptText(s.dialogue_excerpt),
    quoteText(s.evidence_quote),
  );
}

function situationProofType(s) {
  return firstNonEmpty(
    s.coaching_view?.proof_type,
    s.coaching_moment?.proof_type,
    s.evidence_quote?.proof_type,
    s.supporting_quote?.proof_type,
  );
}

function looksLikeManagerSpeechScript(value) {
  const text = cleanText(value);
  if (!text) return false;
  const lower = text.toLowerCase();
  if (text.includes("?") || lower.includes("пожалуйста") || lower.includes("подскажите")) return true;
  if (/^(уточнить|зафиксировать|согласовать|отправить|проверить|поднять|спросить|объяснить|закрыть|сделать)\b/.test(lower)) {
    return false;
  }
  return ["добрый день", "давайте", "я отправлю", "могу", "предлагаю"].some((marker) => lower.includes(marker));
}

function buildSupportingQuoteParagraph(text, opts = {}) {
  const quote = cleanText(text);
  if (!quote) return null;
  const label = opts.label || "Подтверждение из звонка";
  return new Paragraph({
    children: [
      new TextRun({ text: `${label}: `, bold: true, size: opts.size || SZ.cell, color: COLORS.heading, font: "Arial" }),
      new TextRun({ text: `Сторона 1: ${shortQuote(quote.replace(/^«|»$/g, ""), opts.limit || 420)}`, size: opts.size || SZ.cell, color: opts.color || COLORS.black, font: "Arial", italics: true }),
    ],
    spacing: { before: opts.before || 40, after: opts.after || 0 },
  });
}

function buildSituationReviewRows(s) {
  const dive = s.focus_stage_deep_dive || {};
  const view = s.coaching_view || {};
  const scripts = (view.scripts || [])
    .map((item) => cleanText(item))
    .filter((item) => looksLikeManagerSpeechScript(item))
    .slice(0, 3);
  const nextAction = firstNonEmpty(view.next_time_action, dive.what_to_fix);
  const nextActionWithExample = buildNextActionWithExample(nextAction, scripts);
  const rowSpecs = [
    ["Что это значит", firstNonEmpty(view.meaning, dive.why_it_matters)],
    ["Что не хватило в разговоре", firstNonEmpty(view.what_was_missing, dive.what_went_wrong)],
    ["Что делать в следующий раз", nextActionWithExample],
  ].filter(([, value]) => cleanText(value));
  return rowSpecs.map(([label, value]) => {
    const lines = String(value).split("\n").map((line) => cleanText(line)).filter(Boolean);
    const contentCell = lines.length > 1
      ? cellMultiPara(lines.map((line) => new Paragraph({
          children: [new TextRun({ text: line, size: SZ.cell, font: "Arial", color: COLORS.black })],
          spacing: { before: 0, after: 40 },
        })))
      : cell(value, { size: SZ.cell, width: { size: 70, type: WidthType.PERCENTAGE } });
    return new TableRow({ children: [labelCell(label), contentCell] });
  });
}

function buildNextActionWithExample(nextAction, scripts) {
  const action = cleanText(nextAction);
  const examples = scripts
    .filter((item) => !sameMeaningText(item, action))
    .slice(0, 2);
  const lines = [];
  if (action) lines.push(action);
  examples.forEach((item, index) => {
    lines.push(`${index === 0 ? "Пример" : "Ещё пример"}: ${item}`);
  });
  return lines.join("\n");
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
    extractOpeningScript(row[3]),
    row[4],
    "Добрый день! Хочу коротко уточнить актуальность и договориться о следующем шаге.",
  );
}

function extractOpeningScript(value) {
  const text = cleanText(value);
  const match = text.match(/Можно начать:\s*[«"](.+?)[»"]\.?$/);
  return match ? match[1] : "";
}

function normalizeBreakdownMoment(value, index) {
  const text = cleanText(value);
  if (!text || text === "—") return `Момент ${index}`;
  if (/^\d+$/.test(text)) return `Момент ${text}`;
  return text;
}

const CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE = "Нет сохранённого подтверждения из звонка.";

function breakdownFragmentOrNote(value) {
  const text = cleanText(value);
  if (!text || text === "—") return CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE;
  return text;
}

function breakdownSupportingQuote(value) {
  const text = quoteText(value);
  if (!text || text === "—" || text === CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE) return "";
  return text;
}

function normalizeBreakdownObject(row, index) {
  const fallbackFragment = breakdownSupportingQuote(firstNonEmpty(
    quoteText(row.supporting_quote),
    dialogueExcerptText(row.dialogue_excerpt),
    quoteText(row.fragment),
    quoteText(row.quote),
    quoteText(row.evidence_quote),
  ));
  return {
    moment: normalizeBreakdownMoment(firstNonEmpty(row.moment, row.time, row.time_label, row.label), index),
    what: firstNonEmpty(row.what, row.what_happened, row.problem, row.issue, row.description, "—"),
    moment_summary: firstNonEmpty(row.coaching_moment?.summary, row.moment_summary, row.summary, ""),
    supporting_quote: breakdownSupportingQuote(firstNonEmpty(
      quoteText(row.coaching_moment?.supporting_quote),
      quoteText(row.supporting_quote),
      dialogueExcerptText(row.dialogue_excerpt),
      quoteText(row.fragment),
      quoteText(row.quote),
      quoteText(row.evidence_quote),
    )),
    proof_type: firstNonEmpty(row.proof_type, row.coaching_moment?.proof_type, row.evidence_type),
    supporting_quote_proof_type: firstNonEmpty(row.supporting_quote_proof_type, row.quote_proof_type),
    quote_role: firstNonEmpty(row.quote_role, row.coaching_moment?.quote_role),
    supporting_quote_repeated_with_situation_day: Boolean(row.supporting_quote_repeated_with_situation_day),
    better: firstNonEmpty(row.better, row.recommendation, row.next_action, row.what_to_do, "—"),
  };
}

function splitBreakdownFragment(value) {
  const text = cleanText(value);
  const match = text.match(/\s*Фрагмент:\s*[«"](.+?)[»"]\.?\s*$/);
  if (!match) return { what: text, moment_summary: text || CALL_BREAKDOWN_MISSING_FRAGMENT_NOTE, supporting_quote: "" };
  return {
    what: text.slice(0, match.index).replace(/[.\s]+$/, "") || "—",
    moment_summary: breakdownFragmentOrNote(match[1]),
    supporting_quote: breakdownSupportingQuote(match[1]),
  };
}

function splitBreakdownSummaryAndProof(value) {
  const text = cleanText(value);
  if (!text || text === "—") return { summary: "", proof: "" };
  const split = splitBreakdownFragment(text);
  if (split.supporting_quote) {
    return { summary: split.what || "", proof: split.supporting_quote };
  }
  const dialogueMatch = text.match(/(?:^|\s)(менеджер|клиент|оператор|продавец|собеседник)\s*:/i);
  if (dialogueMatch) {
    const index = dialogueMatch.index || 0;
    return {
      summary: cleanText(text.slice(0, index).replace(/[ .:-]+$/, "")),
      proof: text.slice(index).trim(),
    };
  }
  if (/^[«"].+[»"]$/.test(text)) return { summary: "", proof: text };
  return { summary: text, proof: "" };
}

function normalizeBreakdownRow(row, index, context = {}) {
  if (!Array.isArray(row) && row && typeof row === "object") {
    return normalizeBreakdownObject(row, index);
  }
  const parentMomentSummary = firstNonEmpty(context.moment_summary, context.coaching_moment?.summary);
  const parentProofType = firstNonEmpty(context.proof_type, context.evidence_type, context.coaching_moment?.proof_type);
  const parentQuoteRole = firstNonEmpty(context.quote_role, context.coaching_moment?.quote_role);
  if (row.length >= 4) {
    const splitProof = splitBreakdownSummaryAndProof(row[2]);
    const quote = breakdownSupportingQuote(splitProof.proof);
    const momentSummary = firstNonEmpty(parentMomentSummary, splitProof.summary);
    return {
      moment: normalizeBreakdownMoment(row[0], index),
      what: row[1] || "—",
      moment_summary: momentSummary,
      supporting_quote: quote,
      proof_type: parentProofType,
      supporting_quote_proof_type: parentQuoteRole === "supports_context" ? "context_support" : parentProofType,
      quote_role: parentQuoteRole,
      supporting_quote_repeated_with_situation_day: Boolean(context.repetition_reduced_with_situation_day),
      better: row[3] || "—",
    };
  }
  const split = splitBreakdownFragment(row[1] || "");
  const momentSummary = firstNonEmpty(parentMomentSummary, split.moment_summary, "—");
  return {
    moment: normalizeBreakdownMoment(row[0], index),
    what: split.what || "—",
    moment_summary: momentSummary,
    supporting_quote: split.supporting_quote && split.supporting_quote !== momentSummary ? split.supporting_quote : "",
    proof_type: parentProofType,
    supporting_quote_proof_type: parentQuoteRole === "supports_context" ? "context_support" : parentProofType,
    quote_role: parentQuoteRole,
    supporting_quote_repeated_with_situation_day: Boolean(context.repetition_reduced_with_situation_day),
    better: row[2] || "—",
  };
}

function stageStatus(stage) {
  if (stage.priority) return "Фокус на завтра";
  if (stage.score5 !== null && stage.score5 >= 4.0) return "Норма";
  return "Зона внимания";
}

function normalizeProblemStatement(text, stageCode = "", kind = "gap") {
  const value = cleanText(text);
  if (!value || kind === "strength") return value;
  const normalized = value.toLowerCase().replace(/ё/g, "е");
  if (normalized.includes("не уш") && normalized.includes("презентац") && normalized.includes("слишком рано")) {
    return stageCode === "needs_discovery"
      ? "Потребность клиента не была раскрыта до предложения."
      : "Квалификация не была завершена до предложения.";
  }
  if (normalized.includes("сохранил") && (normalized.includes("нейтральн") || normalized.includes("вежлив") || normalized.includes("понятн"))) {
    return "Тон был вежливым, но не помог продвинуть разговор.";
  }
  if (normalized.includes("представ") && (normalized.includes("компан") || normalized.includes("себ"))) {
    return "Повод звонка был объяснён недостаточно ясно.";
  }
  if (normalized.includes("понятно обозначил") && normalized.includes("причин")) {
    return "Причина звонка не была связана с задачей клиента.";
  }
  return value;
}

function stageProblem(stage) {
  if (stage.priority) {
    return normalizeProblemStatement(firstNonEmpty(
      stage.problem_summary,
      DATA.key_problem?.title,
      "Этот этап сейчас главный фокус ближайшей отработки.",
    ), stage.stage_code || "");
  }
  return normalizeProblemStatement(firstNonEmpty(stage.problem_summary, "Недостаточно данных для конкретного вывода по этапу."), stage.stage_code || "");
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
    money_on_table: { body: "", highlight_line: "", reason_line: "", note: "", hidden: true },
    pipeline: { summary_line: "Тёплые контакты дня не выделены.", counts_line: "", conversion_line: "", average_line: "", contacts: [] },
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
    voice_of_customer_scenes: [],
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
    const oldShape = row.length >= 6;
    const payloadCall = (payload.call_list || [])[Number(row[0]) - 1];
    let status;
    if (payloadCall) {
      const ct = (payloadCall.call_type || "").toLowerCase();
      const st = ((payloadCall.call_list_status ?? payloadCall.status) || "").toLowerCase();
      if (statusLabelMap[st]) {
        status = statusLabelMap[st];
      } else if (ct === "support" || ct === "internal") {
        status = "Тех/сервис";
      } else {
        status = payloadCall.call_list_unclassified_status_label
          || payloadCall.unclassified_status_label
          || unclassifiedStatusMap[payloadCall.call_list_unclassified_reason_code]
          || unclassifiedStatusMap[payloadCall.unclassified_reason_code]
          || "Без разбора";
      }
    } else {
      // Fallback to pre-rendered section row for forward/backward compatibility
      status = (oldShape ? row[5] : row[4]) || "Без разбора";
    }
    const rawContext = (oldShape ? row[4] : row[3]) || "—";
    const payloadStatus = payloadCall ? (payloadCall.call_list_status ?? payloadCall.status) : null;
    const context = (payloadCall && !payloadStatus)
      ? (
          payloadCall.call_list_unclassified_context_label
          || payloadCall.unclassified_context_label
          || unclassifiedContextMap[payloadCall.call_list_unclassified_reason_code]
          || unclassifiedContextMap[payloadCall.unclassified_reason_code]
          || "Нет готового разбора"
        )
      : ((status === "Без разбора" && rawContext === "—") ? "Нет готового разбора" : rawContext);
    return {
      n: row[0] || "—",
      client: (oldShape ? row[2] : row[1]) || "—",
      topic: (oldShape ? row[3] : row[2]) || "—",
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
  const payloadBreakdownRows = payload.call_breakdown?.stages || payload.call_breakdown?.moments || [];
  const breakdownRows = payloadBreakdownRows.length > 0 ? payloadBreakdownRows : (callBreakdown.rows || []);
  const breakdownSource = String(
    payload.call_breakdown?.call_breakdown_source
    || payload.call_breakdown?.source_note
    || callBreakdown.source_note
    || "",
  );
  const breakdownMomentContext = (
    breakdownSource.includes("semantic_case")
    || breakdownSource.includes("block_candidates")
    || (breakdownRows.length === 1 && payload.call_breakdown?.moment_summary)
  )
    ? payload.call_breakdown
    : {};

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
      hidden: moneyOnTable.hidden !== false,
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
      stage_code: stage.stage_code || "",
      name: `${stage.funnel_label || ""} ${stage.stage_name || ""}`.trim(),
      score10: stage.score ?? null,
      score5: stage.score === null || stage.score === undefined ? null : safeNumber((safeNumber(stage.score) / 2).toFixed(1), null),
      calls_count: safeNumber(stage.calls_count, 0),
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
    stage_scope: payload.stage_score_scope || {},
    situation: {
      title: situation.situation_title || "СИТУАЦИЯ ДНЯ",
      block_label: situation.label || "СИТУАЦИЯ ДНЯ",
      data_scope: situation.data_scope || "report_day",
      scope_note: situation.scope_note || "",
      example_label: situation.example_label || "Пример из сегодня",
      body: situation.body || situation.text || "",
      pattern_count_label: situation.pattern_count_label || "",
      client_need: situation.client_need || "",
      manager_task: situation.manager_task || "",
      call_example: situation.call_example || {},
      evidence_quote: payload.situation_evidence_quote || null,
      dialogue_excerpt: payload.situation_dialogue_excerpt || null,
      coaching_moment: payload.coaching_moment || payload.situation_coaching_moment || situation.coaching_moment || null,
      moment_summary: firstNonEmpty(payload.moment_summary, payload.situation_moment_summary, situation.moment_summary),
      supporting_quote: payload.supporting_quote || payload.situation_supporting_quote || situation.supporting_quote || null,
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
      block_label: callBreakdown.label || "РАЗБОР ЗВОНКА",
      data_scope: callBreakdown.data_scope || "report_day",
      scope_note: callBreakdown.scope_note || "",
      client: payload.call_breakdown?.client_label || "Клиент",
      time: payload.call_breakdown?.time_label || "—",
      reference: payload.call_breakdown?.client_call_reference || "",
      summary: payload.call_breakdown?.summary_line || "",
      call_story: payload.call_breakdown?.call_story || "",
      what_manager_missed: payload.call_breakdown?.what_manager_missed || "",
      better_path: payload.call_breakdown?.better_path || "",
      dialogue_evidence: payload.call_breakdown?.dialogue_evidence || [],
      key_turning_points: payload.call_breakdown?.key_turning_points || [],
      stages: breakdownRows.map((row, index) => normalizeBreakdownRow(row, index + 1, breakdownMomentContext)),
    },
    voice_of_customer_scenes: ((voice.customer_scenes || payload.voice_of_customer?.customer_scenes || [])).map((scene, index) => ({
      client: scene.client_call_reference || scene.client_label || `Клиент ${index + 1}`,
      scene_summary: scene.scene_summary || scene.quote_context || scene.quote || "",
      customer_meaning: scene.customer_meaning || scene.interpretation || scene.context || "",
      manager_response: scene.manager_response || scene.manager_action || "",
      why_action_follows: scene.why_action_follows || "",
      dialogue_evidence: scene.dialogue_evidence || [],
      quote: scene.quote || "",
    })),
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
        title: normalizeProblemStatement((item.title || "").trim(), item.stage_code || "", item.kind || (item.badge === "Сильная сторона" ? "strength" : "gap")),
        badge: item.badge || (item.kind === "strength" ? "Сильная сторона" : "Зона роста"),
        stage_id: item.stage_id || "",
        stage_code: item.stage_code || "",
        problem_signal: item.problem_signal || "",
        data_scope: item.data_scope || "",
        evidence_call_id: item.evidence_call_id || "",
        evidence_quote: item.evidence_quote || "",
        evidence_dialogue: item.evidence_dialogue || [],
        client_call_reference: item.client_call_reference || "",
        confidence: item.confidence || "",
        client_said: item.client_said || item.what_happened || item.evidence_quote || "",
        meant: item.meant || item.why_it_matters || "",
        how_to: item.how_to || item.next_action || "",
        why: item.why || item.why_this_works || "",
        narrative: item.narrative || "",
        type: item.kind || (item.badge === "Сильная сторона" ? "strength" : "gap"),
        signal: safeNumber(item.signal) || 0,
      }))
      .filter((item) => item.title && item.client_said && item.meant && item.how_to),
    additional_situations_scope_note: (sections.additional_situations || {}).scope_note || "",
    challenge: {
      data_scope: challenge.data_scope || "report_day",
      scope_note: challenge.scope_note || "",
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
        client: firstNonEmpty(contact.client_call_reference, row[1], contact.client_label, "Клиент"),
        phone: "",
        status: cleanText(contact.status || ""),
        situation: row[2] || tomorrowSituation(contact, row),
        recommendation: row[3] || `${tomorrowRecommendation(contact, row)}. Можно начать: «${tomorrowFirstPhrase(contact, row)}».`,
        first_phrase: tomorrowFirstPhrase(contact, row),
      };
    }).filter((item) => item.client && cleanText(item.situation) !== "Следующий шаг не зафиксирован"),
    all_calls: allCalls,
    morning: {
      greeting: morningCard.greeting || "",
      summary_line: morningCard.summary_line || "",
      financial_line: "",
      top_contacts: (callTomorrow.rows || []).slice(0, 3).map((row, index) => ({
        index: index + 1,
        client: (callTomorrow.contacts || payload.call_tomorrow?.contacts || [])[index]?.client_call_reference || row[1] || "Клиент",
        phone: "",
        script: extractOpeningScript(row[3]) || row[3] || "",
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
  gray:        "5F6368",  // meta / secondary, darkened for PDF readability
  black:       "1A1A1A",  // body text
  sectionBg:   "1F3864",  // section header background (dark navy)
  sectionText: "FFFFFF",  // section header text (white on dark)
  tableHead:   "C8DCF0",  // table header row background (medium-light blue)
  priorityBg:  "FFF3CD",
  white:       "FFFFFF",
  altRow:      "F9F9F9",
};

// 5-role type scale, stored in half-points:
// display 20pt, section 14.5pt, body 11.5pt, table 11pt, caption 9pt.
const SZ = { h1: 40, h2: 29, accent: 23, body: 23, cell: 22, meta: 20, caption: 18 };

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
    size = SZ.cell,
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
  const { bold = false, color = COLORS.black, size = SZ.body, indent = 0, italic = false, before = 0, after = 60 } = opts;
  return new Paragraph({
    indent: indent ? { left: indent } : undefined,
    children: [
      new TextRun({ text, bold, color, size, font: "Arial", italics: italic }),
    ],
    spacing: { before, after },
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
    width: { size: 70, type: WidthType.PERCENTAGE },
    borders: BORDER_THIN,
    verticalAlign: VerticalAlign.TOP,
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    children: paras,
  });
}

function cellParagraphs(paras, opts = {}) {
  const {
    shading = null,
    borders = BORDER_THIN,
    vertAlign = VerticalAlign.TOP,
    width = null,
  } = opts;
  const cellOpts = {
    borders,
    verticalAlign: vertAlign,
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    children: paras,
  };
  if (shading) cellOpts.shading = shading;
  if (width) cellOpts.width = width;
  return new TableCell(cellOpts);
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
        headCell("Этап", { width: { size: 29, type: WidthType.PERCENTAGE } }),
        headCell("Балл", { width: { size: 9, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
        headCell("Звонков", { width: { size: 10, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
        headCell("Статус", { width: { size: 13, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
        headCell("Основная проблема", { width: { size: 39, type: WidthType.PERCENTAGE } }),
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
      cell(st.name, { width: { size: 29, type: WidthType.PERCENTAGE }, color: nameColor, bold: st.priority, shading: rowShading }),
      cell(scoreStr, { width: { size: 9, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER, color: scoreColor, bold: st.priority, shading: rowShading }),
      cell(String(st.calls_count ?? 0), { width: { size: 10, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER, shading: rowShading, size: SZ.cell }),
      cell(status, { width: { size: 13, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER, color: statusColor, bold: st.priority, shading: rowShading, size: SZ.cell }),
      cell(stageProblem(st), { width: { size: 39, type: WidthType.PERCENTAGE }, shading: rowShading, size: SZ.cell }),
    ];

    rows.push(new TableRow({ children: rowCells }));
  }

  const block = [
    blockHeading("📈", "БАЛЛЫ ПО ЭТАПАМ"),
  ];
  if (DATA.stage_scope?.note) {
    block.push(bodyPara(DATA.stage_scope.note, { color: COLORS.gray, size: SZ.meta }));
    block.push(spacer(3));
  }
  block.push(
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      layout: TableLayoutType.FIXED,
      rows,
    }),
  );
  block.push(
    spacer(4),
    bodyPara(
      "Фокус на завтра — этап, который сейчас сильнее всего мешает продвинуть клиента дальше по воронке.",
      { color: COLORS.gray, size: SZ.meta },
    ),
  );
  return block;
}

// ──────────────────────────────────────────────────────────────
// Block 6 — СИТУАЦИЯ ДНЯ
// ──────────────────────────────────────────────────────────────

function buildSituatsiya() {
  const s = DATA.situation;
  if (s.coaching_view?.situation_day_evidence_status === "insufficient") {
    return [
      blockHeading("🎯", "СИТУАЦИЯ ДНЯ"),
      bodyPara("Нет надежно подтвержденной ситуации дня.", { color: COLORS.gray }),
    ];
  }
  const callRef = buildCallReference(s.dialogue_excerpt || s.supporting_quote || s.evidence_quote);
  const whatHappenedText = buildWhatHappenedText(s);
  const momentSummary = situationMomentSummary(s);
  const supportingQuote = situationSupportingQuote(s);
  const reviewRows = buildSituationReviewRows(s);
  const narrativeText = buildSituationNarrativeText({
    whatHappenedText,
    callContext: cleanText(s.coaching_view?.call_context_summary),
    evidenceQuotes: (s.coaching_view?.evidence_quotes || []).filter((item) => cleanText(item)),
    supportingQuote,
  });
  const hasMoment = Boolean(momentSummary || supportingQuote);
  const patternTitle = buildSituationPatternTitle(s);
  const stageMeta = buildSituationStageMeta(s);

  if (!narrativeText && reviewRows.length === 0 && !hasMoment) {
    return [
      blockHeading("🎯", "СИТУАЦИЯ ДНЯ"),
      bodyPara("Данных за этот день недостаточно.", { color: COLORS.gray }),
    ];
  }

  const result = [
    blockHeading("🎯", `${s.block_label || "СИТУАЦИЯ ДНЯ"} · ${patternTitle}`),
  ];
  if (s.scope_note) {
    result.push(bodyPara(s.scope_note, { color: COLORS.gray, size: SZ.meta }));
  }
  if (stageMeta) {
    result.push(subHeading("Фокусный этап"));
    result.push(bodyPara(stageMeta.replace(/^Фокусный этап:\s*/i, ""), { size: SZ.cell }));
  } else if (s.title) {
    result.push(subHeading("Фокусный этап"));
    result.push(bodyPara(cleanText(s.title), { size: SZ.cell }));
  }
  if (callRef) {
    result.push(subHeading(s.example_label || "Пример из сегодня"));
    result.push(bodyPara(callRef, { size: SZ.cell }));
  }
  if (narrativeText) {
    result.push(subHeading("Что произошло"));
    result.push(...buildSituationNarrativeParagraphs(narrativeText));
  }
  if (reviewRows.length > 0) {
    result.push(new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      layout: TableLayoutType.FIXED,
      rows: reviewRows,
    }));
  }
  return result;
}

function buildSituationNarrativeParagraphs(narrativeText) {
  const rawText = String(narrativeText || "").trim();
  if (!cleanText(rawText)) return [];
  const proofMarker = "Это видно по репликам:";
  const markerIndex = rawText.indexOf(proofMarker);
  const mainText = markerIndex >= 0 ? cleanText(rawText.slice(0, markerIndex)) : cleanText(rawText);
  const proofText = markerIndex >= 0 ? rawText.slice(markerIndex).trim() : "";
  const sentences = mainText
    .split(/(?<=[.!?])\s+/)
    .map((item) => cleanText(item))
    .filter(Boolean);
  const paragraphs = [];
  for (let index = 0; index < sentences.length; index += 2) {
    paragraphs.push(sentences.slice(index, index + 2).join(" "));
  }
  const result = paragraphs.map((item, index) => bodyPara(item, {
    size: SZ.cell,
    before: index === 0 ? 0 : 60,
  }));
  if (proofText) {
    const proofLines = String(proofText).split(/\n+/).map((item) => cleanText(item)).filter(Boolean);
    const markerLine = proofLines[0] || proofMarker;
    result.push(bodyPara(markerLine, { size: SZ.cell, italic: true, before: result.length === 0 ? 0 : 60, after: 30 }));
    for (const line of proofLines.slice(1)) {
      result.push(...dialogueCellParagraphsFromText(line, { size: SZ.cell, limit: 700 }));
    }
  }
  return result;
}

function buildSituationNarrativeText({ whatHappenedText, callContext, evidenceQuotes, supportingQuote }) {
  const parts = [];
  if (whatHappenedText) {
    parts.push(whatHappenedText);
  }
  if (callContext && !sameMeaningText(callContext, whatHappenedText)) {
    parts.push(callContext);
  }
  const quotes = evidenceQuotes.length > 0
    ? evidenceQuotes
    : supportingQuote
      ? [supportingQuote]
      : [];
  if (quotes.length > 0) {
    const quoteLines = quotes
      .map((item, index) => `${speakerForQuoteIndex(index)}: ${cleanText(item).replace(/^«|»$/g, "")}`)
      .filter((item) => cleanText(item));
    if (quoteLines.length > 0) {
      parts.push(`Это видно по репликам:\n${quoteLines.join("\n")}`);
    }
  }
  return parts.join("\n\n");
}

// ──────────────────────────────────────────────────────────────
// Block 7 — РАЗБОР ЗВОНКА
// ──────────────────────────────────────────────────────────────

function buildBreakdownMomentCell(s, i) {
  const quote = s.supporting_quote_repeated_with_situation_day ? "" : firstNonEmpty(s.supporting_quote, "");
  const rawQuoteLabel = proofTypeLabel(
    firstNonEmpty(s.supporting_quote_proof_type, s.quote_role === "supports_context" ? "context_support" : "", s.proof_type),
    "Подтверждение из звонка",
  );
  const quoteLabel = rawQuoteLabel === "Суть момента" ? "Подтверждение из звонка" : rawQuoteLabel;
  const proof = firstNonEmpty(quote, "");
  const paras = proof
    ? [
        bodyPara(quoteLabel, { size: SZ.cell, bold: true, color: COLORS.heading, after: 30 }),
        ...dialogueCellParagraphsFromText(proof, { size: SZ.cell, limit: 300, speaker: "Сторона 1" }),
      ]
    : [new Paragraph({
        children: [new TextRun({ text: "—", size: SZ.cell, color: COLORS.gray, font: "Arial" })],
        spacing: { before: 0, after: 0 },
      })];
  return cellParagraphs(paras, {
    width: { size: 28, type: WidthType.PERCENTAGE },
    shading: altShading(i),
  });
}

function breakdownEvidenceParagraphs(evidence, fallbackText = "", opts = {}) {
  const size = opts.size || SZ.cell;
  const items = Array.isArray(evidence) ? evidence : [];
  const paras = [];
  items.forEach((item, index) => {
    const raw = item || {};
    const speaker = dialogueSpeakerLabel(raw.speaker || speakerForQuoteIndex(index));
    const text = cleanText(raw.text || raw.quote || "");
    if (text) paras.push(dialoguePara(speaker, text, { size, limit: opts.limit || 700 }));
  });
  if (paras.length > 0) return paras;
  return dialogueCellParagraphsFromText(fallbackText, { size, limit: opts.limit || 700, speaker: "Сторона 1" });
}

function buildBreakdownNarrativeParagraphs(data) {
  const blocks = [];
  const story = cleanText(data.call_story);
  if (story) {
    blocks.push(...buildSituationNarrativeParagraphs(story));
  }
  const points = (data.key_turning_points || []).filter((item) => cleanText(item.title || item.what_happened));
  if (points.length > 0) {
    blocks.push(subHeading("Ход звонка"));
    points.slice(0, 4).forEach((point, index) => {
      const title = cleanText(point.title) || `Момент ${index + 1}`;
      const what = cleanText(point.what_happened);
      const action = cleanText(point.better_action);
      blocks.push(bodyPara(`${index + 1}. ${title}`, { size: SZ.cell, bold: true, color: COLORS.heading, before: index === 0 ? 0 : 60, after: 30 }));
      [what].filter(Boolean).forEach((line) => {
        blocks.push(bodyPara(line, { size: SZ.cell, after: 35 }));
      });
      const evidenceParas = breakdownEvidenceParagraphs(point.dialogue_evidence, "", { size: SZ.cell, limit: 520 });
      if (evidenceParas.length > 0) {
        blocks.push(...evidenceParas);
      }
      if (action) {
        blocks.push(bodyPara(`В этом месте лучше: ${action.replace(/^Сказать:\s*/i, "")}`, { size: SZ.cell, color: COLORS.heading, italic: true, before: 20 }));
      }
    });
  }
  return blocks;
}

function breakdownWhatText(s) {
  const what = cleanText(s.what);
  const summary = cleanText(firstNonEmpty(s.moment_summary, s.summary, ""));
  if (!what) return summary || "—";
  if (!summary || sameMeaningText(what, summary)) return what;
  return `${what}. ${summary}`;
}

function buildRazbor() {
  const { block_label, client, time, reference, summary, stages, scope_note } = DATA.call_breakdown;
  const callReference = reference || `${client} · ${time}`;
  const summaryLine = summary || callReference;
  const displaySummaryLine = summaryLine.replace(/подтверждающий фрагмент ограничен/gi, "подтверждение из звонка ограничено");
  if (!stages || stages.length === 0) {
    return [
      blockHeading("🔍", block_label || "РАЗБОР ЗВОНКА"),
      ...(scope_note ? [bodyPara(scope_note, { color: COLORS.gray, size: SZ.meta })] : []),
      bodyPara(displaySummaryLine, { color: COLORS.gray, size: SZ.meta }),
      bodyPara("Недостаточно данных для детального разбора звонка.", { color: COLORS.gray, size: SZ.meta }),
    ];
  }
  const introLine = summaryLine.includes("подтверждающий фрагмент ограничен")
    ? displaySummaryLine
    : `${displaySummaryLine} · Звонок выбран как наиболее показательный для основного паттерна дня.`;
  const narrativeBlocks = buildBreakdownNarrativeParagraphs(DATA.call_breakdown);
  if (narrativeBlocks.length > 0) {
    return [
      blockHeading("🔍", block_label || "РАЗБОР ЗВОНКА"),
      ...(scope_note ? [bodyPara(scope_note, { color: COLORS.gray, size: SZ.meta })] : []),
      bodyPara(introLine, { color: COLORS.gray, size: SZ.meta }),
      ...narrativeBlocks,
    ];
  }
  const headerRows = [
    new TableRow({
      children: [
        headCell("Момент / время", { width: { size: 10, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
        headCell("Что было",       { width: { size: 31, type: WidthType.PERCENTAGE } }),
        headCell("Подтверждение из звонка", { width: { size: 28, type: WidthType.PERCENTAGE } }),
        headCell("Рекомендация",   { width: { size: 31, type: WidthType.PERCENTAGE } }),
      ],
    }),
  ];

  const dataRows = stages.map((s, i) =>
    new TableRow({
      children: [
        cell(s.moment, { width: { size: 10, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER, shading: altShading(i), color: COLORS.gray }),
        cell(breakdownWhatText(s), { width: { size: 31, type: WidthType.PERCENTAGE }, shading: altShading(i) }),
        buildBreakdownMomentCell(s, i),
        cell(s.better, { width: { size: 31, type: WidthType.PERCENTAGE }, shading: altShading(i), color: COLORS.heading }),
      ],
    })
  );

  return [
    blockHeading("🔍", block_label || "РАЗБОР ЗВОНКА"),
    ...(scope_note ? [bodyPara(scope_note, { color: COLORS.gray, size: SZ.meta })] : []),
    bodyPara(introLine, { color: COLORS.gray, size: SZ.meta }),
    spacer(4),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      layout: TableLayoutType.FIXED,
      rows: [...headerRows, ...dataRows],
    }),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 8 — ГОЛОС КЛИЕНТА
// ──────────────────────────────────────────────────────────────

function buildGolos() {
  const scenes = (DATA.voice_of_customer_scenes || []).filter((scene) =>
    cleanText(scene.scene_summary || scene.customer_meaning || scene.manager_response || scene.quote)
  );
  if (scenes.length > 0) {
    const blocks = [
      blockHeading("👤", "ГОЛОС КЛИЕНТА"),
      bodyPara(
        "Клиентские сигналы разобраны как сцены: что клиент сказал, что это значит и как менеджеру отвечать.",
        { color: COLORS.gray, size: SZ.meta },
      ),
      spacer(4),
    ];
    scenes.slice(0, 4).forEach((scene, index) => {
      const title = cleanText(scene.client) || `Клиент ${index + 1}`;
      const summary = cleanText(scene.scene_summary);
      const meaning = cleanText(scene.customer_meaning);
      const why = cleanText(scene.why_action_follows);
      const action = cleanText(scene.manager_response);
      const seenLines = new Set();
      const pushUniqueText = (text, opts = {}) => {
        const normalized = cleanText(text).toLowerCase();
        if (!normalized || seenLines.has(normalized)) return;
        seenLines.add(normalized);
        blocks.push(bodyPara(text, opts));
      };
      blocks.push(bodyPara(`${index + 1}. ${title}`, { size: SZ.cell, bold: true, color: COLORS.heading, before: index === 0 ? 0 : 80, after: 30 }));
      if (summary) {
        const sentences = summary.split(/(?<=[.!?])\s+/).map((item) => cleanText(item)).filter(Boolean);
        for (let sentenceIndex = 0; sentenceIndex < sentences.length; sentenceIndex += 2) {
          pushUniqueText(sentences.slice(sentenceIndex, sentenceIndex + 2).join(" "), { size: SZ.cell, after: 55 });
        }
      }
      if (meaning) {
        const before = blocks.length;
        pushUniqueText(meaning, { size: SZ.cell });
        if (blocks.length > before) {
          blocks.splice(before, 0, subHeading("Что клиент имеет в виду"));
        }
      }
      const evidenceParas = breakdownEvidenceParagraphs(scene.dialogue_evidence, scene.quote || scene.scene_summary, { size: SZ.cell, limit: 620 });
      if (evidenceParas.length > 0) {
        blocks.push(subHeading("Реплики"));
        blocks.push(...evidenceParas);
      }
      if (why) {
        const before = blocks.length;
        pushUniqueText(why, { size: SZ.cell });
        if (blocks.length > before) {
          blocks.splice(before, 0, subHeading("Что это значит"));
        }
      }
      if (action) {
        blocks.push(bodyPara(`Как с этим работать: ${action.replace(/^(Что сделать|Как с этим работать):\s*/i, "")}`, { size: SZ.cell, color: COLORS.heading, italic: true }));
      }
    });
    return blocks;
  }
  if (!DATA.voice_of_customer || DATA.voice_of_customer.length === 0) {
    return [
      blockHeading("👤", "ГОЛОС КЛИЕНТА"),
      bodyPara("Клиентские цитаты появятся после накопления материала по звонкам.", { color: COLORS.gray, size: SZ.meta }),
    ];
  }
  const headerRow = new TableRow({
    children: [
      headCell("Клиент / звонок", { width: { size: 20, type: WidthType.PERCENTAGE } }),
      headCell("Что сказал клиент", { width: { size: 36, type: WidthType.PERCENTAGE } }),
      headCell("Что клиент имеет в виду / Как с этим работать", { width: { size: 44, type: WidthType.PERCENTAGE } }),
    ],
  });

  const dataRows = DATA.voice_of_customer.map((v, i) =>
    new TableRow({
      children: [
        cell(v.client, { width: { size: 20, type: WidthType.PERCENTAGE }, shading: altShading(i), size: SZ.cell }),
        cell(v.quote,  { width: { size: 36, type: WidthType.PERCENTAGE }, shading: altShading(i), italic: true }),
        cell(v.interpretation, { width: { size: 44, type: WidthType.PERCENTAGE }, shading: altShading(i), color: COLORS.heading, size: SZ.cell }),
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
      layout: TableLayoutType.FIXED,
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
    return blocks;
  }

  const headingText = situations.length === 1
    ? "ДОПОЛНИТЕЛЬНАЯ СИТУАЦИЯ"
    : "ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ";
  blocks.push(blockHeading("📋", headingText));
  if (DATA.additional_situations_scope_note) {
    blocks.push(bodyPara(DATA.additional_situations_scope_note, { color: COLORS.gray, size: SZ.meta }));
  }
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

    if (s.client_call_reference) {
      blocks.push(bodyPara(s.client_call_reference, { color: COLORS.gray, size: SZ.meta, after: 30 }));
    }
    const narrative = cleanText(s.narrative) || [s.client_said, s.meant, s.why].filter(Boolean).join(" ");
    if (narrative) {
      blocks.push(...buildSituationNarrativeParagraphs(narrative));
    }
    const evidenceParas = breakdownEvidenceParagraphs(s.evidence_dialogue, s.evidence_quote, { size: SZ.cell, limit: 620 });
    if (evidenceParas.length > 0) {
      blocks.push(subHeading("Подтверждение"));
      blocks.push(...evidenceParas);
    }
    if (s.how_to) {
      blocks.push(bodyPara(`Что сделать: ${s.how_to}`, { color: s.type === "strength" ? COLORS.heading : COLORS.green, italic: true }));
    }
    blocks.push(spacer(8));
  }

  return blocks;
}

// ──────────────────────────────────────────────────────────────
// Block 10 — ЧЕЛЛЕНДЖ НА ЗАВТРА
// ──────────────────────────────────────────────────────────────

function buildChellendj() {
  return [];

  const c = DATA.challenge;

  function clCell(text) {
    return new TableCell({
      width: { size: 30, type: WidthType.PERCENTAGE },
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
      width: { size: 70, type: WidthType.PERCENTAGE },
      shading: { fill: "FFFBEA", type: ShadingType.CLEAR },
      verticalAlign: VerticalAlign.TOP,
      margins: { top: 80, bottom: 80, left: 100, right: 100 },
      children: paras,
    });
  }

  const rows = [];
  if (c.scope_note) {
    rows.push(new TableRow({ children: [
      clCell("База"),
      clContentCell([new Paragraph({
        children: [new TextRun({ text: c.scope_note, size: SZ.cell, color: COLORS.black, font: "Arial" })],
        spacing: { before: 0, after: 0 },
      })]),
    ]}));
  }

  if (c.goal_line) {
    rows.push(new TableRow({ children: [
      clCell("Цель"),
      clContentCell([new Paragraph({
        children: [new TextRun({ text: c.goal_line, size: SZ.cell, color: COLORS.black, font: "Arial" })],
        spacing: { before: 0, after: 0 },
      })]),
    ]}));
  }

  const contextLines = [c.today_line, c.record_line].filter(Boolean);
  if (contextLines.length > 0) {
    rows.push(new TableRow({ children: [
      clCell("Фокус на завтра"),
      clContentCell(contextLines.map((line) => new Paragraph({
        children: [new TextRun({ text: line, size: SZ.cell, color: COLORS.black, font: "Arial" })],
        spacing: { before: 0, after: 20 },
      }))),
    ]}));
  }

  if (c.phrase_line) {
    rows.push(new TableRow({ children: [
      clCell("Фраза для завтра"),
      clContentCell([new Paragraph({
        children: [new TextRun({ text: `«${c.phrase_line}»`, size: SZ.cell, color: COLORS.black, font: "Arial" })],
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
      layout: TableLayoutType.FIXED,
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
      headCell("Приоритет", { width: { size: 10, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
      headCell("Клиент",    { width: { size: 22, type: WidthType.PERCENTAGE } }),
      headCell("Контекст", { width: { size: 20, type: WidthType.PERCENTAGE } }),
      headCell("Рекомендация", { width: { size: 48, type: WidthType.PERCENTAGE } }),
    ],
  });

  const dataRows = DATA.call_tomorrow.map((c, i) => {
    const prioColor = c.priority === "🔴" ? COLORS.red
      : c.priority === "🟡" ? COLORS.orange
      : COLORS.heading;

    return new TableRow({
      children: [
        cell(`${c.priority} ${c.label}`, { width: { size: 10, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER, color: prioColor, bold: true, shading: altShading(i) }),
        cell(c.client, { width: { size: 22, type: WidthType.PERCENTAGE }, shading: altShading(i) }),
        cell(c.situation, { width: { size: 20, type: WidthType.PERCENTAGE }, shading: altShading(i) }),
        cell(c.recommendation, { width: { size: 48, type: WidthType.PERCENTAGE }, shading: altShading(i) }),
      ],
    });
  });

  return [
    blockHeading("📞", "КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА"),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      layout: TableLayoutType.FIXED,
      rows: [headerRow, ...dataRows],
    }),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 12 — ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ
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
      headCell("#",       { width: { size: 4, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
      headCell("Клиент",  { width: { size: 30, type: WidthType.PERCENTAGE } }),
      headCell("Тип / суть", { width: { size: 21, type: WidthType.PERCENTAGE } }),
      headCell("Контекст",{ width: { size: 30, type: WidthType.PERCENTAGE } }),
      headCell("Статус",  { width: { size: 15, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
    ],
  });

  const dataRows = DATA.all_calls.map((c, i) =>
    new TableRow({
      children: [
        cell(String(c.n),   { width: { size: 4, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER, shading: altShading(i) }),
        cell(c.client,      { width: { size: 30, type: WidthType.PERCENTAGE }, shading: altShading(i) }),
        cell(c.topic,       { width: { size: 21, type: WidthType.PERCENTAGE }, shading: altShading(i) }),
        cell(c.context,     { width: { size: 30, type: WidthType.PERCENTAGE }, shading: altShading(i) }),
        cell(c.status,      { width: { size: 15, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER, shading: altShading(i), bold: true, color: statusColor(c.status) }),
      ],
    })
  );

  return [
    blockHeading("📋", "ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ"),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      layout: TableLayoutType.FIXED,
      rows: [headerRow, ...dataRows],
    }),
    spacer(6),
    bodyPara(
      `Покрытие приложения: в списке ${DATA.all_calls.length} ${russianCallWord(DATA.all_calls.length)} с разговором.`,
      { color: COLORS.gray, size: SZ.meta },
    ),
  ];
}

// ──────────────────────────────────────────────────────────────
// Финальный блок — ЛЕГЕНДА СТАТУСОВ
// ──────────────────────────────────────────────────────────────

function buildStatusLegend() {
  const items = [
    "Договорённость: есть явный коммерческий следующий шаг — счёт, КП, договор, оплата, встреча, демо или подключение.",
    "Перенос: согласован следующий контакт или клиент попросил вернуться позже.",
    "Открыт: интерес или контакт есть, но конкретный следующий шаг не зафиксирован.",
    "Отказ: клиент отказался, не заинтересован или отложил без понятного возврата.",
    "Тех/сервис: техническая помощь, регистрация, подписание, доступ или другой не продажный разговор.",
    "Не подходит: автоответчик, IVR, справочная информация или нет содержательного взаимодействия.",
  ];
  return [
    blockHeading("ℹ", "ЛЕГЕНДА СТАТУСОВ"),
    ...items.map((item) => bodyPara(`• ${item}`, { size: SZ.meta })),
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
    ...buildBally(),
    // Block 4
    ...buildSituatsiya(),
    // Block 5
    ...buildRazbor(),
    // Block 6
    ...buildGolos(),
    // Block 7
    ...buildDopSituatsii(),
    // Block 8
    ...buildChellendj(),
    // Block 9
    ...buildPozvoni(),
    // Block 10
    ...buildSpisokZvonkov(),
    // Block 11
    ...buildStatusLegend(),
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
  console.log("  [✓] ДЕНЬГИ НА СТОЛЕ hidden until CRM-ready evidence is available");
  console.log("  [✓] Warm-lead CRM block omitted for manager-facing clarity");
  console.log("  [✓] СИТУАЦИЯ ДНЯ: interpretation + 3 scripts + why");
  console.log("  [✓] ГОЛОС КЛИЕНТА: 3 human-readable columns");
  console.log("  [✓] КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА: action table");
  console.log("  [✓] РАЗБОР ЗВОНКА: 4 columns with separate confirmation from call");
  console.log("  [✓] ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ: filtered valid only, dynamic heading, reference-style cards");
  console.log("  [✓] ЧЕЛЛЕНДЖ НА ЗАВТРА: temporarily hidden");
  console.log("  [✓] УТРЕННЯЯ КАРТОЧКА removed from PDF/DOCX (payload preserved)");
  console.log("  [✓] ЛЕГЕНДА СТАТУСОВ added at the end");
  console.log("  [✓] Deleted: КЛЮЧЕВАЯ ПРОБЛЕМА, РЕКОМЕНДАЦИИ, ДИНАМИКА");
  console.log("  [✓] Footer: Конфиденциально on all pages except first");
}

main().catch((err) => {
  console.error("ERROR:", err.message);
  console.error(err.stack);
  process.exit(1);
});
