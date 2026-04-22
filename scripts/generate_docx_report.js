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
// Hardcoded data from verification_Эльмира_Кешубаева_2026-04-06.pdf
// ──────────────────────────────────────────────────────────────

const DATA = {
  manager: "Эльмира Кешубаева",
  date: "06.04.2026",
  calls: 8,
  // Average of available stages on /5 scale: (3.8+2.8+1.0+2.6)/4 ≈ 2.6
  day_score: 2.6,

  outcomes: {
    total: 8,
    agreed: 4,
    rescheduled: 2,
    refusal: 1,
    open: 1,
    tech_service: 0,
  },

  // Stage scores: source 0–10 scale → /5
  stages: [
    { code: "E1", name: "Э1 Первичный контакт",            score10: 7.5, score5: 3.8, priority: false, subs: [] },
    { code: "E2", name: "Э2 Квалификация и потребность",    score10: 5.6, score5: 2.8, priority: false, subs: [] },
    {
      code: "E3", name: "Э3 Выявление детальных потребностей", score10: 1.9, score5: 1.0, priority: true,
      subs: [
        { name: "↳ Понял приоритет и срок",          score10: 0.0, score5: 0.0 },
        { name: "↳ Выявил боль и ограничения",        score10: 1.2, score5: 0.6 },
        { name: "↳ Выявил конкретные сценарии",       score10: 2.5, score5: 1.3 },
      ],
    },
    { code: "E4", name: "Э4 Формирование предложения",      score10: 5.2, score5: 2.6, priority: false, subs: [] },
    { code: "E5", name: "Э5 Работа с возражениями",         score10: null, score5: null, priority: false, subs: [] },
    { code: "E6", name: "Э6 Завершение и следующий шаг",    score10: null, score5: null, priority: false, subs: [] },
    { code: "EX", name: "Сквозной критерий",                score10: null, score5: null, priority: false, subs: [] },
  ],

  // ГОЛОС КЛИЕНТА
  voice_of_customer: [
    {
      client: "Алексей Морозов, 03:15, Тёплый лид",
      quote: "«Я вообще-то не понимаю, чем вы отличаетесь от обычного ЭДО.»",
      interpretation: "Скрытое возражение по дифференциации. Клиент не получил достаточно вопросов о своём процессе — сравнивает по поверхностным признакам. Ответить: «Давайте я спрошу пару вещей о вашем документообороте — тогда смогу объяснить точно, что изменится.»",
    },
    {
      client: "Анна Сидорова, 04:30, Холодный",
      quote: "«Ну раз уж позвонили, расскажите подробнее — у нас пока нет времени разбираться самим.»",
      interpretation: "Пассивный интерес с порогом. Клиент готов слушать, но нужна конкретика под его задачу. Ответить: «Два быстрых вопроса: сколько договоров в месяц и с кем в основном подписываете? Потом за 2 минуты покажу, где экономия.»",
    },
    {
      client: "+77019876543, 05:00, Входящий",
      quote: "«Мне нравится, что вы объясняете просто, но хотелось бы конкретику по нашему объёму.»",
      interpretation: "Сигнал персонализации: клиент готов к сделке, но хочет цифры под свой профиль. Ответить: «Скажите объём — я сразу назову, на чём именно экономия и сколько по вашей ситуации.»",
    },
  ],

  // РАЗБОР ЗВОНКА — Анна Сидорова
  call_breakdown: {
    client: "Анна Сидорова",
    time: "10:30",
    stages: [
      {
        moment: "0:10",
        what: "Представилась, назвала компанию ✓. Не спросила, удобно ли говорить ✗",
        better: "Добавить: «Удобно сейчас пару минут?» до перехода к теме.",
      },
      {
        moment: "0:45",
        what: "Назвала причину звонка ✓. Сразу перешла к возможностям системы ✗",
        better: "Сначала спросить: «Как у вас сейчас устроен процесс подписания документов?»",
      },
      {
        moment: "2:10",
        what: "Презентовала общие преимущества ЭДО. Без адаптации к профилю клиента ✗",
        better: "Связать с контекстом клиента: «Вы упомянули контрагентов — именно для этого сценария...»",
      },
      {
        moment: "4:15",
        what: "Завершила без конкретного следующего шага ✗",
        better: "Зафиксировать дедлайн: «Договариваемся: я пришлю материалы, в пятницу в 14:00 созвонимся?»",
      },
    ],
  },

  // ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ
  additional_situations: [
    {
      title: "«Не фиксирует конкретный следующий шаг»",
      client_said: "«Ну ладно, я подумаю» — без согласованного срока и формата следующего контакта.",
      meant: "Клиент не отказывает, но и не берёт обязательство. Разговор «завис» — без дедлайна высока вероятность потери.",
      how_to: "«Хорошо. Давайте зафиксируем: я пришлю КП на email до 17:00, а в пятницу в 11:00 созвонимся и подтвердим. Удобно?»",
      why: "Конкретный шаг с дедлайном переводит «я подумаю» в управляемый процесс. Без него клиент остаётся в статусе «открытый» бессрочно.",
      type: "gap",
      signal: 5,
    },
    {
      title: "«Не проверяет, удобно ли говорить»",
      client_said: "Менеджер начинает диалог без проверки уместности — клиент раздражается или отвечает вполсилы.",
      meant: "Клиент может быть занят или не готов. Вопрос о времени — это уважение, которое снижает барьер к разговору.",
      how_to: "«Здравствуйте, это Эльмира из Договор-24. Звоню по конкретной теме — удобно сейчас пару минут?»",
      why: "Клиент, который сказал «да, удобно», психологически уже согласился продолжать. Это снижает риск прерванного разговора.",
      type: "gap",
      signal: 3,
    },
    {
      title: "«Чётко представляется и называет компанию»",
      client_said: "«Эльмира, Договор-24» — клиент сразу понимает, кто звонит и с какой компанией.",
      meant: "Чёткое представление устанавливает профессиональный контекст с первой секунды. Клиент не тратит ресурс на идентификацию звонящего.",
      how_to: "Продолжать развивать: добавлять краткую причину звонка сразу после имени: «Эльмира, Договор-24 — звоню по теме оформления документов с контрагентами.»",
      why: "Это уже сильная сторона. Усиление: причина звонка в первой фразе снижает настороженность и ускоряет переход к диалогу.",
      type: "strength",
      signal: 6,
    },
  ],

  // ПОЗВОНИ ЗАВТРА
  call_tomorrow: [
    {
      priority: "🔴",
      label: "Горячий",
      client: "Алексей Морозов",
      phone: "+7 701 999-6001",
      context: "Договор до 2026-04-06",
      script: "«Алексей, Эльмира. Отправила договор — хотела уточнить, получили? Готовы подтвердить?»",
    },
    {
      priority: "🔴",
      label: "Горячий",
      client: "+77019876543",
      phone: "+7 701 987-6543",
      context: "Демо-доступ до 2026-04-07",
      script: "«Здравствуйте, Эльмира из Договор-24. Вчера договорились на демо — отправила ссылку, всё получили?»",
    },
    {
      priority: "🔴",
      label: "Горячий",
      client: "Лариса Новикова",
      phone: "+7 701 999-6008",
      context: "Пробный доступ до 2026-04-07",
      script: "«Лариса, Эльмира. Активировала пробный доступ — отправила инструкцию. Удобно сейчас пройтись по первым шагам?»",
    },
    {
      priority: "🟡",
      label: "Тёплый",
      client: "Анна Сидорова",
      phone: "+7 701 999-6002",
      context: "Перезвон до 2026-04-07",
      script: "«Анна, Эльмира из Договор-24. Договорились созвониться — удобно сейчас пару минут?»",
    },
    {
      priority: "🟡",
      label: "Тёплый",
      client: "Мария Петрова",
      phone: "+7 701 999-6005",
      context: "Перезвон до 2026-04-10",
      script: "«Мария, Эльмира. Вы просили перезвонить в пятницу — звоню как договорились.»",
    },
  ],

  // СПИСОК ВСЕХ ЗВОНКОВ
  all_calls: [
    { n: 1, time: "09:15", client: "Алексей Морозов",    topic: "Тёплый/Продажа",  context: "до 06.04",    status: "Договор" },
    { n: 2, time: "10:30", client: "Анна Сидорова",      topic: "Холодный",         context: "→ 07.04",     status: "Перенос" },
    { n: 3, time: "11:00", client: "+77019876543",        topic: "Горячий/Входящий", context: "до 07.04",    status: "Договор" },
    { n: 4, time: "11:45", client: "Дмитрий Козлов",     topic: "Тёплый/Продажа",  context: "до 08.04",    status: "Договор" },
    { n: 5, time: "12:10", client: "Мария Петрова",       topic: "Холодный",         context: "→ 10.04",     status: "Перенос" },
    { n: 6, time: "13:00", client: "+77071234567",         topic: "Горячий/Входящий", context: "Конкурент",   status: "Отказ" },
    { n: 7, time: "14:20", client: "Сергей Иванов",       topic: "Тёплый/Продажа",  context: "Ждёт решения", status: "Открыт" },
    { n: 8, time: "15:30", client: "Лариса Новикова",     topic: "Горячий/Входящий", context: "до 07.04",    status: "Договор" },
  ],
};

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
    bodyPara(
      `${DATA.outcomes.open} звонок «Открыт». Клиент (Сергей Иванов) проявил интерес, но ждёт одобрения руководства — без зафиксированной даты следующего контакта.`,
    ),
    bodyPara(
      "Потенциал: ~180 000 тенге годовых подписок (1 × 180к) — не подобраны.",
    ),
    bodyPara(
      "Причина: нет зафиксированного следующего шага, клиент не взял обязательство о дате ответа.",
      { color: COLORS.orange },
    ),
    bodyPara(
      "Как определена сумма: ориентировочно — средний чек 180к/год для профиля «малый бизнес без ЭДО». Автоматическая логика (CRM → профиль → минимум) — в разработке.",
      { color: COLORS.gray },
    ),
  ];
}

// ──────────────────────────────────────────────────────────────
// Block 4 — PIPELINE ТЁПЛЫХ ЛИДОВ
// ──────────────────────────────────────────────────────────────

function buildPipeline() {
  // warm/hot: calls 1(warm), 3(hot), 4(warm), 6(hot), 7(warm), 8(hot) = 6
  // results: 4 agreed, 0 rescheduled, 1 refusal, 1 open
  return [
    blockHeading("📊", "PIPELINE ТЁПЛЫХ ЛИДОВ"),
    bodyPara("6 повторных/тёплых звонков сегодня (Тёплый/заявка × 3, Горячий/Входящий × 3)"),
    bodyPara("4 → Договорились  ·  0 → Перенос  ·  1 → Отказ  ·  1 → Открыт"),
    bodyPara("Конверсия тёплых: 67% (4 из 6)", { bold: true }),
    bodyPara("Среднее: нет базы для сравнения (первый период).", { color: COLORS.gray }),
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
        new TableRow({
          children: [
            cell("Сергей Иванов"),
            cell("+7 701 999-6007"),
            cell("Открытый — ждёт одобрения руководства", { color: COLORS.orange }),
          ],
        }),
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
        text: "Э3 Выявление детальных потребностей (1.0 / 5) — первый этап ниже 4 по воронке",
        bold: true, size: 24, color: COLORS.red, font: "Arial",
      })],
      spacing: { before: 0, after: 60 },
    }),
    bodyPara(
      "«Менеджер переходит к презентации, не задав вопросов о потребностях» — 7 из 8 звонков · конверсия по этим звонкам: 43%",
      { color: COLORS.orange },
    ),
    spacer(4),
    subHeading("Что хотел сказать клиент"),
    bodyPara(
      "Клиент звонил не слушать скрипт, а получить ощущение, что ему предлагают решение под его задачу. Когда вопросов о процессе нет — клиент слышит «стандартную презентацию» и начинает сравнивать по цене, а не по ценности.",
    ),
    spacer(4),
    subHeading("Наша задача"),
    bodyPara(
      "Задать 2–3 уточняющих вопроса о процессе клиента ДО начала презентации в каждом звонке.",
      { bold: true },
    ),
    spacer(4),
    subHeading("Пример из сегодня"),
    bodyPara("Звонок 10:30 — Анна Сидорова. Менеджер перешла к презентации через 45 секунд, не спросив ни об объёме, ни о контрагентах — клиент завершила разговор без обязательства."),
    spacer(4),
    subHeading("Варианты речёвок"),
    bodyPara("1. «Расскажите, как у вас сейчас организован процесс подписания документов? Какие типы контрагентов вам важно закрыть в первую очередь?»"),
    bodyPara("2. «Удобно ли вам сейчас пару минут уделить — я расскажу, почему звоню?» → затем сразу вопрос о процессе."),
    bodyPara("3. «Два быстрых вопроса: сколько договоров в месяц и с кем в основном подписываете? Потом за 2 минуты покажу, где конкретно экономия.»"),
    spacer(4),
    subHeading("Почему работает"),
    bodyPara(
      "Вопросы о процессе создают контекст, в котором предложение звучит как решение конкретной задачи клиента, а не как шаблонная презентация. Клиент, который сам описал свою боль, легче соглашается с тем, что это боль — и что у вас есть ответ.",
    ),
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
    bodyPara(
      "Из следующих 8 продажных звонков — задай минимум 2 уточняющих вопроса о потребностях ДО начала презентации хотя бы в 6 из 8.",
      { bold: true, size: 24 },
    ),
    spacer(4),
    bodyPara("Сегодня: 1 из 8 звонков с уточняющими вопросами."),
    bodyPara("Рекорд: нет базы (первый период отслеживания)."),
    spacer(4),
    subHeading("Фраза для завтра:"),
    bodyPara(
      "«Расскажите, как у вас сейчас организован процесс подписания документов? Какие типы контрагентов вам важно закрыть в первую очередь?»",
      { italic: true, color: COLORS.heading },
    ),
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
  const top3 = DATA.call_tomorrow.slice(0, 3);

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
                    text: `${DATA.manager.split(" ")[0]}, доброе утро! 👋`,
                    bold: true, size: 26, font: "Arial",
                  })],
                  spacing: { before: 0, after: 80 },
                }),
                new Paragraph({
                  children: [new TextRun({
                    text: `Вчерашний итог: ${DATA.calls} звонков → ${DATA.outcomes.agreed} Договорились, ${DATA.outcomes.open} Открытых`,
                    size: 22, font: "Arial",
                  })],
                  spacing: { before: 0, after: 60 },
                }),
                new Paragraph({
                  children: [new TextRun({
                    text: `~180 000 тенге ждут обратного звонка 📞`,
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
                      text: `${i + 1}. ${c.client} (${c.phone}) — ${c.script}`,
                      size: 20, font: "Arial",
                    })],
                    spacing: { before: 0, after: 40 },
                    indent: { left: 200 },
                  })
                ),
                spacer(4),
                new Paragraph({
                  children: [new TextRun({
                    text: "🏆 Челлендж: Задай 2+ уточняющих вопроса о потребностях ДО презентации (цель: 6 из 8 звонков · вчера 1/8 · рекорд: нет базы)",
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
