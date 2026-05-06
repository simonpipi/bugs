from typing import Any

try:
    from curl_cffi import requests
except ImportError:
    requests = None

CHECK_URL = "https://laowang.vip/captcha/check.php"
REFERER = "https://laowang.vip/member.php?mod=logging&action=login"


def build_check_headers(fingerprint: dict[str, Any]) -> dict[str, str]:
    sec_ch_ua_parts = []
    user_agent_data = fingerprint.get("userAgentData")
    brands = (user_agent_data or {}).get("brands") or []
    for brand in brands:
        name = brand.get("brand")
        version = brand.get("version")
        if name and version:
            sec_ch_ua_parts.append(f'"{name}";v="{version}"')
    sec_ch_ua = ", ".join(sec_ch_ua_parts) or '"Chromium";v="147", "Google Chrome";v="147", "Not.A/Brand";v="8"'
    mobile = "?1" if (user_agent_data or {}).get("mobile") else "?0"
    platform = (user_agent_data or {}).get("platform") or fingerprint.get("platform") or "macOS"

    return {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "cache-control": "no-cache",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://laowang.vip",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": REFERER,
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": mobile,
        "sec-ch-ua-platform": f'"{platform}"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": fingerprint.get("userAgent", ""),
    }


def send_check_request(
    *,
    cookies: dict[str, str],
    headers: dict[str, str],
    payload: dict[str, str],
    proxies: dict[str, str] | None = None,
    check_url: str = CHECK_URL,
    timeout: int = 30,
) -> Any:
    if requests is None:
        raise RuntimeError("缺少依赖: pip install curl_cffi")
    response = requests.post(
        check_url,
        cookies=cookies,
        headers=headers,
        data=payload,
        impersonate="chrome",
        proxies=proxies,
        timeout=timeout,
    )
    return response


if __name__ == "__main__":
    cookies = {
        "X9wU_2132_saltkey": "u8X44G4d",
        "X9wU_2132_lastvisit": "1777516684",
        "PHPSESSID": "dqbpibpf4lu7ckc9knnj89qk6e",
        "_pk_id.2.672d": "1a6f2a0a69900d8d.1777527632.",
        "X9wU_2132_lastact": "1777538869%09member.php%09logging",
        "cf_clearance": "CfqqWCHCqHlpEGbhmSL5eko3lXIqka1OrfDi0t6Aigs-1777538879-1.2.1.1-O3VGNFOQyBIiczIHxPnm09EHtS8DbaQybZCTwrZjpvN59hu4qSN8r4DC7I.HwhC0R1N6UbjRCDVNCEmR_iwA.HW25Uh5FUBFxSY52wi1LU0T5aUe4b_AqqOQlVzcUvLQzRYIjkeSWRDSIVgPYTDlvRY5XUNndzlSwzKKE2lf6jza7YkPjMStffRip2mPyYLfsWUFjJYQ3Dmzr.kxlhS9hItqz_3xFthr3sii7aJT0CQaVUVtAkMqnBScj0axtB.tCVpczgn2au32XnL4AWfOECWGSdfDm2XNzP7P5oDw2qPIZxf4hgAUqT7MFvtJv3NEk.ctmuw1VDFaQCWEjn4W0Q",
    }
    headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "cache-control": "no-cache",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://laowang.vip",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": REFERER,
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    }
    data = {
        "tn_r": "102.00",
        "track": "PHUyCBkODBEDTBoADFsSGQAmNzMXEgMAAURHAygjJQUhDgVWGwJRTVpbEh0AOzgrIFlKRxZSVEd1eXFaQlRZCggAX0xQRwdfQ204MQNjSVZRDEdNd3l1UERQXAMPDlxMUUMEUF5+b2tGXVhLZxgAEiN1fllbUl8CDQpQQF5GBFtXem52UBwbXl0GNgciMiBLT1dEEUpIDRANIVEbTXVpaVQCDgoBXFxFf2N8WURXWwMOCkRXDR5CKgcuNyABQxsJBERHES45JQUtRVICCQoV",
        "ts": "1777541037713",
        "sign": "65f45ab8",
    }
    response = send_check_request(cookies=cookies, headers=headers, payload=data)
    print(response.text)
