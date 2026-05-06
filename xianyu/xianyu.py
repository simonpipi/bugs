import requests
import json
import time
import hashlib
import fetch_token


# 
# 咸鱼请求无法进行流量回放，如果是回访，测试感觉返回的是假数据，和真实的请求接口数据不一致。
#

data = {
    'data': '{"itemId":"","pageSize":30,"pageNumber":1,"machId":"165362_1"}',
}

def generate_sign(token,data):
    """生成签名"""
    # 生成当前时间戳（毫秒级）
    timestamp = int(time.time() * 1000)

    # 构建签名原始字符串
    sign_str = f"{token}&{timestamp}&{APP_KEY}&{data}"

    # 计算MD5签名
    md5 = hashlib.md5()
    md5.update(sign_str.encode("utf-8"))
    sign = md5.hexdigest()

    return sign, timestamp


cookies = fetch_token.get_cookies()
APP_KEY = "34839810"
token = cookies['_m_h5_tk'].split('_')[0]
headers = {
    'accept': 'application/json',
    'accept-language': 'zh-CN,zh;q=0.9',
    'cache-control': 'no-cache',
    'content-type': 'application/x-www-form-urlencoded',
    'origin': 'https://www.goofish.com',
    'pragma': 'no-cache',
    'priority': 'u=1, i',
    'referer': 'https://www.goofish.com/',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    # 'cookie': 'cna=hS9dIrXFsxwCAXug4CTGzSzL; cookie2=123ea59a898772aaa798146f77acfe7b; xlly_s=1; _samesite_flag_=true; t=e67e921b8c1f24324cc8c7bfea2f5591; _tb_token_=f3eae1eeee715; mtop_partitioned_detect=1; _m_h5_tk=8ad43271d3de3656f499d12d6440b82c_1775706013835; _m_h5_tk_enc=cdfcb6cdadcc0cd21006329890f4733f; tracknick=simon_aibenben; unb=140562940; sgcookie=E100d24qRaOSdFNNFozEtKY4LdW0z0q4AjA5xqALK9DLH3iuPiSUlZZc%2BwgPHgvghBzwRex4EzJ71dwpYAGka413zo8%2FVYeoFY1GVo2u5OKOSZI%3D; csg=c48db19c; havana_lgc2_77=eyJoaWQiOjE0MDU2Mjk0MCwic2ciOiJiZjQwZWI5NDUwZDU0MmU5YTljNWJhNjM0NjM3YzM4MSIsInNpdGUiOjc3LCJ0b2tlbiI6IjFLd0Nnakp5X0txODBvZU5XN0JybEV3In0; _hvn_lgc_=77; havana_lgc_exp=1778289719506; sdkSilent=1775784122750; tfstk=g2qEdwizV0V1ANC03-mP7XMOGzmKP05XauGSE82odXcHAHOu7SVtOzaIOLzaZ53ItuyJ4Y2uw9h5pNwLp0nlGs6fcJeK7GJzckkkIh2teYDl52cM76JcGssffwvi465bdhFe7fD-svDoEeXZjYH-K00oKRXZEYOHrHVuIOlteUDnZ20gIYk-Z0muZRXZefDnq2VuIOk-sbDOAyaW7x0hLqpHm96G9_h4Kf-kqkj-8j-qiAH3b-0niVXMV3_-L2l0Kf5UBcXZzWuUfMRxLP24CvPRDHnnzzqIjkfGqc2Y5WDaZs8rsrrL4qZFgEh3vbFZly52YSPKE8kuTipqskyzb2U6hnyZulqIvP52cj4TEuugps8xCz2bAzPC63cQuRVZllO6cm4Y_uummgSJwAfCQuUeZUunBAlfQOzpJpveXm5TOUL-SjkZG9hpyU3nGAlfQO8JyVDsQj6K9',
}
sign , timestamp = generate_sign(token,data['data'])
params = {
    'jsv': '2.7.2',
    'appKey': '34839810',
    't': timestamp,
    'sign': sign,
    'v': '1.0',
    'type': 'originaljson',
    'accountSite': 'xianyu',
    'dataType': 'json',
    'timeout': '20000',
    'api': 'mtop.taobao.idlehome.home.webpc.feed',
    'sessionOption': 'AutoLoginOnly',
    'spm_cnt': 'a21ybx.home.0.0',
}




response = requests.post(
    'https://h5api.m.goofish.com/h5/mtop.taobao.idlehome.home.webpc.feed/1.0/',
    params=params,
    cookies=cookies,
    headers=headers,
    data=data,
)
result = response.json()
print(result)

with open('xianyu_response.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print('响应结果已保存到 xianyu_response.json')
