# Moroska Orders — Telegram Mini App Design

**Date:** 2026-04-09  
**Status:** Approved  
**Hosted at:** https://moroskaorder.netlify.app/

---

## Overview

A personal Telegram Mini App for managing sewing and in-stock orders. Replaces text-based Telegram bot commands with a full visual interface. Only the owner uses this app — no client-facing views.

---

## Architecture

**Frontend:** Vanilla JS + HTML/CSS in a single `index.html`, deployed to Netlify via git push. Uses Telegram CSS variables (`--tg-theme-*`) for automatic light/dark theme support.

**Backend:** Existing Google Apps Script, extended with:
- `doGet(e)` — read endpoints (orders, stats, clients)
- Extended `doPost(e)` — write endpoints for the mini app (create order, update order, change status, archive)

The frontend makes `fetch()` calls to the Apps Script web app URL. The Telegram bot continues to work unchanged on the same script.

**Data:** Two Google Sheets in one spreadsheet:
- `Actual` (renamed from "В работе") — active orders
- `Archive` (renamed from "Архив") — completed/archived orders

---

## Google Sheets Structure

### Columns (both sheets)

| # | Column | Notes |
|---|--------|-------|
| 1 | ID | Auto-incremented integer |
| 2 | Дата создания | dd.MM.yyyy |
| 3 | Имя | Client name |
| 4 | Изделие | Product name |
| 5 | Детали | Details/notes |
| 6 | Цена | Price in RSD |
| 7 | Срок | Deadline date |
| 8 | Статус | Очередь / В работе / Пауза / Готово / Отдано |
| 9 | Фото | Google Drive folder URL |
| 10 | Заметка | Additional note |
| 11 | Модель | Model name |
| 12 | Артикул | Article number (new column, appended to end) |
| 13 | Тип | Заказ / Наличие (new column, appended to end) |

> **Note:** Columns 12 (Артикул) and 13 (Тип) are new — appended at the end to avoid breaking existing column indices in the Apps Script. Existing rows will have empty values — the app handles this gracefully.

---

## Navigation

Bottom tab bar with 3 tabs:

```
┌─────────────────────────────────┐
│         tab content             │
├─────────────────────────────────┤
│  📋 Заказы  │ 📊 Статистика │ 👤 Клиенты │
└─────────────────────────────────┘
```

---

## Tab 1: Заказы (Orders)

### Order List

- "＋ Новый заказ" button at the top
- Orders grouped by status in this order: В работе → Очередь → Пауза → Готово
- Each card shows: `#ID Имя — Модель`
- Tap on card → opens Order Detail sheet

### Order Detail (bottom sheet)

Fields displayed:
- Изделие, Артикул, Модель, Тип (Заказ/Наличие)
- Детали, Цена, Срок, Заметка
- Статус — dropdown, changes immediately on select
- Ссылка на папку Drive (if exists)
- "Редактировать" button — makes all fields editable inline, shows "Сохранить"
- "Перенести в архив" button — only visible when status is "Готово"; moves row to Archive sheet (equivalent to bot command `отдано`)

### New Order Form (bottom sheet)

Fields:
- Имя (text)
- Изделие (text)
- Артикул (text, optional)
- Модель (dropdown: Lada, Larna, Verbena, Ilma, ролл, тарелочка, мусорничка, чехол пяльца, чехол рама, Taloma, Tala, Loboda)
- Тип (toggle or select: Заказ / Наличие)
- Детали (text)
- Цена (number, RSD)
- Срок (date picker)
- Комментарий (text)

On submit: creates new row in Actual sheet, auto-increments ID, sets status to "Очередь", creates Google Drive folder via Apps Script.

---

## Tab 2: Статистика (Statistics)

All data aggregated from both Actual + Archive sheets. No date filters — shows overall picture.

Blocks displayed:
1. **Заказы** — Активные (Actual count) / В архиве (Archive count)
2. **Типы** — На заказ / Из наличия (from Тип column)
3. **Доход** — Общий доход: sum of Цена from Archive
4. **Топ моделей** — sorted by count across both sheets
5. **Дедлайны на этой неделе** — orders from Actual where Срок is within next 7 days, listed with #ID, Имя, date

---

## Tab 3: Клиенты (Clients)

### Client List

- Search input at top (filter by name)
- Each row: `Имя` + order count
- Aggregated from both Actual + Archive by unique Имя value

### Client Detail

Tap on client → shows:
- Header: client name
- Total orders count
- Total spent (sum of Цена for archived orders)
- List of all orders: `#ID Модель — Статус — Цена`
- Tap on order → opens Order Detail sheet (same component as Tab 1)

---

## Google Apps Script API

New endpoints added to existing script:

### GET endpoints (`doGet`)

| action | Returns |
|--------|---------|
| `getOrders` | All rows from Actual sheet |
| `getArchive` | All rows from Archive sheet |
| `getStats` | Aggregated stats object |

### POST endpoints (new actions in `doPost`)

| action | Description |
|--------|-------------|
| `createOrder` | Add new row to Actual, create Drive folder |
| `updateOrder` | Update any fields of an order by ID |
| `updateStatus` | Change status field only |
| `archiveOrder` | Move order from Actual to Archive (sets status = Отдано) |

All requests/responses use JSON. The existing Telegram bot handlers remain untouched.

---

## Deployment

**Frontend (index.html):**
- Push to git → Netlify auto-deploys to https://moroskaorder.netlify.app/

**Google Apps Script:**
- Edit in script.google.com
- Deploy → New version (one-time per script change)
- Same deployment URL as current bot webhook

---

## Out of Scope

- Client-facing views (only owner uses the app)
- Integration with second spreadsheet (client orders from other bot) — артикул field added manually for now
- Photo upload from the mini app (photos still handled via bot)
- Authentication (Telegram Mini App context provides implicit identity)
