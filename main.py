import os, io, zipfile, plistlib, tempfile, subprocess, re, requests, base64, random, string, threading
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== UTILS ==========

def random_string(n=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def shorten(url):
    """Rút gọn link (hỗ trợ itms-services://)"""
    try:
        encoded = requests.utils.quote(url, safe="")
        r = requests.get(f"https://is.gd/create.php?format=simple&url={encoded}", timeout=10)
        if r.status_code == 200 and r.text.startswith("http"):
            return r.text.strip()
    except Exception as e:
        print("Shorten error:", e)
    return url

def github_upload(path, content, message):
    """Upload file lên GitHub"""
    api = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    res = requests.get(api, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    sha = res.json().get("sha") if res.status_code == 200 else None
    payload = {
        "message": message,
        "content": base64.b64encode(content).decode("utf-8")
    }
    if sha:
        payload["sha"] = sha
    up = requests.put(api, headers={"Authorization": f"token {GITHUB_TOKEN}"}, json=payload)
    if up.status_code not in [200, 201]:
        raise Exception(up.text)
    return True

# ========== IPA PARSER ==========

def parse_ipa(file_path):
    info = {"app_name": None, "bundle_id": None, "version": None, "team_name": None, "team_id": None, "error": None}

    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            plist_files = [f for f in z.namelist() if f.startswith("Payload/") and f.endswith(".app/Info.plist")]
            if not plist_files:
                info["error"] = "Không tìm thấy Info.plist"
                return info

            plist_path = plist_files[0]
            data = z.read(plist_path)

            # --- Đọc Info.plist XML/Binary ---
            try:
                plist = plistlib.loads(data)
            except Exception:
                try:
                    from biplist import readPlistFromString
                    plist = readPlistFromString(data)
                except Exception:
                    with tempfile.NamedTemporaryFile(delete=False) as tmp:
                        tmp.write(data)
                        tmp.flush()
                        xml_path = tmp.name + ".xml"
                        try:
                            subprocess.run(["plutil", "-convert", "xml1", tmp.name, "-o", xml_path], timeout=5)
                            with open(xml_path, "rb") as xf:
                                plist = plistlib.load(xf)
                        except:
                            info["error"] = "Không đọc được Info.plist"
                            return info
                        finally:
                            os.remove(tmp.name)
                            if os.path.exists(xml_path): os.remove(xml_path)

            info["app_name"] = plist.get("CFBundleDisplayName") or plist.get("CFBundleName")
            info["bundle_id"] = plist.get("CFBundleIdentifier")
            info["version"] = plist.get("CFBundleShortVersionString")

            # --- Đọc TeamName + TeamID ---
            emb = [f for f in z.namelist() if f.endswith(".app/embedded.mobileprovision")]
            if emb:
                data = z.read(emb[0]).decode("utf-8", errors="ignore")
                m = re.search(r"<plist.*?</plist>", data, re.DOTALL)
                if m:
                    try:
                        plist_emb = plistlib.loads(m.group(0).encode("utf-8"))
                        info["team_name"] = plist_emb.get("TeamName")
                        team_ids = plist_emb.get("TeamIdentifier")
                        if isinstance(team_ids, list) and len(team_ids) > 0:
                            info["team_id"] = team_ids[0]
                    except:
                        pass
    except Exception as e:
        info["error"] = str(e)
    return info

# ========== IPA PROCESSING ==========

def process_ipa(message, file_info):
    try:
        chat_id = message.chat.id
        processing_msg = bot.reply_to(message, "⏳ Đang xử lý file IPA...")

        file = bot.download_file(bot.get_file(file_info.file_id).file_path)
        tmp_path = f"/tmp/{random_string()}.ipa"
        with open(tmp_path, "wb") as f:
            f.write(file)

        meta = parse_ipa(tmp_path)
        rand = random_string()
        ipa_name = f"{rand}.ipa"
        plist_name = f"{rand}.plist"

        ipa_path = f"iPA/{ipa_name}"
        plist_path = f"Plist/{plist_name}"

        ipa_url = f"https://download.khoindvn.io.vn/iPA/{ipa_name}"
        plist_url = f"https://download.khoindvn.io.vn/Plist/{plist_name}"

        # --- Upload IPA ---
        github_upload(ipa_path, open(tmp_path, "rb").read(), f"Upload {ipa_name}")

        # --- Tạo plist ---
        template = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>items</key>
    <array>
        <dict>
            <key>assets</key>
            <array>
                <dict>
                    <key>kind</key>
                    <string>software-package</string>
                    <key>url</key>
                    <string>{ipa_url}</string>
                </dict>
            </array>
            <key>metadata</key>
            <dict>
                <key>bundle-identifier</key>
                <string>{meta.get('bundle_id') or ''}</string>
                <key>bundle-version</key>
                <string>{meta.get('version') or ''}</string>
                <key>kind</key>
                <string>software</string>
                <key>title</key>
                <string>{meta.get('app_name') or ''}</string>
            </dict>
        </dict>
    </array>
</dict>
</plist>"""

        github_upload(plist_path, template.encode("utf-8"), f"Tạo {plist_name}")

        # --- Link cài đặt ---
        install_link = f"itms-services://?action=download-manifest&url={plist_url}"
        short = shorten(install_link)

        msg = (
            f"✅ <b>Upload hoàn tất!</b>\n\n"
            f"📱 Ứng dụng: <b>{meta.get('app_name') or 'Unknown'}</b>\n"
            f"🆔 Bundle: <code>{meta.get('bundle_id') or 'Unknown'}</code>\n"
            f"🔢 Phiên bản: <b>{meta.get('version') or 'Unknown'}</b>\n"
            f"👥 Team: <b>{meta.get('team_name') or 'Unknown'}</b> (<code>{meta.get('team_id') or 'Unknown'}</code>)\n\n"
            f"📦 <b>Tải IPA:</b>\n{ipa_url}\n\n"
            f"📲 <b>Cài trực tiếp:</b>\n{short}"
        )

        bot.delete_message(chat_id, processing_msg.message_id)
        bot.send_message(chat_id, msg, parse_mode="HTML")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Lỗi xử lý IPA: {e}")

# ========== COMMANDS ==========

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message,
        "👋 Gửi file .ipa để bot tự động upload, tạo link cài đặt iOS và rút gọn link.\n\n"
        "Các lệnh:\n"
        "/listipa – Liệt kê file IPA\n"
        "/listplist – Liệt kê file PLIST\n")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    file_info = message.document
    if file_info.file_name.endswith(".ipa"):
        threading.Thread(target=process_ipa, args=(message, file_info)).start()
    else:
        bot.reply_to(message, "❌ Vui lòng gửi đúng định dạng .ipa")

# ========== FLASK WEBHOOK ==========

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def webhook():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "OK", 200

@app.route('/')
def home():
    return "Bot đang chạy ngon 🍀"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
