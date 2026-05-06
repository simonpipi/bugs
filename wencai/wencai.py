import requests

cookies = {
    # 'other_uid': 'Ths_iwencai_Xuangu_0ex2g7pnsvvoie71rps2g7167rz4wvye',
    # '_clck': '13txdxi%7C2%7Cg51%7C0%7C0',
    # 'cid': 'b2283c5598303a6c455f5fde885d20241775609140',
    # 'THSSESSID': '19c230b9682476bea7232a96a5',
    # 'u_ukey': 'A10702B8689642C6BE607730E11E6E4A',
    # 'u_uver': '1.0.0',
    # 'u_dpass': 'cMp6At7ct6v3wxVXrM99pm6WjqvbrOo2y2BRnCIhddWvaMXPkZq9y0sXw2JJ0QcoHi80LrSsTFH9a%2B6rtRvqGg%3D%3D',
    # 'u_did': 'F9D2427358BD4FAEB6B468E3B9AAF84E',
    # 'u_ttype': 'WEB',
    # '_clsk': '66wt3613wkci%7C1775610684516%7C13%7C1%7C',
    # 'v': 'A6TSapdnkcKSweWOwtIYJwKfc6mTPcknimJcyr7FMVowEUqX5k2YN9pxLFoN',
}

headers = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Origin': 'https://www.iwencai.com',
    'Pragma': 'no-cache',
    'Referer': 'https://www.iwencai.com/unifiedwap/result?w=DeepSeek%E6%A6%82%E5%BF%B5&querytype=stock&sign=1775609674057',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'hexin-v': 'A6TSapdnkcKSweWOwtIYJwKfc6mTPcknimJcyr7FMVowEUqX5k2YN9pxLFoN',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    # 'Cookie': 'other_uid=Ths_iwencai_Xuangu_0ex2g7pnsvvoie71rps2g7167rz4wvye; _clck=13txdxi%7C2%7Cg51%7C0%7C0; cid=b2283c5598303a6c455f5fde885d20241775609140; THSSESSID=19c230b9682476bea7232a96a5; u_ukey=A10702B8689642C6BE607730E11E6E4A; u_uver=1.0.0; u_dpass=cMp6At7ct6v3wxVXrM99pm6WjqvbrOo2y2BRnCIhddWvaMXPkZq9y0sXw2JJ0QcoHi80LrSsTFH9a%2B6rtRvqGg%3D%3D; u_did=F9D2427358BD4FAEB6B468E3B9AAF84E; u_ttype=WEB; _clsk=66wt3613wkci%7C1775610684516%7C13%7C1%7C; v=A6TSapdnkcKSweWOwtIYJwKfc6mTPcknimJcyr7FMVowEUqX5k2YN9pxLFoN',
}

data = {
    'query': 'DeepSeek概念',
    'urp_sort_way': 'desc',
    'urp_sort_index': '最新涨跌幅',
    'page': '1',
    'perpage': '50',
    'addheaderindexes': '',
    'condition': '[{"dateText":"","ci":false,"indexName":"所属概念","indexProperties":["包含DeepSeek概念"],"source":"text2sql","type":"index","indexPropertiesMap":{"包含":"DeepSeek概念"},"reportType":"null","score":0,"ciChunk":"deepseek概念","node_type":"index","chunkedResult":"deepseek概念","domain":"abs_股票领域","uiText":"所属概念包含DeepSeek概念","valueType":"_所属概念","sonSize":0}]',
    'codelist': '',
    'indexnamelimit': '',
    'logid': '4a8047845eaf926a42b757ca0c4c5648',
    'ret': 'json_all',
    # 'sessionid': 'b360663a31193d2de60c917ce16d787d',
    'source': 'Ths_iwencai_Xuangu',
    'date_range[0]': '20260408',
    # 'iwc_token': '0af31f9d17756106866511909',
    'urp_use_sort': '1',
    # 'user_id': 'Ths_iwencai_Xuangu_0ex2g7pnsvvoie71rps2g7167rz4wvye',
    'uuids[0]': '24087',
    'query_type': 'stock',
    'comp_id': '6933312',
    'business_cat': 'soniu',
    'uuid': '24087',
}

response = requests.post('https://www.iwencai.com/gateway/urp/v7/landing/getDataList', cookies=cookies, headers=headers, data=data)

print(response.json())