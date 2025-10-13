import os, time, base64, random, string, requests, zipfile, asyncio, re
from io import BytesIO
from urllib.parse import quote_plus
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import TelegramError

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "trinhtruongphong-bot/ipa-host")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DOMAIN = os.getenv("DOMAIN", "https://download.khoindvn.io.vn")

IPA_PATH = os.getenv("IPA_DIR", "IPA")
PLIST_PATH = os.getenv("PLIST_DIR", "Plist")

AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "3"))     # xoá tin nhắn phụ
CDN_SYNC_SECONDS    = int(os.getenv("CDN_SYNC_SECONDS", "30"))       # đợi CDN cho chắc
DEBUG               = os.getenv("DEBUG", "0") == "1"

# ================== UTILS ==================
def random_name(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def _debug(*args):
    if DEBUG:
        print("[DEBUG]", *args)

def _read_mobileprovision(zf: zipfile.ZipFile):
    """
    Trả về: {"team": <str>, "bundle_from_entitlements": <str or None>}
    Đọc TeamName / TeamIdentifier / ApplicationIdentifierPrefix và
    Entitlements['application-identifier'] = PREFIX.BUNDLE
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
                appid = ent.get("application-identifier", "")

                team_name = p.get("TeamName")
                team_ids = p.get("TeamIdentifier") or []
                prefixes = p.get("ApplicationIdentifierPrefix") or []

                team_from_list = team_ids[0] if isinstance(team_ids, list) and team_ids else None
                prefix_from_list = prefixes[0] if isinstance(prefixes, list) and prefixes else None

                bundle_from_ent = None
                if appid and "." in appid:
                    bundle_from_ent = appid.split(".", 1)[1]

                team = team_name or team_from_list or prefix_from_list or "Unknown"
                _debug("mobileprovision:", {"team": team, "bundle_from_entitlements": bundle_from_ent})
                return {"team": team, "bundle_from_entitlements": bundle_from_ent}
    except Exception as ex:
        print("⚠️ mobileprovision parse error:", ex)
    return {}

def _candidate_info_plists(zf: zipfile.ZipFile):
    """Trả về danh sách path Info.plist nằm dưới *.app/…"""
    cands = []
    for name in zf.namelist():
        low = name.lower()
        if low.endswith("info.plist") and ".app/" in low and low.startswith("payload/"):
            cands.append(name)
    _debug("plist candidates:", cands)
    return cands

def _score_plist_path(path: str):
    """
    Điểm cơ bản dựa trên path:
    +2 nếu đúng cấp: Payload/App.app/Info.plist (chỉ 3 segment)
    -3 nếu chứa appex/watchkit/plugins/extension
    """
    low = path.lower()
    parts = low.split("/")
    score = 0
    if len(parts) == 3 and parts[0] == "payload" and parts[1].endswith(".app") and parts[2] == "info.plist":
        score += 2
    if any(x in low for x in [".appex/", "watchkit", "/plugins/", "extension"]):
        score -= 3
    return score

def extract_info_from_ipa(ipa_bytes):
    """
    Chọn Info.plist hợp lý nhất bằng cách CHẤM ĐIỂM + so khớp bundle với entitlements.
    Fallback: iTunesMetadata.plist.
    """
    name = "Unknown"; bundle = "unknown.bundle"; version = "1.0"; team = "Unknown"
    try:
        with zipfile.ZipFile(BytesIO(ipa_bytes)) as ipa:
            # Đọc mobileprovision trước để có bundle/team tham chiếu
            prov = _read_mobileprovision(ipa)
            team = prov.get("team") or team
            bundle_from_ent = prov.get("bundle_from_entitlements")

            # Thu thập tất cả Info.plist
            candidates = _candidate_info_plists(ipa)
            best = None
            best_score = -10**9

            from plistlib import loads
            for pth in candidates:
                try:
                    data = ipa.read(pth)
                    meta = loads(data)
                    cn = meta.get("CFBundleDisplayName") or meta.get("CFBundleName")
                    cb = meta.get("CFBundleIdentifier")
                    cv = meta.get("CFBundleShortVersionString") or meta.get("CFBundleVersion")
                    score = _score_plist_path(pth)

                    # Ưu tiên mạnh nếu bundle trùng entitlements
                    if bundle_from_ent and cb == bundle_from_ent:
                        score += 5

                    # Tránh lấy extension (thiếu title) → phạt nếu không có tên
                    if not cn:
                        score -= 1

                    _debug("candidate", pth, {"name": cn, "bundle": cb, "version": cv, "score": score})

                    if score > best_score and cb:
                        best_score = score
                        best = {"name": cn, "bundle": cb, "version": cv}
                except Exception as ex:
                    _debug("plist parse error:", pth, ex)

            if best:
                name = best.get("name") or name
                bundle = best.get("bundle") or bundle
                version = best.get("version") or version

            # Fallback thêm: iTunesMetadata.plist
            try:
                if (name == "Unknown") or (bundle == "unknown.bundle") or (version == "1.0"):
                    if "iTunesMetadata.plist" in ipa.namelist():
                        from plistlib import loads
                        md = loads(ipa.read("iTunesMetadata.plist"))
                        name = md.get("itemName") or md.get("bundleDisplayName") or name
                        if bundle == "unknown.bundle":
                            bundle = md.get("softwareVersionBundleId") or bundle
                        if version == "1.0":
                            version = md.get("bundleShortVersionString") or version
            except Exception:
                pass

    except Exception as e:
        print("❌ Lỗi đọc IPA:", e)

    return {"name": name or "Unknown", "bundle": bundle or "unknown.bundle", "version": version or "1.0", "team": team or "Unknown"}

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
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"

    total = len(raw_bytes)
    chunk = 1024 * 1024  # 1MB
    parts, done, last = [], 0, -1

    for i in range(0, total, chunk):
        part = base64.b64encode(raw_bytes[i:i+chunk]).decode()
        parts.append(part)
        done += min(chunk, total - i)
        pct = int(done * 100 / total)
        step = pct // 5
        if step > last:
            last = step
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

# ================== COMMANDS ==================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "👋 Xin chào!\nGửi file `.ipa` để upload và tạo link cài đặt iOS.\nGõ /help để xem hướng dẫn."
    )
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ================== UPLOAD FLOW ==================
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.lower().endswith(".ipa"):
        msg = await update.message.reply_text("⚠️ Vui lòng gửi file `.ipa` hợp lệ!")
        context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return

    # (A) Nhận file từ Telegram (có %)
    msg = await update.message.reply_text("📤 Đang nhận file IPA...")
    tg_file = await doc.get_file()
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}"
    r = requests.get(file_url, stream=True)
    total = int(r.headers.get("Content-Length", "0")) or doc.file_size or 0

    buf = BytesIO(); downloaded = 0; last = -1
    for chunk in r.iter_content(chunk_size=524288):
        if not chunk: continue
        buf.write(chunk); downloaded += len(chunk)
        if total > 0:
            pct = int(downloaded * 100 / total); step = pct // 10
            if step > last:
                last = step
                try: await msg.edit_text(f"⬇️ Nhận từ Telegram: {pct}%")
                except: pass

    ipa_bytes = buf.getvalue()
    await msg.edit_text("✅ Đã nhận xong. Đang phân tích…")

    # (B) Phân tích IPA
    info = extract_info_from_ipa(ipa_bytes)
    _debug("IPA info result:", info)
    await msg.edit_text("✅ Phân tích xong. Đang upload GitHub…")

    # (C) Đặt tên & Upload IPA
    rand = random_name()
    ipa_file = f"{IPA_PATH}/{rand}.ipa"
    plist_file = f"{PLIST_PATH}/{rand}.plist"

    ok = await github_upload_with_progress(ipa_file, ipa_bytes, msg, "⬆️ Upload GitHub (IPA)")
    if not ok:
        msg2 = await update.message.reply_text("❌ Upload IPA lên GitHub thất bại.")
        context.application.create_task(auto_delete(context, msg2.chat_id, msg2.message_id))
        return

    ipa_url = f"{DOMAIN}/{ipa_file}"
    plist_url = f"{DOMAIN}/{plist_file}"

    # (D) Tạo & upload manifest .plist
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

    # (E) Đợi CDN & phát hành link
    await asyncio.sleep(CDN_SYNC_SECONDS)
    install_link = f"itms-services://?action=download-manifest&url={plist_url}"
    short_link = shorten_itms(install_link)

    # (F) Gửi kết quả (không auto-delete)
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

# ================== KEEP ALIVE ==================
def keep_alive():
    while True:
        try:
            requests.get(DOMAIN)
        except:
            pass
        time.sleep(50)

# ================== STARTUP (clear webhook) ==================
async def _startup(app):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook cleared & pending updates dropped")
    except TelegramError as e:
        print("⚠️ delete_webhook:", e)

# ================== MAIN ==================
if __name__ == "__main__":
    import threading
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(_startup)         # clear webhook trước khi polling
        .build()
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("listipa", list_ipa))
    app.add_handler(CommandHandler("listplist", list_plist))
    app.add_handler(CallbackQueryHandler(handle_delete))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    threading.Thread(target=keep_alive, daemon=True).start()
    print("🚀 Bot đang chạy (v9.0-robust)…")
    app.run_polling(drop_pending_updates=True)
