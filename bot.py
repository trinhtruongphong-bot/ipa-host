import os
import io
import re
import zipfile
import plistlib
import base64
import requests
import urllib.parse
import random
import string
import time
import math
import aiohttp
import threading, http.server, socketserver
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

# 🌍 ENV CONFIG
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("GITHUB_REPO")
CUSTOM_DOMAIN = "download.khoindvn.io.vn"  # domain của bạn

# -----------------------------
# 🔹 HÀM PHỤ
# -----------------------------
def random_str(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def safe_filename(name):
    # ⚙️ Giữ nguyên dấu "_" và khoảng trắng, chỉ thay ký tự đặc biệt khác
    name = name.replace(" ", "_")
    name = re.sub(r'[^A-Za-z0-9._-]', '_', name)
    return name.strip('_')

# -----------------------------
# 🔹 TẢI FILE CÓ TIẾN TRÌNH %
# -----------------------------
async def download_with_progress(session, file_url, total_size, message):
    downloaded = 0
    chunks = []
    timeout = aiohttp.ClientTimeout(total=1800)
    async with session.get(file_url, timeout=timeout) as resp:
        while True:
            chunk = await resp.content.read(1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            downloaded += len(chunk)
            percent = math.floor(downloaded / total_size * 100)
            if percent % 10 == 0:
                try:
                    await message.edit_text(f"⬆️ Đang tải từ Telegram: {percent}%")
                except:
                    pass
    return b"".join(chunks)

# -----------------------------
# 🔹 XỬ LÝ FILE IPA
# -----------------------------
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document
    if not file or not file.file_name.endswith(".ipa"):
        await update.message.reply_text("📦 Gửi file `.ipa` để upload.")
        return

    file_name = file.file_name
    total_size = file.file_size
    msg = await update.message.reply_text(f"📦 Đã nhận file `{file_name}`, đang xử lý...", parse_mode="Markdown")

    getfile = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": file.file_id}).json()
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{getfile['result']['file_path']}"

    async with aiohttp.ClientSession() as session:
        ipa_bytes = await download_with_progress(session, file_url, total_size, msg)

    await msg.edit_text("📤 Đang upload lên GitHub...")

    app_name = "Unknown"
    bundle_id = "unknown.bundle"
    version = "1.0.0"
    team_name = "Unknown"

    try:
        with zipfile.ZipFile(io.BytesIO(ipa_bytes)) as ipa:
            for name in ipa.namelist():
                if name.endswith("Info.plist") and "Payload/" in name:
                    with ipa.open(name) as plist_file:
                        plist_data = plistlib.load(plist_file)
                        app_name = plist_data.get("CFBundleDisplayName") or plist_data.get("CFBundleName", "Unknown")
                        bundle_id = plist_data.get("CFBundleIdentifier", "unknown.bundle")
                        version = plist_data.get("CFBundleShortVersionString", "1.0.0")
                        team_name = plist_data.get("TeamName", "Unknown")
                    break
    except Exception as e:
        await msg.edit_text(f"⚠️ Lỗi đọc Info.plist: {e}")
        return

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_name = safe_filename(app_name)
    unique_ipa_name = f"{safe_name}_{version}_{timestamp}.ipa"
    ipa_path = f"IPA/{unique_ipa_name}"

    encoded_ipa = base64.b64encode(ipa_bytes).decode("utf-8")
    github_api = f"https://api.github.com/repos/{REPO}/contents/{ipa_path}"
    up = requests.put(
        github_api,
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
        json={"message": f"Upload {unique_ipa_name}", "content": encoded_ipa}
    )

    if up.status_code not in (200, 201):
        await msg.edit_text(f"❌ Upload IPA lỗi:\n{up.text[:400]}")
        return

    raw_ipa_url = f"https://{CUSTOM_DOMAIN}/{ipa_path}"

    # 🧾 Tạo .plist
    plist_random = f"manifest_{random_str(6)}.plist"
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
    plist_path = f"Plist/{plist_random}"
    plist_api = f"https://api.github.com/repos/{REPO}/contents/{plist_path}"
    requests.put(
        plist_api,
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
        json={"message": f"Add manifest {plist_random}", "content": encoded_plist}
    )

    raw_plist_url = f"https://{CUSTOM_DOMAIN}/{plist_path}"
    encoded_url = urllib.parse.quote(raw_plist_url, safe="")
    itms = f"itms-services://?action=download-manifest&url={encoded_url}"

    try:
        short = requests.get("https://is.gd/create.php", params={"format": "simple", "url": itms}).text.strip()
    except:
        short = itms

    reply = (
        f"✅ **Upload thành công!**\n\n"
        f"🧩 **Tên ứng dụng:** {app_name}\n"
        f"🆔 **Bundle ID:** `{bundle_id}`\n"
        f"🔢 **Phiên bản:** {version}\n"
        f"👥 **Team:** {team_name}\n"
        f"💾 **Dung lượng:** {round(total_size / (1024*1024),2)} MB\n\n"
        f"📦 **Tải IPA:**\n{raw_ipa_url}\n\n"
        f"📲 **Cài đặt trực tiếp:**\n{short}"
    )
    await msg.edit_text(reply, parse_mode="Markdown", disable_web_page_preview=True)

# -----------------------------
# 🔹 LỆNH CƠ BẢN
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào!\n\nGửi file `.ipa` để upload và tạo link cài đặt trực tiếp.\n\nGõ /help để xem thêm lệnh."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 **Lệnh hỗ trợ:**\n\n"
        "/listipa – Liệt kê danh sách file IPA\n"
        "/listplist – Liệt kê danh sách file Plist\n"
        "/deleteipa <tên_file.ipa> – Xoá file IPA\n"
        "/deleteplist <tên_file.plist> – Xoá file Plist\n",
        parse_mode="Markdown"
    )

# -----------------------------
# 🔹 DANH SÁCH FILE
# -----------------------------
async def list_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"https://api.github.com/repos/{REPO}/contents/IPA"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        await update.message.reply_text("⚠️ Không thể lấy danh sách IPA.")
        return
    files = [f['name'] for f in r.json() if f['name'].endswith('.ipa')]
    if not files:
        await update.message.reply_text("📭 Chưa có file IPA nào.")
    else:
        text = "📦 **Danh sách file IPA:**\n\n"
        for f in files:
            text += f"- `{f}`\n🔗 https://{CUSTOM_DOMAIN}/IPA/{f}\n\n"
        await update.message.reply_text(text, parse_mode="Markdown")

async def list_plist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"https://api.github.com/repos/{REPO}/contents/Plist"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        await update.message.reply_text("⚠️ Không thể lấy danh sách Plist.")
        return
    files = [f['name'] for f in r.json() if f['name'].endswith('.plist')]
    if not files:
        await update.message.reply_text("📭 Chưa có file Plist nào.")
    else:
        text = "🧾 **Danh sách file Plist:**\n\n"
        for f in files:
            text += f"- `{f}`\n🔗 https://{CUSTOM_DOMAIN}/Plist/{f}\n\n"
        await update.message.reply_text(text, parse_mode="Markdown")

# -----------------------------
# 🔹 XOÁ FILE
# -----------------------------
async def delete_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Dùng: `/deleteipa <tên_file.ipa>`", parse_mode="Markdown")
        return
    name = context.args[0]
    url = f"https://api.github.com/repos/{REPO}/contents/IPA/{name}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        await update.message.reply_text("⚠️ Không tìm thấy file IPA đó.")
        return
    sha = r.json()["sha"]
    d = requests.delete(url, headers=headers, json={"message": f"Delete {name}", "sha": sha})
    if d.status_code in (200, 204):
        await update.message.reply_text(f"🗑️ Đã xoá `{name}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Lỗi khi xoá.")

async def delete_plist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Dùng: `/deleteplist <tên_file.plist>`", parse_mode="Markdown")
        return
    name = context.args[0]
    url = f"https://api.github.com/repos/{REPO}/contents/Plist/{name}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        await update.message.reply_text("⚠️ Không tìm thấy file Plist đó.")
        return
    sha = r.json()["sha"]
    d = requests.delete(url, headers=headers, json={"message": f"Delete {name}", "sha": sha})
    if d.status_code in (200, 204):
        await update.message.reply_text(f"🗑️ Đã xoá `{name}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Lỗi khi xoá.")

# -----------------------------
# 🔹 KEEP BOT ALIVE
# -----------------------------
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
        except Exception as e:
            print(f"Ping lỗi: {e}")
        time.sleep(50)

# -----------------------------
# 🔹 CHẠY BOT
# -----------------------------
if __name__ == "__main__":
    print("🤖 Bot đang khởi động...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("listipa", list_ipa))
    app.add_handler(CommandHandler("listplist", list_plist))
    app.add_handler(CommandHandler("deleteipa", delete_ipa))
    app.add_handler(CommandHandler("deleteplist", delete_plist))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()

    print("🚀 Bot đang hoạt động & giữ kết nối 24/7!")
    app.run_polling()
