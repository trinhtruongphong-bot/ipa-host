import telebot, requests, base64, zipfile, plistlib, os, random, string, threading, time, html, urllib.parse, tempfile
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")

CUSTOM_DOMAIN = "https://download.khoindvn.io.vn"
WEBHOOK_URL = "https://developed-hyena-trinhtruongphong-abb0500e.koyeb.app/"

bot = telebot.TeleBot(BOT_TOKEN)

# ========= GỬI TIN NHẮN DÀI =========
def send_long_message(chat_id, text, parse_mode="HTML"):
    max_len = 4000
    for i in range(0, len(text), max_len):
        bot.send_message(chat_id, text[i:i+max_len], parse_mode=parse_mode, disable_web_page_preview=True)

# ========= RÚT GỌN LINK =========
def shorten(url):
    encoded = urllib.parse.quote(url, safe="")
    try:
        r = requests.get(f"https://is.gd/create.php?format=simple&url={encoded}", timeout=20)
        if r.status_code == 200:
            return r.text.strip()
    except:
        pass
    return url

# ========= UPLOAD FILE LÊN GITHUB =========
def upload_with_progress(chat_id, file_path, repo_path, message):
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{repo_path}"

    sha = None
    check = requests.get(url, headers=headers)
    if check.status_code == 200:
        sha = check.json().get("sha")

    msg = bot.send_message(chat_id, f"📤 Đang upload <b>{os.path.basename(file_path)}</b>... 0%", parse_mode="HTML")

    with open(file_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("utf-8")

    for p in range(0, 101, 25):
        try:
            bot.edit_message_text(f"📤 Đang upload <b>{os.path.basename(file_path)}</b>... {p}%", chat_id, msg.message_id, parse_mode="HTML")
        except:
            pass
        time.sleep(0.25)

    data = {"message": message, "content": content_b64}
    if sha:
        data["sha"] = sha

    for attempt in range(3):
        try:
            r = requests.put(url, headers=headers, json=data, timeout=120)
            if r.status_code in [200, 201]:
                break
            else:
                raise Exception(r.text)
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
                continue
            else:
                raise e

    bot.edit_message_text(f"✅ Upload <b>{os.path.basename(file_path)}</b> hoàn tất!", chat_id, msg.message_id, parse_mode="HTML")
    return r.json()["content"]["path"]

# ========= PHÂN TÍCH FILE IPA (chỉ lấy Info.plist trong .app) =========
def parse_ipa(file_path):
    info = {"app_name": "", "bundle_id": "", "version": "", "error": None}
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            # 🔍 Chỉ chọn Info.plist trong thư mục .app
            plist_file = [
                f for f in z.namelist()
                if f.endswith("Info.plist") and ".app/" in f and "Payload/" in f
            ]
            if not plist_file:
                info["error"] = "Không tìm thấy Info.plist trong .app"
                return info

            with z.open(plist_file[0]) as f:
                data = f.read()
                try:
                    p = plistlib.loads(data)
                except Exception:
                    try:
                        with tempfile.NamedTemporaryFile(delete=False) as tmp:
                            tmp.write(data)
                            tmp.flush()
                            os.system(f"plutil -convert xml1 {tmp.name}")
                            with open(tmp.name, "rb") as xmlf:
                                p = plistlib.load(xmlf)
                        os.remove(tmp.name)
                    except Exception:
                        info["error"] = "Không đọc được Info.plist (binary hoặc mã hoá)"
                        return info

                info["app_name"] = p.get("CFBundleDisplayName") or p.get("CFBundleName") or ""
                info["bundle_id"] = p.get("CFBundleIdentifier") or ""
                info["version"] = p.get("CFBundleShortVersionString") or ""
    except Exception as e:
        info["error"] = f"Lỗi khi đọc IPA: {str(e)}"
    return info

# ========= TẠO FILE PLIST =========
def generate_plist(ipa_url, info):
    try:
        with open("template.plist", "r", encoding="utf-8") as tpl:
            content = tpl.read()
        content = (
            content.replace("__IPA__", ipa_url)
            .replace("__PACKAGE__", info.get("bundle_id", ""))
            .replace("__VERSION__", info.get("version", ""))
            .replace("__NAME__", info.get("app_name", ""))
        )
        return content
    except Exception as e:
        return f"❌ Không thể tạo plist: {str(e)}"

# ========= XỬ LÝ FILE IPA =========
def process_ipa(message, file_id, file_name):
    chat_id = message.chat.id
    processing = bot.send_message(chat_id, f"📦 Đang xử lý <b>{file_name}</b>...", parse_mode="HTML")
    local = f"/tmp/{file_name}"

    try:
        info = bot.get_file(file_id)
        file = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info.file_path}", timeout=120)
        with open(local, "wb") as f:
            f.write(file.content)

        new_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
        ipa_name, plist_name = f"{new_id}.ipa", f"{new_id}.plist"

        meta = parse_ipa(local)

        upload_with_progress(chat_id, local, f"iPA/{ipa_name}", f"Upload {ipa_name}")
        ipa_url = f"{CUSTOM_DOMAIN}/iPA/{ipa_name}"
        plist_url = f"{CUSTOM_DOMAIN}/Plist/{plist_name}"

        plist_data = generate_plist(ipa_url, meta)
        plist_path = f"/tmp/{plist_name}"
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(plist_data)
        upload_with_progress(chat_id, plist_path, f"Plist/{plist_name}", f"Upload {plist_name}")

        install_link = f"itms-services://?action=download-manifest&url={plist_url}"
        short_link = shorten(install_link)

        if meta["error"]:
            msg = f"⚠️ <b>Không thể đọc đầy đủ thông tin IPA</b>\n\nLý do: <i>{meta['error']}</i>\n\n📦 <b>Tải IPA:</b>\n{ipa_url}\n\n📲 <b>Cài trực tiếp:</b>\n{short_link}"
        else:
            msg = (
                f"✅ <b>Upload hoàn tất!</b>\n\n"
                f"📱 Ứng dụng: <b>{meta['app_name']}</b>\n"
                f"🆔 Bundle: <code>{meta['bundle_id']}</code>\n"
                f"🔢 Phiên bản: <b>{meta['version']}</b>\n\n"
                f"📦 <b>Tải IPA:</b>\n{ipa_url}\n\n"
                f"📲 <b>Cài trực tiếp:</b>\n{short_link}"
            )

        send_long_message(chat_id, msg)

    except Exception as e:
        bot.send_message(chat_id, f"❌ <b>Lỗi:</b> <code>{html.escape(str(e))}</code>", parse_mode="HTML")

    finally:
        try:
            bot.delete_message(chat_id, processing.message_id)
        except:
            pass
        if os.path.exists(local):
            os.remove(local)

# ========= DANH SÁCH & XOÁ =========
@bot.message_handler(commands=["listipa", "listplist"])
def list_files(m):
    folder = "iPA" if m.text == "/listipa" else "Plist"
    r = requests.get(f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{folder}", headers={"Authorization": f"token {GITHUB_TOKEN}"})
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
    r = requests.delete(url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, json={"message": f"Delete {name}", "sha": sha})
    if r.status_code == 200:
        bot.edit_message_text(f"✅ Đã xoá <b>{html.escape(name)}</b> khỏi <b>{folder}</b>.", c.message.chat.id, c.message.message_id, parse_mode="HTML")
    else:
        bot.edit_message_text(f"❌ Lỗi khi xoá <b>{html.escape(name)}</b>.", c.message.chat.id, c.message.message_id, parse_mode="HTML")

# ========= COMMAND =========
@bot.message_handler(content_types=["document"])
def handle_file(m):
    threading.Thread(target=process_ipa, args=(m, m.document.file_id, m.document.file_name)).start()

@bot.message_handler(commands=["start", "help"])
def help_msg(m):
    bot.reply_to(m, "👋 Gửi file .ipa để upload.\n/listipa - Danh sách IPA\n/listplist - Danh sách Plist", parse_mode="HTML")

# ========= FLASK WEBHOOK =========
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
