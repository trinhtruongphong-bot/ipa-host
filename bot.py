import os, time, base64, random, string, requests, zipfile, asyncio
from io import BytesIO
from urllib.parse import quote_plus
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import TelegramError

# ========== CONFIG (có thể override qua ENV) ==========
BOT_TOKEN      = os.getenv("BOT_TOKEN")
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN")
GITHUB_REPO    = os.getenv("GITHUB_REPO", "trinhtruongphong-bot/ipa-host")
DOMAIN         = os.getenv("DOMAIN", "https://download.khoindvn.io.vn")  # GitHub Pages custom domain

IPA_PATH       = os.getenv("IPA_DIR", "IPA")
PLIST_PATH     = os.getenv("PLIST_DIR", "Plist")

AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "30"))  # xoá tin nhắn phụ sau 30s
CDN_SYNC_SECONDS    = int(os.getenv("CDN_SYNC_SECONDS", "30"))    # đợi CDN sync cho chắc
DEBUG               = os.getenv("DEBUG", "0") == "1"

# ========== UTILS ==========
def rname(n=6):
    import string, random
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def _dbg(*a):
    if DEBUG:
        print("[DBG]", *a)

async def auto_delete(ctx, chat_id, msg_id, delay=AUTO_DELETE_SECONDS):
    await asyncio.sleep(delay)
    try:
        await ctx.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except:
        pass

def gh_headers():
    return {"Authorization": f"token {GITHUB_TOKEN}"}

def github_list(path):
    r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}", headers=gh_headers(), timeout=30)
    if r.status_code == 200:
        return [x["name"] for x in r.json()]
    return []

def github_delete(path):
    get = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}", headers=gh_headers(), timeout=30)
    if get.status_code != 200: return False
    sha = get.json()["sha"]
    r = requests.delete(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
                        headers=gh_headers(), json={"message": f"delete {path}", "sha": sha}, timeout=30)
    return r.status_code == 200

def shorten_itms(install_link: str):
    """Rút gọn link itms-services bằng is.gd (URL-encode đầy đủ)."""
    try:
        encoded = quote_plus(install_link, safe="")
        r = requests.get(f"https://is.gd/create.php?format=simple&url={encoded}", timeout=8)
        if r.status_code == 200 and r.text.startswith("http"):
            return r.text.strip()
    except Exception as e:
        print("⚠️ is.gd error:", e)
    return None

# ---------- IPA parsing (mạnh tay) ----------
def _read_mobileprovision(zf: zipfile.ZipFile):
    """
    Lấy team + bundle fallback từ embedded.mobileprovision:
    - TeamName / TeamIdentifier / ApplicationIdentifierPrefix
    - Entitlements['application-identifier'] = PREFIX.BUNDLE
    """
    try:
        for name in zf.namelist():
            if name.lower().endswith("embedded.mobileprovision"):
                raw = zf.read(name)
                s = raw.find(b'<?xml'); e = raw.rfind(b'</plist>')
                if s == -1 or e == -1: return {}
                from plistlib import loads
                p = loads(raw[s:e+8])

                ent = p.get("Entitlements", {}) or {}
                appid = ent.get("application-identifier", "")  # PREFIX.BUNDLE hoặc PREFIX.*

                team_name = p.get("TeamName")
                team_ids  = p.get("TeamIdentifier") or []
                prefixes  = p.get("ApplicationIdentifierPrefix") or []

                team_from_list   = team_ids[0]  if isinstance(team_ids, list)  and team_ids  else None
                prefix_from_list = prefixes[0]  if isinstance(prefixes, list)  and prefixes  else None

                bundle_from_ent = None
                if appid and "." in appid:
                    bundle_from_ent = appid.split(".", 1)[1]  # có thể là '*'

                team = team_name or team_from_list or prefix_from_list or "Unknown"
                return {"team": team, "bundle_from_entitlements": bundle_from_ent}
    except Exception as ex:
        print("⚠️ mobileprovision parse error:", ex)
    return {}

def _candidate_info_plists(zf: zipfile.ZipFile):
    """Lấy mọi Info.plist dưới *.app/ (tránh bỏ sót)."""
    cands = []
    for name in zf.namelist():
        low = name.lower()
        if low.startswith("payload/") and ".app/" in low and low.endswith("info.plist"):
            cands.append(name)
    return cands

def _score_path(path: str):
    """Chấm điểm path: +2 nếu đúng cấp chính; -3 nếu thuộc appex/watchkit/plugins/extension."""
    low = path.lower()
    parts = low.split("/")
    score = 0
    if len(parts) == 3 and parts[0] == "payload" and parts[1].endswith(".app") and parts[2] == "info.plist":
        score += 2
    if any(x in low for x in [".appex/", "watchkit", "/plugins/", "extension"]):
        score -= 3
    return score

def extract_info_from_ipa(ipa_bytes: bytes):
    """
    Chọn Info.plist hợp lý nhất bằng chấm điểm + so khớp entitlements.
    Fallback: iTunesMetadata.plist.
    """
    name = "Unknown"; bundle = "unknown.bundle"; version = "1.0"; team = "Unknown"
    try:
        from plistlib import loads
        with zipfile.ZipFile(BytesIO(ipa_bytes)) as ipa:
            prov = _read_mobileprovision(ipa)
            team = prov.get("team") or team
            bundle_from_ent = prov.get("bundle_from_entitlements")

            best = None; best_score = -10**9
            for pth in _candidate_info_plists(ipa):
                try:
                    meta = loads(ipa.read(pth))  # đọc được cả binary & XML
                    cn = meta.get("CFBundleDisplayName") or meta.get("CFBundleName")
                    cb = meta.get("CFBundleIdentifier")
                    cv = meta.get("CFBundleShortVersionString") or meta.get("CFBundleVersion")
                    score = _score_path(pth)
                    if bundle_from_ent and cb == bundle_from_ent:
                        score += 5
                    if not cn:
                        score -= 1
                    if cb and score > best_score:
                        best_score = score
                        best = {"name": cn, "bundle": cb, "version": cv}
                except Exception as e:
                    _dbg("plist parse error", pth, e)

            if best:
                name   = best.get("name")    or name
                bundle = best.get("bundle")  or bundle
                version= best.get("version") or version

            # Fallback thêm: iTunesMetadata.plist
            try:
                if (name == "Unknown") or (bundle == "unknown.bundle") or (version == "1.0"):
                    if "iTunesMetadata.plist" in ipa.namelist():
                        md = loads(ipa.read("iTunesMetadata.plist"))
                        name   = md.get("itemName") or md.get("bundleDisplayName") or name
                        bundle = md.get("softwareVersionBundleId") or bundle
                        version= md.get("bundleShortVersionString") or version
            except Exception:
                pass
    except Exception as e:
        print("❌ IPA parse error:", e)

    return {
        "name": name or "Unknown",
        "bundle": bundle or "unknown.bundle",
        "version": version or "1.0",
        "team": team or "Unknown"
    }

# ---------- Upload GitHub với % (ước lượng) ----------
async def _edit_progress(msg, label, pct):
    try:    await msg.edit_text(f"{label}: {pct}%")
    except:  pass

async def github_upload_with_progress(path: str, raw: bytes, msg, label="⬆️ Upload GitHub"):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    total = len(raw); chunk = 1024 * 1024
    parts, done, last = [], 0, -1

    for i in range(0, total, chunk):
        parts.append(base64.b64encode(raw[i:i+chunk]).decode())
        done += min(chunk, total - i)
        pct = int(done * 100 / total); step = pct // 5
        if step > last:
            last = step
            await _edit_progress(msg, label, min(pct, 95))
        await asyncio.sleep(0)

    payload = {"message": f"Upload {path}", "content": ''.join(parts)}
    try:
        r = requests.put(url, headers=gh_headers(), json=payload, timeout=180)
        await _edit_progress(msg, label, 100)
        return r.status_code in (200, 201)
    except Exception as e:
        print("❌ PUT GitHub error:", e)
        return False

# ========== COMMANDS ==========
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("👋 Xin chào!\nGửi file `.ipa` để upload và tạo link cài đặt iOS.\nGõ /help để xem hướng dẫn.")
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "🧭 Lệnh:\n"
        "/listipa – Danh sách IPA (kèm nút xoá)\n"
        "/listplist – Danh sách Plist (kèm nút xoá)\n"
        "/help – Hướng dẫn\n\n"
        "📤 Gửi file `.ipa` để upload!"
    )
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def _list(update: Update, context: ContextTypes.DEFAULT_TYPE, path, label):
    files = github_list(path)
    if not files:
        msg = await update.message.reply_text(f"📂 Không có file {label}.")
        context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return
    kb = [[InlineKeyboardButton(f"{f} 🗑️", callback_data=f"delete|{path}|{f}")] for f in files]
    msg = await update.message.reply_text(f"📦 Danh sách {label}:", reply_markup=InlineKeyboardMarkup(kb))
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def cmd_listipa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _list(update, context, IPA_PATH, "IPA")

async def cmd_listplist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _list(update, context, PLIST_PATH, "Plist")

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, path, fname = q.data.split("|")
    ok = github_delete(f"{path}/{fname}")
    await q.edit_message_text(f"✅ Đã xoá `{fname}` khỏi `{path}/`" if ok else f"❌ Không thể xoá `{fname}`", parse_mode="Markdown")

# ========== HANDLE IPA ==========
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.lower().endswith(".ipa"):
        msg = await update.message.reply_text("⚠️ Vui lòng gửi file `.ipa` hợp lệ!")
        context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return

    # A) nhận từ Telegram (báo % thật)
    msg = await update.message.reply_text("📤 Đang nhận file IPA…")
    tg_file = await doc.get_file()
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}"
    r = requests.get(file_url, stream=True, timeout=600)
    total = int(r.headers.get("Content-Length", "0")) or doc.file_size or 0

    buf = BytesIO(); done = 0; last = -1
    for chunk in r.iter_content(chunk_size=524288):
        if not chunk: continue
        buf.write(chunk); done += len(chunk)
        if total > 0:
            pct = int(done * 100 / total); step = pct // 10
            if step > last:
                last = step
                try: await msg.edit_text(f"⬇️ Nhận từ Telegram: {pct}%")
                except: pass

    ipa_bytes = buf.getvalue()
    await msg.edit_text("✅ Đã nhận xong. Đang phân tích…")

    # B) phân tích IPA
    info = extract_info_from_ipa(ipa_bytes)
    await msg.edit_text("✅ Phân tích xong. Đang upload GitHub…")

    # C) đặt tên random (không ký tự đặc biệt)
    rid = rname()
    ipa_key   = f"{IPA_PATH}/{rid}.ipa"
    plist_key = f"{PLIST_PATH}/{rid}.plist"

    # D) upload IPA (ước lượng %)
    ok = await github_upload_with_progress(ipa_key, ipa_bytes, msg, "⬆️ Upload GitHub (IPA)")
    if not ok:
        err = await update.message.reply_text("❌ Upload IPA lên GitHub thất bại.")
        context.application.create_task(auto_delete(context, err.chat_id, err.message_id))
        return

    ipa_url   = f"{DOMAIN}/{ipa_key}"
    plist_url = f"{DOMAIN}/{plist_key}"

    # E) tạo & upload manifest .plist (nhỏ, upload một phát)
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
    requests.put(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{plist_key}",
        headers=gh_headers(),
        json={"message": f"Upload {plist_key}", "content": base64.b64encode(plist.encode()).decode()},
        timeout=60
    )

    # F) đợi CDN rồi phát hành link — CHỈ gửi link rút gọn (fallback itms nếu rút gọn fail)
    await asyncio.sleep(CDN_SYNC_SECONDS)
    itms = f"itms-services://?action=download-manifest&url={plist_url}"
    link_display = shorten_itms(itms) or itms

    # G) gửi kết quả (KHÔNG auto-delete)
    lines = [
        "✅ **Upload thành công!**\n",
        f"📱 **Tên ứng dụng:** {info['name']}",
        f"🆔 **Bundle ID:** {info['bundle']}",
        f"🔢 **Phiên bản:** {info['version']}",
        f"👥 **Team ID:** {info['team']}\n",
        f"📦 **Tải IPA:** {ipa_url}",
        f"📲 **Cài trực tiếp:** {link_display}",
    ]
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

# ========== KEEP-ALIVE (Render free) ==========
def keep_alive():
    while True:
        try:
            # ping domain để tiến trình có activity (không bắt buộc)
            requests.get(DOMAIN, timeout=10)
        except:
            pass
        time.sleep(50)

# ========== STARTUP (clear webhook để tránh Conflict) ==========
async def _startup(app):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook cleared & pending updates dropped")
    except TelegramError as e:
        print("⚠️ delete_webhook:", e)

# ========== MAIN ==========
if __name__ == "__main__":
    import threading
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(_startup)   # xoá webhook trước khi polling
        .build()
    )

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("listipa",   cmd_listipa))
    app.add_handler(CommandHandler("listplist", cmd_listplist))
    app.add_handler(CallbackQueryHandler(handle_delete))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    threading.Thread(target=keep_alive, daemon=True).start()
    print("🚀 Bot đang chạy (v9.1)…")
    app.run_polling(drop_pending_updates=True)
