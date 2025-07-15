import requests
import json
import os
from datetime import datetime

# API 網址
url = "https://api2.4gtv.tv/Channel/GetAllChannel/pc/L"

# 需要過濾的頻道名稱列表
BLOCKED_CHANNELS = [
    "鳳梨直擊台",
    "香蕉直擊台",
    "芭樂直擊台"
]

try:
    # 發送 GET 請求
    response = requests.get(url)
    response.raise_for_status()  # 檢查請求是否成功
    
    # 解析 JSON 數據
    data = response.json()
    
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
    
    # 建立輸出目錄
    os.makedirs('output', exist_ok=True)
    
    # 寫入 JSON 文件
    output_path = os.path.join('output', 'fourgtv.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(extracted_data, f, ensure_ascii=False, indent=2)
    
    print(f"成功生成 fourgtv.json ({len(extracted_data)} 則記錄)")
    print(f"跳過頻道: {', '.join(BLOCKED_CHANNELS)}")
    print(f"最後更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

except Exception as e:
    print(f"處理失敗: {str(e)}")
    exit(1)
