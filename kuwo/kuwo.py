import requests
import execjs
import os

def generate_req_id() -> str:
    js_file = os.path.join(os.path.dirname(__file__), 'kuwo.js')
    with open(js_file, 'r', encoding='utf-8') as f:
        js_code = f.read()
    ctx = execjs.compile(js_code)
    return ctx.call('a')

cookies = {
    '_ga': 'GA1.2.359233052.1776234895',
    '_gid': 'GA1.2.1220486680.1776234895',
    'Hm_lvt_cdb524f42f0ce19b169a8071123a4797': '1776223526,1776245659',
    'HMACCOUNT': 'A76667A4B233DCBC',
    'Hm_lpvt_cdb524f42f0ce19b169a8071123a4797': '1776246535',
    '_ga_ETPBRPM9ML': 'GS2.2.s1776245660$o3$g1$t1776246536$j60$l0$h0',
    'Hm_Iuvt_cdb524f42f23cer9b268564v7y735ewrq2324': 'YiXcbrM6p4AFyhR8NSp86QKhfwwQJnYf',
}

headers = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Referer': 'http://www.kuwo.cn/search/list?key=%E5%85%B3%E5%B1%B1%E9%85%921',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    # 'Cookie': '_ga=GA1.2.359233052.1776234895; _gid=GA1.2.1220486680.1776234895; Hm_lvt_cdb524f42f0ce19b169a8071123a4797=1776223526,1776245659; HMACCOUNT=A76667A4B233DCBC; Hm_lpvt_cdb524f42f0ce19b169a8071123a4797=1776246535; _ga_ETPBRPM9ML=GS2.2.s1776245660$o3$g1$t1776246536$j60$l0$h0; Hm_Iuvt_cdb524f42f23cer9b268564v7y735ewrq2324=YiXcbrM6p4AFyhR8NSp86QKhfwwQJnYf',
}

req_id = generate_req_id()
print(f"生成的reqId: {req_id}")

params = {
    'key': '关山酒1',
    'httpsStatus': '1',
    'reqId': req_id,
    'plat': 'web_www',
    'from': '',
}

response = requests.get(
    'http://www.kuwo.cn/openapi/v1/www/search/searchKey',
    params=params,
    cookies=cookies,
    headers=headers,
    verify=False,
)

print(response.text)