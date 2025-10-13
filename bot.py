import os, time, base64, random, string, requests, zipfile, asyncio
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
GITHUB_REPO = "trinhtruongphong-bot/ipa-host"   # repo chứa IPA/Plist
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DOMAIN = "https://download.khoindvn.io.vn"      # domain public

IPA_PATH = "IPA"
PLIST_PATH = "Plist"

AUTO_DELETE_SECONDS = 3      # xoá tin nhắn phụ
CDN_SYNC_SECONDS    = 30     # đợi CDN đồng bộ

# ================== HELPERS ==================
def random_name(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def _candidate_info_plists(zf: zipfile.ZipFile):
    """Trả về list tất cả Info.plist dưới Payload/**.app/Info.plist (không phân biệt hoa/thường)."""
    cands = []
    for name in zf.namelist():
        low = name.lower()
        if low.startswith("payload/") and low.endswith("info.plist") and ".app/" in low:
            cands.append(name)
    return cands

def _read_plist_bytes(b: bytes):
    """Đọc plist (binary/XML)."""
    from plistlib import loads
    return loads(b)

def _read_mobileprovision(zf: zipfile.ZipFile):
    """Team + Bundle fallback từ embedded.mobileprovision."""
    try:
        for name in zf.namelist():
            if name.lower().endswith("embedded.mobileprovision"):
                raw = zf.read(name)
                s = raw.find(b'<?xml'); e = raw.rfind(b'</plist>')
                if s == -1 or e == -1:
                    return {}
                p = _read_plist_bytes(raw[s:e+8])
                ent = p.get("Entitlements", {}) or {}

                appid = ent.get("application-identifier", "")
                team_name = p.get("TeamName")
                team_id_list = p.get("TeamIdentifier")
                prefix_list  = p.get("ApplicationIdentifierPrefix")

                team_from_list   = (team_id_list[0] if isinstance(team_id_list, list) and team_id_list else None)
                prefix_from_list = (prefix_list[0]  if isinstance(prefix_list,  list) and prefix_list  else None)

                bundle_from_ent = None
                if appid and "." in appid:
                    bundle_from_ent = appid.split(".", 1)[1]

                team = team_name or team_from_list or prefix_from_list or "Unknown"
                return {"team": team, "bundle_from_entitlements": bundle_from_ent}
    except Exception as ex:
        print("⚠️ mobileprovision parse error:", ex)
    return {}

def extract_info_from_ipa(ipa_bytes: bytes):
    """
    Chọn Info.plist tốt nhất:
      1) Ưu tiên file có CFBundlePackageType == 'APPL'
      2) Nếu không có, chọn đường dẫn .app/Info.plist ngắn nhất
    Fallback:
      - embedded.mobileprovision (team + bundle)
      - iTunesMetadata.plist (name/bundle/version)
    """
    name = "Unknown"; bundle = "unknown.bundle"; version = "1.0"; team = "Unknown"

    try:
        with zipfile.ZipFile(BytesIO(ipa_bytes)) as zf:
            best_plist_name = None
            best_plist_obj  = None
            chosen_by_appl  = False

            # Tập ứng cử viên
            cands = _candidate_info_plists(zf)
            # Duyệt các Info.plist, ưu tiên 'APPL'
            for path in cands:
                try:
                    p = _read_plist_bytes(zf.read(path))
                    pkg = p.get("CFBundlePackageType")
                    if pkg == "APPL":
                        best_plist_name = path
                        best_plist_obj  = p
                        chosen_by_appl  = True
                        break
                    # Nếu chưa có, ghi nhớ tạm path ngắn nhất
                    if best_plist_name is None or len(path) < len(best_plist_name):
                        best_plist_name = path
                        best_plist_obj  = p
                except Exception as ex:
                    print(f"⚠️ lỗi đọc {path}:", ex)

            # Nếu có ứng cử viên
            if best_plist_obj:
                name   = best_plist_obj.get("CFBundleDisplayName") or best_plist_obj.get("CFBundleName") or name
                bundle = best_plist_obj.get("CFBundleIdentifier") or bundle
                version = (best_plist_obj.get("CFBundleShortVersionString")
                           or best_plist_obj.get("CFBundleVersion")
                           or version)
                print(f"ℹ️ Info.plist chọn: {best_plist_name} (APPL={chosen_by_appl})")
            else:
                print("⚠️ Không tìm thấy Info.plist hợp lệ trong IPA.")

            # Fallback: embedded.mobileprovision
            prov = _read_mobileprovision(zf)
            if prov:
                team = prov.get("team") or team
                if bundle == "unknown.bundle" and prov.get("bundle_from_entitlements"):
                    bundle = prov["bundle_from_entitlements"]

            # Fallback thêm: iTunesMetadata.plist
            try:
                if name == "Unknown" or bundle == "unknown.bundle" or version == "1.0":
                    if "iTunesMetadata.plist" in zf.namelist():
                        meta = _read_plist_bytes(zf.read("iTunesMetadata.plist"))
                        name = meta.get("itemName") or meta.get("bundleDisplayName") or name
                        if bundle == "unknown.bundle":
                            bundle = meta.get("softwareVersionBundleId") or bundle
                        if version == "1.0":
                            version = meta.get("bundleShortVersionString") or version
            except Exception as _:
                pass

    except Exception as e:
        print("❌ Lỗi đọc IPA tổng:", e)

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
    """Ước lượng % upload GitHub: encode base64 theo chunk + PUT 1 lần."""
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    total = len(raw_bytes)
    chunk = 1024 * 1024
    parts = []; done = 0; last = -1
    for i in range(0, total, chunk):
        part = base64.b64encode(raw_bytes[i:i+chunk]).decode()
        parts.append(part)
        done += min(chunk, total - i)
        pct = int(done * 100 / total); step = pct // 5
        if step > last:
            last = step
            await edit_progress(msg, label, min(pct, 95))
        await asyncio.sleep(0)
    payload = {"message": f"Upload {path}", "content": ''.join(parts)}
    try:
        r = requests.put(url, headers=headers, json=payload, timeout=180)
        await edit_progress(msg, label, 100)
        return r.status_code in [200, 201]
    except Exception as e:
        print("❌ PUT GitHub lỗi:", e)
        return False

# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "👋 Xin chào!\nGửi file `.ipa` để upload và tạo link cài đặt iOS.\nGõ /help để xem hướng dẫn."
    )
    context.application.create_task(auto_delete(context, msg.chat_id, msg.message_id))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        "🧭 Lệnh:\n/listipa – Danh sách IPA (kèm nút xoá)\n/listplist – Danh sách Plist (kèm nút xoá)\n/help – Hướng dẫn\n\n📤 Gửi file `.ipa` để upload!"
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
        f"✅ Đã xoá `{filename}` khỏi `{path}/`" if ok else f"❌
