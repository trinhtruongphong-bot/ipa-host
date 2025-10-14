import os, time, base64, random, string, requests, zipfile, asyncio, telegram, nest_asyncio
from io import BytesIO
from urllib.parse import quote_plus
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

# =================== CONFIG ===================
BOT_TOKEN    = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO  = os.getenv("GITHUB_REPO", "trinhtruongphong-bot/ipa-host")
DOMAIN       = os.getenv("DOMAIN", "https://hehe-aoxct.onrender.com")
IPA_PATH     = "IPA"
PLIST_PATH   = "Plist"

# =================== UTILS ===================
def rand_name(n=6): return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))
def md(s): return str(s).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")

def gh_headers(): return {"Authorization": f"token {GITHUB_TOKEN}"}

async def auto_delete(ctx, chat, msg, delay=30):
    await asyncio.sleep(delay)
    try: await ctx.bot.delete_message(chat_id=chat, message_id=msg)
    except: pass

def shorten(url):
    try:
        r = requests.get(f"https://is.gd/create.php?format=simple&url={quote_plus(url)}", timeout=8)
        return r.text.strip() if r.ok and r.text.startswith("http") else url
    except: return url

# =================== IPA PARSING ===================
def parse_mobileprovision(zf):
    try:
        for name in zf.namelist():
            if name.lower().endswith("embedded.mobileprovision"):
                raw = zf.read(name)
                s, e = raw.find(b'<?xml'), raw.rfind(b'</plist>')
                if s == -1 or e == -1: return {}
                from plistlib import loads
                p = loads(raw[s:e+8])
                team = p.get("TeamName") or "Unknown"
                ent = p.get("Entitlements", {})
                appid = ent.get("application-identifier", "")
                bundle_from_ent = appid.split(".", 1)[1] if "." in appid else None
                return {"team": team, "bundle_from_ent": bundle_from_ent}
    except: pass
    return {}

def parse_plist(data):
    try:
        from plistlib import loads
        return loads(data)
    except Exception:
        try:
            from biplist import readPlistFromString
            return readPlistFromString(data)
        except: return None

def extract_info(ipa_bytes, filename):
    name, bundle, version, team = "Unknown", "unknown.bundle", "1.0", "Unknown"
    try:
        with zipfile.ZipFile(BytesIO(ipa_bytes)) as ipa:
            prov = parse_mobileprovision(ipa)
            team = prov.get("team", team)
            bundle_from_ent = prov.get("bundle_from_ent")
            best_meta, best_score = None, -999
            for path in ipa.namelist():
                if not path.lower().endswith("info.plist"): continue
                meta = parse_plist(ipa.read(path))
                if not meta: continue
                low, score = path.lower(), 0
                if "payload/" in low and ".app/" in low: score += 6
                if ".appex" in low: score -= 3
                if meta.get("CFBundleIdentifier"): score += 3
                if bundle_from_ent and meta.get("CFBundleIdentifier") == bundle_from_ent: score += 2
                if meta.get("CFBundlePackageType") == "APPL": score += 2
                if score > best_score:
                    best_score, best_meta = score, meta
            if best_meta:
                name    = best_meta.get("CFBundleDisplayName") or best_meta.get("CFBundleName") or name
                bundle  = best_meta.get("CFBundleIdentifier") or bundle
                version = best_meta.get("CFBundleShortVersionString") or best_meta.get("CFBundleVersion") or version
            elif "iTunesMetadata.plist" in ipa.namelist():
                from plistlib import loads
                mdp = loads(ipa.read("iTunesMetadata.plist"))
                name   = mdp.get("itemName") or name
                bundle = mdp.get("softwareVersionBundleId") or bundle
                version= mdp.get("bundleShortVersionString") or version
            if name == "Unknown": name = os.path.splitext(os.path.basename(filename))[0]
    except Exception as e:
        print("⚠️ Parse error:", e)
    return {"name": name, "bundle": bundle, "version": version, "team": team}

# =================== TELEGRAM BOT ===================
async def start(update, ctx):
    msg = await update.message.reply_text("👋 Gửi file `.ipa` để tạo link cài đặt iOS!")
    ctx.application.create_task(auto_delete(ctx, msg.chat_id, msg.message_id))

async def help_cmd(update, ctx):
    txt = "🧭 Lệnh hỗ trợ:\n/start - Bắt đầu\n/help - Trợ giúp\n\n📤 Gửi file `.ipa` để upload!"
    msg = await update.message.reply_text(txt)
    ctx.application.create_task(auto_delete(ctx, msg.chat_id, msg.message_id))

async def handle_ipa(update, ctx):
    doc = update.message.document
    if not doc.file_name.lower().endswith(".ipa"):
        msg = await update.message.reply_text("⚠️ Vui lòng gửi file `.ipa` hợp lệ!")
        ctx.application.create_task(auto_delete(ctx, msg.chat_id, msg.message_id))
        return

    msg = await update.message.reply_text("📤 Đang tải file IPA...")
    tg_file = await doc.get_file()
    data = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}", timeout=300).content
    info = extract_info(data, doc.file_name)
    rid = rand_name()

    ipa_path = f"{IPA_PATH}/{rid}.ipa"
    plist_path = f"{PLIST_PATH}/{rid}.plist"

    # Upload IPA lên GitHub
    requests.put(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{ipa_path}",
                 headers=gh_headers(),
                 json={"message": f"Upload {ipa_path}",
                       "content": base64.b64encode(data).decode()}, timeout=90)

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict>
<key>assets</key><array><dict><key>kind</key><string>software-package</string>
<key>url</key><string>{DOMAIN}/{ipa_path}</string></dict></array>
<key>metadata</key><dict>
<key>bundle-identifier</key><string>{info['bundle']}</string>
<key>bundle-version</key><string>{info['version']}</string>
<key>kind</key><string>software</string>
<key>title</key><string>{info['name']}</string>
</dict></dict></array></dict></plist>"""

    requests.put(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{plist_path}",
                 headers=gh_headers(),
                 json={"message": f"Upload {plist_path}",
                       "content": base64.b64encode(plist.encode()).decode()}, timeout=90)

    itms = f"itms-services://?action=download-manifest&url={DOMAIN}/{plist_path}"
    short = shorten(itms)

    await msg.edit_text(
        f"✅ **Upload thành công!**\n\n"
        f"📱 Tên ứng dụng: {md(info['name'])}\n"
        f"🆔 Bundle ID: {md(info['bundle'])}\n"
        f"🔢 Phiên bản: {md(info['version'])}\n"
        f"👥 Team: {md(info['team'])}\n\n"
        f"📦 [Tải IPA]({DOMAIN}/{ipa_path})\n"
        f"📲 [Cài trực tiếp]({short})",
        parse_mode="Markdown"
    )

# =================== MAIN (Render fix) ===================
if __name__ == "__main__":
    nest_asyncio.apply()  # vá vòng lặp event loop Render

    async def main():
        bot = telegram.Bot(BOT_TOKEN)
        await bot.delete_webhook(drop_pending_updates=True)  # auto clear webhook

        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_cmd))
        app.add_handler(MessageHandler(filters.Document.ALL, handle_ipa))

        # keep alive thread
        import threading
        threading.Thread(target=lambda: (requests.get(DOMAIN, timeout=10), time.sleep(50)), daemon=True).start()

        print("🚀 Bot đang chạy (Render version)…")
        await app.run_polling()

    asyncio.get_event_loop().run_until_complete(main())
