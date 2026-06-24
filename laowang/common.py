"""跨脚本复用的 JSON、Cookie 和登录态工具函数。"""

import json
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    """读取 UTF-8 JSON 文件，不存在时给出明确错误。"""

    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    """以缩进格式保存 JSON，并自动创建父目录。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_local_path(path: str | Path) -> Path:
    """把命令行传入的相对路径解析为当前工作目录下的绝对路径。"""

    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def format_cookie_header(cookies: dict[str, str]) -> str:
    """把 Cookie 字典格式化成 HTTP Cookie 请求头。"""

    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def response_cookies(response: Any) -> dict[str, str]:
    """从响应对象的 cookie jar 和 Set-Cookie 头中提取 Cookie。"""

    cookies: dict[str, str] = {}
    if getattr(response, "cookies", None) is not None:
        cookies.update(response.cookies.get_dict())

    set_cookie = getattr(response, "headers", {}).get("set-cookie")
    if set_cookie:
        parsed = SimpleCookie()
        parsed.load(set_cookie)
        cookies.update({key: morsel.value for key, morsel in parsed.items()})
    return cookies


def merge_response_cookies(cookies: dict[str, str], response: Any) -> dict[str, str]:
    """把接口响应里的新 Cookie 合并回现有登录态。"""

    merged = dict(cookies)
    merged.update(response_cookies(response))
    return merged


def fingerprint_value(fingerprint: Any) -> str:
    """兼容不同上下文结构中保存的浏览器指纹字段。"""

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


def load_context_and_cookies(
    account: Any,
    *,
    default_context_path: Path,
    default_cookies_path: Path,
) -> tuple[dict[str, Any], dict[str, str], Path]:
    """按账号配置读取 context 与 cookies，并返回后续需要回写的 cookies 路径。"""

    if account is None:
        context_path = default_context_path
        cookies_path = default_cookies_path
    else:
        context_path = account.context_path
        cookies_path = account.cookies_path

    context = load_json(context_path)
    cookies: dict[str, str] = {}
    cookies.update(context.get("cookies") or {})
    cookies.update(load_json(cookies_path))
    return context, cookies, cookies_path
