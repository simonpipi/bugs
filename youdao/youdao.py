import hashlib
import json
import time

import requests
from urllib.parse import urlencode


key_value = 'kSy5gtKA4yRUxAVPJPrdYKZ0jBKyd3t1'

def get_timestamp_ms():
    return int(time.time() * 1000)


def gen_sign(data: dict, key_name: str, key_value):
    payload = data.copy()

    for key in list(payload.keys()):
        if payload[key] == "":
            del payload[key]

    sorted_keys = sorted(key for key in payload.keys() if payload[key] is not None)
    sorted_keys.append(key_name)
    payload[key_name] = key_value

    sign_source = "&".join(f"{key}={payload[key]}" for key in sorted_keys)
    # abtest=0&appVersion=12.0.0&client=webmain&imei=1&keyfrom=webfanyi.webmain&keyid=translate-webmain-key-getter&mid=1&model=1&mysticTime=1775814486663&network=wifi&product=webfanyi&screen=1&targetKeyid=translate-webfanyi-webmain&token=16aeb1c4b5724f9c83a7a117c3d06b85&vendor=web&yduuid=6c440fdd1c674b7cc45183ab323b6452&key=kSy5gtKA4yRUxAVPJPrdYKZ0jBKyd3t1
    # print(sign_source)
    sign = hashlib.md5(sign_source.encode("utf-8")).hexdigest()

    return sign, ",".join(sorted_keys)

def get_token():
    req = {
        "product": "webfanyi",
        "appVersion": "12.0.0",
        "client": "webmain",
        "mid": 1,
        "vendor": "web",
        "screen": 1,
        "model": 1,
        "imei":1,
        "network": "wifi",
        "keyfrom": "webfanyi.webmain",
        "keyid": "translate-webmain-key-getter",
        "mysticTime": get_timestamp_ms(),
        "yduuid": "6c440fdd1c674b7cc45183ab323b6452",
        "abtest": 0,
        "targetKeyid": "translate-webfanyi-webmain"
    }
    sign, sorted_keys = gen_sign(req, "key", key_value)
    req["sign"] = sign
    req["pointParam"] = sorted_keys
    query_string = urlencode(req, safe=",")
    url = f"https://dict-trans.youdao.com/translate/key?{query_string}"
    print(url)
    response = requests.post(
        url,
        cookies=cookies,
        headers=headers,
    )

def get_sse():
    req = {
        "product": "webfanyi",
        "appVersion": "1",
        "client": "webmain",
        "mid": 1,
        "vendor": "web",
        "screen": 1,
        "model": 1,
        "imei":1,
        "network": "wifi",
        "keyfrom": "webfanyi.webmain",
        "keyid": "translate-webfanyi-webmain",
        "mysticTime": get_timestamp_ms(),
        "yduuid": "6c440fdd1c674b7cc45183ab323b6452",
        "modelName": "llmLite",
        "useTerm": "false",
        "i": "%E5%95%8A",
        "from": "zh-CHS",
        "to": "en",
        "token": "16aeb1c4b5724f9c83a7a117c3d06b85",
        "signSecretKey": "BdCYRtHAJxO7yNm9RHwU2JiFISIk62Ts",
        "keyId": "translate-webfanyi-webmain",
        "source": "webmain"
    }
    sign, sorted_keys = gen_sign(req, "key", "BdCYRtHAJxO7yNm9RHwU2JiFISIk62Ts")
    req["sign"] = sign
    req["pointParam"] = sorted_keys

    url = f"https://dict-trans.youdao.com/webtranslate/sse"
    response = requests.post(
        url,
        data=req,
        cookies=cookies,
        headers=headers,
        stream=True,
    )
    event = {}
    chunks = []
    messages = []
    result = {
        "status_code": response.status_code,
        "request_id": None,
        "type": None,
        "translation": "",
        "messages": messages,
    }

    for raw_line in response.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue

        line = raw_line.strip()

        # Empty line means one SSE event is complete.
        if not line:
            if event.get("data"):
                payload = json.loads(event["data"])
            else:
                payload = {}

            if event.get("event") == "begin":
                result["request_id"] = payload.get("requestId")
                result["type"] = payload.get("type")
            elif event.get("event") == "message":
                text = payload.get("transIncre", "")
                if text:
                    chunks.append(text)
                    messages.append(text)
            elif event.get("event") == "end":
                result["request_id"] = result["request_id"] or payload.get("requestId")
                result["type"] = result["type"] or payload.get("type")
                break

            event = {}
            continue

        if ":" not in line:
            continue

        field, value = line.split(":", 1)
        event[field] = value.lstrip()

    result["translation"] = "".join(chunks)
    return result



cookies = {
    'OUTFOX_SEARCH_USER_ID': '-383033159@10.104.133.70',
    'P_INFO': 'hbacc0081090@163.com|1775528102|0|mailmaster_android|11&17|null&null&null#hen&410100#10#0#0|&0||hbacc0081090@163.com',
    'OUTFOX_SEARCH_USER_ID_NCOO': '444219640.44786966',
    'DICT_DOCTRANS_SESSION_ID': 'YmFiY2M2YjctMDBjZS00ZTQ4LWFhNDMtYzA3YzI5MDY0NmVh',
    '_uetsid': '7c45f630348a11f1ae41450790c4aaa4',
    '_uetvid': '7c460b80348a11f1a79df750a9191e72',
}

headers = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    # 'Content-Length': '0',
    'Origin': 'https://fanyi.youdao.com',
    'Pragma': 'no-cache',
    'Referer': 'https://fanyi.youdao.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    # 'Cookie': 'OUTFOX_SEARCH_USER_ID=-383033159@10.104.133.70; P_INFO=hbacc0081090@163.com|1775528102|0|mailmaster_android|11&17|null&null&null#hen&410100#10#0#0|&0||hbacc0081090@163.com; OUTFOX_SEARCH_USER_ID_NCOO=444219640.44786966; DICT_DOCTRANS_SESSION_ID=YmFiY2M2YjctMDBjZS00ZTQ4LWFhNDMtYzA3YzI5MDY0NmVh; _uetsid=7c45f630348a11f1ae41450790c4aaa4; _uetvid=7c460b80348a11f1a79df750a9191e72',
}

# get_token()

# response = requests.post(
#     'https://dict-trans.youdao.com/translate/key?product=webfanyi&appVersion=12.0.0&client=webmain&mid=1&vendor=web&screen=1&model=1&imei=1&network=wifi&keyfrom=webfanyi.webmain&keyid=translate-webmain-key-getter&mysticTime=1775808445958&yduuid=6c440fdd1c674b7cc45183ab323b6452&abtest=0&targetKeyid=translate-webfanyi-webmain&sign=a06c356fb13148039bbe36727deab65f&pointParam=abtest,appVersion,client,imei,keyfrom,keyid,mid,model,mysticTime,network,product,screen,targetKeyid,vendor,yduuid,key',
#     cookies=cookies,
#     headers=headers,
# )



if __name__ == "__main__":
    get_token()