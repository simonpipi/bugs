import argparse
import base64
import hashlib
import json
import random
from typing import Dict
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad


IV = b"0102030405060708"
AES_KEY_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*"

# Matches s.js: Q(n)
PROD_RSA_PUBLIC_KEY_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCYEVrK/4Mahiv0pUJgTybx4J9P5dUT/"
    "Y0PuwMbk+gMU+jrZnBiXGv6/hCH1avIhoBcE535F8nJQQN3UavZdFkYidsoXuEnat3+eVT"
    "p3FslyhRwIBDF09v4vDhRtxFOT+R7uH7h/mzmyA2/+lfIMWGIrffXprYizbV76+YQKhoqF"
    "QIDAQAB"
)

PREVIEW_RSA_PUBLIC_KEY_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC0gABHEoaFAcUPlaqKFn3mOOdQ7m5SII"
    "NJ0+dLo6hq4AcGAJKnYP+uM1Ge0++8SVxPBC2H+AYBiaeYC0UC5El9fAdGRWjRt2QdDqY0"
    "GeB3iPoEAiNvTPgcjKXjt7++fb0CQ2yY9My13py2glTTENCEhD64bjW8n1/9zUrq5XJv7w"
    "IDAQAB"
)


def random_aes_key(length: int = 16) -> str:
    return "".join(random.choice(AES_KEY_CHARS) for _ in range(length))


def aes_encrypt_value(value: str, aes_key: str) -> str:
    cipher = AES.new(aes_key.encode("utf-8"), AES.MODE_CBC, IV)
    encrypted = cipher.encrypt(pad(value.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")


def rsa_encrypt_aes_key(aes_key: str, public_key_b64: str) -> str:
    public_key = RSA.import_key(base64.b64decode(public_key_b64))
    cipher = PKCS1_v1_5.new(public_key)
    # JS does window.btoa(e) before RSA encrypt.
    plaintext = base64.b64encode(aes_key.encode("utf-8"))
    encrypted = cipher.encrypt(plaintext)
    return base64.b64encode(encrypted).decode("utf-8")


def encrypt_params(params: Dict[str, str], preview: bool = False) -> Dict[str, object]:
    aes_key = random_aes_key(16)
    public_key_b64 = PREVIEW_RSA_PUBLIC_KEY_B64 if preview else PROD_RSA_PUBLIC_KEY_B64
    eui_left = rsa_encrypt_aes_key(aes_key, public_key_b64)
    eui_right = base64.b64encode(",".join(params.keys()).encode("utf-8")).decode("utf-8")
    encrypted_params = {
        key: aes_encrypt_value(str(value), aes_key)
        for key, value in params.items()
    }
    return {
        "EUI": f"{eui_left}.{eui_right}",
        "encryptedParams": encrypted_params,
        "aes_key": aes_key,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Xiaomi account login encryption payload from s.js."
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Use preview RSA public key for account.preview.n.xiaomi.net.",
    )

    return parser.parse_args()


def fetch_second_redirect_params(
    start_url: str = "https://account.xiaomi.com",
) -> Dict[str, object]:
    session = requests.Session()
    current_url = start_url
    redirect_chain = []
    second_redirect_params: Dict[str, object] = {}

    for step in range(1, 3):
        response = session.get(current_url, allow_redirects=False, timeout=20)
        location = response.headers.get("Location")
        next_url = urljoin(response.url, location) if location else None

        redirect_chain.append(
            {
                "step": step,
                "status_code": response.status_code,
                "request_url": response.url,
                "location": location,
                "next_url": next_url,
            }
        )

        if not response.is_redirect or not next_url:
            break

        if step == 2:
            parsed_url = urlparse(next_url)
            second_redirect_params = {
                key: values[0] if len(values) == 1 else values
                for key, values in parse_qs(parsed_url.query, keep_blank_values=True).items()
            }

        current_url = next_url

    mobile = "15011155156"
    pwd = "668892"

    data = {
        'bizDeviceType': '',
        'needTheme': 'false',
        'theme': '',
        'showActiveX': 'false',
        'serviceParam': second_redirect_params["serviceParam"],
        'callback': second_redirect_params["callback"],
        'qs': second_redirect_params["qs"],
        'sid': 'passport',
        '_sign': second_redirect_params["_sign"],
        'user': encrypt_params({"user": mobile})["encryptedParams"]["user"],
        'cc': '+86',
        'hash': hashlib.md5(pwd.encode("utf-8")).hexdigest(),
        '_json': 'true',
        'policyName': 'miaccount',
        'captCode': '',
        'deviceFingerprint': 'f14845c18ab3689c495e0b0a4eb7f99c',
    }

    response = session.post('https://account.xiaomi.com/pass/serviceLoginAuth2', data=data)
    print(response.text)


def main() -> None:
    print(fetch_second_redirect_params())
    # args = parse_args()
    # params = {
    #     "user": "15011155156"
    # }
    # result = encrypt_params(params, preview=args.preview)
    # result["redirect_info"] = fetch_second_redirect_params()
    # print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
