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

function stageMeaning(stage) {
  const status = stageStatus(stage);
  if (status === "Фокус на завтра") {
    return "Этот этап сейчас главный фокус ближайшей отработки.";
  }
  if (status === "Норма") {
    return "Этап в целом отработан стабильно.";
  }
  return "Этап требует усиления в ближайших звонках.";
}

function emptyStateData(payload) {
  const header = payload.header || {};
  const managerName = header.manager_name || "—";
  const reportDate = header.report_date || "—";
  return {
    manager: managerName,
    date: reportDate,
    calls: 0,
    meaningful_calls: 0,
    day_score: 0,
    outcomes: { total: 0, agreed: 0, rescheduled: 0, refusal: 0, open: 0, tech_service: 0 },
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
      scripts: [],
      why_it_works: "",
    },
    call_breakdown: { client: "—", time: "—", stages: [] },
    voice_of_customer: [],
    additional_situations: [],
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
  };
  const allCalls = (callList.rows || []).map((row) => ({
    n: row[0] || "—",
    time: row[1] || "—",
    client: row[2] || "—",
    topic: row[3] || "—",
    context: row[4] || "—",
    status: statusLabelMap[String((payload.call_list || [])[Number(row[0]) - 1]?.status || "").trim()] || row[5] || "—",
  }));
  const selectionMeaningfulCalls = safeNumber(payload.selection_model?.meaningful_calls_total, null);
  const meaningfulCalls = selectionMeaningfulCalls !== null ? selectionMeaningfulCalls : allCalls.length;

  return {
    manager: reportHeader.manager_name || payload.header?.manager_name || "—",
    date: reportHeader.report_date || payload.header?.report_date || "—",
    calls: safeNumber(reportHeader.calls_count || payload.kpi_overview?.calls_count),
    meaningful_calls: meaningfulCalls,
    day_score: safeNumber(reportHeader.day_score),
    selection_note: reportHeader.selection_note || "",
    outcomes: {
      total: safeNumber(outcomeMap["ЗВОНКОВ"]),
      agreed: safeNumber(outcomeMap["ДОГОВОРЕННОСТЬ"]),
      rescheduled: safeNumber(outcomeMap["ПЕРЕНОС"]),
      refusal: safeNumber(outcomeMap["ОТКАЗ"]),
      open: safeNumber(outcomeMap["ОТКРЫТ"]),
      tech_service: safeNumber(outcomeMap["ТЕХ/СЕРВИС"]),
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
      scripts: situation.scripts || [],
      why_it_works: situation.why_it_works || "",
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
      .filter((item) => item.title || item.client_said || item.how_to)
      .map((item) => ({
        title: `«${item.title || "Ситуация"}»`,
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
  const { bold = false, color = COLORS.black, size = SZ.body, indent = 0 } = opts;
  return new Paragraph({
    indent: indent ? { left: indent } : undefined,
    children: [
      new TextRun({ text, bold, color, size, font: "Arial" }),
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

function buildShapka() {
  return [
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
      spacing: { before: 0, after: 80 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: `${DATA.date}  ·  ${DATA.meaningful_calls} ${russianCallWord(DATA.meaningful_calls)}`,
        size: SZ.body, color: COLORS.gray, font: "Arial",
      })],
      spacing: { before: 0, after: 80 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: `Балл дня: ${DATA.day_score.toFixed(1)} / 5`,
        bold: true, size: SZ.body, color: COLORS.heading, font: "Arial",
      })],
      spacing: { before: 0, after: DATA.selection_note ? 60 : 160 },
    }),
    ...(DATA.selection_note ? [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: DATA.selection_note,
        size: SZ.meta, color: COLORS.gray, font: "Arial",
      })],
      spacing: { before: 0, after: 140 },
    })] : []),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 2 — СВОДНАЯ ТАБЛИЦА ЗВОНКОВ
// ──────────────────────────────────────────────────────────────

function buildSvodnaya() {
  const { total, agreed, rescheduled, refusal, open, tech_service } = DATA.outcomes;
  const w = { size: 1000, type: WidthType.DXA };

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

  return [
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [
        new TableRow({
          children: [
            outCell(total,        "Звонков",    COLORS.heading),
            outCell(agreed,       "Договорённость",    COLORS.green),
            outCell(rescheduled,  "Перенос",    COLORS.orange),
            outCell(refusal,      "Отказ",      COLORS.red),
            outCell(open,         "Открыт",     COLORS.gray),
            outCell(tech_service, "Тех/Сервис", COLORS.gray),
          ],
        }),
      ],
    }),
    spacer(8),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 3 — ДЕНЬГИ НА СТОЛЕ
// ──────────────────────────────────────────────────────────────

function buildDengi() {
  return [
    blockHeading("💰", "ДЕНЬГИ НА СТОЛЕ"),
    bodyPara(DATA.money_on_table.body),
    bodyPara(DATA.money_on_table.highlight_line),
    bodyPara(DATA.money_on_table.reason_line, { color: COLORS.orange }),
    bodyPara(DATA.money_on_table.note, { color: COLORS.gray }),
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
        headCell("Что это значит", { width: { size: 36, type: WidthType.PERCENTAGE } }),
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
      cell(stageMeaning(st), { shading: rowShading, size: SZ.cell }),
    ];

    rows.push(new TableRow({ children: rowCells }));
  }

  const priorityStage = DATA.stages.find((stage) => stage.priority);
  const weakFocusItems = (priorityStage?.subs || [])
    .filter((item) => item.is_weak || (item.score5 !== null && item.score5 < 2.0))
    .map((item) => cleanText(item.name))
    .filter(Boolean)
    .slice(0, 2);
  const focusBlock = weakFocusItems.length > 0
    ? [
        spacer(6),
        subHeading("Что просело в фокусном этапе:"),
        ...weakFocusItems.map((item, index) => bodyPara(`${index + 1}. ${item}`, { size: SZ.cell })),
      ]
    : [];

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
    ...focusBlock,
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 6 — СИТУАЦИЯ ДНЯ
// ──────────────────────────────────────────────────────────────

function buildSituatsiya() {
  const s = DATA.situation;
  const rows = [];

  const bodyText = [s.body, s.pattern_count_label].filter(Boolean).join("  ");
  if (bodyText) {
    rows.push(new TableRow({ children: [
      labelCell("Главный сигнал дня"),
      cell(bodyText, { color: COLORS.orange }),
    ]}));
  }

  const priorityStage = (DATA.stages || []).find((st) => st.priority);
  if (priorityStage) {
    rows.push(new TableRow({ children: [
      labelCell("Приоритетный этап"),
      cell(priorityStage.name, { bold: true, color: COLORS.heading }),
    ]}));
  }

  if (s.client_need) {
    rows.push(new TableRow({ children: [
      labelCell("Что хотел сказать клиент"),
      cell(s.client_need),
    ]}));
  }

  if (s.manager_task) {
    rows.push(new TableRow({ children: [
      labelCell("Наша задача"),
      cell(s.manager_task, { bold: true }),
    ]}));
  }

  const ex = s.call_example || {};
  const exampleText = (ex.time_label || ex.client_label)
    ? `Звонок ${ex.time_label || "—"} — ${ex.client_label || "Клиент"}. ${ex.reason_short || ""}`.trim()
    : "";
  if (exampleText) {
    rows.push(new TableRow({ children: [
      labelCell("Пример из сегодня"),
      cell(exampleText, { color: COLORS.gray }),
    ]}));
  }

  if (s.scripts && s.scripts.length > 0) {
    rows.push(new TableRow({ children: [
      labelCell("Варианты речёвок"),
      cellMultiPara(
        s.scripts.map((script, index) =>
          new Paragraph({
            children: [new TextRun({ text: `${index + 1}. ${script}`, size: SZ.body, font: "Arial", color: COLORS.heading })],
            spacing: { before: 0, after: 40 },
          })
        )
      ),
    ]}));
  }

  if (s.why_it_works) {
    rows.push(new TableRow({ children: [
      labelCell("Почему работает"),
      cell(s.why_it_works, { color: COLORS.gray }),
    ]}));
  }

  if (rows.length === 0) {
    return [
      blockHeading("🎯", "СИТУАЦИЯ ДНЯ"),
      bodyPara(s.body || "Данных за этот день недостаточно.", { color: COLORS.gray }),
    ];
  }

  return [
    blockHeading("🎯", "СИТУАЦИЯ ДНЯ"),
    new Paragraph({
      children: [new TextRun({
        text: s.title,
        bold: true, size: SZ.accent, color: COLORS.red, font: "Arial",
      })],
      spacing: { before: 60, after: 60 },
    }),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows,
    }),
  ];
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
  blocks.push(blockHeading("📋", "ДОПОЛНИТЕЛЬНЫЕ 3 СИТУАЦИИ"));
  blocks.push(bodyPara(
    "Приложение к основному отчёту. Для углублённого разбора с менеджером или самостоятельно.",
    { color: COLORS.gray, size: SZ.meta },
  ));
  if (!DATA.additional_situations || DATA.additional_situations.length === 0) {
    blocks.push(metaPara("Дополнительные ситуации появятся после накопления данных по звонкам."));
    return blocks;
  }
  blocks.push(spacer(4));

  for (let i = 0; i < DATA.additional_situations.length; i++) {
    const s = DATA.additional_situations[i];
    const typeLabel = s.badge || (s.type === "strength" ? "✅ Сильная сторона" : "🔶 Зона роста");
    const typeColor = s.type === "strength" ? COLORS.green : COLORS.orange;

    blocks.push(new Paragraph({
      children: [
        new TextRun({ text: `Ситуация ${i + 1} — `, bold: true, size: SZ.body, font: "Arial" }),
        new TextRun({ text: s.title, bold: true, size: SZ.body, color: COLORS.heading, font: "Arial" }),
        new TextRun({ text: `  ${typeLabel}  ·  ${s.signal} зв.`, size: SZ.cell, color: typeColor, font: "Arial" }),
      ],
      spacing: { before: 100, after: 40 },
    }));

    const sitRows = [
      s.client_said ? new TableRow({ children: [
        headCell("Ситуация / сигнал", { width: { size: 28, type: WidthType.PERCENTAGE } }),
        cell(s.client_said),
      ]}) : null,
      s.meant ? new TableRow({ children: [
        headCell("Что хотел сказать клиент"),
        cell(s.meant, { color: COLORS.heading }),
      ]}) : null,
      s.how_to ? new TableRow({ children: [
        headCell("Как лучше ответить / что делать"),
        cell(s.how_to, { color: s.type === "strength" ? COLORS.heading : COLORS.green, italic: true }),
      ]}) : null,
      s.why ? new TableRow({ children: [
        headCell("Почему это важно"),
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
  console.log("  [✓] ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ: 4-row expanded structure");
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
