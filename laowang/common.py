import json
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_local_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def format_cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def response_cookies(response: Any) -> dict[str, str]:
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
    merged = dict(cookies)
    merged.update(response_cookies(response))
    return merged


def fingerprint_value(fingerprint: Any) -> str:
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
