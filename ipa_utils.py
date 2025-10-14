# ==========================================================
# ipa_utils.py — Xử lý file IPA
# ==========================================================
# - Giải nén file IPA
# - Đọc Info.plist để lấy App name, Bundle ID, Version
# - Đọc embedded.mobileprovision để lấy Team Name
# ==========================================================

import os
import zipfile
import plistlib
import re
import tempfile

def extract_ipa_info(ipa_path):
    repo = os.getenv("GITHUB_REPO")

    temp_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(ipa_path, "r") as zip_ref:
        zip_ref.extractall(temp_dir)

    payload_dir = os.path.join(temp_dir, "Payload")
    app_dir = None
    for item in os.listdir(payload_dir):
        if item.endswith(".app"):
            app_dir = os.path.join(payload_dir, item)
            break

    if not app_dir:
        raise Exception("Không tìm thấy thư mục .app trong IPA")

    plist_path = os.path.join(app_dir, "Info.plist")
    with open(plist_path, "rb") as f:
        plist_data = plistlib.load(f)

    app_name = plist_data.get("CFBundleDisplayName") or plist_data.get("CFBundleName", "Unknown")
    bundle_id = plist_data.get("CFBundleIdentifier", "unknown.bundle")
    version = plist_data.get("CFBundleShortVersionString", "1.0")

    # Đọc TeamName
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
