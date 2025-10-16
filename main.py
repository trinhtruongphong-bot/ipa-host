import telebot, requests, base64, zipfile, plistlib, re, os, random, string, threading, time, html
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")

WEBHOOK_URL = "https://developed-hyena-trinhtruongphong-abb0500e.koyeb.app/"

bot = telebot.TeleBot(BOT_TOKEN)

# ========== GỬI TIN DÀI ==========
def send_long_message(chat_id, text, parse_mode="HTML"):
    max_len = 4000
    for i in range(0, len(text), max_len):
        bot.send_message(chat_id, text[i:i+max_len], parse_mode=parse_mode, disable_web_page_preview=True)

# ========== UPLOAD CHUẨN BASE64 ==========
def upload_with_progress(chat_id, file_path, repo_path, message):
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{repo_path}"
    msg = bot.send_message(chat_id, f"📤 Đang upload <b>{os.path.basename(file_path)}</b>... 0%", parse_mode="HTML")

    with open(file_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("utf-8")

    for p in range(0, 101, 25):
        try:
            bot.edit_message_text(f"📤 Đang upload <b>{os.path.basename(file_path)}</b>... {p}%", chat_id, msg.message_id, parse_mode="HTML")
        except:
            pass
        time.sleep(0.2)

    data = {"message": message, "content": content_b64}
    r = requests.put(url, headers=headers, json=data)
    if r.status_code not in [200, 201]:
        raise Exception(r.text)

    bot.edit_message_text(f"✅ Upload <b>{os.path.basename(file_path)}</b> hoàn tất!", chat_id, msg.message_id, parse_mode="HTML")
    return r.json()["content"]["path"]

# ========== PHÂN TÍCH IPA ==========
def parse_ipa(file_path):
    info = {"app_name": "Unknown", "bundle_id": "Unknown", "version": "Unknown", "team_name": "Unknown", "team_id": "Unknown"}
    with zipfile.ZipFile(file_path, 'r') as z:
        plist_file = [f for f in z.namelist() if f.endswith("Info.plist") and "Payload/" in f]
        if plist_file:
            with z.open(plist_file[0]) as f:
                p = plistlib.load(f)
                info["app_name"] = p.get("CFBundleDisplayName") or p.get("CFBundleName")
                info["bundle_id"] = p.get("CFBundleIdentifier")
                info["version"] = p.get("CFBundleShortVersionString")
        prov = [f for f in z.namelist() if f.endswith("embedded.mobileprovision")]
        if prov:
            c = z.read(prov[0]).decode("utf-8", errors="ignore")
            n = re.search(r"<key>TeamName</key>\s*<string>(.*?)</string>", c)
            i = re.search(r"<key>TeamIdentifier</key>\s*<array>\s*<string>(.*?)</string>", c)
            info["team_name"] = n.group(1) if n else "Unknown"
            info["team_id"] = i.group(1) if i else "Unknown"
    return info

# ========== TẠO PLIST ==========
def generate_plist(ipa_url, info):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" 
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict>
<key>assets</key><array><dict><key>kind</key><string>software-package</string>
<key>url</key><string>{ipa_url}</string></dict></array>
<key>metadata</key><dict><key>bundle-identifier</key><string>{info['bundle_id']}</string>
<key>bundle-version</key><string>{info['version']}</string>
<key>kind</key><string>software</string><key>title</key><string>{info['app_name']}</string>
</dict></dict></array></dict></plist>"""

# ========== RÚT GỌN LINK ==========
def shorten(url):
    try:
        return requests.get("https://is.gd/create.php", params={"format": "simple", "url": url}).text.strip()
    except:
        return url

# ========== XỬ LÝ FILE IPA ==========
def process_ipa(message, file_id, file_name):
    chat_id = message.chat.id
    processing = bot.send_message(chat_id, f"📦 Đang xử lý <b>{file_name}</b>...", parse_mode="HTML")
    local = f"/tmp/{file_name}"

    try:
        info = bot.get_file(file_id)
        file = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info.file_path}")
        with open(local, "wb") as f:
            f.write(file.content)

        new_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
        ipa_name, plist_name = f"{new_id}.ipa", f"{new_id}.plist"

        meta = parse_ipa(local)

        upload_with_progress(chat_id, local, f"iPA/{ipa_name}", f"Upload {ipa_name}")
        ipa_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/iPA/{ipa_name}"

        plist_data = generate_plist(ipa_url, meta)
        plist_path = f"/tmp/{plist_name}"
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(plist_data)
        upload_with_progress(chat_id, plist_path, f"Plist/{plist_name}", f"Upload {plist_name}")

        plist_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/Plist/{plist_name}"
        short = shorten(f"itms-services://?action=download-manifest&url={plist_url}")

        # Escape URL để không lỗi <a>
        ipa_url_safe = html.escape(ipa_url)
        short_safe = html.escape(short)

        msg = (
            f"✅ <b>Upload hoàn tất!</b>\n\n"
            f"📱 Ứng dụng: <b>{meta['app_name']}</b>\n"
            f"🆔 Bundle: <code>{meta['bundle_id']}</code>\n"
            f"🔢 Phiên bản: <b>{meta['version']}</b>\n"
            f"👥 Team: <b>{meta['team_name']}</b> ({meta['team_id']})\n\n"
            f"📦 <a href='{ipa_url_safe}'>Tải IPA</a>\n"
            f"📲 <a href='{short_safe}'>Cài trực tiếp</a>"
        )
        send_long_message(chat_id, msg)

    except Exception as e:
        err_text = str(e)
        if len(err_text) > 1000:
            err_text = err_text[:1000] + "... (rút gọn)"
        bot.send_message(chat_id, f"❌ <b>Lỗi:</b> <code>{html.escape(err_text)}</code>", parse_mode="HTML")

    finally:
        try:
            bot.delete_message(chat_id, processing.message_id)
        except:
            pass
        if os.path.exists(local):
            os.remove(local)

# ========== DANH SÁCH + XOÁ FILE ==========
@bot.message_handler(commands=["listipa", "listplist"])
def list_files(m):
    folder = "iPA" if m.text == "/listipa" else "Plist"
    r = requests.get(f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{folder}",
                     headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if r.status_code != 200:
        return bot.reply_to(m, "❌ Không thể lấy danh sách.")
    files = [f for f in r.json() if f["name"].endswith(".ipa") or f["name"].endswith(".plist")]
    if not files:
        return bot.reply_to(m, f"📭 Thư mục {folder} trống.")
    kb = telebot.types.InlineKeyboardMarkup()
    for f in files:
        kb.add(telebot.types.InlineKeyboardButton(f"🗑 Xoá {f['name']}", callback_data=f"del:{folder}:{f['name']}:{f['sha']}"))
    bot.send_message(m.chat.id, f"📂 Danh sách file trong <b>{folder}</b>:", parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del:"))
def del_file(c):
    _, folder, name, sha = c.data.split(":")
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{folder}/{name}"
    r = requests.delete(url, headers={"Authorization": f"token {GITHUB_TOKEN}"},
                        json={"message": f"Delete {name}", "sha": sha})
    if r.status_code == 200:
        bot.edit_message_text(f"✅ Đã xoá <b>{html.escape(name)}</b> khỏi <b>{folder}</b>.", c.message.chat.id, c.message.message_id, parse_mode="HTML")
    else:
        bot.edit_message_text(f"❌ Lỗi khi xoá <b>{html.escape(name)}</b>.", c.message.chat.id, c.message.message_id, parse_mode="HTML")

# ========== LỆNH CƠ BẢN ==========
@bot.message_handler(content_types=["document"])
def handle_file(m):
    threading.Thread(target=process_ipa, args=(m, m.document.file_id, m.document.file_name)).start()

@bot.message_handler(commands=["start", "help"])
def help_msg(m):
    bot.reply_to(m, "👋 Gửi file .ipa để upload.\n/listipa - Danh sách IPA\n/listplist - Danh sách Plist", parse_mode="HTML")

# ========== FLASK WEBHOOK ==========
app = Flask(__name__)

@app.route('/', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.data.decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

@app.route('/')
def home():
    return "Bot webhook running."

bot.remove_webhook()
time.sleep(1)
bot.set_webhook(url=WEBHOOK_URL)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
