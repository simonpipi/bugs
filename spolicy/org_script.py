import requests
import execjs

cookies = {
    'Hm_lvt_6146f11e5afab71309b3accbfc4a932e': '1775638484',
    'HMACCOUNT': 'B83A69F8B6485BB0',
    'JSESSIONID': '0DC4B9A58870C151D243E9A2C2E42903',
    'Hm_lpvt_6146f11e5afab71309b3accbfc4a932e': '1775639485',
}

headers = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Content-Type': 'application/octet-stream',
    'Origin': 'https://www.spolicy.com',
    'Pragma': 'no-cache',
    'Referer': 'https://www.spolicy.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    # 'Cookie': 'Hm_lvt_6146f11e5afab71309b3accbfc4a932e=1775638484; HMACCOUNT=B83A69F8B6485BB0; JSESSIONID=0DC4B9A58870C151D243E9A2C2E42903; Hm_lpvt_6146f11e5afab71309b3accbfc4a932e=1775639485',
}

with open('/Users/chenmingbo/Desktop/bugs/org.js', 'r', encoding='utf-8') as f:
    js_code = f.read()

ctx = execjs.compile(js_code)
encrypted_data = ctx.call('encrypt', None)
data = bytes(encrypted_data['data'])

response = requests.post('https://www.spolicy.com/info_api/policyType/showPolicyType', cookies=cookies, headers=headers, data=data)
print(response.json())