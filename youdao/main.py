#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


TRANS_BASE = "https://dict-trans.youdao.com"
DICT_BASE = "https://dict.youdao.com"
AI_BASE = "https://luna-ai.youdao.com"

KEY_GETTER_ID = "translate-webmain-key-getter"
KEY_GETTER_SECRET = "kSy5gtKA4yRUxAVPJPrdYKZ0jBKyd3t1"
TRANSLATE_KEY_ID = "translate-webfanyi-webmain"
JSON_API_SECRET = "t2he2k4m2g6QKRigK0KAmSpXKgAezywG"
DIRECTION_KEY_ID = "ai-translate-direction"
DIRECTION_SECRET = "I5WacgKEZaloWBiDnE1fThnzxYWN30PH"

DEFAULT_HEADERS = {
    "Origin": "https://fanyi.youdao.com",
    "Referer": "https://fanyi.youdao.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
}

try:
    import certifi
except ImportError:
    certifi = None


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def encode_component(value: str) -> str:
    return urllib.parse.quote(value, safe="~()*!.'")


def build_headers(extra=None, cookie: str = "") -> dict:
    headers = dict(DEFAULT_HEADERS)
    if extra:
        headers.update(extra)
    if cookie:
        headers["Cookie"] = cookie
    return headers


def build_yduuid() -> str:
    return secrets.token_hex(16)


def normalize_sign_payload(payload: dict) -> dict:
    result = dict(payload)
    for key in list(result.keys()):
        if result[key] == "":
            del result[key]
    return result


def sign_params(payload: dict, secret: str) -> tuple[str, str]:
    normalized = normalize_sign_payload(payload)
    sorted_keys = sorted(key for key, value in normalized.items() if value is not None)
    sorted_keys.append("key")
    normalized["key"] = secret
    sign_source = "&".join(f"{key}={normalized[key]}" for key in sorted_keys)
    return md5_hex(sign_source), ",".join(sorted_keys)


def gen_param_v3(extra: dict, secret: str, options: dict) -> dict:
    payload = {
        "product": options["product"],
        "appVersion": options["appVersion"],
        "client": options["client"],
        "mid": 1,
        "vendor": "web",
        "screen": 1,
        "model": 1,
        "imei": 1,
        "network": "wifi",
        "keyfrom": options["keyfrom"],
        "keyid": options["keyid"],
        "mysticTime": int(time.time() * 1000),
        "yduuid": options["yduuid"],
        "abtest": 0,
        **extra,
    }
    sign, point_param = sign_params(payload, secret)
    payload["sign"] = sign
    payload["pointParam"] = point_param
    return payload


def fetch_text(url: str, method: str = "POST", headers=None, form=None) -> str:
    data = None
    request_headers = dict(headers or {})
    if form is not None:
        encoded = urllib.parse.urlencode(
            [(key, str(value)) for key, value in form.items()]
        ).encode("utf-8")
        data = encoded
        request_headers.setdefault(
            "Content-Type", "application/x-www-form-urlencoded; charset=UTF-8"
        )

    request = urllib.request.Request(
        url=url,
        data=data,
        headers=request_headers,
        method=method,
    )
    ssl_context = ssl.create_default_context(
        cafile=certifi.where() if certifi is not None else None
    )

    try:
        with urllib.request.urlopen(request, timeout=30, context=ssl_context) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} {error.reason}: {body}") from error


def fetch_json(url: str, method: str = "POST", headers=None, form=None) -> dict:
    text = fetch_text(url=url, method=method, headers=headers, form=form)
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Failed to parse JSON from {url}: {text}") from error


def parse_sse_events(raw_text: str) -> dict:
    events = []
    chunks = []
    request_id = None
    direction = None

    for block in re.split(r"\r?\n\r?\n", raw_text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        event = {}
        for line in lines:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            event[key] = value.strip()

        data = None
        if "data" in event:
            try:
                data = json.loads(event["data"])
            except json.JSONDecodeError:
                data = event["data"]

        if event.get("event") == "begin" and isinstance(data, dict):
            request_id = data.get("requestId") or request_id
            direction = data.get("type") or direction

        if event.get("event") == "message" and isinstance(data, dict):
            text = data.get("transIncre", "")
            if text:
                chunks.append(text)

        if event.get("event") == "end" and isinstance(data, dict):
            request_id = data.get("requestId") or request_id
            direction = data.get("type") or direction

        events.append(
            {
                "id": event.get("id"),
                "event": event.get("event"),
                "data": data,
            }
        )

    return {
        "requestId": request_id,
        "direction": direction,
        "translation": "".join(chunks),
        "events": events,
    }


def get_translate_key(yduuid: str, cookie: str, cached_text_token: str = "") -> dict:
    params = gen_param_v3(
        {
            "targetKeyid": TRANSLATE_KEY_ID,
            **({"token": cached_text_token} if cached_text_token else {}),
        },
        KEY_GETTER_SECRET,
        {
            "product": "webfanyi",
            "appVersion": "12.0.0",
            "client": "webmain",
            "keyfrom": "webfanyi.webmain",
            "keyid": KEY_GETTER_ID,
            "yduuid": yduuid,
        },
    )
    query = urllib.parse.urlencode([(key, str(value)) for key, value in params.items()])
    url = f"{TRANS_BASE}/translate/key?{query}"
    return fetch_json(
        url,
        method="POST",
        headers=build_headers({"Accept": "application/json, text/plain, */*"}, cookie),
    )


def detect_direction(text: str, yduuid: str, cookie: str, ydtoken: str) -> dict:
    params = gen_param_v3(
        {
            "input": encode_component(text),
            **({"token": ydtoken} if ydtoken else {}),
        },
        DIRECTION_SECRET,
        {
            "product": "webfanyi",
            "appVersion": "12.0.0",
            "client": "web",
            "keyfrom": "fanyi.web",
            "keyid": DIRECTION_KEY_ID,
            "yduuid": yduuid,
        },
    )
    return fetch_json(
        f"{AI_BASE}/translate_llm/v3/translateDirection",
        method="POST",
        headers=build_headers({"Accept": "application/json, text/plain, */*"}, cookie),
        form=params,
    )


def translate_sse(
    text: str,
    from_lang: str,
    to_lang: str,
    yduuid: str,
    cookie: str,
    token: str,
    secret_key: str,
    use_term: bool,
) -> dict:
    params = gen_param_v3(
        {
            "modelName": "llmLite",
            "useTerm": str(use_term).lower(),
            "i": encode_component(text),
            "from": from_lang,
            "to": to_lang,
            "signSecretKey": secret_key,
            "keyId": TRANSLATE_KEY_ID,
            "token": token,
            "source": "webmain",
        },
        secret_key,
        {
            "product": "webfanyi",
            "appVersion": "1",
            "client": "webmain",
            "keyfrom": "webfanyi.webmain",
            "keyid": TRANSLATE_KEY_ID,
            "yduuid": yduuid,
        },
    )
    raw_text = fetch_text(
        f"{TRANS_BASE}/webtranslate/sse",
        method="POST",
        headers=build_headers({"Accept": "*/*"}, cookie),
        form=params,
    )
    return parse_sse_events(raw_text)


def build_dict_signature(text: str, timestamp: int) -> dict:
    keyfrom = "webfanyi.webmain"
    client = "webmain"
    suffix = len(f"{text}{keyfrom}") % 10
    t_value = f"{timestamp}{suffix}"
    digest = md5_hex(f"{text}{keyfrom}")
    sign = md5_hex(f"{client}{text}{t_value}{JSON_API_SECRET}{digest}")
    return {
        "sign": sign,
        "t": t_value,
        "client": client,
        "keyfrom": keyfrom,
    }


def get_dict_result(text: str, direction: str, cookie: str) -> dict:
    dict_name = "ec" if direction == "en2zh-CHS" else "ce"
    signature = build_dict_signature(text, int(time.time() * 1000))
    body = {
        "needTranslate": "false",
        "dicts": json.dumps({"count": "1", "dicts": [dict_name]}, separators=(",", ":")),
        "q": text,
        "t": signature["t"],
        "client": signature["client"],
        "sign": signature["sign"],
        "keyfrom": signature["keyfrom"],
    }
    return fetch_json(
        f"{DICT_BASE}/jsonapi_s?doctype=json&jsonversion=4",
        method="POST",
        headers=build_headers({"Accept": "application/json, text/plain, */*"}, cookie),
        form=body,
    )


def get_enhance_result(
    text: str,
    translation: str,
    from_lang: str,
    to_lang: str,
    yduuid: str,
    cookie: str,
    token: str,
    secret_key: str,
) -> dict:
    sign_payload = gen_param_v3(
        {
            "signSecretKey": secret_key,
            "keyId": TRANSLATE_KEY_ID,
            "token": token,
            "source": "webmain",
        },
        secret_key,
        {
            "product": "webfanyi",
            "appVersion": "12.0.0",
            "client": "webmain",
            "keyfrom": "webfanyi.webmain",
            "keyid": TRANSLATE_KEY_ID,
            "yduuid": yduuid,
        },
    )
    body = {
        "srcArticle": encode_component(text),
        "tgtArticle": encode_component(translation),
        "from": from_lang,
        "to": to_lang,
        **sign_payload,
    }
    return fetch_json(
        f"{TRANS_BASE}/translate/enhance",
        method="POST",
        headers=build_headers({"Accept": "application/json, text/plain, */*"}, cookie),
        form=body,
    )


def guess_direction(text: str) -> str:
    return "zh-CHS2en" if any("\u4e00" <= char <= "\u9fff" for char in text) else "en2zh-CHS"


def should_fetch_dict(direction: str, text: str) -> bool:
    return direction in {"en2zh-CHS", "zh-CHS2en"} and len(text) <= 50


def should_fetch_enhance(direction: str) -> bool:
    return direction in {"zh-CHS2en", "en2zh-CHS", "ja2zh-CHS", "ko2zh-CHS"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Youdao text translation protocol client.",
    )
    parser.add_argument("text", nargs="+", help="Text to translate.")
    parser.add_argument("--from", dest="from_lang", default="", help="Source language.")
    parser.add_argument("--to", dest="to_lang", default="", help="Target language.")
    parser.add_argument(
        "--yduuid",
        default=os.environ.get("YOUDAO_YDUUID", ""),
        help="Optional yduuid override.",
    )
    parser.add_argument(
        "--cookie",
        default=os.environ.get("YOUDAO_COOKIE", ""),
        help="Optional Cookie header value.",
    )
    parser.add_argument(
        "--ydtoken",
        default=os.environ.get("YOUDAO_YDTOKEN", ""),
        help="Optional ydtoken for direction detection.",
    )
    parser.add_argument("--use-term", action="store_true", help="Enable terminology mode.")
    parser.add_argument("--no-dict", action="store_true", help="Skip jsonapi_s.")
    parser.add_argument("--no-enhance", action="store_true", help="Skip translate/enhance.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    text = " ".join(args.text).strip()
    yduuid = args.yduuid or build_yduuid()
    from_lang = args.from_lang
    to_lang = args.to_lang
    direction_info = None

    if not from_lang or not to_lang:
        try:
            direction_info = detect_direction(text, yduuid, args.cookie, args.ydtoken)
            direction_value = direction_info.get("data", {}).get("translateDirection")
            if direction_info.get("code") == 0 and direction_value:
                from_lang, to_lang = direction_value.split("2", 1)
        except Exception as error:
            guessed_direction = guess_direction(text)
            from_lang, to_lang = guessed_direction.split("2", 1)
            direction_info = {
                "code": -1,
                "fallback": True,
                "guessedDirection": guessed_direction,
                "error": str(error),
            }

    if not from_lang or not to_lang:
        guessed_direction = guess_direction(text)
        from_lang, to_lang = guessed_direction.split("2", 1)

    key_response = get_translate_key(yduuid, args.cookie)
    if (
        key_response.get("code") != 0
        or not key_response.get("data", {}).get("secretKey")
        or not key_response.get("data", {}).get("token")
    ):
        raise RuntimeError(f"Failed to get translate key: {json.dumps(key_response, ensure_ascii=False)}")

    sse_result = translate_sse(
        text=text,
        from_lang=from_lang,
        to_lang=to_lang,
        yduuid=yduuid,
        cookie=args.cookie,
        token=key_response["data"]["token"],
        secret_key=key_response["data"]["secretKey"],
        use_term=args.use_term,
    )

    direction = sse_result["direction"] or f"{from_lang}2{to_lang}"
    result = {
        "input": text,
        "from": from_lang,
        "to": to_lang,
        "direction": direction,
        "yduuid": yduuid,
        "key": {
            "token": key_response["data"]["token"],
            "secretKey": key_response["data"]["secretKey"],
        },
        "sse": {
            "requestId": sse_result["requestId"],
            "translation": sse_result["translation"],
            "events": sse_result["events"],
        },
        "directionInfo": direction_info,
    }

    if not args.no_enhance and sse_result["translation"] and should_fetch_enhance(direction):
        try:
            result["enhance"] = get_enhance_result(
                text=text,
                translation=sse_result["translation"],
                from_lang=from_lang,
                to_lang=to_lang,
                yduuid=yduuid,
                cookie=args.cookie,
                token=key_response["data"]["token"],
                secret_key=key_response["data"]["secretKey"],
            )
        except Exception as error:
            result["enhance"] = {"error": str(error)}

    if not args.no_dict and should_fetch_dict(direction, text):
        try:
            result["dict"] = get_dict_result(text, direction, args.cookie)
        except Exception as error:
            result["dict"] = {"error": str(error)}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
