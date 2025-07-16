import os
import json
import requests
import datetime
import pytz
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import random
import cloudscraper
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')

# 配置瀏覽器選項
def get_chrome_options():
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
    return chrome_options

# 建立瀏覽器實例
def create_browser():
    chrome_options = get_chrome_options()
    service = Service(ChromeDriverManager().install())
    browser = webdriver.Chrome(service=service, options=chrome_options)
    browser.set_page_load_timeout(30)
    return browser

# 建立Cloudscraper實例
def create_cloudscraper():
    return cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

def create_session():
    """建立帶有重試機制的會話"""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session

def get_4gtv_epg():
    logger.info("正在獲取 四季線上 電子節目表")
    channels = get_4gtv_channels()
    programs = []
    
    # 建立Cloudscraper實例
    scraper = create_cloudscraper()
    
    # 建立瀏覽器實例（備用）
    browser = None
    
    for channel in channels:
        channel_id = channel['channelId']
        channel_name = channel['channelName']
        
        # 添加隨機延遲減少請求頻率
        delay = random.uniform(1.0, 3.0)
        logger.debug(f"等待 {delay:.2f} 秒後獲取 {channel_name} 節目表")
        time.sleep(delay)
        
        # 嘗試多種方法獲取節目表
        channel_programs = None
        methods = [
            lambda: get_4gtv_programs_scraper(channel_id, channel_name, scraper),
            lambda: get_4gtv_programs_selenium(channel_id, channel_name, browser)
        ]
        
        for method in methods:
            try:
                channel_programs = method()
                if channel_programs:
                    break
            except Exception as e:
                logger.warning(f"方法失敗: {e}")
                continue
        
        if channel_programs:
            programs.extend(channel_programs)
        else:
            logger.error(f"所有方法都無法獲取 {channel_name} 節目表")
    
    # 關閉瀏覽器實例
    if browser:
        try:
            browser.quit()
        except:
            pass
    
    return channels, programs

def get_4gtv_channels():
    # 使用新的输出路径
    local_file = os.path.join(OUTPUT_DIR, 'fourgtv.json')
    if os.path.exists(local_file):
        try:
            logger.info(f"從本地檔案讀取頻道列表: {local_file}")
            with open(local_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            channels = [
                {
                    "channelName": item["fsNAME"],
                    "channelId": item["fs4GTV_ID"],
                    "logo": item["fsLOGO_MOBILE"],
                    "description": item.get("fsDESCRIPTION", "")
                }
                for item in data
            ]
            return channels
        
        except Exception as e:
            logger.error(f"讀取本地頻道檔案失敗: {e}")

    try:
        # 如果本地檔案不存在，嘗試從API獲取
        session = create_session()
        api_url = "https://api2.4gtv.tv/Channel/GetAllChannel/pc/L"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        response = session.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        channels = [
            {
                "channelName": item["fsNAME"],
                "channelId": item["fs4GTV_ID"],
                "logo": item["fsLOGO_MOBILE"],
                "description": item.get("fsDESCRIPTION", "")
            }
            for item in data
        ]
        return channels
    
    except Exception as e:
        logger.error(f"獲取頻道列表失敗: {e}")
        return []

def get_4gtv_programs_scraper(channel_id, channel_name, scraper):
    """獲取節目表(繞過Cloudflare防護)"""
    url = f"https://www.4gtv.tv/ProgList/{channel_id}.txt"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Referer": "https://www.4gtv.tv/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://www.4gtv.tv",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin"
    }
    
    try:
        response = scraper.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # 檢查是否是有效的JSON
        if not response.text.strip().startswith(('[', '{')):
            raise ValueError("返回內容不是有效的JSON")
        
        data = response.json()
        
        programs = []
        tz = pytz.timezone('Asia/Taipei')
        
        for item in data:
            start_time = tz.localize(datetime.strptime(
                f"{item['sdate']} {item['stime']}", 
                "%Y-%m-%d %H:%M:%S"
            ))
            end_time = tz.localize(datetime.strptime(
                f"{item['edate']} {item['etime']}", 
                "%Y-%m-%d %H:%M:%S"
            ))
            
            programs.append({
                "channelId": channel_id,
                "channelName": channel_name,
                "programName": item["title"],
                "description": item.get("content", ""),
                "start": start_time,
                "end": end_time
            })
        
        logger.success(f"成功獲取 {channel_name} 節目表 ({len(programs)} 個節目)")
        return programs
    
    except Exception as e:
        status_code = response.status_code if 'response' in locals() else 'N/A'
        logger.error(f"獲取 {channel_name} 節目表失敗. URL: {url} 狀態碼: {status_code} 錯誤: {e}")
        return None

def get_4gtv_programs_selenium(channel_id, channel_name, browser=None):
    """獲取節目表"""
    url = f"https://www.4gtv.tv/ProgList/{channel_id}.txt"
    
    # 如果未提供瀏覽器實例，則建立一個
    create_new_browser = browser is None
    if create_new_browser:
        browser = create_browser()
    
    try:
        logger.info(f"正在訪問: {url}")
        browser.get(url)
        
        # 等待頁面加載
        time.sleep(2.5)
        
        # 獲取頁面內容
        content = browser.page_source
        
        # 嘗試從pre標簽獲取JSON數據
        if '<pre' in content:
            pre_element = browser.find_element('tag name', 'pre')
            json_text = pre_element.text
        else:
            # 直接獲取body內容
            body_element = browser.find_element('tag name', 'body')
            json_text = body_element.text
        
        # 檢查是否是有效的JSON
        if not json_text.strip().startswith(('[', '{')):
            raise ValueError("返回內容不是有效的JSON")
        
        # 解析JSON
        data = json.loads(json_text)
        
        programs = []
        tz = pytz.timezone('Asia/Taipei')
        
        for item in data:
            start_time = tz.localize(datetime.strptime(
                f"{item['sdate']} {item['stime']}", 
                "%Y-%m-%d %H:%M:%S"
            ))
            end_time = tz.localize(datetime.strptime(
                f"{item['edate']} {item['etime']}", 
                "%Y-%m-%d %H:%M:%S"
            ))
            
            programs.append({
                "channelId": channel_id,
                "channelName": channel_name,
                "programName": item["title"],
                "description": item.get("content", ""),
                "start": start_time,
                "end": end_time
            })
        
        logger.success(f"成功獲取 {channel_name} 節目表 ({len(programs)} 個節目)")
        return programs
    
    except Exception as e:
        logger.error(f"獲取 {channel_name} 節目表失敗: {e}")
        return None
    
    finally:
        # 如果是新建立的瀏覽器，則關閉它
        if create_new_browser and browser:
            try:
                browser.quit()
            except:
                pass

def generate_xml(channels, programs, filename):
    tv = ET.Element("tv", attrib={
        "info-name": "四季線上電子節目表單",
        "info-url": "https://www.4gtv.tv"
    })
    
    # 按頻道名稱分組節目
    programs_by_channel = {}
    for program in programs:
        channel_name = program["channelName"]
        if channel_name not in programs_by_channel:
            programs_by_channel[channel_name] = []
        programs_by_channel[channel_name].append(program)
    
    # 按頻道排序節目
    for channel_name in programs_by_channel:
        # 確保節目按開始時間排序
        programs_by_channel[channel_name].sort(key=lambda x: x["start"])
    
    # 添加頻道和節目信息（頻道和其節目連續排列）
    for channel in channels:
        channel_name = channel["channelName"]
        
        channel_elem = ET.SubElement(tv, "channel", id=channel_name)
        display_name = ET.SubElement(channel_elem, "display-name")
        display_name.text = channel_name
        
        if channel.get("logo"):
            icon = ET.SubElement(channel_elem, "icon")
            icon.set("src", channel["logo"])
        
        # 添加該頻道的節目
        if channel_name in programs_by_channel:
            for program in programs_by_channel[channel_name]:
                try:
                    # 格式化時區信息 (+0800)
                    start_str = program["start"].strftime("%Y%m%d%H%M%S %z").replace(" ", "")
                    end_str = program["end"].strftime("%Y%m%d%H%M%S %z").replace(" ", "")
                    
                    programme = ET.SubElement(tv, "programme")
                    programme.set("channel", channel_name)
                    programme.set("start", start_str)
                    programme.set("stop", end_str)
                    
                    title = ET.SubElement(programme, "title")
                    title.text = program["programName"]
                    title.set("lang", "zh")
                    
                    if program.get("description"):
                        desc = ET.SubElement(programme, "desc")
                        desc.text = program["description"]
                        desc.set("lang", "zh")
                except Exception as e:
                    logger.error(f"生成節目 {program.get('programName', '未知節目')} XML 失敗: {e}")
    
    # 生成XML檔案 - 確保使用UTF-8編碼
    try:
        # 建立XML
        tree = ET.ElementTree(tv)
        
        # 添加XML聲明並設置編碼
        xml_str = ET.tostring(tv, encoding="utf-8", xml_declaration=True)
        
        # 手動寫入檔案以確保UTF-8編碼
        with open(filename, "wb") as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8" ?>\n')
            f.write(b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n')
            f.write(xml_str)
            
        logger.info(f"電子節目表單已生成: {filename}")
    except Exception as e:
        logger.error(f"寫入XML檔案失敗: {e}")
        raise
    
    # 生成XML檔案
    tree = ET.ElementTree(tv)
    tree.write(filename, encoding="utf-8", xml_declaration=True)
    logger.info(f"電子節目表單已生成: {filename}")

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    log_file = os.path.join(OUTPUT_DIR, 'epg_generator.log')
    logger.add(
        log_file,
        rotation="1 day", 
        retention="7 days", 
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
    )
    
    try:
        logger.info("="*50)
        logger.info("開始生成四季線上電子節目表單")
        logger.info(f"開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"輸出目錄: {OUTPUT_DIR}")
        
        channels, programs = get_4gtv_epg()
        logger.info(f"共獲取 {len(channels)} 個頻道, {len(programs)} 個節目")
        
        # 設置XML輸出路徑
        xml_file = os.path.join(OUTPUT_DIR, '4g.xml')
        generate_xml(channels, programs, xml_file)
        logger.success(f"EPG生成完成: {xml_file}")
    except Exception as e:
        logger.critical(f"EPG生成失敗: {str(e)}")
        logger.exception(e)
        exit(1)
