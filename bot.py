import os, time, base64, random, string, requests, zipfile, asyncio
from io import BytesIO
from urllib.parse import quote_plus
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ========== CONFIG ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_REPO = "trinhtruongphong-bot/ipa-host"   # Repo chứa IPA/Plist
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DOMAIN = "https://download.khoindvn.io.vn"      # Domain public (Pages/CDN)

IPA_PATH = "IPA"
PLIST_PATH = "Plist"

AUTO_DELETE_SECONDS = 3      # Xoá tin nhắn phụ sau 3s
CDN_SYNC_SECONDS    = 30     # Chờ CDN 30s rồi gửi link (ổn định)

# ========== HELPERS ==========
def random_name(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def _find_main_info_plist(zf: zipfile.ZipFile):
    """
    Chỉ lấy Info.plist ở đúng cấp: Payload/<App>.app/Info.plist
    (tránh nhầm extension/watchOS)
    """
    candidates = []
    for name in zf.namelist():
        low = name.lower()
        if low.endswith("info.plist") and low.startswith("payload/") and ".app/" in low:
            parts = low.split("/")
            # Expect: ["payload", "<app>.app", "info.plist"]
            if len(parts) == 3 and parts[0] == "payload" and parts[1].endswith(".app"):
                candidates.append(name)
    if candidates:
        # nếu có nhiều, lấy path ngắn nhất (ứng dụng chính)
        return min(candidates, key=len)
    return None

def _read_mobileprovision(zf: zipfile.ZipFile):
    """
    Lấy Team + Bundle fallback từ embedded.mobileprovision:
    - TeamName, TeamIdentifier, ApplicationIdentifierPrefix
    - Entitlements['application-identifier'] = <prefix>.<bundle>
    """
    try:
        for name in zf.namelist():
            if name.lower().endswith("embedded.mobileprovision"):
                raw = zf.read(name)
                s = raw.find(b'<?xml'); e = raw.rfind(b'</plist>')
                if s == -1 or e == -1:
                    return {}
                from plistlib import loads
                p = loads(raw[s:e+8])

                ent = p.get("Entitlements", {}) or {}
                appid = ent.get("application-identifier", "")  # PREFIX.BUNDLE
                team_name = p.get("TeamName")
                team_id_list = p.get("TeamIdentifier")
                prefix_list = p.get("ApplicationIdentifierPrefix")

                team_from_list = (team_id_list[0] if isinstance(team_id_list, list) and team_id_list else None)
                prefix_from_list = (prefix_list[0] if isinstance(prefix_list, list) and prefix_list else None)

                bundle_from_ent = None
                if appid and "." in appid:
                    bundle_from_ent = appid.split(".", 1)[1]

                team = team_name or team_from_list or prefix_from_list or "Unknown"
                return {"team": team, "bundle_from_entitlements": bundle_from_ent}
    except Exception as ex:
        print("⚠️ mobileprovision parse error:", ex)
    return {}

def extract_info_from_ipa(ipa_bytes):
    """
    Đọc Info.plist CHUẨN (đúng app chính). Fallback:
    - embedded.mobileprovision → team + bundle
    - iTunesMetadata.plist → name/bundle/version nếu thiếu
    """
    name = "Unknown"; bundle = "unknown.bundle"; version = "1.0"; team = "Unknown"

    try:
        with zipfile.ZipFile(BytesIO(ipa_bytes)) as ipa:
            # 1) Info.plist ở vị trí chuẩn
            plist_path = _find_main_info_plist(ipa)
            if plist_path:
                from plistlib import loads
                data = ipa.read(plist_path)
                p = loads(data)
                name = p.get("CFBundleDisplayName") or p.get("CFBundleName") or name
                bundle = p.get("CFBundleIdentifier") or bundle
                version = p.get("CFBundleShortVersionString") or p.get("CFBundleVersion") or version

            # 2) Fallback: embedded.mobileprovision
            prov = _read_mobileprovision(ipa)
            if prov:
                team = prov.get("team") or team
                if bundle == "unknown.bundle" and prov.get("bundle_from_entitlements"):
                    bundle = prov["bundle_from_entitlements"]

            # 3) Fallback thêm: iTunesMetadata.plist (nếu có)
            try:
                if name == "Unknown" or bundle == "unknown.bundle" or version == "1.0":
                    if "iTunesMetadata.plist" in ipa.namelist():
                        from plistlib import loads
                        meta = loads(ipa.read("iTunesMetadata.plist"))
                        name = meta.get("itemName") or meta.get("bundleDisplayName") or name
                        if bundle == "unknown.bundle":
                            bundle = meta.get("softwareVersionBundleId") or bundle
                        if version == "1.0":
                            version = meta.get("bundleShortVersionString") or version
            except Exception:
                pass

    except Exception as e:
        print("❌ Lỗi đọc IPA:", e)

    return {"name": name, "bundle": bundle, "version": version, "team": team}

def github_list(path):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return [f["name"] for f in r.json()]
    return []

def github_delete(path):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return False
    sha = r.json()["sha"]
    data = {"message": f"delete {path}", "sha": sha}
    return requests.delete(url, headers=headers, json=data).status_code == 200

async def auto_delete(context, chat_id, message_id, delay=AUTO_DELETE_SECONDS):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

def shorten_itms(install_link: str):
    """Rút gọn itms-services (URL-encode đầy đủ) → trả về link is.gd hoặc None."""
    try:
        encoded = quote_plus(install_link, safe="")
        r = requests.get(f"https://is.gd/create.php?format=simple&url={encoded}", timeout=6)
        if r.status_code == 200 and r.text.startswith("http"):
            return r.text.strip()
    except Exception as e:
        print("⚠️ is.gd error:", e)
    return None

async def edit_progress(msg, label, pct):
    try:
        await msg.edit_text(f"{label}: {pct}%")
    except:
        pass

async def github_upload_with_progress(path: str, raw_bytes: bytes, msg, label="⬆️ Upload GitHub"):
    """
    Ước lượng % upload GitHub: encode base64 từng chunk để báo %,
    rồi PUT một lần (GitHub Contents API không có multipart).
    """
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"

    total = len(raw_bytes)
    chunk = 1024 * 1024  # 1MB
    parts = []
    done = 0
    last_shown = -1

    for i in range(0, total, chunk):
        part = base64.b64encode(raw_bytes[i:i+chunk]).decode()
        parts.append(part)
        done += min(chunk, total - i)
        pct = int(done * 100 / total)
        step = pct // 5  # cập nhật mỗi 5%
        if step > last_shown:
            last_shown = step
            await edit_progress(msg, label, min(pct, 95))
        await asyncio.sleep(0)

    encoded = ''.join(parts)
    payload = {"message": f"Upload {path}", "content": encoded}
    try:
        r = requests.put(url, headers=headers, json=payload, timeout=180)
        await edit_progress(msg, label, 100)
        return r.status_code in [200, 201]
    except Exception as e:
        print("❌ PUT GitHub lỗi:", e)
        return False

# ========== COMMANDS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "👋 Xin chào!\nGửi file `.ipa` để upload và tạo link cài đặt iOS.\nGõ /help để xem hướng dẫn."
    )
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "🧭 Lệnh:\n"
        "/listipa – Danh sách IPA (kèm nút xoá)\n"
        "/listplist – Danh sách Plist (kèm nút xoá)\n"
        "/help – Hướng dẫn\n\n"
        "📤 Gửi file `.ipa` để upload!"
    )
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE, path, label):
    files = github_list(path)
    if not files:
        msg = await update.message.reply_text(f"📂 Không có file {label}.")
        context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return
    keyboard = [[InlineKeyboardButton(f"{f} 🗑️", callback_data=f"delete|{path}|{f}")] for f in files]
    msg = await update.message.reply_text(f"📦 Danh sách {label}:", reply_markup=InlineKeyboardMarkup(keyboard))
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def list_ipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_files(update, context, IPA_PATH, "IPA")

async def list_plist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_files(update, context, PLIST_PATH, "Plist")

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, path, filename = q.data.split("|")
    ok = github_delete(f"{path}/{filename}")
    await q.edit_message_text(
        f"✅ Đã xoá `{filename}` khỏi `{path}/`" if ok else f"❌ Không thể xoá `{filename}`",
        parse_mode="Markdown"
    )

# ========== UPLOAD FLOW ==========
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.lower().endswith(".ipa"):
        msg = await update.message.reply_text("⚠️ Vui lòng gửi file `.ipa` hợp lệ!")
        context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return

    # (A) Nhận file từ Telegram, có % thật
    msg = await update.message.reply_text("📤 Đang nhận file IPA...")
    tg_file = await doc.get_file()
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}"
    r = requests.get(file_url, stream=True)
    total = int(r.headers.get("Content-Length", "0")) or doc.file_size or 0

    buf = BytesIO(); downloaded = 0; last = -1
    for chunk in r.iter_content(chunk_size=524288):  # 512KB
        if not chunk:
            continue
        buf.write(chunk)
        downloaded += len(chunk)
        if total > 0:
            pct = int(downloaded * 100 / total); step = pct // 10
            if step > last:
                last = step
                try:
                    await msg.edit_text(f"⬇️ Nhận từ Telegram: {pct}%")
                except:
                    pass

    ipa_bytes = buf.getvalue()
    await msg.edit_text("✅ Đã nhận xong. Đang chuẩn bị upload lên GitHub…")

    # (B) Trích xuất info & đặt tên random
    info = extract_info_from_ipa(ipa_bytes)
    rand = random_name()
    ipa_file = f"{IPA_PATH}/{rand}.ipa"
    plist_file = f"{PLIST_PATH}/{rand}.plist"

    # (C) Upload IPA lên GitHub (báo % ước lượng)
    ok = await github_upload_with_progress(ipa_file, ipa_bytes, msg, "⬆️ Upload GitHub (IPA)")
    if not ok:
        msg2 = await update.message.reply_text("❌ Upload IPA lên GitHub thất bại.")
        context.application.create_task(auto_delete(context, msg2.chat_id, msg2.message_id))
        return

    ipa_url = f"{DOMAIN}/{ipa_file}"
    plist_url = f"{DOMAIN}/{plist_file}"

    # (D) Tạo manifest .plist và upload (file nhỏ, không cần %)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict>
<key>assets</key><array><dict><key>kind</key><string>software-package</string>
<key>url</key><string>{ipa_url}</string></dict></array>
<key>metadata</key><dict>
<key>bundle-identifier</key><string>{info['bundle']}</string>
<key>bundle-version</key><string>{info['version']}</string>
<key>kind</key><string>software</string>
<key>title</key><string>{info['name']}</string>
</dict></dict></array></dict></plist>"""

    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url_pl = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{plist_file}"
    payload_pl = {"message": f"Upload {plist_file}", "content": base64.b64encode(plist.encode()).decode()}
    requests.put(url_pl, headers=headers, json=payload_pl, timeout=60)

    # (E) Chờ CDN đồng bộ rồi phát hành link
    await asyncio.sleep(CDN_SYNC_SECONDS)
    install_link = f"itms-services://?action=download-manifest&url={plist_url}"
    short_link = shorten_itms(install_link)

    # (F) Gửi kết quả cuối (KHÔNG auto-delete)
    lines = [
        "✅ **Upload thành công!**\n",
        f"📱 **Tên ứng dụng:** {info['name']}",
        f"🆔 **Bundle ID:** {info['bundle']}",
        f"🔢 **Phiên bản:** {info['version']}",
        f"👥 **Team ID:** {info['team']}\n",
        f"📦 **Tải IPA:** {ipa_url}",
        f"📲 **Cài trực tiếp (itms):** {install_link}",
    ]
    if short_link:
        lines.append(f"🔗 **Rút gọn (is.gd):** {short_link}")
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ========== KEEP ALIVE (Render Free) ==========
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
    app.add_handler(CallbackQueryHandler(handle_delete))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    threading.Thread(target=keep_alive, daemon=True).start()
    print("🚀 Bot đang chạy (v8.9-fix2 | auto-delete=3s, cdn-wait=30s)…")
    app.run_polling()
