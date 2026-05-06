import requests

cookies = {
    'uLocale': 'zh_CN',
    'deviceId': 'wb_077501eb-0aae-445a-8ace-a063d8cc1d58',
    'pass_ua': 'web',
}

headers = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'EUI': 'bZhWvz24yolZFmjWNxnjf+YV/gkBBiw0N+PgCxk1xWgOwODeDCVcHouAIUmxPhP7pTwJiVsXNNRRd9rSy7pBhxbbeBVzGEA1QdIzCG2gZJuSm7e8p4UB/U4/kZQDUMK3WAtLM1zfoItCQ2hWU3OuE0rN2e+6bfcp/N+SisAHPzQ=.dXNlcg==',
    'Origin': 'https://account.xiaomi.com',
    'Pragma': 'no-cache',
    'Referer': 'https://account.xiaomi.com/fe/service/login/password?_group=DEFAULT&sid=passport&qs=%253Fcallback%253Dhttps%25253A%25252F%25252Faccount.xiaomi.com%25252Fsts%25253Fsign%25253DZvAtJIzsDsFe60LdaPa76nNNP58%2525253D%252526followup%25253Dhttps%2525253A%2525252F%2525252Faccount.xiaomi.com%2525252Fpass%2525252Fauth%2525252Fsecurity%2525252Fhome%252526sid%25253Dpassport%2526sid%253Dpassport%2526_group%253DDEFAULT&callback=https%3A%2F%2Faccount.xiaomi.com%2Fsts%3Fsign%3DZvAtJIzsDsFe60LdaPa76nNNP58%253D%26followup%3Dhttps%253A%252F%252Faccount.xiaomi.com%252Fpass%252Fauth%252Fsecurity%252Fhome%26sid%3Dpassport&_sign=2%26V1_passport%26BUcblfwZ4tX84axhVUaw8t6yi2E%3D&serviceParam=%7B%22checkSafePhone%22%3Afalse%2C%22checkSafeAddress%22%3Afalse%2C%22lsrp_score%22%3A0.0%7D&showActiveX=false&theme=&needTheme=false&bizDeviceType=&_locale=zh_CN',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    # 'Cookie': 'uLocale=zh_CN; deviceId=wb_077501eb-0aae-445a-8ace-a063d8cc1d58; pass_ua=web',
}

data = {
    'bizDeviceType': '',
    'needTheme': 'false',
    'theme': '',
    'showActiveX': 'false',
    'serviceParam': '{"checkSafePhone":false,"checkSafeAddress":false,"lsrp_score":0.0}',
    'callback': 'https://account.xiaomi.com/sts?sign=ZvAtJIzsDsFe60LdaPa76nNNP58%3D&followup=https%3A%2F%2Faccount.xiaomi.com%2Fpass%2Fauth%2Fsecurity%2Fhome&sid=passport',
    'qs': '%3Fcallback%3Dhttps%253A%252F%252Faccount.xiaomi.com%252Fsts%253Fsign%253DZvAtJIzsDsFe60LdaPa76nNNP58%25253D%2526followup%253Dhttps%25253A%25252F%25252Faccount.xiaomi.com%25252Fpass%25252Fauth%25252Fsecurity%25252Fhome%2526sid%253Dpassport%26sid%3Dpassport%26_group%3DDEFAULT',
    'sid': 'passport',
    '_sign': '2&V1_passport&BUcblfwZ4tX84axhVUaw8t6yi2E=',
    'user': '3jf1b3beDcgWNeqeSw4zCg==',
    'cc': '+86',
    'hash': 'F395621613C76A14C59A3DD80D5ACED3',
    '_json': 'true',
    'policyName': 'miaccount',
    'captCode': '',
    'deviceFingerprint': 'f14845c18ab3689c495e0b0a4eb7f99c',
}

response = requests.post('https://account.xiaomi.com/pass/serviceLoginAuth2', cookies=cookies, headers=headers, data=data)
print(response.text)