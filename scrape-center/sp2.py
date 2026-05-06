import base64
import hashlib
import time

import requests


def make_token(*args):
    timestamp = str(round(time.time()))
    parts = [str(arg) for arg in args]
    parts.append(timestamp)
    sha1_hex = hashlib.sha1(",".join(parts).encode("utf-8")).hexdigest()
    return base64.b64encode(f"{sha1_hex},{timestamp}".encode("utf-8")).decode("utf-8")

headers = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Referer': 'https://spa2.scrape.center/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
}

params = {
    'limit': '10',
    'offset': '0',
}

params['token'] = make_token('/api/movie', params['offset'])

response = requests.get(
    'https://spa2.scrape.center/api/movie/',
    params=params,
    headers=headers,
    timeout=10,
)
response.raise_for_status()
print(response.json())
