# Photo Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "📸 Добавить фото" button to the order edit form that opens the Telegram bot chat with the order ID pre-filled, so the user can send a photo directly to the bot and have it saved to the order's folder on the server.

**Architecture:** Bot relay via Telegram deep link. The Mini App opens `https://t.me/<BOT_USERNAME>?text=<order_id>` using `tg.openTelegramLink`. The bot's existing `save_photo_to_order` handles downloading and saving. Two small fixes in `main.py`: extend the regex to match `DDMM-XXX` order IDs, and add a timestamp to filenames to prevent overwrites.

**Tech Stack:** Vanilla JS (index.html), FastAPI + Python (main.py), Telegram Bot API (long polling)

---

### Task 1: Fix filename collision and extend bot regex in `main.py`

**Files:**
- Modify: `main.py:359` — add timestamp to saved photo filename
- Modify: `main.py:583` — extend regex to also match `DDMM-XXX` format

- [ ] **Step 1: Fix filename collision in `save_photo_to_order`**

  At `main.py:359`, replace:
  ```python
  dest = os.path.join(folder, f"{prefix}_{order_id}.jpg")
  ```
  with:
  ```python
  ts = datetime.now().strftime("%Y%m%d_%H%M%S")
  dest = os.path.join(folder, f"{prefix}_{order_id}_{ts}.jpg")
  ```
  (`datetime` is already imported at the top of `main.py`.)

- [ ] **Step 2: Extend bot regex to match order ID format**

  At `main.py:583`, replace:
  ```python
  if re.match(r"^\d+$", text) and photo:
  ```
  with:
  ```python
  if re.match(r"^\d+$|^\d{4}-\d{3}$", text) and photo:
  ```

- [ ] **Step 3: Manual smoke test**

  Send a photo to the bot with caption `1104-123` (replace with a real order ID from your DB). Verify:
  - Bot replies: `📸 Фото сохранено в #1104-123`
  - File appears in `uploads/1104-123/Процесс_1104-123_<timestamp>.jpg`
  - Sending a second photo creates a second file (not overwrites).

- [ ] **Step 4: Commit**

  ```bash
  git add main.py
  git commit -m "fix: extend photo bot handler to match order ID format, add timestamp to filenames"
  ```

---

### Task 2: Add photo button to the order edit form in `index.html`

**Files:**
- Modify: `index.html:459` — add `BOT_USERNAME` constant
- Modify: `index.html` (near line 768) — add button and handler

- [ ] **Step 1: Add `BOT_USERNAME` constant**

  At `index.html:459`, after the `SCRIPT_URL` line:
  ```js
  const SCRIPT_URL = 'https://your-ubuntu-domain.com';
  ```
  add:
  ```js
  const BOT_USERNAME = 'YourBotUsername'; // Telegram bot @username without @
  ```
  Replace `YourBotUsername` with the actual bot username.

- [ ] **Step 2: Add `addPhoto` function**

  Find any existing standalone function in the `<script>` block (e.g. near other UI helpers) and add:
  ```js
  function addPhoto(orderId) {
    tg.openTelegramLink(`https://t.me/${BOT_USERNAME}?text=${orderId}`);
  }
  ```

- [ ] **Step 3: Add button to edit form**

  At `index.html:768`, the current line is:
  ```js
  ${order.photo ? `<div style="margin-bottom:16px"><a class="detail-link" href="${order.photo}" target="_blank">📁 Открыть папку Drive</a></div>` : ''}
  ```
  Replace with:
  ```js
  <div style="margin-bottom:16px">
    <button class="btn-secondary" style="width:100%" onclick="addPhoto('${order.id}')">📸 Добавить фото</button>
  </div>
  ```
  (The old Drive folder link pointed to a local filesystem path and was non-functional — removed.)

- [ ] **Step 4: Bump `APP_VERSION`**

  At `index.html:457`:
  ```js
  const APP_VERSION = '1.2.0';
  ```

- [ ] **Step 5: Manual smoke test**

  Open the Mini App, tap an order to edit it. Verify:
  - "📸 Добавить фото" button is visible.
  - Tapping it opens the bot chat with the order ID pre-filled in the message input.
  - Attach a photo and send — bot replies confirming the save.

- [ ] **Step 6: Commit**

  ```bash
  git add index.html
  git commit -m "feat: add photo upload button to order edit form (bot relay)"
  ```
