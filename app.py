# ==========================================================
# app.py — Flask API + Telegram Webhook (Render)
# ==========================================================
# - /upload : nhận file IPA, xử lý, upload GitHub
# - /webhook/<BOT_TOKEN> : nhận update từ Telegram
# ==========================================================

import os
import tempfile
import requests
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application
from ipa_utils import extract_ipa_info
from github_uploader import upload_to_github
import base64
import random
import string
import json

app = Flask(__name__)

# === ENV CONFIG ===
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
REPO = os.getenv("GITHUB_REPO")
BRANCH = os.getenv("GITHUB_BRANCH", "main")
WEBHOOK_URL = f"https://hehe-aoxt.onrender.com/webhook/{BOT_TOKEN}"  # 👉 thay domain nếu khác

# Tạo Telegram Application (webhook mode)
telegram_app = Application.builder().token(BOT_TOKEN).build()

# ==========================================================
# 1️⃣ ROUTE: /upload (xử lý IPA)
# ==========================================================
@app.route("/upload", methods=["POST"])
def upload_ipa():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    ipa_file = request.files["file"]
    temp_path = os.path.join(tempfile.gettempdir(), ipa_file.filename)
    ipa_file.save(temp_path)

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

# ==========================================================
# 2️⃣ ROUTE: /webhook/<BOT_TOKEN>
# ==========================================================
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), telegram_app.bot)
        telegram_app.update_queue.put_nowait(update)
    except Exception as e:
        print("❌ Webhook error:", e)
    return "OK", 200

# ==========================================================
# 3️⃣ KHỞI ĐỘNG SERVER + ĐĂNG KÝ WEBHOOK
# ==========================================================
if __name__ == "__main__":
    print("🚀 Starting Flask + Telegram Webhook Server...")
    # Đăng ký webhook với Telegram
    res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}")
    print("🌍 Webhook set:", res.text)
    app.run(host="0.0.0.0", port=5000)
