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
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("GITHUB_REPO")
CUSTOM_DOMAIN = "download.khoindvn.io.vn"  # 🌐 domain riêng của bạn

# ----------------------------
# 🔹 HỖ TRỢ
# ----------------------------

def random_str(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def delete_github_file(path: str):
    user, repo_name = REPO.split("/")
    api_url = f"https://api.github.com/repos/{user}/{repo_name}/contents/{path}"
    get_req = requests.get(api_url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if get_req.status_code != 200:
        return f"❌ Không tìm thấy file: `{path}`"
    sha = get_req.json()["sha"]
    del_req = requests.delete(
        api_url,
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
        json={"message": f"Delete {path}", "sha": sha},
    )
    if del_req.status_code == 200:
        return f"🗑️ Đã xoá file: `{path}`"
    else:
        return f"⚠️ Lỗi khi xoá: {del_req.text[:200]}"

# ----------------------------
# 🔹 DOWNLOAD FILE CÓ TIẾN TRÌNH %
# ----------------------------

async def download_with_progress(session, file_url, total_size, message):
    downloaded = 0
    chunks = []
    async with session.get(file_url) as resp:
        async for chunk in resp.content.iter_chunked(1024 * 1024):  # 1MB
            chunks.append(chunk)
            downloaded += len(chunk)
            percent = math.floor(downloaded / total_size * 100)
            if percent % 10 == 0:
                try:
                    await message.edit_text(f"⬆️ Đang tải từ Telegram: {percent}%")
                except:
                    pass
    return b"".join(chunks)

# ----------------------------
# 🔹 XỬ LÝ FILE IPA
# ----------------------------

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document
    if not file or not file.file_name.endswith(".ipa"):
        await update.message.reply_text("📦 Gửi file `.ipa` để bắt đầu upload.")
        return

    file_name = file.file_name
    total_size = file.file_size
    msg = await update.message.reply_text(f"📦 Đã nhận file `{file_name}`, đang tải lên...", parse_mode="Markdown")

    getfile = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": file.file_id}).json()
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{getfile['result']['file_path']}"

    async with aiohttp.ClientSession() as session:
        ipa_bytes = await download_with_progress(session, file_url, total_size, msg)

    await msg.edit_text("📤 Đang upload lên GitHub...")

    # Lấy thông tin từ IPA
    app_name = "Unknown App"
    bundle_id = "unknown.bundle"
    version = "1.0.0"
    team_name = "Unknown Team"

    try:
        with zipfile.ZipFile(io.BytesIO(ipa_bytes)) as ipa:
            plist_path = None
            for name in ipa.namelist():
                if name.endswith("Info.plist") and "Payload/" in name and name.count("/") == 2:
                    plist_path = name
                    break
            if plist_path:
                with ipa.open(plist_path) as plist_file:
                    plist_data = plistlib.load(plist_file)
                    app_name = plist_data.get("CFBundleDisplayName") or plist_data.get("CFBundleName", "Unknown App")
                    bundle_id = plist_data.get("CFBundleIdentifier", "unknown.bundle")
                    version = plist_data.get("CFBundleShortVersionString", "1.0.0")
                    team_name = plist_data.get("TeamName", "Unknown Team")
    except Exception as e:
        await msg.edit_text(f"⚠️ Không đọc được Info.plist: {e}")
        return

    # Upload IPA lên GitHub
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', app_name)
    unique_ipa_name = f"{safe_name}_{version}_{timestamp}.ipa"
    b64_ipa = base64.b64encode(ipa_bytes).decode("utf-8")

    ipa_path = f"IPA/{unique_ipa_name}"
    github_api = f"https://api.github.com/repos/{REPO}/contents/{ipa_path}"
    up = requests.put(
        github_api,
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
        json={"message": f"Upload {unique_ipa_name}", "content": b64_ipa},
    )

    if up.status_code not in (200, 201):
        await msg.edit_text(f"❌ Upload IPA lỗi:\n{up.text[:400]}")
        return

    raw_ipa_url = f"https://{CUSTOM_DOMAIN}/{ipa_path}"

    # Tạo file .plist
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

    b64_plist = base64.b64encode(plist_content.encode()).decode()
    plist_path = f"Plist/{plist_random}"
    plist_api = f"https://api.github.com/repos/{REPO}/contents/{plist_path}"
    requests.put(
        plist_api,
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
        json={"message": f"Add manifest {plist_random}", "content": b64_plist},
    )

    raw_plist_url = f"https://{CUSTOM_DOMAIN}/{plist_path}"
    encoded_url = urllib.parse.quote(raw_plist_url, safe="")
    itms = f"itms-services://?action=download-manifest&url={encoded_url}"

    try:
        short = requests.get("https://is.gd/create.php", params={"format": "simple", "url": itms}).text.strip()
    except:
        short = itms

    reply = (
        f"✅ **Upload thành công ứng dụng!**\n\n"
        f"🧩 **Tên ứng dụng:** {app_name}\n"
        f"🆔 **Bundle ID:** `{bundle_id}`\n"
        f"🔢 **Phiên bản:** {version}\n"
        f"👥 **Team:** {team_name}\n"
        f"💾 **Dung lượng:** {round(total_size / (1024*1024),2)} MB\n\n"
        f"📦 **Tải IPA:**\n{raw_ipa_url}\n\n"
        f"📲 **Cài đặt trực tiếp (rút gọn):**\n{short}"
    )
    await msg.edit_text(reply, parse_mode="Markdown", disable_web_page_preview=True)

# ----------------------------
# 🔹 LỆNH /START /HELP
# ----------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 **Xin chào!**\n\n"
        "Mình là **IPA Upload Bot** – giúp bạn upload file `.ipa` lên GitHub "
        "và tạo **link cài đặt trực tiếp iOS (itms-services)**.\n\n"
        "📦 Gửi file `.ipa` để bắt đầu.\n\n"
        "👉 Gõ `/help` để xem hướng dẫn chi tiết."
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🧭 **Hướng dẫn sử dụng**\n\n"
        "📤 Gửi file .ipa: Bot tự upload & tạo link cài đặt.\n\n"
        "💡 Lệnh:\n"
        "`/listipa` – Liệt kê file IPA\n"
        "`/listplist` – Liệt kê file Plist\n"
        "`/deleteipa <tên_file>` – Xoá IPA\n"
        "`/deleteplist <tên_file>` – Xoá Plist\n\n"
        "🌐 Trang tải: https://download.khoindvn.io.vn\n"
        "👨‍💻 Developer: Khoindvn"
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)

# ----------------------------
# 🔹 KHỞI CHẠY BOT
# ----------------------------

if __name__ == "__main__":
    print("🤖 Bot đang chạy...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.run_polling()
