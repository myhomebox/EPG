from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import json
import os
from datetime import datetime

# 設置 Chrome 選項
chrome_options = Options()
chrome_options.add_argument("--headless")  # 無頭模式
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# 需要過濾的頻道名稱列表
BLOCKED_CHANNELS = [
    "鳳梨直擊台",
    "香蕉直擊台",
    "芭樂直擊台"
]

try:
    # 初始化瀏覽器
    driver = webdriver.Chrome(options=chrome_options)
    driver.get("https://api2.4gtv.tv/Channel/GetAllChannel/pc/L")
    
    # 獲取頁面內容
    content = driver.page_source
    if '<!DOCTYPE html>' in content:
        # 可能是 HTML 錯誤頁面
        print(f"獲取到 HTML 內容而非 JSON: {content[:200]}")
        exit(1)
    
    # 解析 JSON 數據
    data = json.loads(content)
    
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
finally:
    if driver:
        driver.quit()
