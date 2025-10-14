import os, time, base64, random, string, requests, zipfile, asyncio, telegram
from io import BytesIO
from urllib.parse import quote_plus
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# =================== CONFIG ===================
BOT_TOKEN      = os.getenv("BOT_TOKEN")
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN")
GITHUB_REPO    = os.getenv("GITHUB_REPO", "trinhtruongphong-bot/ipa-host")
DOMAIN         = os.getenv("DOMAIN", "https://hehe-aoxct.onrender.com")
IPA_PATH       = os.getenv("IPA_DIR", "IPA")
PLIST_PATH     = os.getenv("PLIST_DIR", "Plist")
AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "30"))
CDN_SYNC_SECONDS    = int(os.getenv("CDN_SYNC_SECONDS", "30"))

# =================== UTILS ===================
def rname(n=6): return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))
def md_escape_v1(s): return str(s).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")

async def auto_delete(ctx, chat_id, msg_id, delay=AUTO_DELETE_SECONDS):
    await asyncio.sleep(delay)
    try: await ctx.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except: pass

def gh_headers(): return {"Authorization": f"token {GITHUB_TOKEN}"}

def github_list(path):
    r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}", headers=gh_headers(), timeout=30)
    return [x["name"] for x in r.json()] if r.status_code == 200 else []

def github_delete(path):
    g = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}", headers=gh_headers(), timeout=30)
    if g.status_code != 200: return False
    sha = g.json()["sha"]
    r = requests.delete(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
                        headers=gh_headers(), json={"message": f"delete {path}", "sha": sha}, timeout=30)
    return r.status_code == 200

def shorten_itms(url):
    try:
        r = requests.get(f"https://is.gd/create.php?format=simple&url={quote_plus(url, safe='')}", timeout=8)
        return r.text.strip() if r.status_code == 200 and r.text.startswith("http") else None
    except: return None

# =================== IPA PARSING ===================
def _read_mobileprovision(zf):
    try:
        for name in zf.namelist():
            if name.lower().endswith("embedded.mobileprovision"):
                print(f"📄 [DEBUG] Found provisioning: {name}")
                raw = zf.read(name)
                s = raw.find(b'<?xml'); e = raw.rfind(b'</plist>')
                if s == -1 or e == -1: 
                    print("⚠️ [DEBUG] Invalid mobileprovision XML structure")
                    return {}
                from plistlib import loads
                p = loads(raw[s:e+8])
                ent = p.get("Entitlements", {}) or {}
                appid = ent.get("application-identifier", "")
                team_name = p.get("TeamName") or "Unknown"
                bundle_from_ent = appid.split(".", 1)[1] if appid and "." in appid else None
                print(f"👥 [DEBUG] TeamName={team_name}, BundleFromEnt={bundle_from_ent}")
                return {"team": team_name, "bundle_from_entitlements": bundle_from_ent}
    except Exception as ex:
        print("⚠️ [DEBUG] mobileprovision parse error:", ex)
    return {}

def _parse_plist(data):
    try:
        from plistlib import loads
        return loads(data)
    except Exception:
        try:
            from biplist import readPlistFromString
            return readPlistFromString(data)
        except Exception:
            return None

def extract_info_from_ipa(ipa_bytes: bytes, file_name="Unknown.ipa"):
    name, bundle, version, team = "Unknown", "unknown.bundle", "1.0", "Unknown"
    try:
        print(f"📦 [DEBUG] Opening IPA: {file_name}")
        with zipfile.ZipFile(BytesIO(ipa_bytes)) as ipa:
            prov = _read_mobileprovision(ipa)
            team = prov.get("team", team)
            bundle_from_ent = prov.get("bundle_from_entitlements")
            print(f"🔍 [DEBUG] Searching Info.plist files...")
            best_meta, best_score = None, -9999

            for path in ipa.namelist():
                if not path.lower().endswith("info.plist"): 
                    continue
                meta = _parse_plist(ipa.read(path))
                if not isinstance(meta, dict): 
                    continue
                low = path.lower(); score = 0
                if "payload/" in low and ".app/" in low: score += 6
                if ".appex/" in low or "extension" in low: score -= 6
                if meta.get("CFBundleIdentifier"): score += 4
                if bundle_from_ent and meta.get("CFBundleIdentifier") == bundle_from_ent: score += 3
                if meta.get("CFBundlePackageType") == "APPL": score += 4
                if meta.get("CFBundleExecutable"): score += 1
                if score > best_score:
                    best_score, best_meta = score, meta
                    print(f"🧩 [DEBUG] Found better Info.plist: {path} (score={score})")

            if best_meta:
                name    = best_meta.get("CFBundleDisplayName") or best_meta.get("CFBundleName") or name
                bundle  = best_meta.get("CFBundleIdentifier") or bundle
                version = best_meta.get("CFBundleShortVersionString") or best_meta.get("CFBundleVersion") or version
                print(f"✅ [DEBUG] Info.plist result: {name}, {bundle}, {version}")
            else:
                print("⚠️ [DEBUG] No Info.plist found, trying iTunesMetadata.plist...")
                if "iTunesMetadata.plist" in ipa.namelist():
                    from plistlib import loads
                    md = loads(ipa.read("iTunesMetadata.plist"))
                    name   = md.get("itemName") or md.get("bundleDisplayName") or name
                    bundle = md.get("softwareVersionBundleId") or bundle
                    version= md.get("bundleShortVersionString") or version
                    print(f"✅ [DEBUG] Got from iTunesMetadata: {name}, {bundle}, {version}")
                else:
                    print("❌ [DEBUG] No iTunesMetadata.plist found either.")

            if name == "Unknown" and file_name:
                name = os.path.splitext(os.path.basename(file_name))[0]
                print(f"🪪 [DEBUG] Using filename as app name: {name}")

    except Exception as e:
        print("❌ [DEBUG] IPA parse error:", e)

    print(f"📦 [FINAL DEBUG] name={name}, bundle={bundle}, version={version}, team={team}")
    return {"name": name, "bundle": bundle, "version": version, "team": team}

# =================== GITHUB UPLOAD ===================
async def _edit_progress(msg, label, pct):
    try: await msg.edit_text(f"{label}: {pct}%")
    except: pass

async def github_upload_with_progress(path, raw, msg, label="⬆️ Upload GitHub"):
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
    r = requests.put(url, headers=gh_headers(), json=payload, timeout=180)
    await _edit_progress(msg, label, 100)
    return r.status_code in (200, 201)

# =================== TELEGRAM COMMANDS ===================
async def cmd_start(update, context):
    msg = await update.message.reply_text("👋 Gửi file `.ipa` để upload và tạo link cài đặt iOS.\\nGõ /help để xem hướng dẫn.")
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def cmd_help(update, context):
    msg = await update.message.reply_text("🧭 Lệnh:\\n/listipa – Danh sách IPA\\n/listplist – Danh sách Plist\\n/help – Hướng dẫn\\n\\n📤 Gửi file `.ipa` để upload!")
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def _list(update, context, path, label):
    files = github_list(path)
    if not files:
        msg = await update.message.reply_text(f"📂 Không có file {label}.")
        context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return
    kb = [[InlineKeyboardButton(f"{f} 🗑️", callback_data=f"delete|{path}|{f}")] for f in files]
    msg = await update.message.reply_text(f"📦 Danh sách {label}:", reply_markup=InlineKeyboardMarkup(kb))
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def cmd_listipa(update, context): await _list(update, context, IPA_PATH, "IPA")
async def cmd_listplist(update, context): await _list(update, context, PLIST_PATH, "Plist")

async def handle_delete(update, context):
    q = update.callback_query; await q.answer()
    _, path, fname = q.data.split("|")
    ok = github_delete(f"{path}/{fname}")
    await q.edit_message_text(f"✅ Đã xoá `{md_escape_v1(fname)}` khỏi `{path}/`" if ok else f"❌ Không thể xoá `{md_escape_v1(fname)}`", parse_mode="Markdown")

# =================== HANDLE IPA ===================
async def handle_file(update, context):
    doc = update.message.document
    if not doc.file_name.lower().endswith(".ipa"):
        msg = await update.message.reply_text("⚠️ Vui lòng gửi file `.ipa` hợp lệ!")
        context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return

    msg = await update.message.reply_text("📤 Đang nhận file IPA…")
    tg_file = await doc.get_file()
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}"
    r = requests.get(file_url, stream=True, timeout=600)
    buf = BytesIO(); [buf.write(c) for c in r.iter_content(chunk_size=524288)]
    ipa_bytes = buf.getvalue()
    print(f"📩 [DEBUG] IPA size: {len(ipa_bytes)} bytes")

    await msg.edit_text("✅ Đã nhận xong. Đang phân tích…")
    info = extract_info_from_ipa(ipa_bytes, doc.file_name)
    await msg.edit_text("✅ Phân tích xong. Đang upload GitHub…")

    rid = rname(); ipa_key = f"{IPA_PATH}/{rid}.ipa"; plist_key = f"{PLIST_PATH}/{rid}.plist"
    ok = await github_upload_with_progress(ipa_key, ipa_bytes, msg, "⬆️ Upload GitHub (IPA)")
    if not ok:
        err = await update.message.reply_text("❌ Upload IPA lên GitHub thất bại.")
        context.application.create_task(auto_delete(context, err.chat_id, err.message_id)); return

    ipa_url, plist_url = f"{DOMAIN}/{ipa_key}", f"{DOMAIN}/{plist_key}"
    plist_template = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict>
<key>assets</key><array><dict><key>kind</key><string>software-package</string>
<key>url</key><string>__IPA__</string></dict></array>
<key>metadata</key><dict>
<key>bundle-identifier</key><string>__PACKAGE__</string>
<key>bundle-version</key><string>__VERSION__</string>
<key>kind</key><string>software</string>
<key>title</key><string>__NAME__</string>
</dict></dict></array></dict></plist>"""

    plist = (plist_template.replace("__IPA__", ipa_url)
                          .replace("__PACKAGE__", info['bundle'])
                          .replace("__VERSION__", info['version'])
                          .replace("__NAME__", info['name']))

    requests.put(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{plist_key}",
                 headers=gh_headers(),
                 json={"message": f"Upload {plist_key}", "content": base64.b64encode(plist.encode()).decode()},
                 timeout=60)

    await asyncio.sleep(CDN_SYNC_SECONDS)
    itms = f"itms-services://?action=download-manifest&url={plist_url}"
    link_display = shorten_itms(itms) or itms

    lines = [
        "✅ **Upload thành công!**\\n",
        f"📱 **Tên ứng dụng:** {md_escape_v1(info['name'])}",
        f"🆔 **Bundle ID:** {md_escape_v1(info['bundle'])}",
        f"🔢 **Phiên bản:** {md_escape_v1(info['version'])}",
        f"👥 **Team:** {md_escape_v1(info['team'])}\\n",
        f"📦 **Tải IPA:** {ipa_url}",
        f"📲 **Cài trực tiếp:** {link_display}",
    ]
    await msg.edit_text("\\n".join(lines), parse_mode="Markdown")

# =================== MAIN ===================
if __name__ == "__main__":
    import threading

    async def startup():
        bot = telegram.Bot(BOT_TOKEN)
        await bot.delete_webhook(drop_pending_updates=True)
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("listipa", cmd_listipa))
        app.add_handler(CommandHandler("listplist", cmd_listplist))
        app.add_handler(CallbackQueryHandler(handle_delete))
        app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
        threading.Thread(target=lambda: (requests.get(DOMAIN, timeout=10), time.sleep(50)), daemon=True).start()
        print("🚀 Bot đang chạy (TeamName + Debug + Auto webhook clear + FixLoop)…")
        await app.run_polling()

    asyncio.run(startup())
