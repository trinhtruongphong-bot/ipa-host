# ==========================================================
# app.py — Flask API + Telegram Webhook cho Render
# ==========================================================
# - /upload: nhận file IPA, phân tích, upload GitHub
# - /webhook/<BOT_TOKEN>: nhận update từ Telegram (Webhook)
# - Tự động đăng ký webhook khi khởi động
# ==========================================================

import os
import tempfile
import random
import string
import requests
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application
from ipa_utils import extract_ipa_info
from github_uploader import upload_to_github

# ----------------------------------------------------------
# 🔧 Cấu hình cơ bản
# ----------------------------------------------------------
app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
REPO = os.getenv("GITHUB_REPO")
BRANCH = os.getenv("GITHUB_BRANCH", "main")

# ⚠️ Cập nhật domain theo Render của bạn
DOMAIN = "https://hehe-aoxt.onrender.com"
WEBHOOK_URL = f"{DOMAIN}/webhook/{BOT_TOKEN}"

# Khởi tạo Telegram Application
telegram_app = Application.builder().token(BOT_TOKEN).build()

# ----------------------------------------------------------
# 1️⃣ API /upload — nhận file IPA và tạo link tải
# ----------------------------------------------------------
@app.route("/upload", methods=["POST"])
def upload_ipa():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    ipa_file = request.files["file"]
    temp_path = os.path.join(tempfile.gettempdir(), ipa_file.filename)
    ipa_file.save(temp_path)

    # 🧩 Phân tích IPA
    info = extract_ipa_info(temp_path)

    # Random tên file
    ipa_name = "".join(random.choices(string.ascii_lowercase + string.digits, k=6)) + ".ipa"
    plist_name = ipa_name.replace(".ipa", ".plist")

    # Upload IPA lên GitHub
    with open(temp_path, "rb") as f:
        ipa_url = upload_to_github(f"iPA/{ipa_name}", f.read())

    # Tạo file PLIST
    plist_content = f"""
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
        <key>items</key>
        <array>
            <dict>
                <key>assets</key>
                <array>
                    <dict>
                        <key>kind</key><string>software-package</string>
                        <key>url</key><string>{ipa_url}</string>
                    </dict>
                </array>
                <key>metadata</key>
                <dict>
                    <key>bundle-identifier</key><string>{info['bundle_id']}</string>
                    <key>bundle-version</key><string>{info['version']}</string>
                    <key>kind</key><string>software</string>
                    <key>title</key><string>{info['app_name']}</string>
                </dict>
            </dict>
        </array>
    </dict>
    </plist>
    """.strip()

    plist_url = upload_to_github(f"Plist/{plist_name}", plist_content)

    # Link cài trực tiếp (rút gọn)
    install_url = f"itms-services://?action=download-manifest&url={plist_url}"
    try:
        short_url = requests.get(f"https://is.gd/create.php?format=simple&url={install_url}").text
    except:
        short_url = install_url

    return jsonify({
        "app_name": info["app_name"],
        "bundle_id": info["bundle_id"],
        "version": info["version"],
        "team_name": info["team_name"],
        "ipa_url": ipa_url,
        "install_url": short_url
    })

# ----------------------------------------------------------
# 2️⃣ Webhook — nhận tin nhắn Telegram
# ----------------------------------------------------------
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), telegram_app.bot)
        telegram_app.update_queue.put_nowait(update)
    except Exception as e:
        print("❌ Webhook error:", e)
    return "OK", 200

# ----------------------------------------------------------
# 3️⃣ Auto đăng ký webhook khi khởi động
# ----------------------------------------------------------
@app.before_first_request
def set_webhook():
    try:
        print("🌍 Đang đăng ký webhook với Telegram ...")
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        data = {"url": WEBHOOK_URL}
        res = requests.post(url, data=data)
        print("✅ Kết quả:", res.text)
    except Exception as e:
        print("❌ Lỗi setWebhook:", e)

# ----------------------------------------------------------
# 4️⃣ Chạy server Flask
# ----------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Server Flask + Webhook khởi động ...")
    app.run(host="0.0.0.0", port=5000)
