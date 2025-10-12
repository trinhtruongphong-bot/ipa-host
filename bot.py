import os, time, base64, random, string, requests, zipfile
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ========== CONFIG ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_REPO = "trinhtruongphong-bot/ipa-host"  # repo cố định
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DOMAIN = "https://download.khoindvn.io.vn"      # domain cố định

IPA_PATH = "IPA"
PLIST_PATH = "Plist"

# ========== HELPER ==========
def random_name(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def extract_info_from_ipa(ipa_bytes):
    """Đọc Info.plist chuẩn 100% từ file IPA"""
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

def check_link(url, timeout=30):
    for i in range(timeout):
        try:
            if requests.head(url, timeout=5).status_code == 200:
                return True
        except:
            pass
        time.sleep(1)
    return False

def shorten(url):
    try:
        r = requests.get(f"https://is.gd/create.php?format=simple&url={url}", timeout=5)
        return r.text if r.status_code == 200 else url
    except:
        return url

# ========== COMMANDS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào!\n"
        "Gửi file `.ipa` để upload và tạo link cài đặt trực tiếp iOS.\n"
        "Gõ /help để xem hướng dẫn chi tiết."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧭 Lệnh khả dụng:\n"
        "/listipa – Danh sách IPA (có nút xoá)\n"
        "/listplist – Danh sách Plist (có nút xoá)\n"
        "/help – Xem hướng dẫn\n\n"
        "Chỉ cần gửi file `.ipa` để upload!"
    )

async def list_files(update: Update, path, filetype):
    files = github_list(path)
    if not files:
        await update.message.reply_text(f"📂 Không có file {filetype}.")
        return
    keyboard = []
    for f in files:
        keyboard.append([InlineKeyboardButton(f"🗑️ Xoá {f}", callback_data=f"delete|{path}|{f}")])
    await update.message.reply_text(f"📦 Danh sách {filetype}:", reply_markup=InlineKeyboardMarkup(keyboard))

async def list_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_files(update, IPA_PATH, "IPA")

async def list_plist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_files(update, PLIST_PATH, "Plist")

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, path, filename = query.data.split("|")
    ok = github_delete(f"{path}/{filename}")
    if ok:
        await query.edit_message_text(f"✅ Đã xoá `{filename}` khỏi `{path}/`", parse_mode="Markdown")
    else:
        await query.edit_message_text(f"❌ Không thể xoá `{filename}`", parse_mode="Markdown")

# ========== UPLOAD ==========
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(".ipa"):
        await update.message.reply_text("⚠️ Vui lòng gửi file `.ipa` hợp lệ!")
        return

    msg = await update.message.reply_text("📤 Đang xử lý file...")
    file = await doc.get_file()
    ipa_bytes = await file.download_as_bytearray()
    info = extract_info_from_ipa(ipa_bytes)

    rand = random_name()
    ipa_file = f"{IPA_PATH}/{rand}.ipa"
    plist_file = f"{PLIST_PATH}/{rand}.plist"

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

    # 🕒 Kiểm tra link
    ready = check_link(ipa_url, timeout=30)
    install_link = f"itms-services://?action=download-manifest&url={plist_url}"
    short_link = shorten(install_link)

    text = (
        f"✅ **Upload thành công!**\n\n"
        f"📱 **Tên ứng dụng:** {info['name']}\n"
        f"🆔 **Bundle ID:** {info['bundle']}\n"
        f"🔢 **Phiên bản:** {info['version']}\n"
        f"👥 **Team ID:** {info['team']}\n\n"
        f"📦 **Tải IPA:** {ipa_url}\n"
        f"📲 **Cài đặt trực tiếp (rút gọn):** {short_link}\n\n"
    )
    if not ready:
        text += "⚠️ GitHub có thể cần vài giây để đồng bộ file. Nếu chưa tải được, hãy đợi thêm 20–30s rồi thử lại."

    await msg.edit_text(text, parse_mode="Markdown")

# ========== KEEP ALIVE ==========
def keep_alive():
    while True:
        try:
            requests.get(DOMAIN)
        except:
            pass
        time.sleep(50)

# ========== MAIN ==========
if __name__ == "__main__":
    import threading
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("listipa", list_ipa))
    app.add_handler(CommandHandler("listplist", list_plist))
    app.add_handler(CallbackQueryHandler(handle_delete))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    threading.Thread(target=keep_alive, daemon=True).start()
    print("🚀 Bot đang chạy (v8-final)...")
    app.run_polling()
