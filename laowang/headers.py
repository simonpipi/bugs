"""统一生成接近浏览器的请求头。

各业务脚本根据请求类型调用 image/check/document/submit 头部，避免每个
脚本手写 sec-fetch、UA Client Hints、origin 等容易不一致的字段。
"""

from typing import Any
from urllib.parse import urlparse


DEFAULT_SEC_CH_UA = '"Chromium";v="147", "Google Chrome";v="147", "Not.A/Brand";v="8"'


def _context_get(context: Any, key: str, default: Any = None) -> Any:
    """兼容 dict 和 dataclass/object 两种上下文读取方式。"""

    if isinstance(context, dict):
        return context.get(key, default)
    return getattr(context, key, default)


def format_sec_ch_ua(data: dict[str, Any] | None) -> str:
    """把 navigator.userAgentData.brands 转成 sec-ch-ua 请求头。"""

    if data and "userAgentData" in data:
        data = data.get("userAgentData") or {}
    brands = (data or {}).get("brands") or []
    values = []
    for brand in brands:
        name = brand.get("brand")
        version = brand.get("version")
        if name and version:
            values.append(f'"{name}";v="{version}"')
    return ", ".join(values) or DEFAULT_SEC_CH_UA


def browser_headers(
    context: Any,
    *,
    referer: str,
    accept: str,
    destination: str,
    mode: str,
    site: str = "same-origin",
    content_type: str | None = None,
    include_sec_fetch_user: bool = False,
    include_upgrade: bool = False,
    priority: str | None = None,
) -> dict[str, str]:
    """按请求场景生成基础浏览器请求头。"""

    fingerprint = _context_get(context, "fingerprint", {}) or {}
    user_agent_data = fingerprint.get("userAgentData") or {}
    platform = user_agent_data.get("platform") or fingerprint.get("platform") or "macOS"
    mobile = "?1" if user_agent_data.get("mobile") else "?0"
    headers = dict(_context_get(context, "headers", {}) or {})
    headers.update(
        {
            "accept": accept,
            "accept-language": headers.get("accept-language", "zh-CN,zh;q=0.9"),
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": referer,
            "sec-ch-ua": format_sec_ch_ua(fingerprint),
            "sec-ch-ua-mobile": mobile,
            "sec-ch-ua-platform": f'"{platform}"',
            "sec-fetch-dest": destination,
            "sec-fetch-mode": mode,
            "sec-fetch-site": site,
            "user-agent": fingerprint.get("userAgent") or headers.get("user-agent", ""),
        }
    )
    if priority:
        headers["priority"] = priority
    else:
        headers.pop("priority", None)

    if content_type:
        headers["content-type"] = content_type
        parsed = urlparse(referer)
        # 有请求体的同源提交需要带 origin，图片/普通文档请求则移除它。
        headers["origin"] = f"{parsed.scheme}://{parsed.netloc}"
    else:
        headers.pop("content-type", None)
        headers.pop("origin", None)

    if include_sec_fetch_user:
        headers["sec-fetch-user"] = "?1"
    else:
        headers.pop("sec-fetch-user", None)

    if include_upgrade:
        headers["upgrade-insecure-requests"] = "1"
    else:
        headers.pop("upgrade-insecure-requests", None)
    return headers


def image_headers(context: Any, *, referer: str) -> dict[str, str]:
    """验证码图片请求头。"""

    return browser_headers(
        context,
        referer=referer,
        accept="image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        destination="image",
        mode="no-cors",
    )


def check_headers(context: Any, *, referer: str) -> dict[str, str]:
    """验证码 check.php 表单提交请求头。"""

    return browser_headers(
        context,
        referer=referer,
        accept="*/*",
        destination="empty",
        mode="cors",
        content_type="application/x-www-form-urlencoded",
        priority="u=1, i",
    )


def document_headers(context: Any, *, referer: str, site: str = "same-origin") -> dict[str, str]:
    """普通页面跳转/打开请求头。"""

    return browser_headers(
        context,
        referer=referer,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        destination="document",
        mode="navigate",
        site=site,
        include_upgrade=True,
    )


def submit_headers(
    context: Any,
    *,
    referer: str,
    destination: str = "document",
    include_sec_fetch_user: bool = False,
) -> dict[str, str]:
    """表单提交请求头，默认模拟 document/iframe 导航提交。"""

    return browser_headers(
        context,
        referer=referer,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        destination=destination,
        mode="navigate",
        content_type="application/x-www-form-urlencoded",
        include_sec_fetch_user=include_sec_fetch_user,
        include_upgrade=True,
    )
