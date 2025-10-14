import os, zipfile, plistlib, requests, re
from base64 import b64encode

GITHUB_API = "https://api.github.com"

def extract_info(ipa_path):
    info = {'name': 'Unknown', 'bundle': 'unknown.bundle', 'version': '1.0', 'team': 'Unknown'}
    try:
        with zipfile.ZipFile(ipa_path, 'r') as z:
            plist_path = [f for f in z.namelist() if f.endswith('Info.plist')][0]
            with z.open(plist_path) as f:
                plist_data = plistlib.load(f)
            info['name'] = plist_data.get('CFBundleName', 'Unknown')
            info['bundle'] = plist_data.get('CFBundleIdentifier', 'unknown.bundle')
            info['version'] = plist_data.get('CFBundleShortVersionString', '1.0')

            prov_files = [f for f in z.namelist() if 'embedded.mobileprovision' in f]
            if prov_files:
                with z.open(prov_files[0]) as f:
                    content = f.read().decode('utf-8', errors='ignore')
                    team_name_match = re.search(r'<key>Name</key>\s*<string>([^<]+)</string>', content)
                    if team_name_match:
                        info['team'] = team_name_match.group(1)
    except Exception as e:
        print("Lỗi extract_info:", e)
    return info

def upload_to_github(file_path, folder=None, rename=None):
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    GITHUB_REPO = os.getenv("GITHUB_REPO")
    file_name = rename if rename else os.path.basename(file_path)
    folder_path = f"{folder}/{file_name}" if folder else file_name
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{folder_path}"

    with open(file_path, "rb") as f:
        content = b64encode(f.read()).decode()

    data = {"message": f"Upload {folder_path}", "content": content}
    r = requests.put(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }, json=data)

    if r.status_code in [200, 201]:
        return f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{folder_path}"
    else:
        print(r.text)
        raise Exception(f"Upload thất bại: {r.text}")

def shorten_url(url):
    try:
        api = "https://is.gd/create.php"
        params = {"format": "simple", "url": url}
        r = requests.get(api, params=params, timeout=5)
        if r.status_code == 200:
            return r.text.strip()
    except:
        pass
    return url

def list_github_files(folder):
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    GITHUB_REPO = os.getenv("GITHUB_REPO")
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{folder}"
    r = requests.get(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    })
    if r.status_code == 200:
        return [f for f in r.json() if f['type'] == 'file']
    else:
        print("List files error:", r.text)
        return []

def delete_github_file(folder, filename):
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    GITHUB_REPO = os.getenv("GITHUB_REPO")
    path = f"{folder}/{filename}"
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}"

    get = requests.get(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    })
    if get.status_code != 200:
        return False
    sha = get.json()['sha']

    data = {"message": f"Delete {path}", "sha": sha}
    r = requests.delete(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }, json=data)
    return r.status_code == 200
