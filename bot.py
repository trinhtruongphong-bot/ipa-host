import os
import time
import base64
import random
import string
import requests
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIG ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_USER = os.getenv("GITHUB_USER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DOMAIN = os.getenv("DOMAIN", "https://download.khoindvn.io.vn")

IPA_PATH = "IPA"
PLIST_PATH = "Plist"

# ========== HELPER ==========
def random_name(length=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def clean_name(name):
    return ''.join(c for c in name if c.isalnum())

def github_upload(path, content, message="upload file"):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"message": message, "content": base64.b64encode(content).decode('utf-8')}
    r = requests.put(url, headers=headers, json=data)
    return r.status_code in [200, 201]

def github_list(path):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return [f["name"] for f in r.json()]
    return []

def github_delete(path):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return False
    sha = r.json()["sha"]
    data = {"message": f"delete {path}", "sha": sha}
    return requests.delete(url, headers=headers, json=data).status_code == 200

def extract_info_plist(ipa_bytes):
    """Đọc Info.plist từ file IPA (chuẩn Apple)"""
    try:
        with zipfile.ZipFile(BytesIO(ipa_bytes)) as z:
            for name in z.namelist():
                if "Info.plist" in name and "Payload" in name:
                    plist_data = z.read(name)
                    root = ET.fromstring(plist_data)
                    info = {}
                    for i, node in enumerate(root):
                        if node.tag == "key" and i + 1 < len(root):
                            key = node.text
                            value_node = root[i + 1]
                            if value_node.tag in ["string", "integer"]:
                                info[key] = value_node.text
                    return {
                        "name": info.get("CFBundleDisplayName") or info.get("CFBundleName", "Unknown"),
                        "bundle": info.get("CFBundleIdentifier", "Unknown"),
                        "version": info.get("CFBundleShortVersionString", "1.0")
                    }
    except Exception as e:
        print("Lỗi đọc plist:", e)
    return {"name": "Unknown", "bundle": "Unknown", "version": "1.0"}

def check_link(url, timeout=90):
    for i in range(timeout):
        try:
            if requests.head(url).status_code == 200:
                return True
        except:
            pass
        time.sleep(2)
    return False

# ========== COMMANDS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào!\n"
        "Mình là IPA Upload Bot – giúp bạn upload file .ipa lên GitHub và tạo link cài đặt trực tiếp iOS.\n"
        "Gửi file .ipa để bắt đầu.\n"
        "Gõ /help để xem hướng dẫn chi tiết."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧭 Hướng dẫn sử dụng:\n"
        "• Gửi file .ipa để upload & tạo link cài đặt.\n\n"
        "📜 Lệnh:\n"
        "/listipa – Danh sách file IPA\n"
        "/listplist – Danh sách file manifest (plist)\n"
        "/deleteipa <tên_file> – Xoá file IPA\n"
        "/deleteplist <tên_file> – Xoá file Plist\n"
        "/help – Xem hướng dẫn\n"
        "/start – Khởi động lại bot"
    )

async def list_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = github_list(IPA_PATH)
    if not files:
        await update.message.reply_text("📂 Không có file IPA nào.")
    else:
        msg = "\n".join(f"- {f}" for f in files)
        await update.message.reply_text(f"📦 Danh sách IPA:\n{msg}")

async def list_plist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = github_list(PLIST_PATH)
    if not files:
        await update.message.reply_text("📂 Không có file Plist nào.")
    else:
        msg = "\n".join(f"- {f}" for f in files)
        await update.message.reply_text(f"📜 Danh sách Plist:\n{msg}")

async def delete_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("⚠️ Dùng: /deleteipa <tên_file>")
        return
    name = context.args[0]
    ok = github_delete(f"{IPA_PATH}/{name}")
    await update.message.reply_text("🗑️ Xoá thành công!" if ok else "❌ Không tìm thấy file IPA.")

async def delete_plist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("⚠️ Dùng: /deleteplist <tên_file>")
        return
    name = context.args[0]
    ok = github_delete(f"{PLIST_PATH}/{name}")
    await update.message.reply_text("🗑️ Xoá thành công!" if ok else "❌ Không tìm thấy file plist.")

# ========== UPLOAD ==========
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(".ipa"):
        await update.message.reply_text("⚠️ Vui lòng gửi file .ipa hợp lệ!")
        return

    await update.message.reply_text("⏳ Đang upload lên GitHub...")

    file = await doc.get_file()
    ipa_bytes = await file.download_as_bytearray()
    info = extract_info_plist(ipa_bytes)

    rand = random_name()
    ipa_filename = f"{rand}.ipa"
    plist_filename = f"{rand}.plist"

    github_upload(f"{IPA_PATH}/{ipa_filename}", ipa_bytes)

    ipa_url = f"{DOMAIN}/{IPA_PATH}/{ipa_filename}"
    plist_url = f"{DOMAIN}/{PLIST_PATH}/{plist_filename}"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict><key>assets</key><array>
<dict><key>kind</key><string>software-package</string><key>url</key><string>{ipa_url}</string></dict>
</array><key>metadata</key><dict><key>bundle-identifier</key><string>{info['bundle']}</string>
<key>bundle-version</key><string>{info['version']}</string><key>kind</key><string>software</string>
<key>title</key><string>{info['name']}</string></dict></dict></array></dict></plist>"""

    github_upload(f"{PLIST_PATH}/{plist_filename}", plist_content.encode())

    if not check_link(ipa_url):
        await update.message.reply_text("⚠️ File chưa sẵn sàng, vui lòng chờ vài giây rồi thử lại.")
        return

    install_link = f"itms-services://?action=download-manifest&url={plist_url}"
    await update.message.reply_text(
        f"✅ Upload thành công!\n"
        f"📱 Ứng dụng: {info['name']}\n"
        f"🆔 Bundle ID: {info['bundle']}\n"
        f"📦 Phiên bản: {info['version']}\n"
        f"🔗 Tải IPA: {ipa_url}\n"
        f"📲 Cài đặt trực tiếp: {install_link}"
    )

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
    app.add_handler(CommandHandler("deleteipa", delete_ipa))
    app.add_handler(CommandHandler("deleteplist", delete_plist))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    threading.Thread(target=keep_alive, daemon=True).start()
    print("🚀 Bot đang chạy...")
    app.run_polling()
