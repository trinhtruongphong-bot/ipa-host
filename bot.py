# ==========================================================
# bot.py — Logic xử lý Telegram command & file upload
# ==========================================================

import os
import time
import math
import requests
from github_uploader import delete_from_github
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

REPO = os.getenv("GITHUB_REPO")
FLASK_URL = "https://hehe-aoxt.onrender.com/upload"  # Domain Flask

# ==============================
# Command: /start, /help
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Xin chào!\n\n"
        "Gửi file `.ipa` để tôi phân tích và tạo link cài đặt.\n"
        "Hỗ trợ gửi nhiều file cùng lúc, tôi sẽ xử lý lần lượt.\n\n"
        "/help — Hướng dẫn\n/listipa — Liệt kê file IPA\n/listplist — Liệt kê file PLIST"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 *Hướng dẫn:*\nGửi file `.ipa`, tôi sẽ upload và tạo link cài trực tiếp.",
        parse_mode="Markdown"
    )

# ==============================
# Upload IPA handler
# ==============================
def estimate_time(file_size):
    size_mb = file_size / (1024 * 1024)
    return math.ceil(5 + size_mb * 3)

async def handle_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(".ipa"):
        await update.message.reply_text("⚠️ Vui lòng gửi đúng file .ipa")
        return

    file_info = await context.bot.get_file(doc.file_id)
    path = f"/tmp/{doc.file_name}"
    await file_info.download_to_drive(path)
    size = os.path.getsize(path)
    est = estimate_time(size)
    status = await update.message.reply_text(f"⏳ Đang xử lý *{doc.file_name}*...\nDự kiến ~{est} giây", parse_mode="Markdown")

    with open(path, "rb") as f:
        res = requests.post(FLASK_URL, files={"file": f})
    if res.status_code != 200:
        await update.message.reply_text("❌ Lỗi khi upload IPA.")
        return

    d = res.json()
    text = (
        f"✅ *Upload hoàn tất!*\n\n"
        f"📱 *App:* {d['app_name']}\n"
        f"🆔 *Bundle:* {d['bundle_id']}\n"
        f"🔢 *Version:* {d['version']}\n"
        f"👥 *Team:* {d['team_name']}\n\n"
        f"📦 [Tải IPA]({d['ipa_url']})\n"
        f"📲 [Cài trực tiếp]({d['install_url']})"
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    time.sleep(30)
    try:
        await context.bot.delete_message(update.message.chat_id, status.message_id)
    except:
        pass

# ==============================
# Danh sách & Xoá file
# ==============================
def get_files(subdir, limit=10):
    api = f"https://api.github.com/repos/{REPO}/contents/{subdir}"
    res = requests.get(api)
    if res.status_code != 200:
        return []
    files = [f["name"] for f in sorted(res.json(), key=lambda x: x["name"], reverse=True)]
    return files[:limit]

async def listipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = get_files("iPA")
    if not files:
        await update.message.reply_text("📂 Không có file IPA.")
        return
    btns = [[InlineKeyboardButton(f"🗑️ {f}", callback_data=f"del_ipa:{f}")] for f in files]
    await update.message.reply_text("📦 *File IPA gần nhất:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns))

async def listplist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = get_files("Plist")
    if not files:
        await update.message.reply_text("📂 Không có file PLIST.")
        return
    btns = [[InlineKeyboardButton(f"🗑️ {f}", callback_data=f"del_plist:{f}")] for f in files]
    await update.message.reply_text("📄 *File PLIST gần nhất:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns))

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("del_ipa:"):
        fname, path = q.data.split(":", 1)[1], "iPA/" + q.data.split(":", 1)[1]
    else:
        fname, path = q.data.split(":", 1)[1], "Plist/" + q.data.split(":", 1)[1]
    ok = delete_from_github(path)
    await q.edit_message_text(f"✅ Đã xoá {fname}" if ok else "❌ Lỗi xoá file")
