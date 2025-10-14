# ==========================================================
# ipa_utils.py — Xử lý file IPA
# ==========================================================
# Nhiệm vụ:
# - Giải nén file IPA (thực chất là ZIP)
# - Đọc Info.plist để lấy:
#     + CFBundleName (App Name)
#     + CFBundleIdentifier (Bundle ID)
#     + CFBundleShortVersionString (Version)
# - Đọc embedded.mobileprovision để lấy TeamName
# ==========================================================

import os
import zipfile
import plistlib
import re
import tempfile
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

def extract_ipa_info(ipa_path):
    # Đọc config để lấy repo name (cho link GitHub)
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)
    repo = config["github"]["repo"]

    temp_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(ipa_path, "r") as zip_ref:
        zip_ref.extractall(temp_dir)

    # Tìm thư mục Payload
    payload_dir = os.path.join(temp_dir, "Payload")
    app_dir = None
    for item in os.listdir(payload_dir):
        if item.endswith(".app"):
            app_dir = os.path.join(payload_dir, item)
            break

    if not app_dir:
        raise Exception("Không tìm thấy thư mục .app trong IPA")

    # Đọc Info.plist
    plist_path = os.path.join(app_dir, "Info.plist")
    with open(plist_path, "rb") as f:
        plist_data = plistlib.load(f)

    app_name = plist_data.get("CFBundleDisplayName") or plist_data.get("CFBundleName", "Unknown")
    bundle_id = plist_data.get("CFBundleIdentifier", "unknown.bundle")
    version = plist_data.get("CFBundleShortVersionString", "1.0")

    # Đọc TeamName từ embedded.mobileprovision
    prov_path = os.path.join(app_dir, "embedded.mobileprovision")
    team_name = "Unknown"
    if os.path.exists(prov_path):
        with open(prov_path, "rb") as f:
            data = f.read().decode("utf-8", errors="ignore")
            match = re.search(r"<key>TeamName</key>\s*<string>(.*?)</string>", data)
            if match:
                team_name = match.group(1)

    return {
        "app_name": app_name,
        "bundle_id": bundle_id,
        "version": version,
        "team_name": team_name,
        "repo": repo
    }
