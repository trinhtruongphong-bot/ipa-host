# ==========================================================
# bot.py — Telegram bot chính
# ==========================================================
# Nhiệm vụ:
# - Lắng nghe lệnh /start, /help, /listipa, /listplist
# - Nhận file .ipa từ người dùng, upload lên Flask API
# - Hiển thị trạng thái xử lý và kết quả cuối
# - Tự động xoá tin nhắn tạm sau 30 giây
# - Xoá file .ipa / .plist trên GitHub khi nhấn 🗑️
# ==========================================================

import os
import time
import math
import requests
import yaml
import threading
from github_uploader import delete_from_github

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

# Đọc config
with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

BOT_TOKEN = config["telegram"]["token"]
FLASK_URL = "http://localhost:5000/upload"  # Khi chạy cùng Render, Flask và bot cùng service
REPO = config["github"]["repo"]

# ==============================
# Hàm tiện ích
# ==============================
def estimate_time(file_size):
    # file_size tính bằng byte → đổi sang MB
    size_mb = file_size / (1024 * 1024)
    return math.ceil(5 + size_mb * 3)  # mỗi MB ~3s, cộng 5s khởi đầu

async def delete_message_later(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id, delay=30):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

# ==============================
# Command handlers
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Xin chào!\n\n"
        "Gửi file `.ipa` vào đây để tôi phân tích và tạo link cài đặt.\n"
        "Bạn có thể gửi **nhiều file cùng lúc**, tôi sẽ xử lý từng cái.\n\n"
        "🧠 Lệnh có sẵn:\n"
        "/help — Hướng dẫn chi tiết\n"
        "/listipa — Liệt kê 10 file IPA gần nhất\n"
        "/listplist — Liệt kê 10 file PLIST gần nhất"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📱 *Hướng dẫn sử dụng bot IPA Server:*\n\n"
        "1️⃣ Gửi file `.ipa` (một hoặc nhiều file cùng lúc)\n"
        "2️⃣ Tôi sẽ tải lên GitHub, tạo file `.plist` và link cài trực tiếp.\n"
        "3️⃣ Chờ trong vài chục giây, bạn sẽ nhận được kết quả.\n\n"
        "⚙️ Lệnh khác:\n"
        "/listipa — Danh sách file IPA\n"
        "/listplist — Danh sách file manifest (.plist)"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ==============================
# Xử lý khi nhận file .ipa
# ==============================
async def handle_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document
    if not file.file_name.endswith(".ipa"):
        await update.message.reply_text("⚠️ Vui lòng gửi đúng file .ipa")
        return

    file_info = await context.bot.get_file(file.file_id)
    file_path = f"/tmp/{file.file_name}"
    await file_info.download_to_drive(file_path)
    size = os.path.getsize(file_path)
    est = estimate_time(size)

    # Gửi tin nhắn tạm
    status_msg = await update.message.reply_text(
        f"⏳ Đang xử lý file *{file.file_name}*...\nDự kiến: ~{est} giây",
        parse_mode="Markdown"
    )

    # Gửi file tới Flask API
    with open(file_path, "rb") as f:
        res = requests.post(FLASK_URL, files={"file": f})

    if res.status_code != 200:
        await update.message.reply_text("❌ Lỗi khi upload IPA, vui lòng thử lại.")
        return

    data = res.json()

    text = (
        f"✅ *Upload hoàn tất!*\n\n"
        f"📱 *App:* {data['app_name']}\n"
        f"🆔 *Bundle:* {data['bundle_id']}\n"
        f"🔢 *Version:* {data['version']}\n"
        f"👥 *Team:* {data['team_name']}\n\n"
        f"📦 [Tải IPA]({data['ipa_url']})\n"
        f"📲 [Cài trực tiếp]({data['install_url']})"
    )

    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)

    # Xoá tin nhắn tạm sau 30s
    threading.Thread(
        target=lambda: time.sleep(30) or context.application.create_task(
            context.bot.delete_message(update.message.chat_id, status_msg.message_id)
        )
    ).start()

# ==============================
# Danh sách file IPA / PLIST
# ==============================
def get_github_files(subdir, limit=10):
    api = f"https://api.github.com/repos/{REPO}/contents/{subdir}"
    res = requests.get(api)
    if res.status_code != 200:
        return []
    files = [f["name"] for f in sorted(res.json(), key=lambda x: x["name"], reverse=True)]
    return files[:limit]

async def listipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = get_github_files("iPA")
    if not files:
        await update.message.reply_text("📂 Không có file IPA nào.")
        return

    buttons = []
    for f in files:
        buttons.append([InlineKeyboardButton(f"🗑️ {f}", callback_data=f"del_ipa:{f}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    text = "📦 *10 file IPA gần nhất:*\nChọn file để xoá ⬇️"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def listplist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = get_github_files("Plist")
    if not files:
        await update.message.reply_text("📂 Không có file PLIST nào.")
        return

    buttons = []
    for f in files:
        buttons.append([InlineKeyboardButton(f"🗑️ {f}", callback_data=f"del_plist:{f}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    text = "📄 *10 file PLIST gần nhất:*\nChọn file để xoá ⬇️"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

# ==============================
# Xử lý xoá file GitHub
# ==============================
async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("del_ipa:"):
        fname = query.data.split(":", 1)[1]
        path = f"iPA/{fname}"
    elif query.data.startswith("del_plist:"):
        fname = query.data.split(":", 1)[1]
        path = f"Plist/{fname}"
    else:
        return

    ok = delete_from_github(path)
    if ok:
        await query.edit_message_text(f"✅ Đã xoá file: {fname}")
    else:
        await query.edit_message_text("❌ Không xoá được file, kiểm tra GitHub token.")

# ==============================
# Main loop
# ==============================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("listipa", listipa))
    app.add_handler(CommandHandler("listplist", listplist))
    app.add_handler(CallbackQueryHandler(delete_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_ipa))

    print("🤖 Bot đang chạy...")
    app.run_polling()

if __name__ == "__main__":
    main()
