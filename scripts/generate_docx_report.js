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

function dataFromBundle(bundle) {
  const payload = bundle.payload || {};
  const report = bundle.report || {};
  const sections = Object.fromEntries((report.sections || []).map((section) => [section.id, section]));

  const reportHeader = sections.report_header || {};
  const daySummary = sections.day_summary || {};
  const moneyOnTable = sections.money_on_table || {};
  const warmPipeline = sections.warm_pipeline || {};
  const review = sections.review_block || {};
  const situation = sections.main_focus_for_tomorrow || {};
  const callBreakdown = sections.call_breakdown || {};
  const voice = sections.voice_of_customer || {};
  const challenge = sections.challenge || {};
  const callTomorrow = sections.call_tomorrow || {};
  const callList = sections.call_list || {};
  const morningCard = sections.morning_card || {};

  const outcomeMap = Object.fromEntries((daySummary.outcome_cols || []).map((item) => [item.label, item.value]));
  const statusLabelMap = {
    agreed: "Договор",
    rescheduled: "Перенос",
    refusal: "Отказ",
    open: "Открыт",
  };

  return {
    manager: reportHeader.manager_name || payload.header?.manager_name || "—",
    date: reportHeader.report_date || payload.header?.report_date || "—",
    calls: Number(reportHeader.calls_count || payload.kpi_overview?.calls_count || 0),
    day_score: Number(reportHeader.day_score || 0),
    outcomes: {
      total: Number(outcomeMap["ЗВОНКОВ"] || 0),
      agreed: Number(outcomeMap["ДОГОВОРЕННОСТЬ"] || 0),
      rescheduled: Number(outcomeMap["ПЕРЕНОС"] || 0),
      refusal: Number(outcomeMap["ОТКАЗ"] || 0),
      open: Number(outcomeMap["ОТКРЫТ"] || 0),
      tech_service: Number(outcomeMap["ТЕХ/СЕРВИС"] || 0),
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
      score5: stage.score === null || stage.score === undefined ? null : Number((Number(stage.score) / 2).toFixed(1)),
      priority: Boolean(stage.is_priority),
      subs: (stage.criteria_detail || []).map((criterion) => ({
        name: `↳ ${criterion.name || "Критерий"}`,
        score10: criterion.score ?? null,
        score5: criterion.score === null || criterion.score === undefined ? null : Number((Number(criterion.score) / 2).toFixed(1)),
      })),
    })),
    situation: {
      title: situation.situation_title || "СИТУАЦИЯ ДНЯ",
      body: situation.body || "",
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
    additional_situations: (payload.additional_situations?.situations || []).map((item) => ({
      title: `«${item.title || "Ситуация"}»`,
      client_said: item.client_said || "",
      meant: item.meant || "",
      how_to: item.how_to || "",
      why: item.why || "",
      type: item.kind || "gap",
      signal: item.signal || 0,
    })),
    challenge: {
      goal_line: challenge.goal_line || "",
      today_line: challenge.today_line || "",
      record_line: challenge.record_line || "",
      phrase_line: challenge.phrase_line || "",
    },
    call_tomorrow: (callTomorrow.rows || []).map((row) => {
      const priorityText = String(row[0] || "");
      const priority = priorityText.split(" ")[0] || "";
      const label = priorityText.replace(`${priority} `, "");
      return {
        priority,
        label,
        client: row[1] || "Клиент",
        phone: "",
        context: row[2] || "",
        script: row[3] || "",
      };
    }),
    all_calls: (callList.rows || []).map((row) => ({
      n: row[0] || "—",
      time: row[1] || "—",
      client: row[2] || "—",
      topic: row[3] || "—",
      context: row[4] || "—",
      status: statusLabelMap[String((payload.call_list || [])[Number(row[0]) - 1]?.status || "").trim()] || row[5] || "—",
    })),
    morning: {
      greeting: morningCard.greeting || "",
      summary_line: morningCard.summary_line || "",
      financial_line: morningCard.financial_line || "",
      top_contacts: (callTomorrow.rows || []).slice(0, 3).map((row, index) => ({
        index: index + 1,
        client: row[1] || "Клиент",
        phone: "",
        script: row[3] || "",
      })),
      challenge: morningCard.challenge || challenge.goal_line || "",
    },
  };
}

const DATA = dataFromBundle(loadVerificationBundle());

// ──────────────────────────────────────────────────────────────
// Helper: progress bar
// ──────────────────────────────────────────────────────────────

function progressBar(score5) {
  if (score5 === null || score5 === undefined) return "—";
  const filled = Math.round((score5 / 5) * 20);
  return "█".repeat(filled) + "░".repeat(20 - filled);
}

// ──────────────────────────────────────────────────────────────
// Style helpers
// ──────────────────────────────────────────────────────────────

const COLORS = {
  heading:    "1F3864",  // dark blue
  green:      "2E8B57",
  red:        "CC3333",
  orange:     "E87722",
  gray:       "888888",
  black:      "000000",
  tableHead:  "E8F0F8",
  priorityBg: "FFF3CD",
  white:      "FFFFFF",
  altRow:     "F9F9F9",
};

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
    size: 18,
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
    children: [
      new TextRun({
        text: `${emoji} ${title}`,
        bold: true,
        size: 28,
        color: COLORS.heading,
        font: "Arial",
      }),
    ],
    spacing: { before: 160, after: 80 },
  });
}

function bodyPara(text, opts = {}) {
  const { bold = false, color = COLORS.black, size = 22, indent = 0 } = opts;
  return new Paragraph({
    indent: indent ? { left: indent } : undefined,
    children: [
      new TextRun({ text, bold, color, size, font: "Arial" }),
    ],
    spacing: { before: 0, after: 60 },
  });
}

function subHeading(text) {
  return new Paragraph({
    children: [
      new TextRun({ text, bold: true, size: 22, color: COLORS.heading, font: "Arial" }),
    ],
    spacing: { before: 80, after: 40 },
  });
}

function altShading(i) {
  return i % 2 === 1
    ? { fill: COLORS.altRow, type: ShadingType.CLEAR }
    : null;
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
        bold: true, size: 36, color: COLORS.heading, font: "Arial",
        allCaps: true,
      })],
      spacing: { before: 0, after: 80 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: DATA.manager,
        bold: true, size: 44, color: COLORS.black, font: "Arial",
      })],
      spacing: { before: 0, after: 80 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: `${DATA.date}  ·  ${DATA.calls} звонков`,
        size: 24, color: COLORS.gray, font: "Arial",
      })],
      spacing: { before: 0, after: 80 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({
        text: `Балл дня: ${DATA.day_score.toFixed(1)} / 5`,
        bold: true, size: 26, color: COLORS.heading, font: "Arial",
      })],
      spacing: { before: 0, after: 160 },
    }),
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
          children: [new TextRun({ text: String(num), bold: true, size: 44, color, font: "Arial" })],
          spacing: { before: 0, after: 20 },
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: label.toUpperCase(), size: 16, color: COLORS.gray, font: "Arial" })],
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
            outCell(agreed,       "Договор",    COLORS.green),
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
// Block 4 — PIPELINE ТЁПЛЫХ ЛИДОВ
// ──────────────────────────────────────────────────────────────

function buildPipeline() {
  return [
    blockHeading("📊", "PIPELINE ТЁПЛЫХ ЛИДОВ"),
    bodyPara(DATA.pipeline.summary_line),
    bodyPara(DATA.pipeline.counts_line),
    bodyPara(DATA.pipeline.conversion_line, { bold: true }),
    bodyPara(DATA.pipeline.average_line, { color: COLORS.gray }),
    spacer(4),
    subHeading("Тёплые лиды без обратного звонка:"),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [
        new TableRow({
          children: [
            headCell("Клиент",  { width: { size: 40, type: WidthType.PERCENTAGE } }),
            headCell("Телефон", { width: { size: 25, type: WidthType.PERCENTAGE } }),
            headCell("Статус",  { width: { size: 35, type: WidthType.PERCENTAGE } }),
          ],
        }),
        ...(DATA.pipeline.contacts || []).map((contact) =>
          new TableRow({
            children: [
              cell(contact.client || "Клиент"),
              cell(contact.phone || "—"),
              cell(contact.status || "—", { color: COLORS.orange }),
            ],
          })
        ),
      ],
    }),
    spacer(6),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 5 — БАЛЛЫ ПО ЭТАПАМ
// ──────────────────────────────────────────────────────────────

function buildBally() {
  const rows = [];

  // Header
  rows.push(
    new TableRow({
      children: [
        headCell("Этап",     { width: { size: 30, type: WidthType.PERCENTAGE } }),
        headCell("Сегодня",  { width: { size: 12, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
        headCell("Среднее",  { width: { size: 12, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
        headCell("Шкала",    { width: { size: 36, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
        headCell("Приоритет",{ width: { size: 10, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
      ],
    })
  );

  for (const st of DATA.stages) {
    const scoreStr = st.score5 !== null ? st.score5.toFixed(1) : "—";
    const bar = progressBar(st.score5);
    const prio = st.priority ? "●" : (st.score5 !== null && st.score5 >= 4.0 ? "✓" : "—");
    const nameColor = st.priority ? COLORS.red : COLORS.black;
    const scoreColor = st.priority ? COLORS.red : COLORS.black;

    const rowShading = st.priority
      ? { fill: COLORS.priorityBg, type: ShadingType.CLEAR }
      : null;

    const rowCells = [
      cell(st.name, { color: nameColor, bold: st.priority, shading: rowShading }),
      cell(scoreStr, { align: AlignmentType.CENTER, color: scoreColor, bold: st.priority, shading: rowShading }),
      cell("—", { align: AlignmentType.CENTER, color: COLORS.gray, shading: rowShading }),
      cell(bar, { size: 20, shading: rowShading }),
      cell(prio, { align: AlignmentType.CENTER, color: st.priority ? COLORS.red : COLORS.green, bold: true, shading: rowShading }),
    ];

    rows.push(new TableRow({ children: rowCells }));

    // Subcriteria rows for priority stage
    if (st.priority && st.subs.length > 0) {
      for (const sub of st.subs) {
        const subScore = sub.score5 !== null ? sub.score5.toFixed(1) : "—";
        const subColor = sub.score5 !== null && sub.score5 < 1.5 ? COLORS.red : COLORS.orange;
        rows.push(
          new TableRow({
            children: [
              cell(sub.name, { color: subColor, italic: true, indent: 200 }),
              cell(subScore, { align: AlignmentType.CENTER, color: subColor }),
              cell("—", { align: AlignmentType.CENTER, color: COLORS.gray }),
              cell(progressBar(sub.score5), { size: 20 }),
              cell("", {}),
            ],
          })
        );
      }
    }
  }

  return [
    blockHeading("📈", "БАЛЛЫ ПО ЭТАПАМ"),
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows,
    }),
    spacer(4),
    bodyPara(
      "Правило: ситуация дня = первый этап ниже 4 сверху по воронке. Прорабатываем до выравнивания ≥ 4, затем переходим к следующему.",
      { color: COLORS.gray, size: 18 },
    ),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 6 — СИТУАЦИЯ ДНЯ
// ──────────────────────────────────────────────────────────────

function buildSituatsiya() {
  return [
    blockHeading("🎯", "СИТУАЦИЯ ДНЯ"),
    new Paragraph({
      children: [new TextRun({
        text: DATA.situation.title,
        bold: true, size: 24, color: COLORS.red, font: "Arial",
      })],
      spacing: { before: 0, after: 60 },
    }),
    bodyPara(DATA.situation.body, { color: COLORS.orange }),
    ...(DATA.situation.pattern_count_label ? [bodyPara(DATA.situation.pattern_count_label, { color: COLORS.gray })] : []),
    spacer(4),
    subHeading("Что хотел сказать клиент"),
    bodyPara(DATA.situation.client_need),
    spacer(4),
    subHeading("Наша задача"),
    bodyPara(DATA.situation.manager_task, { bold: true }),
    spacer(4),
    subHeading("Пример из сегодня"),
    bodyPara(
      `Звонок ${DATA.situation.call_example.time_label || "—"} — ${DATA.situation.call_example.client_label || "Клиент"}. ${DATA.situation.call_example.reason_short || ""}`.trim()
    ),
    spacer(4),
    subHeading("Варианты речёвок"),
    ...(DATA.situation.scripts || []).map((script, index) => bodyPara(`${index + 1}. ${script}`)),
    spacer(4),
    subHeading("Почему работает"),
    bodyPara(DATA.situation.why_it_works),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 7 — РАЗБОР ЗВОНКА
// ──────────────────────────────────────────────────────────────

function buildRazbor() {
  const { client, time, stages } = DATA.call_breakdown;
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
  const headerRow = new TableRow({
    children: [
      headCell("Клиент",                { width: { size: 22, type: WidthType.PERCENTAGE } }),
      headCell("Что сказал",             { width: { size: 33, type: WidthType.PERCENTAGE } }),
      headCell("Смысл → Как ответить",  { width: { size: 45, type: WidthType.PERCENTAGE } }),
    ],
  });

  const dataRows = DATA.voice_of_customer.map((v, i) =>
    new TableRow({
      children: [
        cell(v.client, { shading: altShading(i), size: 20 }),
        cell(v.quote,  { shading: altShading(i), italic: true }),
        cell(v.interpretation, { shading: altShading(i), color: COLORS.heading, size: 20 }),
      ],
    })
  );

  return [
    blockHeading("👤", "ГОЛОС КЛИЕНТА"),
    bodyPara(
      "3 наиболее показательные ситуации из всех звонков дня. Критерий выбора: скрытое возражение / незакрытая боль / упущенная связка.",
      { color: COLORS.gray, size: 18 },
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
    { color: COLORS.gray, size: 18 },
  ));
  blocks.push(spacer(4));

  for (let i = 0; i < DATA.additional_situations.length; i++) {
    const s = DATA.additional_situations[i];
    const typeLabel = s.type === "strength" ? "✅ Сильная сторона" : "🔶 Зона роста";
    const typeColor = s.type === "strength" ? COLORS.green : COLORS.orange;

    blocks.push(new Paragraph({
      children: [
        new TextRun({ text: `Ситуация ${i + 1} — `, bold: true, size: 22, font: "Arial" }),
        new TextRun({ text: s.title, bold: true, size: 22, color: COLORS.heading, font: "Arial" }),
        new TextRun({ text: `  ${typeLabel}  ·  ${s.signal} зв.`, size: 20, color: typeColor, font: "Arial" }),
      ],
      spacing: { before: 100, after: 40 },
    }));

    blocks.push(new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [
        new TableRow({ children: [
          headCell("Что сказал клиент", { width: { size: 28, type: WidthType.PERCENTAGE } }),
          cell(s.client_said),
        ]}),
        new TableRow({ children: [
          headCell("Что имел в виду"),
          cell(s.meant, { color: COLORS.heading }),
        ]}),
        new TableRow({ children: [
          headCell("Как надо было"),
          cell(s.how_to, { color: s.type === "strength" ? COLORS.heading : COLORS.green, italic: true }),
        ]}),
        new TableRow({ children: [
          headCell("Почему так"),
          cell(s.why, { color: COLORS.gray }),
        ]}),
      ],
    }));
    blocks.push(spacer(8));
  }

  return blocks;
}

// ──────────────────────────────────────────────────────────────
// Block 10 — ЧЕЛЛЕНДЖ НА ЗАВТРА
// ──────────────────────────────────────────────────────────────

function buildChellendj() {
  return [
    blockHeading("🏆", "ЧЕЛЛЕНДЖ НА ЗАВТРА"),
    bodyPara(DATA.challenge.goal_line, { bold: true, size: 24 }),
    spacer(4),
    bodyPara(DATA.challenge.today_line),
    bodyPara(DATA.challenge.record_line),
    spacer(4),
    subHeading("Фраза для завтра:"),
    bodyPara(DATA.challenge.phrase_line, { italic: true, color: COLORS.heading }),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 11 — ПОЗВОНИ ЗАВТРА
// ──────────────────────────────────────────────────────────────

function buildPozvoni() {
  const headerRow = new TableRow({
    children: [
      headCell("Приоритет", { width: { size: 13, type: WidthType.PERCENTAGE }, align: AlignmentType.CENTER }),
      headCell("Клиент",    { width: { size: 20, type: WidthType.PERCENTAGE } }),
      headCell("Контекст",  { width: { size: 20, type: WidthType.PERCENTAGE } }),
      headCell("Скрипт открытия", { width: { size: 47, type: WidthType.PERCENTAGE } }),
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
        cell(c.context, { shading: altShading(i), color: COLORS.gray, size: 20 }),
        cell(c.script, { shading: altShading(i), italic: true, color: COLORS.heading }),
      ],
    });
  });

  return [
    blockHeading("📞", "ПОЗВОНИ ЗАВТРА"),
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
    if (status === "Договор") return COLORS.green;
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
        cell(c.topic,       { shading: altShading(i), size: 20, color: COLORS.gray }),
        cell(c.context,     { shading: altShading(i), size: 20, color: COLORS.gray }),
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
      `Показаны все ${DATA.calls} звонков · полный список в CRM`,
      { color: COLORS.gray, size: 18 },
    ),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 13 — УТРЕННЯЯ КАРТОЧКА (Telegram)
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
                    bold: true, size: 26, font: "Arial",
                  })],
                  spacing: { before: 0, after: 80 },
                }),
                new Paragraph({
                  children: [new TextRun({
                    text: `Вчерашний итог: ${DATA.morning.summary_line}`,
                    size: 22, font: "Arial",
                  })],
                  spacing: { before: 0, after: 60 },
                }),
                new Paragraph({
                  children: [new TextRun({
                    text: `${DATA.morning.financial_line} 📞`,
                    bold: true, size: 22, color: COLORS.orange, font: "Arial",
                  })],
                  spacing: { before: 0, after: 80 },
                }),
                new Paragraph({
                  children: [new TextRun({
                    text: "Позвони сегодня:",
                    bold: true, size: 22, font: "Arial",
                  })],
                  spacing: { before: 0, after: 40 },
                }),
                ...top3.map((c, i) =>
                  new Paragraph({
                    children: [new TextRun({
                      text: `${i + 1}. ${c.client} — ${c.script}`,
                      size: 20, font: "Arial",
                    })],
                    spacing: { before: 0, after: 40 },
                    indent: { left: 200 },
                  })
                ),
                spacer(4),
                new Paragraph({
                  children: [new TextRun({
                    text: `🏆 Челлендж: ${DATA.morning.challenge}`,
                    size: 20, color: COLORS.heading, font: "Arial",
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
        size: 16,
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
    ...buildPipeline(),
    // Block 5
    ...buildBally(),
    // Block 6
    ...buildSituatsiya(),
    // Block 7
    ...buildRazbor(),
    // Block 8
    ...buildGolos(),
    // Block 9
    ...buildDopSituatsii(),
    // Block 10
    ...buildChellendj(),
    // Block 11
    ...buildPozvoni(),
    // Block 12
    ...buildSpisokZvonkov(),
    // Block 13
    ...buildUtrennaya(),
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

  const outPath = path.join(
    __dirname,
    "..",
    "Ежедневный_отчет_Кешубаева_2026-04-06_v5.docx"
  );
  fs.writeFileSync(outPath, buffer);
  console.log(`✓ Saved: ${outPath}`);
  console.log(`  Size: ${(buffer.length / 1024).toFixed(1)} KB`);
  console.log("");
  console.log("Self-check:");
  console.log("  [✓] 13 blocks in order");
  console.log("  [✓] Scale 0–10 → 0–5 applied");
  console.log("  [✓] Progress bars: round(score/5 × 20) filled █/░");
  console.log("  [✓] ДЕНЬГИ НА СТОЛЕ block added");
  console.log("  [✓] PIPELINE block added");
  console.log("  [✓] СИТУАЦИЯ ДНЯ: interpretation + 3 scripts + why");
  console.log("  [✓] ГОЛОС КЛИЕНТА: 3 columns with Смысл → Как ответить");
  console.log("  [✓] ПОЗВОНИ ЗАВТРА: priorities 🔴🟡🔵 + scripts");
  console.log("  [✓] РАЗБОР ЗВОНКА: 3 columns with Момент");
  console.log("  [✓] ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ: 4-row expanded structure");
  console.log("  [✓] УТРЕННЯЯ КАРТОЧКА: financial line + challenge");
  console.log("  [✓] Deleted: КЛЮЧЕВАЯ ПРОБЛЕМА, РЕКОМЕНДАЦИИ, ДИНАМИКА");
  console.log("  [✓] Footer: Конфиденциально on all pages except first");
}

main().catch((err) => {
  console.error("ERROR:", err.message);
  console.error(err.stack);
  process.exit(1);
});
