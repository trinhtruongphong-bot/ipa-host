import telebot, os, tempfile, random, string, plistlib, re
from dotenv import load_dotenv
from utils import extract_info, upload_to_github, shorten_url, list_github_files, delete_github_file

load_dotenv()
bot = telebot.TeleBot(os.getenv("BOT_TOKEN"))
GITHUB_REPO = os.getenv("GITHUB_REPO")

def random_code(length=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# Escape ký tự đặc biệt MarkdownV2
def escape_md(text):
    if not text:
        return ''
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))

# ----------------- UPLOAD IPA -----------------
@bot.message_handler(content_types=['document'])
def handle_ipa(message):
    try:
        temp_msg = bot.send_message(message.chat.id, f"📦 Đang xử lý `{escape_md(message.document.file_name)}`...", parse_mode="MarkdownV2")

        file_info = bot.get_file(message.document.file_id)
        file_data = bot.download_file(file_info.file_path)
        code = random_code()

        ipa_name = f"{code}.ipa"
        plist_name = f"{code}.plist"
        temp_ipa = os.path.join(tempfile.gettempdir(), ipa_name)

        with open(temp_ipa, "wb") as f:
            f.write(file_data)

        info = extract_info(temp_ipa)
        app_name = info.get('name', 'Unknown')
        bundle = info.get('bundle', 'unknown.bundle')
        version = info.get('version', '1.0')
        team = info.get('team', 'Unknown')

        ipa_url = upload_to_github(temp_ipa, folder="iPA", rename=ipa_name)

        temp_plist = os.path.join(tempfile.gettempdir(), plist_name)
        manifest = {
            "items": [{
                "assets": [{"kind": "software-package", "url": ipa_url}],
                "metadata": {
                    "bundle-identifier": bundle,
                    "bundle-version": version,
                    "kind": "software",
                    "title": app_name
                }
            }]
        }
        with open(temp_plist, 'wb') as f:
            plistlib.dump(manifest, f)

        plist_url = upload_to_github(temp_plist, folder="plist", rename=plist_name)
        install_link = f"itms-services://?action=download-manifest&url={plist_url}"
        short_install = shorten_url(install_link)

        msg = f"""
✅ *Upload thành công\!*

📱 *Tên ứng dụng:* {escape_md(app_name)}
🆔 *Bundle ID:* `{escape_md(bundle)}`
🔢 *Phiên bản:* {escape_md(version)}
👥 *Team:* {escape_md(team)}

📦 [Tải IPA]({escape_md(ipa_url)})
📲 [Cài trực tiếp]({escape_md(short_install)})
🆔 *Mã tệp:* `{escape_md(code)}`
"""

        bot.send_message(message.chat.id, msg, parse_mode="MarkdownV2")
        bot.delete_message(message.chat.id, temp_msg.id)
        os.remove(temp_ipa)
        os.remove(temp_plist)

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Lỗi xử lý IPA: {escape_md(str(e))}", parse_mode="MarkdownV2")

# ----------------- LIST FILES -----------------
@bot.message_handler(commands=['listipa'])
def list_ipa(message):
    temp_msg = bot.send_message(message.chat.id, "🔍 Đang tải danh sách iPA...", parse_mode="MarkdownV2")
    files = list_github_files("iPA")
    bot.delete_message(message.chat.id, temp_msg.id)

    if not files:
        bot.send_message(message.chat.id, "❌ Không tìm thấy file IPA nào.", parse_mode="MarkdownV2")
        return

    for file in files:
        fname = escape_md(file['name'])
        url = escape_md(file['download_url'])
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🗑️ Xoá", callback_data=f"del|iPA|{file['name']}"))
        bot.send_message(message.chat.id, f"📦 `{fname}`\n🔗 {url}", parse_mode="MarkdownV2", reply_markup=markup)

@bot.message_handler(commands=['listplist'])
def list_plist(message):
    temp_msg = bot.send_message(message.chat.id, "🔍 Đang tải danh sách plist...", parse_mode="MarkdownV2")
    files = list_github_files("plist")
    bot.delete_message(message.chat.id, temp_msg.id)

    if not files:
        bot.send_message(message.chat.id, "❌ Không tìm thấy file plist nào.", parse_mode="MarkdownV2")
        return

    for file in files:
        fname = escape_md(file['name'])
        url = escape_md(file['download_url'])
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🗑️ Xoá", callback_data=f"del|plist|{file['name']}"))
        bot.send_message(message.chat.id, f"🧾 `{fname}`\n🔗 {url}", parse_mode="MarkdownV2", reply_markup=markup)

# ----------------- DELETE -----------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("del|"))
def delete_file(call):
    _, folder, fname = call.data.split("|")
    try:
        success = delete_github_file(folder, fname)
        if success:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.id,
                                  text=f"🗑️ Đã xoá `{escape_md(fname)}` khỏi `{escape_md(folder)}/`", parse_mode="MarkdownV2")
        else:
            bot.answer_callback_query(call.id, "❌ Xoá thất bại hoặc file không tồn tại.")
    except Exception as e:
        bot.answer_callback_query(call.id, f"Lỗi xoá file: {e}")

print("🤖 Bot đang chạy...")
bot.polling(non_stop=True)
