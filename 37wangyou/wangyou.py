import requests
import random

def custom_base64_encode(s: str) -> str:
    ch = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    out = ""
    i = 0
    length = len(s)
    
    while i < length:
        c1 = ord(s[i]) & 0xff
        i += 1
        
        if i == length:
            out += ch[c1 >> 2]
            out += ch[(c1 & 0x3) << 4]
            out += "=="
            break
        
        c2 = ord(s[i])
        i += 1
        
        if i == length:
            out += ch[c1 >> 2]
            out += ch[((c1 & 0x3) << 4) | ((c2 & 0xF0) >> 4)]
            out += ch[(c2 & 0xF) << 2]
            out += "="
            break
        
        c3 = ord(s[i])
        i += 1
        
        out += ch[c1 >> 2]
        out += ch[((c1 & 0x3) << 4) | ((c2 & 0xF0) >> 4)]
        out += ch[((c2 & 0xF) << 2) | ((c3 & 0xC0) >> 6)]
        out += ch[c3 & 0x3F]
    
    return out

def encrypt_password(password: str) -> str:
    ch = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    max_pos = len(ch) - 2
    w = []
    
    for i in range(15):
        w.append(ch[random.randint(0, max_pos)])
        if i == 7:
            w.append(password[:3])
        if i == 12:
            w.append(password[3:])
    
    combined = ''.join(w)
    encoded = custom_base64_encode(combined)
    return encoded

cookies = {
    '37wanrefer': 'cloud.tencent.com',
    'Hm_lvt_2bff1797982a3dfe38d535d59aca3334': '1776040745',
    'Hm_lpvt_2bff1797982a3dfe38d535d59aca3334': '1776040745',
    'HMACCOUNT': 'B83A69F8B6485BB0',
    'tg_uv': 'KjvcaeX07CUBAAAAV81t',
    'PHPSESSID': 'gd7cn5jf1ki41kcioi1bpou816',
}

headers = {
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Referer': 'https://www.37.com/',
    'Sec-Fetch-Dest': 'script',
    'Sec-Fetch-Mode': 'no-cors',
    'Sec-Fetch-Site': 'same-site',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    # 'Cookie': '37wanrefer=cloud.tencent.com; Hm_lvt_2bff1797982a3dfe38d535d59aca3334=1776040745; Hm_lpvt_2bff1797982a3dfe38d535d59aca3334=1776040745; HMACCOUNT=B83A69F8B6485BB0; tg_uv=KjvcaeX07CUBAAAAV81t; PHPSESSID=gd7cn5jf1ki41kcioi1bpou816',
}

original_pwd = "simon5.."
pwd = encrypt_password(original_pwd)

print(f"原始密码: {original_pwd}")
print(f"加密后密码: {pwd}")



params = {
    'callback': 'jQuery18306203547276567382_1776040744355',
    'action': 'login',
    'login_account': 'hbacc0081090',
    'password': pwd,
    'ajax': '0',
    'remember_me': '1',
    'save_state': '1',
    'ltype': '1',
    'tj_from': '100',
    's': '1',
    'img_ver': '1.0',
    'tj_way': '1',
    '_': '1776041085248',
}

response = requests.get('https://my.37.com/api/login.php', params=params, cookies=cookies, headers=headers)
print(response.text)