# Работа вне рабочего времени по проекту

Период: май-июнь 2026
Часовой пояс: Алматы / UTC+5

В расчет включены:

- выходные дни полностью;
- будние дни только после 19:00.

Итог:

- минимальная подтвержденная оценка по git: 10.8 часа;
- оценка активных рабочих сессий по чату: около 29.4 часа.

Git и чат не складываются: это два взгляда на одну и ту же работу. Git
показывает минимум по моментам сохранения результата, чат лучше отражает
обсуждение, постановку задач агентам, контроль прогонов и проверку результата.

## Сводка по месяцам

| Месяц | Оценка по чату | Git минимум | Верхнеуровнево что делали |
| --- | ---: | ---: | --- |
| Май 2026 | 21.0 ч | 10.3 ч | Стабилизировали manager_daily отчет, PDF/Telegram delivery, meaningful calls, eligibility, LLM2/LLM3 report blocks, subagent simulation, Situation Day и call breakdown. |
| Июнь 2026 | 7.9 ч | 0.5 ч | Проверяли LLM2 по Толегену, делали controlled rerun, разбирали Kimi/OpenAI, оптимизировали LLM2 input, compact LLM2/STT pipeline и логику оценки LLM2D. |

## Таблица по дням

| Дата | День | Время Алматы | Оценка по чату | Git минимум | Что делали вне рабочего времени |
| --- | --- | --- | ---: | ---: | --- |
| 2026-05-03 | Вс | 15:26-16:38, 20:23-22:21 | 3.18 ч | 2.89 ч | Проверяли актуальное состояние проекта; калибровали meaningful calls; нормализовали eligibility; исправляли счетчики в PDF; улучшали визуальную читаемость manager_daily; убирали лишние блоки из отчета. |
| 2026-05-05 | Вт | 20:42-22:10 | 1.47 ч | 1.13 ч | Разбирали readiness отчета; фиксировали validation failures; проверяли safe preview; уточняли delivery semantics и explicit report delivery. |
| 2026-05-10 | Вс | 17:12-22:00, 23:08-00:00 | 5.66 ч | 5.29 ч | Пересобирали финальные PDF; отправляли Telegram test delivery; документировали LLM2 instruction map; проводили verification run; полировали blockers; настраивали quality gates. |
| 2026-05-18 | Пн | 21:21-22:22 | 1.02 ч | 0.50 ч | Переходили к LLM3 composers и переработке report blocks. |
| 2026-05-25 | Пн | 20:32-22:51 | 2.30 ч | 0.50 ч | Обсуждали временную имитацию LLM через Codex-subagents; готовили режим subagent simulation для проверки LLM2/LLM3 без реальных моделей. |
| 2026-05-26 | Вт | 19:00-21:20 | 2.34 ч | - | Работали над documentation / Gate 3; проверяли contract validation; собирали review artifacts. |
| 2026-05-27 | Ср | 19:00-00:00 | 5.00 ч | - | Разбирали системную ошибку связки блоков; уточняли контекст Situation Day и call breakdown; готовили исправления для отчетного слоя. |
| 2026-06-01 | Пн | 20:28-00:00 | 3.52 ч | 0.50 ч | Проверяли LLM2 по звонкам Толегена; запускали controlled rerun; собирали и проверяли отчет. |
| 2026-06-02 | Вт | 20:32-00:00 | 3.46 ч | - | Разбирали ограничения Kimi/OpenAI; оптимизировали LLM2 input; обсуждали LLM2A, LLM2B и LLM2D. |
| 2026-06-03 | Ср | 19:00-19:35 | 0.60 ч | - | Продолжали full pipeline / STT / compact LLM2; контролировали текущий прогон. |
| 2026-06-05 | Пт | 19:00-19:17 | 0.30 ч | - | Упрощали логику оценки и coaching decision для LLM2D. |

## Сводка по блокам

| Блок | Что вошло |
| --- | --- |
| Manager daily report | PDF, визуальная читаемость, счетчики, структура отчета, скрытие лишних блоков, quality gates. |
| Selection / funnel / statuses | Meaningful calls, eligibility normalization, taxonomy статусов, корректность воронки и списка звонков. |
| Delivery and verification | Telegram test delivery, safe preview, verification runs, explicit delivery. |
| LLM2 / LLM3 semantic layer | LLM2 instruction map, Situation Day, call breakdown, LLM3 composers, status/context fixes. |
| Runtime / model modes | Codex-subagent simulation, Kimi/OpenAI разбор, compact LLM2 inputs, controlled reruns. |

## Примечание

Это оценка по локальным техническим следам проекта. Самой консервативной цифрой
является git minimum. Более реалистичной оценкой активной работы является
chat-based estimate, потому что большая часть работы проходила через постановку
задач, контроль агентов, анализ результатов и повторные проверки в чате.
