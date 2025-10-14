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

# =================== IPA ANALYZER ===================
def parse_mobileprovision(raw):
    try:
        s, e = raw.find(b'<?xml'), raw.rfind(b'</plist>')
        if s == -1 or e == -1: return {}
        from plistlib import loads
        p = loads(raw[s:e+8])
        team = p.get("TeamName") or "Unknown"
        appid = p.get("Entitlements", {}).get("application-identifier", "")
        appid = appid.split(".", 1)[1] if "." in appid else appid
        created = str(p.get("CreationDate", ""))[:19].replace("T", " ")
        expired = str(p.get("ExpirationDate", ""))[:19].replace("T", " ")
        appname = p.get("AppIDName") or "Unknown"
        return {
            "team": team,
            "appid": appid,
            "appname": appname,
            "created": created,
            "expired": expired
        }
    except Exception as e:
        print("⚠️ Parse provision error:", e)
        return {}

def parse_plist(data):
    try:
        from plistlib import loads
        return loads(data)
    except:
        try:
            from biplist import readPlistFromString
            return readPlistFromString(data)
        except: return None

def extract_info(ipa_bytes, filename):
    info = {"appname":"Unknown","bundle":"unknown.bundle","version":"1.0",
            "team":"Unknown","created":"-","expired":"-"}
    try:
        with zipfile.ZipFile(BytesIO(ipa_bytes)) as ipa:
            for name in ipa.namelist():
                if name.lower().endswith("embedded.mobileprovision"):
                    prov = parse_mobileprovision(ipa.read(name))
                    info.update(prov)
                    break

            best_meta, best_score = None, -999
            for path in ipa.namelist():
                if not path.lower().endswith("info.plist"): continue
                meta = parse_plist(ipa.read(path))
                if not meta: continue
                low, score = path.lower(), 0
                if "payload/" in low and ".app/" in low: score += 6
                if meta.get("CFBundleIdentifier"): score += 3
                if meta.get("CFBundlePackageType") == "APPL": score += 2
                if score > best_score: best_score, best_meta = score, meta
            if best_meta:
                info["appname"] = best_meta.get("CFBundleDisplayName") or best_meta.get("CFBundleName") or info["appname"]
                info["bundle"]  = best_meta.get("CFBundleIdentifier") or info["bundle"]
                info["version"] = best_meta.get("CFBundleShortVersionString") or best_meta.get("CFBundleVersion") or info["version"]
    except Exception as e:
        print("⚠️ Parse error:", e)
    return info

# =================== TELEGRAM BOT ===================
async def start(update, ctx):
    msg = await update.message.reply_text("👋 Gửi file `.ipa` để bot phân tích và tạo link cài đặt!")
    ctx.application.create_task(auto_delete(ctx, msg.chat_id, msg.message_id))

async def help_cmd(update, ctx):
    txt = "🧭 /start - Bắt đầu\n/help - Hướng dẫn\nGửi file `.ipa` để tạo link OTA"
    msg = await update.message.reply_text(txt)
    ctx.application.create_task(auto_delete(ctx, msg.chat_id, msg.message_id))

async def handle_ipa(update, ctx):
    doc = update.message.document
    if not doc.file_name.lower().endswith(".ipa"):
        msg = await update.message.reply_text("⚠️ Gửi file `.ipa` hợp lệ nhé!")
        ctx.application.create_task(auto_delete(ctx, msg.chat_id, msg.message_id))
        return

    msg = await update.message.reply_text("📤 Đang tải và phân tích IPA...")
    tg_file = await doc.get_file()
    data = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}", timeout=300).content
    info = extract_info(data, doc.file_name)
    rid = rand_name()

    ipa_path = f"{IPA_PATH}/{rid}.ipa"
    plist_path = f"{PLIST_PATH}/{rid}.plist"

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
<key>title</key><string>{info['appname']}</string>
</dict></dict></array></dict></plist>"""

    requests.put(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{plist_path}",
                 headers=gh_headers(),
                 json={"message": f"Upload {plist_path}",
                       "content": base64.b64encode(plist.encode()).decode()}, timeout=90)

    itms = f"itms-services://?action=download-manifest&url={DOMAIN}/{plist_path}"
    short = shorten(itms)

    await msg.edit_text(
        f"✅ **Upload thành công!**\n\n"
        f"📱 App Name: {md(info['appname'])}\n"
        f"🆔 Package Name: {md(info['bundle'])}\n"
        f"🔢 Version: {md(info['version'])}\n"
        f"👥 Team Name: {md(info['team'])}\n"
        f"📅 Cert: {md(info['created'])} → {md(info['expired'])}\n\n"
        f"📦 [Tải IPA]({DOMAIN}/{ipa_path})\n"
        f"📲 [Cài trực tiếp]({short})",
        parse_mode="Markdown"
    )

# =================== MAIN ===================
if __name__ == "__main__":
    nest_asyncio.apply()
    async def main():
        bot = telegram.Bot(BOT_TOKEN)
        await bot.delete_webhook(drop_pending_updates=True)

        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_cmd))
        app.add_handler(MessageHandler(filters.Document.ALL, handle_ipa))

        import threading
        threading.Thread(target=lambda: (requests.get(DOMAIN, timeout=10), time.sleep(50)), daemon=True).start()

        print("🚀 Bot Certificate Parser đang chạy trên Render...")
        await app.run_polling()

    asyncio.get_event_loop().run_until_complete(main())
