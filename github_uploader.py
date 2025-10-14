# ==========================================================
# github_uploader.py — Upload / Xoá file trên GitHub
# ==========================================================
# Dùng GitHub REST API v3
# ==========================================================

import base64
import requests
import os

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("GITHUB_REPO")
BRANCH = os.getenv("GITHUB_BRANCH", "main")

def upload_to_github(path_in_repo, content):
    if isinstance(content, str):
        content = content.encode("utf-8")

    api_url = f"https://api.github.com/repos/{REPO}/contents/{path_in_repo}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

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
        return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{path_in_repo}"
    else:
        print("❌ GitHub upload error:", res.text)
        return None

def delete_from_github(path_in_repo):
    api_url = f"https://api.github.com/repos/{REPO}/contents/{path_in_repo}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
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
