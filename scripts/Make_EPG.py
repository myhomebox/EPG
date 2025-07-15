import os
import json
import requests
import datetime
import pytz
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from loguru import logger

def get_4gtv_channels():
    # 優先檢查本地文件是否存在
    local_file = "../output/fourgtv.json"
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
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        response.encoding = "utf-8"
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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        response.encoding = "utf-8"
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
                "description": "",
                "start": start_time,
                "end": end_time
            })
        
        return programs
    
    except Exception as e:
        logger.error(f"獲取 {channel_name} 節目表失敗: {e}")
        return []

def generate_xml(channels, programs, filename="../output/4g.xml"):
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
        programme = ET.SubElement(tv, "programme", 
            start=program["start"].strftime("%Y%m%d%H%M%S %z"),
            stop=program["end"].strftime("%Y%m%d%H%M%S %z"),
            channel=program["channelId"]
        )
        ET.SubElement(programme, "title").text = program["programName"]
        if program.get("description"):
            ET.SubElement(programme, "desc").text = program["description"]
    
    # 生成XML文件
    tree = ET.ElementTree(tv)
    tree.write(filename, encoding="utf-8", xml_declaration=True)
    logger.info(f"EPG文件已生成: {filename}")

if __name__ == "__main__":
	os.makedirs("output", exist_ok=True)
	
    logger.add("./output/epg_generator.log", rotation="1 day", retention="7 days")
    try:
        channels, programs = get_4gtv_epg()
        generate_xml(channels, programs, "./output/4g.xml")
        logger.success("EPG生成完成")
    except Exception as e:
        logger.critical(f"EPG生成失敗: {e}")
