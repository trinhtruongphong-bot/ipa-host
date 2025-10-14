# ==========================================================
# bot.py — Telegram bot chính (Render version)
# ==========================================================
# - Kết nối Flask API https://hehe-aoxt.onrender.com/upload
# - Chạy Polling, không cần webhook
# - Tự xoá tin tạm sau 30s
# ==========================================================

import os
import time
import math
import requests
import threading
from github_uploader import delete_from_github
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
REPO = os.getenv("GITHUB_REPO")
FLASK_URL = "https://hehe-aoxt.onrender.com/upload"  # ✅ dùng domain Render thực tế

def estimate_time(file_size):
    size_mb = file_size / (1024 * 1024)
    return math.ceil(5 + size_mb * 3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Xin chào!\n\n"
        "Gửi file `.ipa` để tôi phân tích và tạo link cài đặt.\n"
        "Hỗ trợ gửi nhiều file cùng lúc, tôi sẽ xử lý lần lượt.\n\n"
        "🧠 Lệnh có sẵn:\n"
        "/help — Hướng dẫn\n"
        "/listipa — 10 file IPA gần nhất\n"
        "/listplist — 10 file PLIST gần nhất"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 Cách dùng:\n"
        "1️⃣ Gửi file .ipa\n"
        "2️⃣ Tôi upload lên GitHub và tạo link cài trực tiếp\n"
        "3️⃣ Bạn nhận được kết quả chi tiết sau vài chục giây\n\n"
        "/listipa - Liệt kê file IPA\n"
        "/listplist - Liệt kê file PLIST"
    )

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

    status_msg = await update.message.reply_text(
        f"⏳ Đang xử lý *{file.file_name}*...\nDự kiến: ~{est} giây",
        parse_mode="Markdown"
    )

    with open(file_path, "rb") as f:
        res = requests.post(FLASK_URL, files={"file": f})

    if res.status_code != 200:
        await update.message.reply_text("❌ Lỗi upload IPA. Kiểm tra server Flask.")
        return

    data = res.json()
    msg = (
        f"✅ *Upload hoàn tất!*\n\n"
        f"📱 *App:* {data['app_name']}\n"
        f"🆔 *Bundle:* {data['bundle_id']}\n"
        f"🔢 *Version:* {data['version']}\n"
        f"👥 *Team:* {data['team_name']}\n\n"
        f"📦 [Tải IPA]({data['ipa_url']})\n"
        f"📲 [Cài trực tiếp]({data['install_url']})"
    )

    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)

    # Tự xóa tin nhắn tạm sau 30s
    threading.Thread(
        target=lambda: time.sleep(30) or context.application.create_task(
            context.bot.delete_message(update.message.chat_id, status_msg.message_id)
        )
    ).start()

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
        await update.message.reply_text("📂 Không có file IPA.")
        return
    buttons = [[InlineKeyboardButton(f"🗑️ {f}", callback_data=f"del_ipa:{f}")] for f in files]
    await update.message.reply_text(
        "📦 *10 file IPA gần nhất:*\nChọn file để xoá ⬇️",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def listplist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = get_github_files("Plist")
    if not files:
        await update.message.reply_text("📂 Không có file PLIST.")
        return
    buttons = [[InlineKeyboardButton(f"🗑️ {f}", callback_data=f"del_plist:{f}")] for f in files]
    await update.message.reply_text(
        "📄 *10 file PLIST gần nhất:*\nChọn file để xoá ⬇️",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("del_ipa:"):
        fname, path = query.data.split(":", 1)[1], "iPA/" + query.data.split(":", 1)[1]
    elif query.data.startswith("del_plist:"):
        fname, path = query.data.split(":", 1)[1], "Plist/" + query.data.split(":", 1)[1]
    else:
        return
    ok = delete_from_github(path)
    text = f"✅ Đã xoá file: {fname}" if ok else "❌ Lỗi xoá file GitHub."
    await query.edit_message_text(text)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("listipa", listipa))
    app.add_handler(CommandHandler("listplist", listplist))
    app.add_handler(CallbackQueryHandler(delete_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_ipa))
    print("🤖 Bot đang chạy (Polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()
