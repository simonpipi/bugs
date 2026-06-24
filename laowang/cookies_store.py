"""通过 Playwright 刷新老王论坛账号的浏览器上下文和 Cookie。

该脚本负责启动真实浏览器、采集页面指纹和登录表单、通过滑块验证码，
并在账号配置中写回 context.json/cookies.json，供后续协议脚本复用。
"""

import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    from .captcha_flow import pass_slider_captcha
    from .common import format_cookie_header, save_json
    from .feich_captcha import fetch_captcha_image
    from .headers import browser_headers, check_headers
    from .login import login
except ImportError:
    from captcha_flow import pass_slider_captcha
    from common import format_cookie_header, save_json
    from feich_captcha import fetch_captcha_image
    from headers import browser_headers, check_headers
    from login import login
try:
    from .account_config import DEFAULT_CONFIG_PATH, AccountConfig, select_account_configs
except ImportError:
    from account_config import DEFAULT_CONFIG_PATH, AccountConfig, select_account_configs

URL = "https://laowang.vip/member.php?mod=logging&action=login"
BASE_DIR = Path(__file__).resolve().parent
SCREENSHOT_PATH = BASE_DIR / "security_verification_popup.png"
CONTEXT_JSON_PATH = BASE_DIR / "context.json"
COOKIES_JSON_PATH = BASE_DIR / "cookies.json"
DEBUG_DIR = BASE_DIR.parent / "debug"
REQUEST_PROXIES = {
    "http": "http://127.0.0.1:7897",
    "https": "http://127.0.0.1:7897",
}
DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)
DEFAULT_BROWSER_VIEWPORT = {"width": 1280, "height": 720}
DEFAULT_BROWSER_SCREEN = {"width": 1280, "height": 720}

STEALTH_INIT_SCRIPT = r"""
(() => {
  const defineGetter = (obj, prop, value) => {
    try {
      Object.defineProperty(obj, prop, {
        get: () => value,
        configurable: true
      });
    } catch (e) {}
  };

  defineGetter(Navigator.prototype, "webdriver", undefined);
  defineGetter(Navigator.prototype, "languages", ["zh-CN", "zh"]);
  defineGetter(Navigator.prototype, "language", "zh-CN");
  defineGetter(Navigator.prototype, "platform", "MacIntel");
  defineGetter(Navigator.prototype, "hardwareConcurrency", 6);
  defineGetter(Navigator.prototype, "deviceMemory", 16);

  if (!window.chrome) {
    Object.defineProperty(window, "chrome", {
      value: { runtime: {} },
      configurable: true
    });
  }
})();
"""

JS = r"""
(() => {
  function canvasFingerprint() {
    try {
      const canvas = document.createElement("canvas");
      canvas.width = 220;
      canvas.height = 198;

      const ctx = canvas.getContext("2d");
      if (!ctx) return "nc";

      ctx.fillStyle = "rgba(100,200,50,0.8)";
      ctx.textBaseline = "alphabetic";
      ctx.fillRect(0, 0, 220, 30);

      ctx.fillStyle = "#069";
      ctx.font = "14px Arial,sans-serif";
      ctx.fillText("Lw老王_fp😀", 4, 20);

      ctx.fillStyle = "#f0a";
      ctx.font = "11px Georgia";
      ctx.fillText("hfsdn", 80, 26);

      return canvas.toDataURL().slice(-40);
    } catch (e) {
      return "ce";
    }
  }

  function webglRenderer() {
    try {
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
      if (!gl) return "";

      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      if (ext) return gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "";

      return gl.getParameter(gl.RENDERER) || "";
    } catch (e) {
      return "";
    }
  }

  return {
    browserFpField: document.getElementById("browser_fp")?.value || "",
    userAgent: navigator.userAgent,
    languages: navigator.languages,
    language: navigator.language,
    screenWidth: screen.width,
    screenHeight: screen.height,
    colorDepth: screen.colorDepth,
    timezoneOffset: new Date().getTimezoneOffset(),
    platform: navigator.platform,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory || "",
    userAgentData: navigator.userAgentData ? {
      brands: navigator.userAgentData.brands,
      mobile: navigator.userAgentData.mobile,
      platform: navigator.userAgentData.platform
    } : null,
    canvasTail: canvasFingerprint(),
    webglRenderer: webglRenderer()
  };
})()
"""

LOGIN_FORM_JS = r"""
(() => {
  const form = document.querySelector('form[name="login"]');
  if (!form) return null;

  const fields = Array.from(form.querySelectorAll("input, select, textarea, button")).map((el) => {
    const info = {
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || "",
      name: el.getAttribute("name") || "",
      id: el.id || "",
      value: "value" in el ? el.value : "",
      disabled: Boolean(el.disabled),
      required: Boolean(el.required),
      placeholder: el.getAttribute("placeholder") || "",
      autocomplete: el.getAttribute("autocomplete") || "",
    };

    if ("checked" in el) info.checked = Boolean(el.checked);
    if (el.tagName.toLowerCase() === "select") {
      info.options = Array.from(el.options).map((option) => ({
        value: option.value,
        text: option.text,
        selected: option.selected,
      }));
    }
    return info;
  });

  return {
    name: form.getAttribute("name") || "",
    id: form.id || "",
    action: form.action || "",
    actionAttr: form.getAttribute("action") || "",
    method: form.method || "",
    methodAttr: form.getAttribute("method") || "",
    enctype: form.enctype || "",
    target: form.target || "",
    fields,
  };
})()
"""


@dataclass(frozen=True)
class BrowserRequestContext:
    """从浏览器页面采集出的协议请求上下文。"""

    cookies: dict[str, str]
    headers: dict[str, str]
    fingerprint: dict[str, Any]
    login_form: dict[str, Any] | None
    cookie_header: str
    storage_state: dict[str, Any]


@dataclass(frozen=True)
class CaptchaCheckResult:
    """cookies_store 对验证码结果的轻量包装。"""

    check_text: str
    cookies: dict[str, str]


def _proxy_server(proxies: dict[str, str] | None) -> str | None:
    """从 requests 风格代理配置中取出 Playwright 可用的代理地址。"""

    if not proxies:
        return None
    return proxies.get("https") or proxies.get("http")


def _launch_chromium(p: Any, *, headless: bool, proxies: dict[str, str] | None) -> Any:
    """启动 Chromium；优先使用本机 Chrome channel，失败时回退到内置浏览器。"""

    launch_options: dict[str, Any] = {
        "headless": headless,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    proxy_server = _proxy_server(proxies)
    if proxy_server:
        launch_options["proxy"] = {"server": proxy_server}

    try:
        return p.chromium.launch(channel="chrome", **launch_options)
    except Exception:
        return p.chromium.launch(**launch_options)


def _page_preview(page: Any, *, limit: int = 300) -> str:
    """提取当前页面的短文本，用于风控/表单缺失时报错定位。"""

    try:
        return " ".join(page.content().split())[:limit]
    except Exception:
        return ""


def _raise_if_login_form_missing(page: Any, response: Any, login_form: dict[str, Any] | None) -> None:
    """登录表单缺失时给出更明确的环境/风控提示。"""

    if login_form:
        return

    status = getattr(response, "status", None)
    title = ""
    try:
        title = page.title()
    except Exception:
        pass

    preview = _page_preview(page)
    raise RuntimeError(
        "未拿到登录表单，停止刷新 cookies。"
        f"status={status}, url={page.url!r}, title={title!r}。"
        "当前页面很可能仍是 Cloudflare/风控验证页；请确认代理 127.0.0.1:7897 可用，"
        "并优先使用默认 headed 模式完成浏览器验证。"
        f"页面预览: {preview}"
    )


def build_captcha_headers(fingerprint: dict[str, Any], *, referer: str = URL) -> dict[str, str]:
    """构造验证码图片请求头，尽量贴近浏览器发起的 image 请求。"""

    return browser_headers(
        {"fingerprint": fingerprint},
        referer=referer,
        accept="image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        destination="image",
        mode="no-cors",
        priority="i",
    )


def get_browser_request_context(
    *,
    url: str = URL,
    headless: bool = True,
    proxies: dict[str, str] | None = REQUEST_PROXIES,
    timeout: int = 60000,
    form_timeout: int = 5000,
) -> BrowserRequestContext:
    """打开登录页并采集 Cookie、指纹、登录表单和 storage_state。"""

    with sync_playwright() as p:
        browser = _launch_chromium(p, headless=headless, proxies=proxies)
        try:
            browser_context = browser.new_context(
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                user_agent=DEFAULT_BROWSER_USER_AGENT,
                viewport=DEFAULT_BROWSER_VIEWPORT,
                screen=DEFAULT_BROWSER_SCREEN,
                device_scale_factor=2,
                is_mobile=False,
                has_touch=False,
            )
            browser_context.add_init_script(STEALTH_INIT_SCRIPT)
            page = browser_context.new_page()

            # 先等待 DOM，再短等 networkidle/登录表单；遇到风控页时后续会明确报错。
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout, 10000))
            except PlaywrightTimeoutError:
                pass
            try:
                page.wait_for_selector('form[name="login"]', state="attached", timeout=form_timeout)
            except PlaywrightTimeoutError:
                pass

            fingerprint = page.evaluate(JS)
            login_form = page.evaluate(LOGIN_FORM_JS)
            _raise_if_login_form_missing(page, response, login_form)
            storage_state = browser_context.storage_state()
            cookies_list = storage_state.get("cookies", [])
        finally:
            browser.close()

    cookies = {cookie["name"]: cookie["value"] for cookie in cookies_list}
    cookie_header = format_cookie_header(cookies)
    headers = build_captcha_headers(fingerprint, referer=url)
    return BrowserRequestContext(
        cookies=cookies,
        headers=headers,
        fingerprint=fingerprint,
        login_form=login_form,
        cookie_header=cookie_header,
        storage_state=storage_state,
    )


def pass_captcha_check(
    context: BrowserRequestContext,
    *,
    cookies_path: Path = COOKIES_JSON_PATH,
) -> CaptchaCheckResult:
    """基于浏览器上下文完成一次验证码校验，并保存校验后的 Cookie。"""

    result = pass_slider_captcha(
        context=context,
        cookies=context.cookies,
        image_headers=context.headers,
        check_headers=check_headers(context, referer=URL),
        proxies=REQUEST_PROXIES,
        filename_prefix="tncode",
        debug_dir=DEBUG_DIR,
    )
    save_json(cookies_path, result.cookies)

    return CaptchaCheckResult(
        check_text=result.check_text,
        cookies=result.cookies,
    )


def save_context_with_cookies(path: Path, context: BrowserRequestContext, cookies: dict[str, str]) -> None:
    """把采集到的上下文和最新 Cookie 写入 context.json。"""

    context_data = asdict(context)
    context_data["cookies"] = cookies
    context_data["cookie_header"] = format_cookie_header(cookies)
    save_json(path, context_data)


def refresh_account(account: AccountConfig, *, headless: bool = True) -> None:
    """刷新单个账号的登录态；账号配置缺少密码时只保存未登录上下文。"""

    print(f"account: {account.name}")
    context = get_browser_request_context(headless=headless, proxies=REQUEST_PROXIES)
    save_context_with_cookies(account.context_path, context, context.cookies)
    save_json(account.cookies_path, context.cookies)
    print("fingerprint data:", context.fingerprint)
    # print("login form:", context.login_form)
    print("cookie header:", context.cookie_header)
    print("context saved:", account.context_path.resolve())
    print("cookies saved:", account.cookies_path.resolve())

    captcha_check = pass_captcha_check(context, cookies_path=account.cookies_path)
    check_text = captcha_check.check_text
    login_cookies = dict(captcha_check.cookies)

    login_username = account.username
    login_password = account.password
    if not login_username or not login_password:
        print(f"skip login: 账号 {account.name} 缺少 username/password 配置")
    else:
        login_response = login(
            login_username,
            login_password,
            context,
            check_text,
            cookies=login_cookies,
            proxies=REQUEST_PROXIES,
        )
        print(f"login response status: {login_response.status_code}")
        print(f"login response: {login_response.text[:1000]}")
        print(f"login response cookies: {login_response.cookies.get_dict() if getattr(login_response, 'cookies', None) else {}}")
        if getattr(login_response, "cookies", None) is not None:
            login_cookies.update(login_response.cookies.get_dict())
        save_json(account.cookies_path, login_cookies)
        save_context_with_cookies(account.context_path, context, login_cookies)
        print("cookies saved:", account.cookies_path.resolve())
        print("context saved:", account.context_path.resolve())


def parse_args() -> argparse.Namespace:
    """解析刷新账号登录态的命令行参数。"""

    parser = argparse.ArgumentParser(description="刷新老王账号的 context 和 cookies")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="账号配置文件路径，默认 laowang/accounts.json",
    )
    parser.add_argument("--account", help="只刷新指定账号名")
    parser.add_argument("--all", action="store_true", help="刷新配置中的全部账号")
    parser.add_argument("--headless", action="store_true", help="使用无头浏览器（更容易触发风控）")
    parser.add_argument("--headed", action="store_false", dest="headless", help="显示浏览器窗口，默认启用")
    parser.set_defaults(headless=False)
    return parser.parse_args()


def main() -> int:
    """命令行入口，支持单账号或全部账号刷新。"""

    args = parse_args()
    accounts = select_account_configs(
        config_path=Path(args.config),
        account_name=args.account,
        all_accounts=args.all,
    )

    failed: list[tuple[str, Exception]] = []
    for account in accounts:
        try:
            refresh_account(account, headless=args.headless)
        except Exception as exc:
            failed.append((account.name, exc))
            print(f"account {account.name} failed: {exc}", file=sys.stderr)
            if not args.all:
                break

    if failed:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
