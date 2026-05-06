import requests
import json
import re

def extract_rid_from_jsonp(jsonp_str):
    """
    从 JSONP 格式的字符串中提取 rid 值
    
    Args:
        jsonp_str: JSONP 格式的字符串，例如: sm_1775742412882({...})
    
    Returns:
        str: rid 的值，如果提取失败返回 None
    """
    try:
        # 使用正则表达式提取 JSON 部分
        # 匹配函数名后的括号内容
        pattern = r'\((.*)\)$'
        match = re.search(pattern, jsonp_str)
        
        if not match:
            return None
        
        json_str = match.group(1)
        
        # 解析 JSON
        data = json.loads(json_str)
        
        # 提取 detail.rid
        rid = data.get('detail', {}).get('rid')
        
        return rid
        
    except (json.JSONDecodeError, AttributeError, KeyError) as e:
        print(f"解析 JSONP 字符串时出错: {e}")
        return None

headers = {
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Referer': 'https://www.duitang.com/',
    'Sec-Fetch-Dest': 'script',
    'Sec-Fetch-Mode': 'no-cors',
    'Sec-Fetch-Site': 'cross-site',
    'Sec-Fetch-Storage-Access': 'active',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
}

params = {
    'channel': 'DEFAULT',
    'sdkver': '1.1.3',
    'appId': 'default',
    'model': 'slide',
    'rversion': '1.0.3',
    'data': '{}',
    'callback': 'sm_1775742412882',
    'lang': 'zh-cn',
    'organization': 'ltA7kUoBFCTVmRodXoKD',
}

response = requests.get('https://captcha1.fengkongcloud.cn/ca/v1/register', params=params, headers=headers)
print(response.text)

# 使用示例
rid = extract_rid_from_jsonp(response.text)
print(f"提取到的 rid: {rid}")


cookies = {
    'js': '1',
    'HWWAFSESID': '332ce7678522c24ae1',
    'HWWAFSESTIME': '1775733050987',
    'sessionid': '358ff104-2555-4c33-9b6e-8925cb305eff',
    'js': '1',
    'Hm_lvt_d8276dcc8bdfef6bb9d5bc9e3bcfcaf4': '1775733052',
    'HMACCOUNT': 'B83A69F8B6485BB0',
    '_gid': 'GA1.2.95783973.1775733053',
    'Hm_lpvt_d8276dcc8bdfef6bb9d5bc9e3bcfcaf4': '1775742398',
    '_ga_EE20FJFZZQ': 'GS2.1.s1775742398$o2$g0$t1775742398$j60$l0$h0',
    '_ga': 'GA1.2.969297703.1775733053',
}

headers = {
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Origin': 'https://www.duitang.com',
    'Pragma': 'no-cache',
    'Referer': 'https://www.duitang.com/login/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    # 'Cookie': 'js=1; HWWAFSESID=332ce7678522c24ae1; HWWAFSESTIME=1775733050987; sessionid=358ff104-2555-4c33-9b6e-8925cb305eff; js=1; Hm_lvt_d8276dcc8bdfef6bb9d5bc9e3bcfcaf4=1775733052; HMACCOUNT=B83A69F8B6485BB0; _gid=GA1.2.95783973.1775733053; Hm_lpvt_d8276dcc8bdfef6bb9d5bc9e3bcfcaf4=1775742398; _ga_EE20FJFZZQ=GS2.1.s1775742398$o2$g0$t1775742398$j60$l0$h0; _ga=GA1.2.969297703.1775733053',
}

data = {
    'login_name': 'chenmingsimon@gmail.com',
    'pswd': 'YhkpbPu8S1Q9kLwIMBz3i9emVVHCDxetXTY4yLCKSnwGE5bUMfUm/qWVTqumeCEENhpFxXmZYjLD9XbNnbERPxSHW3X/tKr1NtyKVN6lb9Qh0rnoNTHddU7ZQehZLXtp2+iKHXTzOVEFYY60ZdeZUrObdVNZNfxaIN3dwRLLKiTdPwoi+Eh52fAmBx6cmQkyIbR+tYt4MurWSWFxnQD+W96BN8RTx1IV4vkBmQNq5rXdamDaXiMh4fBYBg+RqQxuFZYWuFgqbtWMklKiWMrtLdVBpLDPmh9yfOTpXAYS0boQcpoVQ40Icby7MPO/711XsFIRbo45V7fud38ocyTmMQ==',
    '': '',
    'rid': rid,
    'remember': 'false',
}

response = requests.post('https://www.duitang.com/login/', cookies=cookies, headers=headers, data=data)
print(response.text)
