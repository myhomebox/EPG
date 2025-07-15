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

def create_session():
    """创建带有重试机制的会话"""
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
    
    for channel in channels:
        channel_id = channel['channelId']
        channel_name = channel['channelName']
        
        # 添加随机延迟减少请求频率
        delay = random.uniform(0.5, 2.0)
        logger.debug(f"等待 {delay:.2f} 秒後獲取 {channel_name} 節目表")
        time.sleep(delay)
        
        channel_programs = get_4gtv_programs(channel_id, channel_name)
        if channel_programs:
            programs.extend(channel_programs)
    
    return channels, programs

def get_4gtv_channels():
    # 優先檢查本地文件是否存在
    local_file = "./output/fourgtv.json"
    if os.path.exists(local_file):
        try:
            logger.info("從本地文件讀取頻道列表")
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
    
    try:
        session = create_session()
        response = session.get(url, headers=headers, timeout=10)
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

def get_4gtv_programs(channel_id, channel_name):
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
    
    session = create_session()
    try:
        response = session.get(url, headers=headers, timeout=10)
        response.raise_for_status()
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
        return []

def generate_xml(channels, programs, filename="./output/4g.xml"):
    tv = ET.Element("tv", attrib={
        "generator-info-name": "四季線上電子節目表單",
        "generator-info-url": "https://www.4gtv.tv"
    })
    
    # 添加頻道信息
    for channel in channels:
        channel_elem = ET.SubElement(tv, "channel", id=channel["channelId"])
        ET.SubElement(channel_elem, "display-name").text = channel["channelName"]
        if channel.get("logo"):
            ET.SubElement(channel_elem, "icon", src=channel["logo"])
    
    # 添加節目信息
    for program in programs:
        try:
            # 格式化时区信息 (+0800)
            start_str = program["start"].strftime("%Y%m%d%H%M%S %z")
            end_str = program["end"].strftime("%Y%m%d%H%M%S %z")
            
            programme = ET.SubElement(tv, "programme", 
                start=start_str,
                stop=end_str,
                channel=program["channelId"]
            )
            ET.SubElement(programme, "title").text = program["programName"]
            if program.get("description"):
                ET.SubElement(programme, "desc").text = program["description"]
        except Exception as e:
            logger.error(f"生成節目 {program['programName']} XML 失敗: {e}")
    
    # 生成XML文件
    tree = ET.ElementTree(tv)
    tree.write(filename, encoding="utf-8", xml_declaration=True)
    logger.info(f"EPG文件已生成: {filename}")

if __name__ == "__main__":
    # 確保輸出目錄存在
    os.makedirs("output", exist_ok=True)
    
    logger.add("./output/epg_generator.log", rotation="1 day", retention="7 days", encoding="utf-8")
    try:
        logger.info("="*50)
        logger.info("開始生成四季線上EPG")
        logger.info(f"開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        channels, programs = get_4gtv_epg()
        logger.info(f"共獲取 {len(channels)} 個頻道, {len(programs)} 個節目")
        
        generate_xml(channels, programs, "./output/4g.xml")
        logger.success("EPG生成完成")
    except Exception as e:
        logger.critical(f"EPG生成失敗: {e}")
        raise
