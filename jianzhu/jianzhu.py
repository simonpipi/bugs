import json
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

cookies = {
    'Hm_lvt_b1b4b9ea61b6f1627192160766a9c55c': '1775988309',
    'Hm_lpvt_b1b4b9ea61b6f1627192160766a9c55c': '1775988309',
    'HMACCOUNT': 'B83A69F8B6485BB0',
}

headers = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Referer': 'https://jzsc.mohurd.gov.cn/data/company',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'accessToken': '',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'timeout': '30000',
    'v': '231012',
    # 'Cookie': 'Hm_lvt_b1b4b9ea61b6f1627192160766a9c55c=1775988309; Hm_lpvt_b1b4b9ea61b6f1627192160766a9c55c=1775988309; HMACCOUNT=B83A69F8B6485BB0',
}


def decrypt_hex_aes_cbc_js_style(cipher_hex: str, key: str, iv: str) -> str:
    ciphertext = bytes.fromhex(cipher_hex.strip())
    key_b = key.encode("utf-8")
    iv_b = iv.encode("utf-8")
    cipher = AES.new(key=key_b, mode=AES.MODE_CBC, iv=iv_b)
    decrypted = cipher.decrypt(ciphertext)
    return unpad(decrypted, AES.block_size).decode("utf-8")


params = {
    'pg': '0',
    'pgsz': '15',
    'total': '0',
}

response = requests.get(
    'https://jzsc.mohurd.gov.cn/APi/webApi/dataservice/query/comp/list',
    params=params,
    cookies=cookies,
    headers=headers,
    timeout=30,
)
print(response.status_code)
print(response.text[:200])

if response.ok:
    plaintext = decrypt_hex_aes_cbc_js_style(
        response.text,
        key='Dt8j9wGw%6HbxfFn',
        iv='0123456789ABCDEF',
    )
    data = json.loads(plaintext)
    print(json.dumps(data, ensure_ascii=False, indent=2))
