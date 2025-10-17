import telebot, requests, base64, zipfile, plistlib, os, random, string, threading, time, html, tempfile, subprocess, re
from flask import Flask, request

# ========= CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")

CUSTOM_DOMAIN = "https://download.khoindvn.io.vn"
WEBHOOK_URL = "https://developed-hyena-trinhtruongphong-abb0500e.koyeb.app/"

bot = telebot.TeleBot(BOT_TOKEN)

# ========= RÚT GỌN LINK =========
def shorten(url):
    try:
        r = requests.get(f"https://is.gd/create.php?format=simple&url={url}", timeout=10)
        if r.status_code == 200 and r.text.startswith("http"):
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

    r = requests.put(url, headers=headers, json=data)
    bot.edit_message_text(f"✅ Upload <b>{os.path.basename(file_path)}</b> hoàn tất!", chat_id, msg.message_id, parse_mode="HTML")
    threading.Timer(30.0, lambda: bot.delete_message(chat_id, msg.message_id)).start()
    return r.json()["content"]["path"]

# ========= PHÂN TÍCH FILE IPA (ĐỌC 100% + TEAM NAME) =========
def parse_ipa(file_path):
    info = {"app_name": None, "bundle_id": None, "version": None, "team_name": None, "team_id": None, "error": None}

    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            # ✅ Chỉ đọc đúng Info.plist trong .app
            plist_files = [f for f in z.namelist() if f.startswith("Payload/") and f.endswith(".app/Info.plist")]
            if not plist_files:
                info["error"] = "Không tìm thấy Info.plist trong .app"
                return info

            plist_path = plist_files[0]
            data = z.read(plist_path)

            # --- Giải mã Info.plist ---
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
                        except Exception as e:
                            info["error"] = f"Không thể đọc Info.plist: {str(e)}"
                            return info
                        finally:
                            os.remove(tmp.name)
                            if os.path.exists(xml_path): os.remove(xml_path)

            info["app_name"] = plist.get("CFBundleDisplayName") or plist.get("CFBundleName")
            info["bundle_id"] = plist.get("CFBundleIdentifier")
            info["version"] = plist.get("CFBundleShortVersionString")

            # ✅ Đọc Team Name + Team ID từ embedded.mobileprovision
            embedded_files = [f for f in z.namelist() if f.endswith(".app/embedded.mobileprovision")]
            if embedded_files:
                emb_path = embedded_files[0]
                emb_data = z.read(emb_path).decode("utf-8", errors="ignore")
                match = re.search(r"<plist.*?</plist>", emb_data, re.DOTALL)
                if match:
                    plist_xml = match.group(0).encode("utf-8")
                    try:
                        emb_plist = plistlib.loads(plist_xml)
                        info["team_name"] = emb_plist.get("TeamName")
                        team_ids = emb_plist.get("TeamIdentifier")
                        if isinstance(team_ids, list) and len(team_ids) > 0:
                            info["team_id"] = team_ids[0]
                    except Exception:
                        pass

            if not all([info["app_name"], info["bundle_id"], info["version"]]):
                info["error"] = "Không thể đọc đầy đủ metadata trong Info.plist"

    except Exception as e:
        info["error"] = f"Lỗi khi đọc IPA: {str(e)}"

    return info

# ========= TẠO FILE PLIST =========
def generate_plist(ipa_url, info):
    with open("template.plist", "r", encoding="utf-8") as tpl:
        plist = tpl.read()
    plist = (
        plist.replace("__IPA__", ipa_url)
        .replace("__PACKAGE__", info["bundle_id"] or "")
        .replace("__VERSION__", info["version"] or "")
        .replace("__NAME__", info["app_name"] or "")
    )
    return plist

# ========= XỬ LÝ FILE IPA =========
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
        if meta["error"]:
            raise Exception(meta["error"])

        upload_with_progress(chat_id, local, f"iPA/{ipa_name}", f"Upload {ipa_name}")
        ipa_url = f"{CUSTOM_DOMAIN}/iPA/{ipa_name}"
        plist_url = f"{CUSTOM_DOMAIN}/Plist/{plist_name}"

        plist_data = generate_plist(ipa_url, meta)
        tmp_plist = f"/tmp/{plist_name}"
        with open(tmp_plist, "w", encoding="utf-8") as f:
            f.write(plist_data)

        upload_with_progress(chat_id, tmp_plist, f"Plist/{plist_name}", f"Upload {plist_name}")
        install_link = f"itms-services://?action=download-manifest&url={plist_url}"
        short = shorten(install_link)

        msg = (
            f"✅ <b>Upload hoàn tất!</b>\n\n"
            f"📱 Ứng dụng: <b>{meta['app_name']}</b>\n"
            f"🆔 Bundle: <code>{meta['bundle_id']}</code>\n"
            f"🔢 Phiên bản: <b>{meta['version']}</b>\n"
            f"👥 Team: <b>{meta.get('team_name') or 'Không rõ'}</b> "
            f"(<code>{meta.get('team_id') or 'Không rõ'}</code>)\n\n"
            f"📦 <b>Tải IPA:</b>\n{ipa_url}\n\n"
            f"📲 <b>Cài trực tiếp:</b>\n{short}"
        )
        bot.send_message(chat_id, msg, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        bot.send_message(chat_id, f"❌ <b>Lỗi:</b> <code>{html.escape(str(e))}</code>", parse_mode="HTML")

    finally:
        try:
            bot.delete_message(chat_id, processing.message_id)
        except:
            pass
        if os.path.exists(local):
            os.remove(local)

# ========= LỆNH =========
@bot.message_handler(content_types=["document"])
def handle_file(m):
    threading.Thread(target=process_ipa, args=(m, m.document.file_id, m.document.file_name)).start()

@bot.message_handler(commands=["start", "help"])
def start_help(m):
    bot.reply_to(m, "👋 Gửi file .ipa để tạo link cài đặt.\nTự động đọc Info.plist + Team Name, upload lên GitHub và tạo link iOS.", parse_mode="HTML")

# ========= FLASK WEBHOOK =========
app = Flask(__name__)

@app.route('/', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.data.decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

@app.route('/')
def home():
    return "Bot đang hoạt động 🚀"

bot.remove_webhook()
time.sleep(1)
bot.set_webhook(url=WEBHOOK_URL)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
