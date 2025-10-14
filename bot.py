import telebot, os, tempfile, random, string, plistlib
from dotenv import load_dotenv
from utils import extract_info, upload_to_github, shorten_url, list_github_files, delete_github_file

load_dotenv()
bot = telebot.TeleBot(os.getenv("BOT_TOKEN"))
GITHUB_REPO = os.getenv("GITHUB_REPO")

def random_code(length=5):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# ----------------- UPLOAD IPA -----------------
@bot.message_handler(content_types=['document'])
def handle_ipa(message):
    try:
        # Tin nhắn tạm
        temp_msg = bot.send_message(message.chat.id, f"📦 Đang xử lý `{message.document.file_name}`...", parse_mode="Markdown")

        file_info = bot.get_file(message.document.file_id)
        file_data = bot.download_file(file_info.file_path)
        code = random_code()

        ipa_name = f"{code}.ipa"
        plist_name = f"{code}.plist"
        temp_ipa = os.path.join(tempfile.gettempdir(), ipa_name)

        # Lưu file IPA tạm
        with open(temp_ipa, "wb") as f:
            f.write(file_data)

        # Phân tích thông tin IPA
        info = extract_info(temp_ipa)
        app_name = info.get('name', 'Unknown')
        bundle = info.get('bundle', 'unknown.bundle')
        version = info.get('version', '1.0')
        team = info.get('team', 'Unknown')

        # Upload IPA → iPA/
        ipa_url = upload_to_github(temp_ipa, folder="iPA", rename=ipa_name)

        # Tạo file plist → plist/
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

        # Link cài trực tiếp (rút gọn)
        install_link = f"itms-services://?action=download-manifest&url={plist_url}"
        short_install = shorten_url(install_link)

        # Gửi kết quả
        msg = f"""
✅ **Upload thành công!**

📱 **Tên ứng dụng:** {app_name}
🆔 **Bundle ID:** `{bundle}`
🔢 **Phiên bản:** {version}
👥 **Team:** {team}

📦 [Tải IPA]({ipa_url})
📲 [Cài trực tiếp]({short_install})
🆔 Mã tệp: `{code}`
"""
        bot.send_message(message.chat.id, msg, parse_mode="Markdown")

        # Xoá tin tạm
        bot.delete_message(message.chat.id, temp_msg.id)

        # Dọn file tạm
        os.remove(temp_ipa)
        os.remove(temp_plist)

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Lỗi xử lý IPA: {e}")

# ----------------- LIST FILES -----------------
@bot.message_handler(commands=['listipa'])
def list_ipa(message):
    temp_msg = bot.send_message(message.chat.id, "🔍 Đang tải danh sách iPA...")
    files = list_github_files("iPA")
    bot.delete_message(message.chat.id, temp_msg.id)

    if not files:
        bot.send_message(message.chat.id, "❌ Không tìm thấy file IPA nào.")
        return

    for file in files:
        fname = file['name']
        url = file['download_url']
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🗑️ Xoá", callback_data=f"del|iPA|{fname}"))
        bot.send_message(message.chat.id, f"📦 `{fname}`\n🔗 {url}", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['listplist'])
def list_plist(message):
    temp_msg = bot.send_message(message.chat.id, "🔍 Đang tải danh sách plist...")
    files = list_github_files("plist")
    bot.delete_message(message.chat.id, temp_msg.id)

    if not files:
        bot.send_message(message.chat.id, "❌ Không tìm thấy file plist nào.")
        return

    for file in files:
        fname = file['name']
        url = file['download_url']
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🗑️ Xoá", callback_data=f"del|plist|{fname}"))
        bot.send_message(message.chat.id, f"🧾 `{fname}`\n🔗 {url}", parse_mode="Markdown", reply_markup=markup)

# ----------------- DELETE FILE -----------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("del|"))
def delete_file(call):
    _, folder, fname = call.data.split("|")
    try:
        success = delete_github_file(folder, fname)
        if success:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.id,
                                  text=f"🗑️ Đã xoá `{fname}` khỏi `{folder}/`", parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Xoá thất bại hoặc file không tồn tại.")
    except Exception as e:
        bot.answer_callback_query(call.id, f"Lỗi xoá file: {e}")

print("🤖 Bot đang chạy...")
bot.polling(non_stop=True)
