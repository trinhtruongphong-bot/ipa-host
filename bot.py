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
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("GITHUB_REPO")

CUSTOM_DOMAIN = "download.khoindvn.io.vn"  # 🌐 Domain riêng của bạn

# ----------------------------
# 🔹 HÀM HỖ TRỢ
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
# 🔹 XỬ LÝ FILE IPA
# ----------------------------

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg.document or not msg.document.file_name.endswith(".ipa"):
        await msg.reply_text("📦 Gửi cho mình file `.ipa` (ứng dụng iOS).")
        return

    file = msg.document
    getfile = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": file.file_id}).json()
    if not getfile.get("ok"):
        await msg.reply_text("⚠️ Không lấy được file_path từ Telegram.")
        return

    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{getfile['result']['file_path']}"
    ipa_bytes = requests.get(file_url).content
    file_size_mb = round(len(ipa_bytes) / (1024 * 1024), 2)

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
        await msg.reply_text(f"⚠️ Không đọc được Info.plist trong IPA: {e}")
        return

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', app_name)
    unique_ipa_name = f"{safe_name}_{version}_{timestamp}.ipa"

    # Upload IPA vào thư mục IPA/
    b64_ipa = base64.b64encode(ipa_bytes).decode("utf-8")
    ipa_path = f"IPA/{unique_ipa_name}"
    github_api = f"https://api.github.com/repos/{REPO}/contents/{ipa_path}"
    up = requests.put(
        github_api,
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
        json={"message": f"Upload {unique_ipa_name}", "content": b64_ipa},
    )
    if up.status_code not in (200, 201):
        await msg.reply_text(f"❌ Upload IPA lỗi:\n{up.text[:400]}")
        return

    # Link IPA qua domain riêng
    raw_ipa_url = f"https://{CUSTOM_DOMAIN}/{ipa_path}"

    # Tạo .plist
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
        f"💾 **Dung lượng:** {file_size_mb} MB\n\n"
        f"📦 **Tải IPA:**\n{raw_ipa_url}\n\n"
        f"📲 **Cài đặt trực tiếp (rút gọn):**\n{short}"
    )
    await msg.reply_text(reply, parse_mode="Markdown", disable_web_page_preview=True)

# ----------------------------
# 🔹 LỆNH /START & /HELP
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
        "📤 **Gửi file .ipa:** Bot sẽ tự upload & tạo link cài đặt.\n\n"
        "💡 **Các lệnh:**\n"
        "`/listipa` – Danh sách file IPA\n"
        "`/listplist` – Danh sách file manifest (.plist)\n"
        "`/deleteipa <tên_file>` – Xoá file IPA\n"
        "`/deleteplist <tên_file>` – Xoá file Plist\n"
        "`/getlink <tên_file>` – Tạo lại link cài đặt từ IPA cũ\n\n"
        "🌐 **Trang tải:** https://download.khoindvn.io.vn\n"
        "👨‍💻 Developer: Khoindvn"
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)

# ----------------------------
# 🔹 KHỞI ĐỘNG BOT
# ----------------------------

if __name__ == "__main__":
    print("🤖 Bot đang chạy...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(CommandHandler("deleteipa", delete_github_file))
    app.add_handler(CommandHandler("deleteplist", delete_github_file))
    app.run_polling()
