import argparse
import base64
import hashlib
import json
import time
import requests
from dataclasses import dataclass
from typing import Any

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


JsonDict = dict[str, Any]

DEFAULT_APP_ID = "c9379359685"
DEFAULT_APP_KEY = "awo6ureum8bn"
DEFAULT_ENCRYPT_KEY_B64 = "vYQ7DJugkbUZjnw2zi1u3LfUBHJt0QoyO/OJ3uq/Vjk="


def sha1_password(password: str) -> str:
    return hashlib.sha1(password.encode("utf-8")).hexdigest()


def encode_mobile(mobile: str) -> str:
    return base64.b64encode(mobile.encode("utf-8")).decode("utf-8")


def normalize_login_payload(payload: JsonDict) -> JsonDict:
    normalized = dict(payload)
    if "mobile" in normalized and isinstance(normalized["mobile"], str):
        normalized["mobile"] = encode_mobile(normalized["mobile"])
    if "password" in normalized and isinstance(normalized["password"], str):
        normalized["password"] = sha1_password(normalized["password"])
    return normalized


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


def _is_empty_object(value: JsonDict) -> bool:
    if not _is_object(value):
        raise ValueError("param must be an object")
    return len(value) == 0


def _should_keep(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list) and len(value) == 0:
        return False
    if isinstance(value, dict) and len(value) == 0:
        return False
    return True


def _is_empty_scalar(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return False
    return value in ("", None)


def build_sorted_query(params: JsonDict | None = None) -> str:
    params = params or {}
    if _is_empty_object(params):
        return ""

    ordered_keys = sorted(params.keys())
    filtered: JsonDict = {}
    for key in ordered_keys:
        value = params[key]
        if _should_keep(value):
            filtered[key] = value

    parts: list[str] = []
    for key in filtered:
        value = filtered[key]
        if isinstance(value, (dict, list)) or _is_empty_scalar(value):
            continue
        parts.append(f"{key}={value}")
    return "&".join(parts)


def t6(app_id: str, app_key: str, biz_content: JsonDict | None = None, token: str | None = None) -> JsonDict:
    if not app_id or not app_key:
        raise ValueError("请传入数据加密的 appId 和 appKey")

    biz_content = biz_content or {}
    query = build_sorted_query(biz_content)
    ts = int(time.time())

    sign_source = f"{query}&" if query else ""
    sign_source += f"appId={app_id}&appKey={app_key}&time={ts}"
    if token:
        sign_source += f"&token={token}"

    sign = hashlib.md5(sign_source.encode("utf-8")).hexdigest().lower()
    return {
        "appId": app_id,
        "sign": sign,
        "time": ts,
        "bizContent": biz_content,
    }

def aes_ecb_encrypt_base64(plaintext: str, encrypt_key_b64: str) -> str:
    key = base64.b64decode(encrypt_key_b64)
    cipher = AES.new(key, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")


def aes_ecb_decrypt_base64(ciphertext_b64: str, encrypt_key_b64: str) -> Any:
    key = base64.b64decode(encrypt_key_b64)
    cipher = AES.new(key, AES.MODE_ECB)
    decrypted = cipher.decrypt(base64.b64decode(ciphertext_b64))
    text = unpad(decrypted, AES.block_size).decode("utf-8")
    return json.loads(text)


@dataclass(slots=True)
class KukeCrypto:
    app_id: str
    app_key: str
    encrypt_key_b64: str

    def post_body_encryption(self, data: JsonDict | None = None, token: str | None = None) -> JsonDict:
        return t6(self.app_id, self.app_key, data or {}, token)

    def encrypt(self, data: JsonDict | None = None, token: str | None = None, use_aes: bool = False) -> JsonDict | str:
        signed = self.post_body_encryption(data, token)
        if not use_aes:
            return signed
        return aes_ecb_encrypt_base64(json.dumps(signed, ensure_ascii=False, separators=(",", ":")), self.encrypt_key_b64)

    def decrypt(self, payload: Any, encrypted: bool) -> Any:
        if isinstance(payload, str) and encrypted:
            return aes_ecb_decrypt_base64(payload, self.encrypt_key_b64)
        return payload


def _parse_json_arg(value: str | None) -> JsonDict:
    if not value:
        return {'mobile':'15011112222','password':'12345678'}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("--data must decode to an object")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproduce Kuke T6/P6 signing and AES body encryption.")
    parser.add_argument("--app-id", default=DEFAULT_APP_ID, help="requestAppid from runtime config")
    parser.add_argument("--app-key", default=DEFAULT_APP_KEY, help="requestAppkey from runtime config")
    parser.add_argument("--encrypt-key", default=DEFAULT_ENCRYPT_KEY_B64, help="requestEncryptKey from runtime config, base64 text")
    parser.add_argument("--data", help='JSON object, e.g. \'{"mobile":"xxx"}\'')
    parser.add_argument("--token", help="kk-token")
    parser.add_argument("--aes", default=True, action="store_true", help="Return AES-encrypted body like P6.encrypt(..., type=true)")
    parser.add_argument("--password", help="Plaintext password to SHA1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_payload = _parse_json_arg(args.data)

    payload = normalize_login_payload(raw_payload)
    crypto = KukeCrypto(
        app_id=args.app_id,
        app_key=args.app_key,
        encrypt_key_b64=args.encrypt_key,
    )
    data = crypto.post_body_encryption(payload, args.token)
    key = crypto.encrypt(data, args.token, use_aes=args.aes)

    url = "https://www.kuke99.com/prod-api/kukecoreuser/pc/user/passwordLogin"
    r = requests.post(url, json=key, timeout=20)
    print(r.status_code)
    print(r.text)



if __name__ == "__main__":
    main()
