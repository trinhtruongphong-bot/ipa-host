import telebot
import requests
import base64
import zipfile
import plistlib
import re
import os
import random
import string
import threading
import time

# ========== CONFIG ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")

bot = telebot.TeleBot(BOT_TOKEN)

# ========== GITHUB UPLOAD ==========
def upload_to_github(path, content, message):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    # Kiểm tra nếu file tồn tại (để lấy SHA xoá/update)
    get_resp = requests.get(url, headers=headers)
    sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

    data = {"message": message, "content": content}
    if sha:
        data["sha"] = sha

    r = requests.put(url, headers=headers, json=data)
    if r.status_code not in [200, 201]:
        raise Exception(f"❌ Upload thất bại: {r.text}")
    return r.json()["content"]["path"]

# ========== PHÂN TÍCH IPA ==========
def parse_ipa(file_path):
    info = {"app_name": "Unknown", "bundle_id": "Unknown", "version": "Unknown", "team_name": "Unknown", "team_id": "Unknown"}
    with zipfile.ZipFile(file_path, 'r') as z:
        plist_file = [f for f in z.namelist() if f.endswith("Info.plist") and "Payload/" in f]
        if plist_file:
            with z.open(plist_file[0]) as f:
                plist_data = plistlib.load(f)
                info["app_name"] = plist_data.get("CFBundleDisplayName") or plist_data.get("CFBundleName")
                info["bundle_id"] = plist_data.get("CFBundleIdentifier")
                info["version"] = plist_data.get("CFBundleShortVersionString")

        prov_file = [f for f in z.namelist() if f.endswith("embedded.mobileprovision")]
        if prov_file:
            content = z.read(prov_file[0]).decode("utf-8", errors="ignore")
            team_name = re.search(r"<key>TeamName</key>\s*<string>(.*?)</string>", content)
            team_id = re.search(r"<key>TeamIdentifier</key>\s*<array>\s*<string>(.*?)</string>", content)
            info["team_name"] = team_name.group(1) if team_name else "Unknown"
            info["team_id"] = team_id.group(1) if team_id else "Unknown"
    return info

# ========== TẠO FILE PLIST ==========
def generate_plist(ipa_url, info):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" 
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>items</key>
  <array>
    <dict>
      <key>assets</key>
      <array>
        <dict>
          <key>kind</key><string>software-package</string>
          <key>url</key><string>{ipa_url}</string>
        </dict>
      </array>
      <key>metadata</key>
      <dict>
        <key>bundle-identifier</key><string>{info['bundle_id']}</string>
        <key>bundle-version</key><string>{info['version']}</string>
        <key>kind</key><string>software</string>
        <key>title</key><string>{info['app_name']}</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>"""

# ========== RÚT GỌN LINK ==========
def shorten_url(url):
    try:
        r = requests.get("https://is.gd/create.php", params={"format": "simple", "url": url})
        return r.text.strip()
    except Exception:
        return url

# ========== XỬ LÝ IPA ==========
def process_ipa(message, file_id, file_name):
    chat_id = message.chat.id
    processing_msg = bot.send_message(chat_id, f"📦 Đang xử lý {file_name}...")
    try:
        # Download file
        file_info = bot.get_file(file_id)
        file_data = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}")
        local_path = f"/tmp/{file_name}"
        with open(local_path, "wb") as f:
            f.write(file_data.content)

        # Random tên file
        new_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
        ipa_name = f"{new_id}.ipa"

        # Phân tích
        info = parse_ipa(local_path)

        # Upload IPA
        ipa_b64 = base64.b64encode(open(local_path, "rb").read()).decode("utf-8")
        upload_to_github(f"iPA/{ipa_name}", ipa_b64, f"Upload {ipa_name}")

        ipa_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/iPA/{ipa_name}"

        # Tạo PLIST
        plist_content = generate_plist(ipa_url, info)
        plist_b64 = base64.b64encode(plist_content.encode()).decode("utf-8")
        plist_name = f"{new_id}.plist"
        upload_to_github(f"Plist/{plist_name}", plist_b64, f"Upload {plist_name}")

        plist_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/Plist/{plist_name}"
        install_link = f"itms-services://?action=download-manifest&url={plist_url}"
        short_link = shorten_url(install_link)

        # Gửi kết quả
        result = (
            f"✅ Upload hoàn tất!\n\n"
            f"📱 App: {info['app_name']}\n"
            f"🆔 Bundle: {info['bundle_id']}\n"
            f"🔢 Phiên bản: {info['version']}\n"
            f"👥 Team: {info['team_name']} ({info['team_id']})\n\n"
            f"📦 Tải IPA: {ipa_url}\n"
            f"📲 [Cài trực tiếp]({short_link})"
        )
        bot.send_message(chat_id, result, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Lỗi: {e}")
    finally:
        # Xoá tin nhắn tạm
        try:
            time.sleep(1)
            bot.delete_message(chat_id, processing_msg.message_id)
        except:
            pass
        if os.path.exists(local_path):
            os.remove(local_path)

# ========== HANDLERS ==========
@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    bot.reply_to(message, (
        "👋 Xin chào!\n"
        "Gửi file .ipa để upload lên GitHub.\n\n"
        "Lệnh hỗ trợ:\n"
        "/listipa – Liệt kê file IPA\n"
        "/listplist – Liệt kê file PLIST"
    ))

@bot.message_handler(commands=["listipa", "listplist"])
def list_files(message):
    folder = "iPA" if message.text == "/listipa" else "Plist"
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{folder}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        bot.reply_to(message, "❌ Không thể lấy danh sách file.")
        return

    files = [f["name"] for f in r.json() if f["name"].endswith(".ipa") or f["name"].endswith(".plist")]
    if not files:
        bot.reply_to(message, f"📭 Thư mục {folder} trống.")
        return

    msg = f"📂 Danh sách file trong `{folder}`:\n\n" + "\n".join(f"• {f}" for f in files)
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(content_types=["document"])
def handle_document(message):
    file_name = message.document.file_name
    file_id = message.document.file_id
    threading.Thread(target=process_ipa, args=(message, file_id, file_name)).start()

# ========== CHẠY BOT ==========
bot.infinity_polling()
