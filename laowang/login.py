"""使用浏览器采集到的登录表单和验证码结果提交论坛登录。"""

import base64
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse

try:
    from curl_cffi import requests
except ImportError:
    requests = None


DEFAULT_LOGIN_REFERER = "https://laowang.vip/member.php?mod=logging&action=login"


def _context_get(context: Any, key: str, default: Any = None) -> Any:
    """兼容 dict 和 BrowserRequestContext 两种上下文。"""

    if isinstance(context, dict):
        return context.get(key, default)
    return getattr(context, key, default)


def _split_action(action: str, *, base_url: str) -> tuple[str, dict[str, str]]:
    """把 form action 拆成无 query 的 URL 和 query 参数字典。"""

    action_url = urljoin(base_url, action or base_url)
    parsed = urlparse(action_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return url, params


def _build_data_from_form(login_form: dict[str, Any] | None) -> dict[str, str]:
    """从浏览器采集的登录表单字段还原提交数据。"""

    data: dict[str, str] = {}
    if not login_form:
        return data

    for field in login_form.get("fields") or []:
        if field.get("disabled"):
            continue

        name = field.get("name")
        if not name:
            continue

        field_type = (field.get("type") or "").lower()
        tag = (field.get("tag") or "").lower()
        # 浏览器不会把按钮、文件框、未勾选单选/复选项作为普通字段提交。
        if tag == "button" or field_type in {"button", "submit", "image", "reset", "file"}:
            continue
        if field_type in {"checkbox", "radio"} and not field.get("checked"):
            continue

        data[name] = str(field.get("value") or "")
    return data


def _fingerprint_value(fingerprint: Any) -> str:
    """提取登录表单需要提交的浏览器指纹字符串。"""

    if isinstance(fingerprint, str):
        return fingerprint
    if not isinstance(fingerprint, dict):
        return ""

    return str(
        fingerprint.get("browserFpField")
        or fingerprint.get("fingerprint")
        or fingerprint.get("fp")
        or ""
    )


def _build_login_headers(
    context: Any,
    *,
    login_url: str,
    referer: str,
) -> dict[str, str]:
    """构造登录表单提交请求头。"""

    headers = dict(_context_get(context, "headers", {}) or {})
    parsed = urlparse(login_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    headers.update(
        {
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
            ),
            "content-type": "application/x-www-form-urlencoded",
            "origin": origin,
            "referer": referer,
            "sec-fetch-dest": "iframe",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
        }
    )
    return headers


def login(
    username: str,
    password: str,
    browser_context: Any,
    check_response_text: str,
    *,
    cookies: dict[str, str] | None = None,
    proxies: dict[str, str] | None = None,
    timeout: int = 30,
) -> Any:
    """提交 Discuz 登录表单，复用浏览器采集到的表单、请求头和 Cookie。"""

    if requests is None:
        raise RuntimeError("缺少依赖: pip install curl_cffi")

    login_form = _context_get(browser_context, "login_form")
    if not login_form:
        raise ValueError("browser_context.login_form 为空，无法获取登录 form 信息")

    referer = "https://laowang.vip/forum.php?mod=guide"
    login_url, params = _split_action(str(login_form.get("action") or ""), base_url=referer)
    params["inajax"] = "1"
    data = _build_data_from_form(login_form)

    encoded_password = base64.b64encode(password.encode("utf-8")).decode("ascii")
    # 站点登录接口期望 password 字段使用 base64:// 前缀包装。
    data.update(
        {
            "username": username,
            "password": f"base64://{encoded_password}",
            "clicaptcha-submit-info": check_response_text,
            "fingerprint": _fingerprint_value(_context_get(browser_context, "fingerprint")),
        }
    )

    headers = _build_login_headers(browser_context, login_url=login_url, referer=referer)
    request_cookies = dict(_context_get(browser_context, "cookies", {}) or {})
    if cookies:
        request_cookies.update(cookies)
    method = (login_form.get("method") or "post").lower()

    request_kwargs = {
        "params": params,
        "cookies": request_cookies,
        "headers": headers,
        "impersonate": "chrome",
        "proxies": proxies,
        "timeout": timeout,
    }
    if method == "get":
        request_kwargs["params"] = {**params, **data}
        return requests.get(login_url, **request_kwargs)

    return requests.post(login_url, data=data, **request_kwargs)


if __name__ == "__main__":
    try:
        from .cookies_store import REQUEST_PROXIES, get_browser_request_context
    except ImportError:
        from cookies_store import REQUEST_PROXIES, get_browser_request_context

    context = get_browser_request_context()
    response = login(
        "账号",
        "密码",
        context,
        "send_check_request 返回的 check_response.text",
        proxies=REQUEST_PROXIES,
    )
    print(response.status_code)
    print(response.text)
