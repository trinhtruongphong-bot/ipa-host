# ==========================================================
# app.py — Flask server chính cho IPA Upload API
# ==========================================================
# Nhiệm vụ:
# - Nhận file .ipa qua /upload
# - Phân tích thông tin IPA (app name, bundle ID, version, team name)
# - Random tên file
# - Upload .ipa và .plist lên GitHub (thư mục iPA/ và Plist/)
# - Sinh link cài itms-services://
# - Rút gọn link bằng is.gd
# ==========================================================

import os
import secrets
import tempfile
import plistlib
from flask import Flask, request, jsonify
from ipa_utils import extract_ipa_info
from github_uploader import upload_to_github
import requests

app = Flask(__name__)

# Hàm rút gọn link bằng is.gd
def shorten_url(url):
    try:
        res = requests.get(f"https://is.gd/create.php?format=simple&url={url}", timeout=5)
        if res.status_code == 200:
            return res.text.strip()
    except Exception:
        pass
    return url

@app.route("/upload", methods=["POST"])
def upload_ipa():
    if "file" not in request.files:
        return jsonify({"error": "Thiếu file IPA"}), 400

    ipa_file = request.files["file"]
    if not ipa_file.filename.endswith(".ipa"):
        return jsonify({"error": "Chỉ chấp nhận file .ipa"}), 400

    # Tạo file tạm để xử lý
    temp_dir = tempfile.mkdtemp()
    ipa_path = os.path.join(temp_dir, ipa_file.filename)
    ipa_file.save(ipa_path)

    # Phân tích thông tin IPA
    info = extract_ipa_info(ipa_path)

    # Random tên file
    rand_name = secrets.token_urlsafe(6)[:6]

    ipa_remote_path = f"iPA/{rand_name}.ipa"
    plist_remote_path = f"Plist/{rand_name}.plist"

    # Tạo nội dung file .plist
    ipa_url = f"https://raw.githubusercontent.com/{info['repo']}/main/{ipa_remote_path}"
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
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
</plist>"""

    # Upload IPA và Plist lên GitHub
    ipa_url_github = upload_to_github(ipa_remote_path, ipa_path)
    plist_url_github = upload_to_github(plist_remote_path, plist_content.encode())

    # Link cài trực tiếp
    install_url = f"itms-services://?action=download-manifest&url={plist_url_github}"
    short_install = shorten_url(install_url)

    result = {
        "app_name": info["app_name"],
        "bundle_id": info["bundle_id"],
        "version": info["version"],
        "team_name": info["team_name"],
        "ipa_url": ipa_url_github,
        "plist_url": plist_url_github,
        "install_url": short_install,
    }

    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
