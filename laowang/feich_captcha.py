from pathlib import Path
import random
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any

try:
    from curl_cffi import requests
except ImportError:
    requests = None

CAPTCHA_URL = 'https://laowang.vip/captcha/tncode.php'


@dataclass(frozen=True)
class CaptchaFetchResult:
    image_path: Path
    cookies: dict[str, str]
    headers: dict[str, str]
    response_headers: dict[str, str]
    status_code: int


def image_suffix_from_response(response):
    content_type = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    content_type_map = {
        'image/png': '.png',
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'image/avif': '.avif',
        'image/bmp': '.bmp',
    }
    if content_type in content_type_map:
        return content_type_map[content_type]

    data = response.content[:32]
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return '.gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return '.webp'
    if data[4:12] == b'ftypavif':
        return '.avif'
    if data.startswith(b'BM'):
        return '.bmp'

    raise ValueError(f'无法识别图片格式，Content-Type={content_type!r}, 文件头={data.hex()}')


def save_image_response(response, filename_prefix='tncode'):
    if response.status_code != 200:
        preview = response.text[:300] if hasattr(response, 'text') else response.content[:300]
        raise RuntimeError(
            f'请求失败: HTTP {response.status_code}\n'
            f'Content-Type: {response.headers.get("content-type", "")}\n'
            f'响应预览: {preview}'
        )
    suffix = image_suffix_from_response(response)
    path = Path(f'{filename_prefix}{suffix}')
    path.write_bytes(response.content)
    return path


def _extract_response_cookies(response) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if getattr(response, 'cookies', None) is not None:
        cookies.update(response.cookies.get_dict())

    set_cookie = response.headers.get('set-cookie')
    if set_cookie:
        parsed = SimpleCookie()
        parsed.load(set_cookie)
        cookies.update({key: morsel.value for key, morsel in parsed.items()})
    return cookies


def fetch_captcha_image(
    *,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    proxies: dict[str, str] | None = None,
    captcha_url: str = CAPTCHA_URL,
    filename_prefix: str = 'tncode',
    params: dict[str, Any] | None = None,
    timeout: int = 60,
) -> CaptchaFetchResult:
    if requests is None:
        raise RuntimeError('缺少依赖: pip install curl_cffi')

    request_cookies = dict(cookies or {})
    request_headers = dict(headers or {})
    request_params = {'t': str(random.random())}
    if params:
        request_params.update(params)

    response = requests.get(
        captcha_url,
        params=request_params,
        cookies=request_cookies,
        headers=request_headers,
        impersonate='chrome',
        proxies=proxies,
        timeout=timeout,
    )
    image_path = save_image_response(response, filename_prefix=filename_prefix)

    merged_cookies = dict(request_cookies)
    merged_cookies.update(_extract_response_cookies(response))
    return CaptchaFetchResult(
        image_path=image_path,
        cookies=merged_cookies,
        headers=request_headers,
        response_headers=dict(response.headers),
        status_code=response.status_code,
    )


if __name__ == '__main__':
    result = fetch_captcha_image()
    print(f'图片已保存: {result.image_path.resolve()}')
    print('cookies:', result.cookies)
