import math
import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

async def download_with_progress(session, file_url, total_size, message):
    downloaded = 0
    chunks = []
    async with session.get(file_url) as resp:
        async for chunk in resp.content.iter_chunked(1024 * 1024):  # 1MB
            chunks.append(chunk)
            downloaded += len(chunk)
            percent = math.floor(downloaded / total_size * 100)
            if percent % 10 == 0:
                try:
                    await message.edit_text(f"⬆️ Đang tải từ Telegram: {percent}%")
                except:
                    pass
    return b"".join(chunks)

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document
    file_name = file.file_name
    total_size = file.file_size

    # Báo nhận file
    msg = await update.message.reply_text(f"📦 Đã nhận file `{file_name}`, đang tải lên...", parse_mode="Markdown")

    # Lấy link tải file Telegram
    getfile = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": file.file_id}).json()
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{getfile['result']['file_path']}"

    # Tải file theo phần trăm
    async with aiohttp.ClientSession() as session:
        ipa_bytes = await download_with_progress(session, file_url, total_size, msg)

    # Khi tải xong thì báo đang upload lên GitHub
    await msg.edit_text("📤 Đang upload lên GitHub...")

    # Upload file lên GitHub (phần code upload cũ giữ nguyên)
    encoded_content = base64.b64encode(ipa_bytes).decode('utf-8')
    github_api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/iPA/{file_name}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    data = {
        "message": f"Upload {file_name}",
        "content": encoded_content,
        "branch": "main"
    }

    upload = requests.put(github_api, headers=headers, json=data)
    if upload.status_code in [200, 201]:
        ipa_url = f"https://download.khoindvn.io.vn/iPA/{file_name}"
        await msg.edit_text(f"✅ **Upload thành công {file_name}**\n📲 Link tải: {ipa_url}", parse_mode="Markdown")
    else:
        await msg.edit_text(f"❌ Lỗi upload GitHub: {upload.status_code}")
