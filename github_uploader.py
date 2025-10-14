# ==========================================================
# github_uploader.py — Upload / Xoá file trên GitHub
# ==========================================================
# Nhiệm vụ:
# - Upload file .ipa và .plist lên branch main
# - Xoá file theo yêu cầu (khi nhấn nút 🗑️ trong Telegram)
# ==========================================================

import base64
import requests
import yaml
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

# Đọc thông tin GitHub từ config.yaml
with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

GITHUB_TOKEN = config["github"]["token"]
REPO = config["github"]["repo"]
BRANCH = config["github"]["branch"]

def upload_to_github(path_in_repo, content):
    """
    Upload file (bytes hoặc text) lên GitHub
    """
    if isinstance(content, str):
        content = content.encode("utf-8")

    api_url = f"https://api.github.com/repos/{REPO}/contents/{path_in_repo}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    # Kiểm tra file đã tồn tại chưa (để lấy SHA nếu cần cập nhật)
    sha = None
    res = requests.get(api_url, headers=headers)
    if res.status_code == 200:
        sha = res.json().get("sha")

    data = {
        "message": f"Upload {path_in_repo}",
        "content": base64.b64encode(content).decode("utf-8"),
        "branch": BRANCH
    }
    if sha:
        data["sha"] = sha

    res = requests.put(api_url, headers=headers, json=data)
    if res.status_code in [200, 201]:
        # Trả về raw.githubusercontent link
        return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{path_in_repo}"
    else:
        print("❌ GitHub upload error:", res.text)
        return None

def delete_from_github(path_in_repo):
    """
    Xoá file trên GitHub theo đường dẫn
    """
    api_url = f"https://api.github.com/repos/{REPO}/contents/{path_in_repo}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    # Lấy SHA của file cần xoá
    res = requests.get(api_url, headers=headers)
    if res.status_code != 200:
        return False

    sha = res.json()["sha"]
    data = {
        "message": f"Delete {path_in_repo}",
        "sha": sha,
        "branch": BRANCH
    }

    res = requests.delete(api_url, headers=headers, json=data)
    return res.status_code == 200
