import json
import os
import time
import pytz
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import requests
from loguru import logger
import urllib3
import ssl

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 自定義 SSL 上下文
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# 配置日志
logger.add("epg_generator.log", rotation="1 day", retention="7 days", level="INFO")

def fetch_channels_with_selenium():
    """獲取頻道數據"""
    logger.info("正在獲取頻道數據")
    driver = None
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
        logger.info(f"正在訪問: {api_url}")
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
                logger.error(f"JSON 解析錯誤，內容: {content[:200]}")
                return []
        else:
            logger.warning(f"獲取到非 JSON 內容: {content[:200]}")
            # 嘗試從 pre 標簽獲取數據
            try:
                pre_element = driver.find_element("tag name", "pre")
                content = pre_element.text
                data = json.loads(content)
            except:
                logger.error("無法解析內容為 JSON")
                return []
        
        # 檢查數據結構
        if "Data" not in data or not isinstance(data["Data"], list):
            logger.error(f"API 返回無效數據: {data}")
            return []
        
        # 過濾不需要的頻道
        blocked_channels = ["鳳梨直擊台", "香蕉直擊台", "芭樂直擊台"]
        channels = []
        for channel in data["Data"]:
            channel_name = channel.get("fsNAME", "")
            if any(blocked in channel_name for blocked in blocked_channels):
                logger.info(f"已跳過頻道: {channel_name}")
                continue
                
            channels.append({
                "channelName": channel_name,
                "channelId": channel.get("fs4GTV_ID"),
                "logo": channel.get("fsLOGO_MOBILE"),
                "description": channel.get("fsDESCRIPTION", "")
            })
        
        logger.info(f"成功獲取 {len(channels)} 個頻道")
        return channels
    
    except Exception as e:
        logger.error(f"獲取頻道數據失敗: {str(e)}")
        return []
    finally:
        try:
            if driver:
                driver.quit()
        except:
            pass

def get_programs_for_channel(channel_id, channel_name):
    """獲取單個頻道的節目表"""
    logger.info(f"正在獲取 {channel_name} 節目表")
    url = f"https://www.4gtv.tv/ProgList/{channel_id}.txt"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Referer": f"https://www.4gtv.tv/channel.html?channel={channel_id}",
        "Origin": "https://www.4gtv.tv"
    }
    
    try:
        # 使用自定義 SSL 上下文
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        response.encoding = "utf-8"
        
        # 檢查響應狀態
        if response.status_code != 200:
            logger.warning(f"頻道 {channel_name} 節目表獲取失敗: HTTP {response.status_code}")
            return []
        
        # 嘗試解析 JSON
        try:
            data = response.json()
        except json.JSONDecodeError:
            logger.error(f"頻道 {channel_name} 節目表解析失敗: 無效 JSON")
            return []
        
        programs = []
        tz = pytz.timezone('Asia/Taipei')
        
        for item in data:
            try:
                # 處理開始時間
                start_time = datetime.strptime(
                    f"{item['sdate']} {item['stime']}", 
                    "%Y-%m-%d %H:%M:%S"
                )
                start_time = tz.localize(start_time)
                
                # 處理結束時間
                end_time = datetime.strptime(
                    f"{item['edate']} {item['etime']}", 
                    "%Y-%m-%d %H:%M:%S"
                )
                end_time = tz.localize(end_time)
                
                programs.append({
                    "channelId": channel_id,
                    "channelName": channel_name,
                    "programName": item["title"],
                    "description": item.get("sub_title", "") or item.get("description", ""),
                    "start": start_time,
                    "end": end_time
                })
                
            except Exception as e:
                logger.warning(f"頻道 {channel_name} 節目解析錯誤: {str(e)}")
        
        logger.info(f"頻道 {channel_name} 獲取 {len(programs)} 個節目")
        return programs
    
    except Exception as e:
        logger.error(f"獲取 {channel_name} 節目表失敗: {str(e)}")
        return []

def generate_epg_xml(channels, all_programs):
    """生成 EPG XML 文件"""
    logger.info("開始生成 四季線上電子節目表單 XML 數據")
    
    # 建立 XML 結構
    tv = ET.Element("tv")
    tv.set("generator-info-name", "四季線上電子節目表單")
    tv.set("generator-info-url", "https://www.4gtv.tv")
    
    # 添加頻道信息
    for channel in channels:
        channel_elem = ET.SubElement(tv, "channel", id=channel["channelId"])
        ET.SubElement(channel_elem, "display-name").text = channel["channelName"]
        if channel["logo"]:
            ET.SubElement(channel_elem, "icon", src=channel["logo"])
    
    # 添加節目信息
    for programs in all_programs:
        for program in programs:
            # 建立節目元素
            program_elem = ET.SubElement(
                tv, 
                "programme",
                start=program["start"].strftime("%Y%m%d%H%M%S %z"),
                stop=program["end"].strftime("%Y%m%d%H%M%S %z"),
                channel=program["channelId"]
            )
            title_elem = ET.SubElement(program_elem, "title")
            title_elem.text = program["programName"]
            title_elem.set("lang", "zh")
            
            # 添加描述
            if program["description"]:
                desc_elem = ET.SubElement(program_elem, "desc")
                desc_elem.text = program["description"]
                desc_elem.set("lang", "zh")
    
    # 生成 XML 字符串
    xml_str = ET.tostring(tv, encoding="utf-8")
    
    # 添加 XML 聲明
    xml_with_declaration = b'<?xml version="1.0" encoding="utf-8"?>\n' + xml_str
    
    # 美化 XML 格式
    dom = minidom.parseString(xml_with_declaration)
    pretty_xml = dom.toprettyxml(indent="  ", encoding="utf-8")
    
    # 保存到文件
    os.makedirs("output", exist_ok=True)
    with open("output/4g.xml", "wb") as f:
        f.write(pretty_xml)
    
    logger.success("電子節目表單 生成完成，保存到 output/4g.xml")
    return True

def main():
    # 第一步：獲取頻道數據
    channels = fetch_channels_with_selenium()
    if not channels:
        logger.error("無法獲取頻道數據，電子節目表單 生成終止")
        return
    
    # 第二步：獲取所有頻道的節目表
    all_programs = []
    for channel in channels:
        programs = get_programs_for_channel(channel["channelId"], channel["channelName"])
        all_programs.append(programs)
    
    # 第三步：生成 電子節目表單
    generate_epg_xml(channels, all_programs)

if __name__ == "__main__":
    main()
