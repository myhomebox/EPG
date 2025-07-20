import asyncio
import datetime
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from xml.dom import minidom

import cloudscraper
import pytz
from bs4 import BeautifulSoup as bs
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from loguru import logger

# 全局時區設置
TAIPEI_TZ = pytz.timezone('Asia/Taipei')
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0'
]

def init_webdriver():
    """初始化 Selenium WebDriver"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={USER_AGENTS[0]}")
    
    # 嘗試使用系統已安裝的 Chrome
    try:
        return webdriver.Chrome(options=options)
    except:
        # 如果找不到 Chrome，嘗試使用 chromedriver-autoinstaller
        try:
            import chromedriver_autoinstaller
            chromedriver_autoinstaller.install()
            return webdriver.Chrome(options=options)
        except Exception as e:
            logger.error(f"初始化 WebDriver 失敗: {str(e)}")
            return None

async def get_tbc_epg():
    """獲取TBC所有頻道的EPG數據"""
    logger.info("正在獲取TBC電子節目表")
    channels = await get_channels_tbc()
    programs = []
    
    if not channels:
        logger.error("無法獲取頻道清單，無法繼續獲取節目表")
        return [], []
    
    # 獲取今天和未來6天的節目表
    for day_offset in range(7):
        dt = datetime.now(TAIPEI_TZ) + timedelta(days=day_offset)
        date_str = dt.strftime('%Y/%m/%d')
        
        for channel in channels:
            channel_id = channel["id"][0]
            try:
                channel_programs = await get_epgs_tbc(channel_id, date_str)
                # 添加頻道ID到每個節目
                for program in channel_programs:
                    program["channelId"] = channel_id
                programs.extend(channel_programs)
            except Exception as e:
                logger.error(f"獲取頻道 {channel['name']} 節目表失敗: {str(e)}")
    
    return channels, programs

async def get_epgs_tbc(channel_id, date_str):
    """獲取指定頻道和日期的節目表"""
    programs = []
    url = f"https://www.tbc.net.tw/EPG/Channel?channelId={channel_id}"
    
    try:
        # 嘗試使用 Cloudscraper
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, timeout=30)
        
        if response.status_code != 200:
            logger.warning(f"Cloudscraper 請求失敗: HTTP {response.status_code}")
            raise Exception(f"HTTP {response.status_code}")
        
        soup = bs(response.text, "html.parser")
        
        # 找到對應日期的節目清單
        date_header = soup.find("h2", class_="program_title", string=date_str)
        if not date_header:
            logger.debug(f"頻道 {channel_id} 沒有找到日期 {date_str} 的節目")
            return programs
            
        ul = date_header.find_next_sibling("ul", class_="list_program2")
        if not ul:
            logger.debug(f"頻道 {channel_id} 日期 {date_str} 沒有節目清單")
            return programs
            
        program_items = ul.find_all("li")
        logger.info(f"頻道 {channel_id} 日期 {date_str} 找到 {len(program_items)} 個節目")
        
        for li in program_items:
            time_delay = li.get("time", "").strip()
            time_match = re.search(r"(\d+:\d+)~(\d+:\d+)", time_delay)
            if not time_match:
                logger.debug(f"跳過無效時間格式: {time_delay}")
                continue
                
            start_str, end_str = time_match.groups()
            try:
                start_time = datetime.strptime(f"{date_str} {start_str}", "%Y/%m/%d %H:%M")
                end_time = datetime.strptime(f"{date_str} {end_str}", "%Y/%m/%d %H:%M")
                
                # 處理跨天節目
                if end_time < start_time:
                    end_time += timedelta(days=1)
                
                # 添加時區信息
                start_time = TAIPEI_TZ.localize(start_time)
                end_time = TAIPEI_TZ.localize(end_time)
                
                title = li.find("p").text.strip() if li.find("p") else "無標題"
                desc = li.get("desc", "").strip()
                
                programs.append({
                    "channelName": li.get("channelname", ""),
                    "programName": title,
                    "description": desc,
                    "start": start_time,
                    "end": end_time
                })
            except ValueError as e:
                logger.error(f"解析時間失敗: {date_str} {start_str}-{end_str}: {str(e)}")
            
    except Exception as e:
        logger.error(f"Cloudscraper 獲取節目表失敗，嘗試使用 Selenium: {str(e)}")
        # 如果 Cloudscraper 失敗，嘗試使用 Selenium
        try:
            driver = init_webdriver()
            if not driver:
                logger.error("無法初始化 WebDriver")
                return programs
                
            logger.info(f"使用 Selenium 獲取頻道 {channel_id} 節目表")
            driver.get(url)
            
            # 等待頁面加載
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CLASS_NAME, "list_program2"))
            )
            
            # 獲取頁面源碼
            html = driver.page_source
            driver.quit()
            
            soup = bs(html, "html.parser")
            
            # 找到對應日期的節目清單
            date_header = soup.find("h2", class_="program_title", string=date_str)
            if not date_header:
                logger.debug(f"[Selenium] 頻道 {channel_id} 沒有找到日期 {date_str} 的節目")
                return programs
                
            ul = date_header.find_next_sibling("ul", class_="list_program2")
            if not ul:
                logger.debug(f"[Selenium] 頻道 {channel_id} 日期 {date_str} 沒有節目清單")
                return programs
                
            program_items = ul.find_all("li")
            logger.info(f"[Selenium] 頻道 {channel_id} 日期 {date_str} 找到 {len(program_items)} 個節目")
            
            for li in program_items:
                time_delay = li.get("time", "").strip()
                time_match = re.search(r"(\d+:\d+)~(\d+:\d+)", time_delay)
                if not time_match:
                    continue
                    
                start_str, end_str = time_match.groups()
                start_time = datetime.strptime(f"{date_str} {start_str}", "%Y/%m/%d %H:%M")
                end_time = datetime.strptime(f"{date_str} {end_str}", "%Y/%m/%d %H:%M")
                
                # 處理跨天節目
                if end_time < start_time:
                    end_time += timedelta(days=1)
                
                # 添加時區信息
                start_time = TAIPEI_TZ.localize(start_time)
                end_time = TAIPEI_TZ.localize(end_time)
                
                title = li.find("p").text.strip() if li.find("p") else "無標題"
                desc = li.get("desc", "").strip()
                
                programs.append({
                    "channelName": li.get("channelname", ""),
                    "programName": title,
                    "description": desc,
                    "start": start_time,
                    "end": end_time
                })
            
        except Exception as selenium_e:
            logger.error(f"Selenium 獲取節目表失敗: {str(selenium_e)}")
    
    return programs

async def get_channels_tbc():
    """獲取TBC所有頻道清單"""
    channels = []
    url = "https://www.tbc.net.tw/EPG"
    
    try:
        # 嘗試使用 Cloudscraper
        logger.info("嘗試使用 Cloudscraper 獲取頻道清單")
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, timeout=30)
        
        if response.status_code == 200:
            soup = bs(response.text, "html.parser")
            channel_items = soup.select("ul.list_tv > li")
            logger.info(f"[Cloudscraper] 找到 {len(channel_items)} 個頻道")
            
            for li in channel_items:
                name = li.get("title", "").strip()
                if not name:
                    continue
                    
                channel_id = li.get("id", "")
                img = li.find("img")
                img_src = img["src"] if img and img.has_attr("src") else ""
                
                channels.append({
                    "name": name,
                    "id": [channel_id],
                    "url": li.find("a")["href"] if li.find("a") else "",
                    "source": "tbc",
                    "logo": img_src,
                    "desc": "",
                    "sort": "海外",
                })
            
            if channels:
                logger.success(f"使用 Cloudscraper 成功獲取 {len(channels)} 個頻道")
                return channels
    
    except Exception as e:
        logger.error(f"Cloudscraper 獲取頻道清單失敗: {str(e)}")
    
    # 如果 Cloudscraper 失敗，嘗試使用 Selenium
    try:
        logger.info("嘗試使用 Selenium 獲取頻道清單")
        driver = init_webdriver()
        if not driver:
            logger.error("無法初始化 WebDriver")
            return []
            
        driver.get(url)
        
        # 等待頁面加載
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ul.list_tv > li"))
        )
        
        # 獲取頁面源碼
        html = driver.page_source
        driver.quit()
        
        soup = bs(html, "html.parser")
        channel_items = soup.select("ul.list_tv > li")
        logger.info(f"[Selenium] 找到 {len(channel_items)} 個頻道")
        
        for li in channel_items:
            name = li.get("title", "").strip()
            if not name:
                continue
                
            channel_id = li.get("id", "")
            img = li.find("img")
            img_src = img["src"] if img and img.has_attr("src") else ""
            
            channels.append({
                "name": name,
                "id": [channel_id],
                "url": li.find("a")["href"] if li.find("a") else "",
                "source": "tbc",
                "logo": img_src,
                "desc": "",
                "sort": "海外",
            })
            
        logger.success(f"使用 Selenium 成功獲取 {len(channels)} 個頻道")
        return channels
        
    except Exception as e:
        logger.error(f"獲取TBC頻道清單失敗: {str(e)}")
        return []

def generate_xmltv(channels, programs, filename="tbc.xml"):
    """生成XMLTV格式的EPG檔案"""
    logger.info(f"開始生成XMLTV檔案: {filename}")
    
    # 創建根元素
    root = ET.Element("tv", attrib={
        "generator-info-name": "TBC_EPG_Scraper",
        "generator-info-url": "https://github.com/yourusername/tbc-epg"
    })
    
    # 添加頻道
    for channel in channels:
        channel_id = channel["id"][0]
        channel_elem = ET.SubElement(root, "channel", id=channel_id)
        
        ET.SubElement(channel_elem, "display-name").text = channel["name"]
        if channel.get("logo"):
            ET.SubElement(channel_elem, "icon", src=channel["logo"])
    
    # 添加節目
    for program in programs:
        # XMLTV時間格式: YYYYMMDDHHMMSS +0000
        start_time = program["start"].strftime("%Y%m%d%H%M%S %z").replace(" ", "")
        end_time = program["end"].strftime("%Y%m%d%H%M%S %z").replace(" ", "")
        
        programme = ET.SubElement(root, "programme", {
            "start": start_time,
            "stop": end_time,
            "channel": program["channelId"]
        })
        
        title = ET.SubElement(programme, "title")
        title.text = program["programName"]
        
        if program["description"]:
            desc = ET.SubElement(programme, "desc")
            desc.text = program["description"]
    
    # 生成XML字符串
    rough_string = ET.tostring(root, encoding="utf-8")
    reparsed = minidom.parseString(rough_string)
    
    # 寫入檔案
    with open(filename, "w", encoding="utf-8") as f:
        f.write(reparsed.toprettyxml(indent="  "))
    
    logger.success(f"已生成XMLTV檔案: {filename}, 包含{len(channels)}個頻道, {len(programs)}個節目")

# 主函數
async def main():
    # 確保輸出目錄存在
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "tbc.xml")
    
    # 獲取EPG數據並生成XML
    channels, programs = await get_tbc_epg()
    generate_xmltv(channels, programs, output_file)

if __name__ == '__main__':
    asyncio.run(main())
