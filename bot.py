import os, time, base64, random, string, requests, zipfile, asyncio, math
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ========== CONFIG ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_REPO = "trinhtruongphong-bot/ipa-host"  # repo chứa IPA/Plist
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DOMAIN = "https://download.khoindvn.io.vn"     # domain public (GitHub Pages/CDN)

IPA_PATH = "IPA"
PLIST_PATH = "Plist"

# ========== HELPER ==========
def random_name(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def extract_info_from_ipa(ipa_bytes):
    """Đọc Info.plist chuẩn từ IPA để lấy name/bundle/version/team."""
    try:
        with zipfile.ZipFile(BytesIO(ipa_bytes)) as ipa:
            for name in ipa.namelist():
                if name.endswith("Info.plist") and "Payload" in name:
                    data = ipa.read(name)
                    from plistlib import loads
                    p = loads(data)
                    return {
                        "name": p.get("CFBundleDisplayName") or p.get("CFBundleName", "Unknown"),
                        "bundle": p.get("CFBundleIdentifier", "unknown.bundle"),
                        "version": p.get("CFBundleShortVersionString", "1.0"),
                        "team": p.get("com.apple.developer.team-identifier", "Unknown")
                    }
    except Exception as e:
        print("❌ Lỗi đọc Info.plist:", e)
    return {"name": "Unknown", "bundle": "unknown.bundle", "version": "1.0", "team": "Unknown"}

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

async def auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id, delay=30):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

async def edit_progress(msg, label, pct):
    try:
        await msg.edit_text(f"{label}: {pct}%")
    except:
        pass

async def github_upload_with_progress(path: str, raw_bytes: bytes, msg, label="⬆️ Upload GitHub"):
    """
    Upload file lên GitHub Contents API kèm % ước lượng.
    Cách làm: mã hoá Base64 theo từng chunk và cập nhật %; sau đó PUT 1 lần.
    """
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"

    # Encode base64 theo chunks để báo % (dựa trên byte đã mã hoá)
    total = len(raw_bytes)
    chunk = 1024 * 1024  # 1MB/chunk
    parts = []
    done = 0
    last_shown = -1

    for i in range(0, total, chunk):
        part = base64.b64encode(raw_bytes[i:i+chunk]).decode()
        parts.append(part)
        done += min(chunk, total - i)
        pct = int(done * 100 / total)
        step = pct // 5  # cập nhật mỗi 5%
        if step > last_shown:
            last_shown = step
            await edit_progress(msg, label, min(pct, 95))  # giữ max 95% trước khi PUT

        await asyncio.sleep(0)  # nhường event loop

    encoded = ''.join(parts)
    payload = {"message": f"Upload {path}", "content": encoded}

    # Gửi PUT (bước cuối)
    try:
        r = requests.put(url, headers=headers, json=payload, timeout=120)
        await edit_progress(msg, label, 100)
        return r.status_code in [200, 201]
    except Exception as e:
        print("❌ Lỗi PUT GitHub:", e)
        return False

# ========== COMMANDS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "👋 Xin chào!\nGửi file `.ipa` để upload và tạo link cài đặt trực tiếp iOS.\nGõ /help để xem hướng dẫn."
    )
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "🧭 Lệnh khả dụng:\n"
        "/listipa – Danh sách IPA (có nút xoá)\n"
        "/listplist – Danh sách Plist (có nút xoá)\n"
        "/help – Xem hướng dẫn\n\n"
        "📤 Gửi file `.ipa` để upload!"
    )
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

async def list_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_files(update, context, IPA_PATH, "IPA")

async def list_plist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_files(update, context, PLIST_PATH, "Plist")

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, path, filename = query.data.split("|")
    ok = github_delete(f"{path}/{filename}")
    await query.edit_message_text(
        f"✅ Đã xoá `{filename}` khỏi `{path}/`" if ok else f"❌ Không thể xoá `{filename}`",
        parse_mode="Markdown"
    )

# ========== UPLOAD ==========
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(".ipa"):
        msg = await update.message.reply_text("⚠️ Vui lòng gửi file `.ipa` hợp lệ!")
        context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return

    # 1) Hiển thị tiến độ nhận file (%)
    msg = await update.message.reply_text("📤 Đang nhận file IPA...")
    tg_file = await doc.get_file()

    # Tải stream từ Telegram để có % thật
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}"
    r = requests.get(file_url, stream=True)
    total = int(r.headers.get("Content-Length", "0")) or doc.file_size or 0

    buf = BytesIO()
    downloaded = 0
    last_step = -1
    for chunk in r.iter_content(chunk_size=524288):  # 512KB/chunk
        if not chunk: continue
        buf.write(chunk)
        downloaded += len(chunk)
        if total > 0:
            pct = int(downloaded * 100 / total)
            step = pct // 10  # 10% một lần
            if step > last_step:
                last_step = step
                try:
                    await msg.edit_text(f"⬇️ Nhận file từ Telegram: {pct}%")
                except:
                    pass

    ipa_bytes = buf.getvalue()
    await msg.edit_text("✅ Đã nhận xong. Đang chuẩn bị upload lên GitHub…")

    # 2) Trích xuất info & đặt tên random
    info = extract_info_from_ipa(ipa_bytes)
    rand = random_name()
    ipa_file = f"{IPA_PATH}/{rand}.ipa"
    plist_file = f"{PLIST_PATH}/{rand}.plist"

    # 3) Upload IPA lên GitHub với % ước lượng
    ok = await github_upload_with_progress(ipa_file, ipa_bytes, msg, label="⬆️ Upload GitHub (IPA)")
    if not ok:
        msg2 = await update.message.reply_text("❌ Upload IPA lên GitHub thất bại.")
        context.application.create_task(auto_delete(context, msg2.chat_id, msg2.message_id))
        return

    ipa_url = f"{DOMAIN}/{ipa_file}"
    plist_url = f"{DOMAIN}/{plist_file}"

    # 4) Tạo PLIST manifest và upload (file nhỏ nên không cần %)
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

    # upload plist (nhanh, không cần progress)
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url_pl = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{plist_file}"
    payload_pl = {"message": f"Upload {plist_file}", "content": base64.b64encode(plist.encode()).decode()}
    requests.put(url_pl, headers=headers, json=payload_pl, timeout=60)

    # 5) Chờ CDN đồng bộ 30s rồi gửi link
    await asyncio.sleep(30)
    install_link = f"itms-services://?action=download-manifest&url={plist_url}"
    short_link = shorten(install_link)

    # 6) Gửi kết quả cuối (KHÔNG auto-delete)
    await msg.edit_text(
        f"✅ **Upload thành công!**\n\n"
        f"📱 **Tên ứng dụng:** {info['name']}\n"
        f"🆔 **Bundle ID:** {info['bundle']}\n"
        f"🔢 **Phiên bản:** {info['version']}\n"
        f"👥 **Team ID:** {info['team']}\n\n"
        f"📦 **Tải IPA:** {ipa_url}\n"
        f"📲 **Cài đặt trực tiếp (rút gọn):** {short_link}",
        parse_mode="Markdown"
    )

# ========== KEEP ALIVE (Render free) ==========
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
    print("🚀 Bot đang chạy (v8.8-final)…")
    app.run_polling()
