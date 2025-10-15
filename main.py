import telebot, requests, base64, zipfile, plistlib, re, os, random, string, threading, time
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
bot = telebot.TeleBot(BOT_TOKEN)

# ========== UPLOAD VỚI % TIẾN TRÌNH ==========
def upload_with_progress(chat_id, file_path, repo_path, message):
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{repo_path}"
    file_size = os.path.getsize(file_path)
    uploaded = 0
    content_b64 = ""
    msg = bot.send_message(chat_id, f"📤 Đang upload {os.path.basename(file_path)}... 0%")
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(200_000)
            if not chunk:
                break
            content_b64 += base64.b64encode(chunk).decode("utf-8")
            uploaded += len(chunk)
            percent = int(uploaded / file_size * 100)
            try: bot.edit_message_text(f"📤 Đang upload {os.path.basename(file_path)}... {percent}%", chat_id, msg.message_id)
            except: pass
    data = {"message": message, "content": content_b64}
    r = requests.put(url, headers=headers, json=data)
    if r.status_code not in [200, 201]: raise Exception(r.text)
    bot.edit_message_text(f"✅ Upload {os.path.basename(file_path)} hoàn tất!", chat_id, msg.message_id)
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
    try: return requests.get("https://is.gd/create.php", params={"format": "simple", "url": url}).text.strip()
    except: return url

# ========== UPLOAD IPA ==========
def process_ipa(message, file_id, file_name):
    chat_id = message.chat.id
    processing = bot.send_message(chat_id, f"📦 Đang xử lý {file_name}...")
    try:
        info = bot.get_file(file_id)
        file = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info.file_path}")
        local = f"/tmp/{file_name}"
        open(local, "wb").write(file.content)
        new_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
        ipa_name, plist_name = f"{new_id}.ipa", f"{new_id}.plist"
        meta = parse_ipa(local)
        upload_with_progress(chat_id, local, f"iPA/{ipa_name}", f"Upload {ipa_name}")
        ipa_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/iPA/{ipa_name}"
        plist_data = generate_plist(ipa_url, meta)
        upload_with_progress(chat_id, f"/tmp/{plist_name}", f"Plist/{plist_name}", f"Upload {plist_name}")
        open(f"/tmp/{plist_name}", "w").write(plist_data)
        plist_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/Plist/{plist_name}"
        short = shorten(f"itms-services://?action=download-manifest&url={plist_url}")
        msg = (f"✅ Upload hoàn tất!\n\n📱 App: {meta['app_name']}\n🆔 Bundle: {meta['bundle_id']}\n"
               f"🔢 Phiên bản: {meta['version']}\n👥 Team: {meta['team_name']} ({meta['team_id']})\n\n"
               f"📦 Tải IPA: {ipa_url}\n📲 [Cài trực tiếp]({short})")
        bot.send_message(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Lỗi: {e}")
    finally:
        try: bot.delete_message(chat_id, processing.message_id)
        except: pass
        if os.path.exists(local): os.remove(local)

# ========== DANH SÁCH + XOÁ FILE ==========
@bot.message_handler(commands=["listipa", "listplist"])
def list_files(m):
    folder = "iPA" if m.text == "/listipa" else "Plist"
    r = requests.get(f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{folder}",
                     headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if r.status_code != 200: return bot.reply_to(m, "❌ Không thể lấy danh sách.")
    files = [f for f in r.json() if f["name"].endswith(".ipa") or f["name"].endswith(".plist")]
    if not files: return bot.reply_to(m, f"📭 Thư mục {folder} trống.")
    kb = telebot.types.InlineKeyboardMarkup()
    for f in files:
        kb.add(telebot.types.InlineKeyboardButton(f"🗑 Xoá {f['name']}", callback_data=f"del:{folder}:{f['name']}:{f['sha']}"))
    bot.send_message(m.chat.id, f"📂 Danh sách file trong {folder}:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del:"))
def del_file(c):
    _, folder, name, sha = c.data.split(":")
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{folder}/{name}"
    r = requests.delete(url, headers={"Authorization": f"token {GITHUB_TOKEN}"},
                        json={"message": f"Delete {name}", "sha": sha})
    if r.status_code == 200:
        bot.edit_message_text(f"✅ Đã xoá {name} khỏi {folder}.", c.message.chat.id, c.message.message_id)
    else:
        bot.edit_message_text(f"❌ Lỗi khi xoá {name}.", c.message.chat.id, c.message.message_id)

# ========== NHẬN FILE IPA ==========
@bot.message_handler(content_types=["document"])
def handle_file(m):
    threading.Thread(target=process_ipa, args=(m, m.document.file_id, m.document.file_name)).start()

@bot.message_handler(commands=["start", "help"])
def help_msg(m):
    bot.reply_to(m, "👋 Gửi file .ipa để upload.\n/lisipa - Danh sách IPA\n/listplist - Danh sách Plist")

bot.infinity_polling()
