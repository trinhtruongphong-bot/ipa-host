import os, time, base64, random, string, requests, zipfile, asyncio
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from aiohttp import web

# ========== CONFIG ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = "trinhtruongphong-bot/ipa-host"
DOMAIN = "https://download.khoindvn.io.vn"
APP_URL = "https://ipa-host-dkoq.onrender.com"  # domain Render của bạn

IPA_PATH = "IPA"
PLIST_PATH = "Plist"

# ========== HELPER ==========
def random_name(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def extract_info_from_ipa(ipa_bytes):
    """Đọc Info.plist chuẩn 100% từ IPA"""
    try:
        with zipfile.ZipFile(BytesIO(ipa_bytes)) as ipa:
            for name in ipa.namelist():
                if name.endswith("Info.plist") and "Payload" in name:
                    plist_data = ipa.read(name)
                    from plistlib import loads
                    plist = loads(plist_data)
                    return {
                        "name": plist.get("CFBundleDisplayName") or plist.get("CFBundleName", "Unknown"),
                        "bundle": plist.get("CFBundleIdentifier", "unknown.bundle"),
                        "version": plist.get("CFBundleShortVersionString", "1.0"),
                        "team": plist.get("com.apple.developer.team-identifier", "Unknown")
                    }
    except Exception as e:
        print("❌ Lỗi đọc Info.plist:", e)
    return {"name": "Unknown", "bundle": "unknown.bundle", "version": "1.0", "team": "Unknown"}

def github_upload(path, content):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"message": f"Upload {path}", "content": base64.b64encode(content).decode()}
    r = requests.put(url, headers=headers, json=data)
    return r.status_code in [200, 201]

def github_list(path):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return [f["name"] for f in r.json()]
    return []

def github_delete(path):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return False
    sha = r.json()["sha"]
    data = {"message": f"delete {path}", "sha": sha}
    return requests.delete(url, headers=headers, json=data).status_code == 200

def shorten(url):
    try:
        r = requests.get(f"https://is.gd/create.php?format=simple&url={url}", timeout=5)
        return r.text if r.status_code == 200 else url
    except:
        return url

async def auto_delete(context, chat_id, msg_id, delay=30):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except:
        pass

# ========== COMMANDS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("👋 Xin chào!\nGửi file `.ipa` để upload và tạo link cài đặt iOS.")
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🧭 /listipa – danh sách IPA\n/listplist – danh sách Plist\n/help – hướng dẫn")
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE, path, label):
    files = github_list(path)
    if not files:
        msg = await update.message.reply_text(f"📂 Không có file {label}.")
        context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return
    keyboard = []
    for f in files:
        keyboard.append([InlineKeyboardButton(f"{f} 🗑️", callback_data=f"delete|{path}|{f}")])
    msg = await update.message.reply_text(f"📦 Danh sách {label}:", reply_markup=InlineKeyboardMarkup(keyboard))
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def listipa(update, context): await list_files(update, context, "IPA", "IPA")
async def listplist(update, context): await list_files(update, context, "Plist", "Plist")

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, path, filename = query.data.split("|")
    ok = github_delete(f"{path}/{filename}")
    await query.edit_message_text(f"✅ Đã xoá {filename}" if ok else f"❌ Không thể xoá {filename}")

# ========== UPLOAD ==========
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(".ipa"):
        msg = await update.message.reply_text("⚠️ Vui lòng gửi file `.ipa`!")
        context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return

    msg = await update.message.reply_text("📤 Đang nhận file IPA...")
    file = await doc.get_file()

    total_size = doc.file_size
    chunk_size = 1024 * 512  # 512KB mỗi chunk
    downloaded = 0
    buffer = BytesIO()

    async for chunk in file.download_as_stream():
        buffer.write(chunk)
        downloaded += len(chunk)
        percent = int(downloaded / total_size * 100)
        if percent % 10 == 0:
            try:
                await msg.edit_text(f"⬆️ Tiến độ upload: {percent}%")
            except:
                pass

    ipa_bytes = buffer.getvalue()
    await msg.edit_text("✅ Đã tải xong, đang upload lên GitHub...")

    info = extract_info_from_ipa(ipa_bytes)
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    ipa_file = f"IPA/{rand}.ipa"
    plist_file = f"Plist/{rand}.plist"

    github_upload(ipa_file, ipa_bytes)
    ipa_url = f"{DOMAIN}/{ipa_file}"
    plist_url = f"{DOMAIN}/{plist_file}"

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict>
<key>assets</key><array><dict><key>kind</key><string>software-package</string>
<key>url</key><string>{ipa_url}</string></dict></array>
<key>metadata</key><dict>
<key>bundle-identifier</key><string>{info['bundle']}</string>
<key>bundle-version</key><string>{info['version']}</string>
<key>kind</key><string>software</string>
<key>title</key><string>{info['name']}</string>
</dict></dict></array></dict></plist>"""
    github_upload(plist_file, plist.encode())

    await asyncio.sleep(30)
    install_link = f"itms-services://?action=download-manifest&url={plist_url}"
    short = shorten(install_link)

    await msg.edit_text(
        f"✅ **Upload thành công!**\n\n"
        f"📱 Tên: {info['name']}\n🆔 {info['bundle']}\n🔢 {info['version']}\n"
        f"📦 [Tải IPA]({ipa_url})\n📲 [Cài trực tiếp (rút gọn)]({short})",
        parse_mode="Markdown"
    )

# ========== MAIN ==========
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(CommandHandler("listipa", listipa))
    app.add_handler(CommandHandler("listplist", listplist))
    app.add_handler(CallbackQueryHandler(handle_delete))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    async def webhook(request):
        data = await request.json()
        await app.update_queue.put(Update.de_json(data, app.bot))
        return web.Response()

    webapp = web.Application()
    webapp.router.add_post(f"/{BOT_TOKEN}", webhook)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()

    webhook_url = f"{APP_URL}/{BOT_TOKEN}"
    await app.bot.set_webhook(webhook_url)
    print(f"🚀 Webhook đang chạy tại: {webhook_url}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
