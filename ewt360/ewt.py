import time
import hashlib
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


KEY = b"20171109124536982017110912453698"
IV = b"2017110912453698"


def password_encrypt(password: str):
    if password is None:
        return None
    if password == "":
        return ""
    cipher = AES.new(KEY, AES.MODE_CBC, IV)
    encrypted = cipher.encrypt(pad(password.encode("utf-8"), AES.block_size))
    return encrypted.hex().upper()


def get_server_time(session: requests.Session) -> str:
    local_now = str(int(time.time() * 1000))
    url = f"https://gateway.ewt360.com/api/commondata/server/gettime?t={local_now}"
    r = session.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()
    return str(data["data"]["timestamp"])


def make_sign(timestamp: str) -> str:
    return hashlib.md5((timestamp + "bdc739ff2dcf").encode()).hexdigest().upper()


def build_headers(timestamp: str, token: str | None = None):
    headers = {
        'accept': 'application/json',
        'accept-language': 'zh-CN,zh;q=0.9',
        'access-control-allow-origin': '*',
        'cache-control': 'no-cache',
        'content-type': 'application/json',
        'origin': 'https://web.ewt360.com',
        'platform': '1',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': 'https://web.ewt360.com/',
        'referurl': 'https://web.ewt360.com/register/#/login',
        'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'secretid': '2',
        "sign": make_sign(timestamp),
        "timestamp": timestamp,
        'token': '0',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    }
    return headers


def login(username: str, password: str, extra: dict | None = None):
    s = requests.Session()
    timestamp = get_server_time(s)
    headers = build_headers(timestamp)

    payload = {
        "platform": 1,
        "userName": username,
        "password": password_encrypt(password),
        "webVersion": "pc_20250101",
    }
    if extra:
        payload.update(extra)

    url = "https://gateway.ewt360.com/api/authcenter/v2/oauth/login/account"
    r = s.post(url, json=payload, headers=headers, timeout=20)
    print(r.status_code)
    print(r.text)
    return r

if __name__ == "__main__":
    login("chenmingsimon@gmail.com", "13123123")
