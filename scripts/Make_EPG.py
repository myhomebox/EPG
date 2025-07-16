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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')

def create_cloudscraper():
    """建立Cloudscraper實例，繞過Cloudflare防護"""
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
    
    for channel in channels:
        channel_id = channel['channelId']
        channel_name = channel['channelName']
        
        # 添加隨機延遲減少請求頻率
        delay = random.uniform(1.0, 3.0)
        logger.debug(f"等待 {delay:.2f} 秒後獲取 {channel_name} 節目表")
        time.sleep(delay)
        
        try:
            channel_programs = get_4gtv_programs_scraper(channel_id, channel_name, scraper)
            if channel_programs:
                programs.extend(channel_programs)
                logger.success(f"成功獲取 {channel_name} 節目表 ({len(channel_programs)} 個節目)")
            else:
                logger.warning(f"無法獲取 {channel_name} 節目表")
        except Exception as e:
            logger.error(f"獲取 {channel_name} 節目表失敗: {e}")
    
    return channels, programs

def get_4gtv_channels():
    local_file = os.path.join(OUTPUT_DIR, 'fourgtv.json')
    if os.path.exists(local_file):
        try:
            logger.info(f"從本地文件讀取頻道列表: {local_file}")
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
            logger.error(f"讀取本地頻道文件失敗: {e}")

def get_4gtv_programs_scraper(channel_id, channel_name, scraper):
    """獲取節目表"""
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
    
    # 添加頻道和節目信息
    for channel in channels:
        channel_name = channel["channelName"]
        
        # 使用channelName作為id
        channel_elem = ET.SubElement(tv, "channel", id=channel_name)
        display_name = ET.SubElement(channel_elem, "display-name")
        display_name.text = channel_name
        
        if channel.get("logo"):
            icon = ET.SubElement(channel_elem, "icon", src=channel["logo"])
        
        # 添加該頻道的節目
        if channel_name in programs_by_channel:
            # 節目按開始時間排序
            sorted_programs = sorted(programs_by_channel[channel_name], key=lambda x: x["start"])
            
            for program in sorted_programs:
                try:
                    # 格式化時區信息 (+0800)
                    start_str = program["start"].strftime("%Y%m%d%H%M%S %z").replace(" ", "")
                    end_str = program["end"].strftime("%Y%m%d%H%M%S %z").replace(" ", "")
                    
                    programme = ET.SubElement(tv, "programme")
                    programme.set("channel", channel_name)
                    programme.set("start", start_str)
                    programme.set("stop", end_str)
                    
                    title = ET.SubElement(programme, "title", lang="zh")
                    title.text = program["programName"]
                    
                    if program.get("description"):
                        desc = ET.SubElement(programme, "desc", lang="zh")
                        desc.text = program["description"]
                except Exception as e:
                    logger.error(f"生成節目 {program.get('programName', '未知節目')} XML 失敗: {e}")
    
    # 生成XML文件
    tree = ET.ElementTree(tv)
    tree.write(filename, encoding="utf-8", decode="utf-8", xml_declaration=True)
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
