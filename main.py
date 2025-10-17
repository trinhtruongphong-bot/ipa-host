import telebot, requests, os, base64, zipfile, plistlib, random, string, tempfile
from flask import Flask, request

# --- Cấu hình ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
DOMAIN = "https://download.khoindvn.io.vn"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Hàm rút gọn link TinyURL ---
def shorten(url):
    """Rút gọn link qua TinyURL (ổn định & vĩnh viễn)"""
    try:
        api_url = "https://api.tinyurl.com/create"
        headers = {"Content-Type": "application/json"}
        payload = {"url": url}
        res = requests.post(api_url, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if "data" in data and "tiny_url" in data["data"]:
                return data["data"]["tiny_url"]
            elif "tiny_url" in data:
                return data["tiny_url"]
        print(f"⚠️ TinyURL API trả về không hợp lệ: {res.text[:200]}")
        return url
    except Exception as e:
        print(f"❌ Lỗi shorten() TinyURL: {e}")
        return url

# --- Sinh chuỗi ngẫu nhiên ---
def random_string(length=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# --- Upload file lên GitHub ---
def upload_to_github(path, content, message):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    data = {"message": message, "content": base64.b64encode(content).decode("utf-8")}
    res = requests.put(url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, json=data)
    if res.status_code in [200, 201]:
        return True
    print("❌ Lỗi upload GitHub:", res.text)
    return False

# --- Lấy thông tin từ Info.plist ---
def extract_ipa_info(ipa_path):
    try:
        with zipfile.ZipFile(ipa_path, 'r') as z:
            app_folder = [f for f in z.namelist() if f.endswith(".app/")][0]
            plist_path = app_folder + "Info.plist"
            with z.open(plist_path) as f:
                plist_data = plistlib.load(f)
                name = plist_data.get("CFBundleDisplayName") or plist_data.get("CFBundleName", "Unknown")
                bundle = plist_data.get("CFBundleIdentifier", "Unknown")
                version = plist_data.get("CFBundleShortVersionString", "Unknown")
        return name, bundle, version
    except Exception as e:
        print("❌ Lỗi đọc Info.plist:", e)
        return "Unknown", "Unknown", "Unknown"

# --- Lấy Team Name từ embedded.mobileprovision ---
def extract_team_info(ipa_path):
    try:
        with zipfile.ZipFile(ipa_path, 'r') as z:
            prov_path = [f for f in z.namelist() if f.endswith(".mobileprovision")][0]
            with z.open(prov_path) as f:
                content = f.read().decode(errors="ignore")
                team_name = content.split("<key>TeamName</key>")[1].split("<string>")[1].split("</string>")[0]
                team_id = content.split("<key>TeamIdentifier</key>")[1].split("<array>")[1].split("<string>")[1].split("</string>")[0]
                return team_name, team_id
    except:
        pass
    return "Unknown", "Unknown"

# --- Tạo file .plist ---
def create_manifest_plist(ipa_url, bundle, version, name):
    template = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict>
<key>assets</key><array><dict><key>kind</key><string>software-package</string>
<key>url</key><string>{ipa_url}</string></dict></array>
<key>metadata</key><dict><key>bundle-identifier</key><string>{bundle}</string>
<key>bundle-version</key><string>{version}</string><key>kind</key><string>software</string>
<key>title</key><string>{name}</string></dict></dict></array></dict></plist>"""
    return template.encode("utf-8")

# --- Xử lý khi người dùng gửi file IPA ---
@bot.message_handler(content_types=['document'])
def handle_file(message):
    file_info = bot.get_file(message.document.file_id)
    file_name = message.document.file_name
    if not file_name.endswith(".ipa"):
        return bot.reply_to(message, "❌ Vui lòng gửi đúng file .ipa")

    processing_msg = bot.reply_to(message, "🔄 Đang xử lý, vui lòng chờ...")
    file_path = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

    r = requests.get(file_path)
    if r.status_code != 200:
        return bot.reply_to(message, "❌ Không tải được file từ Telegram.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ipa") as tmp:
        tmp.write(r.content)
        tmp_path = tmp.name

    name, bundle, version = extract_ipa_info(tmp_path)
    team_name, team_id = extract_team_info(tmp_path)

    rand = random_string()
    ipa_filename = f"iPA/{rand}.ipa"
    plist_filename = f"Plist/{rand}.plist"

    # Upload IPA
    with open(tmp_path, "rb") as f:
        ipa_content = f.read()
    upload_to_github(ipa_filename, ipa_content, f"Upload {file_name}")

    ipa_url = f"{DOMAIN}/iPA/{rand}.ipa"
    plist_content = create_manifest_plist(ipa_url, bundle, version, name)
    upload_to_github(plist_filename, plist_content, f"Tạo plist {file_name}")

    plist_url = f"{DOMAIN}/Plist/{rand}.plist"
    install_link = f"itms-services://?action=download-manifest&url={plist_url}"
    short_install_link = shorten(install_link)

    bot.delete_message(message.chat.id, processing_msg.id)
    bot.send_message(
        message.chat.id,
        f"✅ Upload hoàn tất!\n\n"
        f"📱 Ứng dụng: {name}\n"
        f"🆔 Bundle: {bundle}\n"
        f"🔢 Phiên bản: {version}\n"
        f"👥 Team: {team_name} ({team_id})\n\n"
        f"📦 Tải IPA:\n{ipa_url}\n\n"
        f"📲 Cài trực tiếp:\n{short_install_link}"
    )

# --- Lệnh /start ---
@bot.message_handler(commands=['start', 'help'])
def start(message):
    bot.reply_to(message,
                 "👋 Gửi file .ipa để upload và tạo link cài đặt iOS tự động.\n\n"
                 "Bot hỗ trợ:\n"
                 "• Upload IPA → GitHub\n"
                 "• Tạo file .plist\n"
                 "• Đọc Info.plist (App name, Bundle, Version)\n"
                 "• Rút gọn link TinyURL\n"
                 "• Hiển thị Team Name")

# --- Flask webhook ---
@app.route('/')
def home():
    return "Bot đang chạy ngon 🔥"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "ok", 200

if __name__ == "__main__":
    if os.getenv("USE_WEBHOOK", "True") == "True":
        app.run(host="0.0.0.0", port=8000)
    else:
        bot.infinity_polling()
