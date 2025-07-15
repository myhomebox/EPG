from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import json
import os
import time
from datetime import datetime

# 需要過濾的頻道名稱列表
BLOCKED_CHANNELS = [
    "鳳梨直擊台",
    "香蕉直擊台",
    "芭樂直擊台"
]

try:
    # 設置 Chrome 選項
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-setuid-sandbox")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    
    # 使用 webdriver-manager 自動管理驅動
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )
    
    # 設置頁面加載超時時間
    driver.set_page_load_timeout(30)
    
    # 訪問 API URL
    api_url = "https://api2.4gtv.tv/Channel/GetAllChannel/pc/L"
    print(f"正在訪問: {api_url}")
    driver.get(api_url)
    
    # 等待頁面加載
    time.sleep(3)
    
    # 獲取頁面內容
    content = driver.page_source
    
    # 檢查是否是 JSON 內容
    if content.strip().startswith('{') or content.strip().startswith('['):
        # 嘗試解析 JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            print(f"JSON 解析錯誤，內容: {content[:200]}")
            exit(1)
    else:
        print(f"獲取到非 JSON 內容: {content[:200]}")
        # 嘗試從 pre 標籤獲取數據
        try:
            pre_element = driver.find_element("tag name", "pre")
            content = pre_element.text
            data = json.loads(content)
        except:
            print("無法解析內容為 JSON")
            exit(1)
    
    # 檢查數據結構
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
    
    # 建立輸出目錄
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    # 寫入 JSON 文件
    output_path = os.path.join(output_dir, 'fourgtv.json')
    with open(output_path, 'w', encoding='utf-8') as f:
       json.dump(extracted_data, f, ensure_ascii=False, indent=2)
    
    print(f"成功生成 ./output/fourgtv.json ({len(extracted_data)} 條記錄)")
    print(f"跳過頻道: {', '.join(BLOCKED_CHANNELS)}")
    print(f"最後更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

except Exception as e:
    print(f"處理失敗: {str(e)}")
    exit(1)
finally:
    try:
        if driver:
            driver.quit()
    except:
        pass
