# Photo Upload — Design Spec

**Date:** 2026-04-11

## Goal

Allow master users to attach photos to an order from the Mini App. Photos are stored on the server filesystem under `uploads/<order_id>/`. No photo viewing in the Mini App — management happens via the filesystem or a file browser on the server.

## Approach: Bot relay via deep link

The user taps a button in the order detail view. The app opens the Telegram bot chat with the order ID pre-filled in the message input. The user attaches a photo and sends it. The bot downloads the photo from Telegram CDN and saves it to the order's folder.

This reuses existing infrastructure (`save_photo_to_order`, `download_photo`) and avoids any file upload complexity in the Mini App.

## Changes

### `index.html`

1. Add `BOT_USERNAME` constant near the top of the `<script>` section:
   ```js
   const BOT_USERNAME = 'YourBotUsername'; // Telegram bot @username (without @)
   ```

2. In the order edit form (`renderEditForm`), add a button next to the existing folder link (both are in the same area):
   ```html
   <button class="btn-secondary" onclick="addPhoto('${order.id}')">📸 Добавить фото</button>
   ```

3. Add handler function:
   ```js
   function addPhoto(orderId) {
     tg.openTelegramLink(`https://t.me/${BOT_USERNAME}?text=${orderId}`);
   }
   ```

   `tg.openTelegramLink` opens the URL within Telegram's own navigation (does not leave the app context on most platforms).

### `main.py`

1. Extend photo-saving bot handler to match the `DDMM-XXX` order ID format (line ~583):

   **Before:**
   ```python
   if re.match(r"^\d+$", text) and photo:
       ok = await save_photo_to_order(text, photo, "Процесс")
   ```

   **After:**
   ```python
   if re.match(r"^\d+$|^\d{4}-\d{3}$", text) and photo:
       ok = await save_photo_to_order(text, photo, "Процесс")
   ```

2. Fix filename collision in `save_photo_to_order` — add timestamp so multiple uploads don't overwrite each other (line ~359):

   **Before:**
   ```python
   dest = os.path.join(folder, f"{prefix}_{order_id}.jpg")
   ```

   **After:**
   ```python
   ts = datetime.now().strftime("%Y%m%d_%H%M%S")
   dest = os.path.join(folder, f"{prefix}_{order_id}_{ts}.jpg")
   ```

## Data flow

```
User taps "📸 Добавить фото"
  → tg.openTelegramLink opens bot chat, order ID pre-filled
  → User attaches photo, sends message
  → Bot receives: text = "1104-123", photo = [...]
  → re.match(r"^\d{4}-\d{3}$", text) matches
  → save_photo_to_order("1104-123", photo, "Процесс")
    → SELECT photo FROM orders WHERE id = "1104-123"  → "uploads/1104-123"
    → download_photo(file_id) → saves to "uploads/1104-123/Процесс_1104-123_20260411_143022.jpg"
  → Bot replies: "📸 Фото сохранено в #1104-123"
```

## Out of scope

- Viewing photos in the Mini App
- Deleting photos
- Multiple photo selection at once (user sends photos one by one)
- Photos for archived orders (bot handler only queries `orders` table; archive support can be added later if needed)
