# ==========================================================
# bot.py — Telegram bot chính (Free Plan tối ưu)
# ==========================================================
# - Chạy polling an toàn trong cùng service với Flask
# - Có delay nhẹ khởi động để Flask ổn định trước
# - Hạn chế Conflict bằng session_timeout & single polling loop
# ==========================================================

import os
import time
import math
import requests
import threading
import asyncio
from github_uploader import delete_from_github
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ===================== Cấu hình =====================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
REPO = os.getenv("GITHUB_REPO")
FLASK_URL = "https://hehe-aoxt.onrender.com/upload"  # Domain Flask Render
POLL_INTERVAL = 3  # Thời gian chờ giữa mỗi vòng polling

# ===================== Tiện ích =====================
def estimate_time(file_size):
    size_mb = file_size / (1024 * 1024)
    return math.ceil(5 + size_mb * 3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Xin chào!\n\n"
        "Gửi file `.ipa` để tôi phân tích và tạo link cài đặt.\n"
        "Bạn có thể gửi nhiều file, tôi sẽ xử lý lần lượt.\n\n"
        "🧠 Lệnh có sẵn:\n"
        "/help — Hướng dẫn\n"
        "/listipa — Liệt kê 10 file IPA gần nhất\n"
        "/listplist — Liệt kê 10 file PLIST gần nhất"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 Cách dùng:\n"
        "1️⃣ Gửi file .ipa\n"
        "2️⃣ Tôi upload lên GitHub và tạo link cài trực tiếp\n"
        "3️⃣ Bạn nhận kết quả sau vài chục giây\n\n"
        "/listipa - Liệt kê file IPA\n"
        "/listplist - Liệt kê file PLIST"
    )

# ===================== Xử lý file IPA =====================
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
        try:
            res = requests.post(FLASK_URL, files={"file": f}, timeout=120)
        except Exception as e:
            await update.message.reply_text(f"❌ Lỗi kết nối server Flask: {e}")
            return

    if res.status_code != 200:
        await update.message.reply_text("❌ Upload thất bại, kiểm tra Flask server.")
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

    threading.Thread(
        target=lambda: time.sleep(30) or context.application.create_task(
            context.bot.delete_message(update.message.chat_id, status_msg.message_id)
        )
    ).start()

# ===================== Liệt kê file GitHub =====================
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
    buttons = [[InlineKeyboardButton(f"🗑️ {f}", callback_data=f"del_ipa:{f}")] for f in files]
    await update.message.reply_text(
        "📦 *10 file IPA gần nhất:*\nChọn file để xoá ⬇️",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def listplist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = get_github_files("Plist")
    if not files:
        await update.message.reply_text("📂 Không có file PLIST nào.")
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

# ===================== Chạy polling an toàn =====================
def main():
    print("🚀 Đợi 5s để Flask ổn định...")
    time.sleep(5)  # đợi Flask server khởi động xong

    app = ApplicationBuilder().token(BOT_TOKEN).read_timeout(30).write_timeout(30).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("listipa", listipa))
    app.add_handler(CommandHandler("listplist", listplist))
    app.add_handler(CallbackQueryHandler(delete_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_ipa))

    print("🤖 Bot đang chạy (Polling an toàn)...")
    app.run_polling(stop_signals=None, allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
