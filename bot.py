import os, io, re, zipfile, plistlib, base64, requests, urllib.parse, random, string, time, math, aiohttp, threading, http.server, socketserver
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

# =====================
# 🌍 CONFIG
# =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("GITHUB_REPO")
CUSTOM_DOMAIN = os.getenv("CUSTOM_DOMAIN", "download.khoindvn.io.vn")

# =====================
# 🧠 UTILITIES
# =====================
def random_str(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def extract_info_from_ipa(ipa_bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(ipa_bytes)) as ipa:
            for name in ipa.namelist():
                if name.endswith("Info.plist") and "Payload/" in name:
                    with ipa.open(name) as plist_file:
                        plist_data = plistlib.load(plist_file)
                        app_name = plist_data.get("CFBundleDisplayName") or plist_data.get("CFBundleName", "Unknown")
                        bundle_id = plist_data.get("CFBundleIdentifier", "unknown.bundle")
                        version = plist_data.get("CFBundleShortVersionString", "1.0.0")
                        team_id = plist_data.get("com.apple.developer.team-identifier", "Unknown")
                    return app_name, bundle_id, version, team_id
    except Exception as e:
        print(f"❌ Lỗi Info.plist: {e}")
    return "Unknown", "unknown.bundle", "1.0.0", "Unknown"

def wait_until_github_ready(url, timeout=90):
    print(f"🔍 Kiểm tra link: {url}")
    for i in range(timeout):
        try:
            r = requests.head(url, timeout=5)
            if r.status_code == 200:
                print(f"✅ Link sẵn sàng sau {i*2} giây.")
                return True
        except:
            pass
        if i % 5 == 0:
            print(f"⏳ Chờ GitHub sync... ({i*2}s)")
        time.sleep(2)
    return False

# =====================
# 📤 HANDLE IPA UPLOAD
# =====================
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document
    if not file or not file.file_name.endswith(".ipa"):
        await update.message.reply_text("📦 Gửi file `.ipa` để upload.")
        return

    total_size = file.file_size
    msg = await update.message.reply_text(f"📥 Nhận `{file.file_name}` — đang tải về...", parse_mode="Markdown")

    # Lấy file từ Telegram
    getfile = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": file.file_id}).json()
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{getfile['result']['file_path']}"

    async with aiohttp.ClientSession() as session:
        ipa_bytes = b""
        downloaded = 0
        timeout = aiohttp.ClientTimeout(total=1800)
        async with session.get(file_url, timeout=timeout) as resp:
            async for chunk in resp.content.iter_chunked(1024 * 512):
                ipa_bytes += chunk
                downloaded += len(chunk)
                percent = math.floor(downloaded / total_size * 100)
                if percent % 20 == 0:
                    try:
                        await msg.edit_text(f"⬇️ Đang tải: {percent}%")
                    except:
                        pass

    app_name, bundle_id, version, team_id = extract_info_from_ipa(ipa_bytes)
    await msg.edit_text(f"📤 Đang upload `{app_name}` lên GitHub...", parse_mode="Markdown")

    tag = random_str(6)
    ipa_name = f"{tag}.ipa"
    plist_name = f"{tag}.plist"
    ipa_path = f"IPA/{ipa_name}"

    encoded_ipa = base64.b64encode(ipa_bytes).decode("utf-8")
    github_api = f"https://api.github.com/repos/{REPO}/contents/{ipa_path}"
    up = requests.put(
        github_api,
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
        json={"message": f"Upload {ipa_name}", "content": encoded_ipa}
    )
    if up.status_code not in (200, 201):
        await msg.edit_text(f"❌ Upload lỗi: {up.text[:400]}")
        return

    raw_ipa_url = f"https://{CUSTOM_DOMAIN}/{ipa_path}"

    # 🕒 Kiểm tra file hoạt động
    await msg.edit_text("⏳ Đang đồng bộ file lên GitHub... vui lòng chờ 1 phút.")
    ready = wait_until_github_ready(raw_ipa_url, 90)
    if not ready:
        await msg.edit_text("⚠️ GitHub chưa cập nhật link, thử lại sau (mất ~30–60s).")
        return

    # 🧾 Tạo file plist
    plist_path = f"Plist/{plist_name}"
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
<key>items</key>
<array>
<dict>
<key>assets</key>
<array>
<dict>
<key>kind</key><string>software-package</string>
<key>url</key><string>{raw_ipa_url}</string>
</dict>
</array>
<key>metadata</key>
<dict>
<key>bundle-identifier</key><string>{bundle_id}</string>
<key>bundle-version</key><string>{version}</string>
<key>kind</key><string>software</string>
<key>title</key><string>{app_name}</string>
</dict>
</dict>
</array>
</dict>
</plist>"""
    encoded_plist = base64.b64encode(plist_content.encode()).decode("utf-8")
    plist_api = f"https://api.github.com/repos/{REPO}/contents/{plist_path}"
    requests.put(
        plist_api,
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
        json={"message": f"Upload {plist_name}", "content": encoded_plist}
    )

    raw_plist_url = f"https://{CUSTOM_DOMAIN}/{plist_path}"
    encoded_url = urllib.parse.quote(raw_plist_url, safe="")
    itms = f"itms-services://?action=download-manifest&url={encoded_url}"
    short = requests.get("https://is.gd/create.php", params={"format": "simple", "url": itms}).text.strip()

    reply = (
        f"✅ **Upload thành công!**\n\n"
        f"📱 **Tên ứng dụng:** {app_name}\n"
        f"🆔 **Bundle ID:** `{bundle_id}`\n"
        f"🔢 **Phiên bản:** {version}\n"
        f"👥 **Team ID:** {team_id}\n"
        f"💾 **Dung lượng:** {round(total_size / (1024*1024),2)} MB\n\n"
        f"📦 **Tải IPA:**\n{raw_ipa_url}\n\n"
        f"📲 **Cài đặt trực tiếp:**\n{short}"
    )
    await msg.edit_text(reply, parse_mode="Markdown", disable_web_page_preview=True)

# =====================
# 🔧 COMMANDS
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Gửi file `.ipa` để upload và tạo link cài đặt trực tiếp.\nGõ /help để xem hướng dẫn."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 **Các lệnh hỗ trợ:**\n"
        "/listipa – Danh sách file IPA\n"
        "/listplist – Danh sách file Plist\n"
        "/deleteipa <tên_file>\n"
        "/deleteplist <tên_file>\n"
        "/getipa <tên_file>\n",
        parse_mode="Markdown"
    )

async def getipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("📦 Nhập tên file IPA!\nVí dụ: `/getipa fh28ks.ipa`", parse_mode="Markdown")
        return
    ipa_name = args[0]
    plist_name = ipa_name.replace(".ipa", ".plist")
    ipa_url = f"https://{CUSTOM_DOMAIN}/IPA/{ipa_name}"
    plist_url = f"https://{CUSTOM_DOMAIN}/Plist/{plist_name}"
    itms = f"itms-services://?action=download-manifest&url={plist_url}"
    msg = f"📦 **{ipa_name}**\n🔗 [Tải IPA]({ipa_url})\n📲 **Cài đặt:** {itms}"
    await update.message.reply_text(msg, parse_mode="Markdown")

# =====================
# 🔁 KEEP ALIVE
# =====================
def keep_alive():
    port = 10000
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"🌐 Keep-alive server running on port {port}")
        httpd.serve_forever()

def self_ping():
    while True:
        try:
            requests.get(f"https://{CUSTOM_DOMAIN}")
        except:
            pass
        time.sleep(50)

# =====================
# 🚀 RUN
# =====================
if __name__ == "__main__":
    print("🤖 Bot khởi động...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("getipa", getipa))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()
    app.run_polling(concurrent_updates=True)
