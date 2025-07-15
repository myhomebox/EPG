import requests
import json
import os
from datetime import datetime
import urllib3

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# API 網址
url = "https://api2.4gtv.tv/Channel/GetAllChannel/pc/L"

# 需要過濾的頻道名稱列表
BLOCKED_CHANNELS = [
    "鳳梨直擊台",
    "香蕉直擊台",
    "芭樂直擊台"
]

# 添加瀏覽器級別的請求頭
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://www.4gtv.tv",
    "Referer": "https://www.4gtv.tv/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

try:
    # 發送 GET 請求並禁用 SSL 驗證
    response = requests.get(
        url,
        headers=HEADERS,
        verify=False,
        timeout=30
    )
    
    # 檢查響應狀態
    if response.status_code != 200:
        print(f"錯誤狀態碼: {response.status_code}")
        print(f"響應內容: {response.text[:200]}")
        exit(1)
        
    # 解析 JSON 數據
    data = response.json()
    
    # 檢查是否有有效數據
    if "Data" not in data or not isinstance(data["Data"], list):
        print(f"API 返回無效數據: {data}")
        exit(1)
    
    # 提取所需字段並過濾特定頻道
    extracted_data = []
    for channel in data.get("Data", []):
        channel_name = channel.get("fsNAME", "")
        
        # 檢查是否在禁止列表中
        if any(blocked in channel_name for blocked in BLOCKED_CHANNELS):
            print(f"已跳過頻道: {channel_name}")
            continue
            
        extracted_data.append({
            "fsNAME": channel_name,
            "fs4GTV_ID": channel.get("fs4GTV_ID"),
            "fsLOGO_MOBILE": channel.get("fsLOGO_MOBILE"),
            "fsDESCRIPTION": channel.get("fsDESCRIPTION")
        })
    
    # 創建輸出目錄
    os.makedirs('output', exist_ok=True)
    
    # 寫入 JSON 文件
    output_path = os.path.join('output', 'fourgtv.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(extracted_data, f, ensure_ascii=False, indent=2)
    
    print(f"成功生成 fourgtv.json ({len(extracted_data)} 條記錄)")
    print(f"跳過頻道: {', '.join(BLOCKED_CHANNELS)}")
    print(f"最後更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

except Exception as e:
    print(f"處理失敗: {str(e)}")
    exit(1)
