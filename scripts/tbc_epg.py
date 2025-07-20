import asyncio
import datetime
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from xml.dom import minidom

import pytz
import requests
from bs4 import BeautifulSoup as bs

from loguru import logger

# 全局時區設置
TAIPEI_TZ = pytz.timezone('Asia/Taipei')
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

async def get_tbc_epg():
    """獲取TBC所有頻道的EPG數據"""
    logger.info("正在獲取TBC電子節目表")
    channels = await get_channels_tbc()
    programs = []
    
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
    url = f"https://www.tbc.net.tw/EPG/Channel?channelId={channel_id}"
    programs = []
    
    try:
        response = await asyncio.to_thread(requests.get, url, headers=headers, timeout=30)
        response.encoding = "utf-8"
        soup = bs(response.text, "html.parser")
        
        # 找到對應日期的節目清單
        date_header = soup.find("h2", class_="program_title", string=date_str)
        if not date_header:
            return programs
            
        ul = date_header.find_next_sibling("ul", class_="list_program2")
        if not ul:
            return programs
            
        for li in ul.find_all("li"):
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
            
            title = li.find("p").text.strip()
            desc = li.get("desc", "").strip()
            
            programs.append({
                "channelName": li.get("channelname", ""),
                "programName": title,
                "description": desc,
                "start": start_time,
                "end": end_time
            })
            
    except Exception as e:
        logger.error(f"解析頻道 {channel_id} 節目表失敗: {str(e)}")
    
    return programs

async def get_channels_tbc():
    """獲取TBC所有頻道清單"""
    channels = []
    cookies = {"ASP.NET_SessionId": "pug4ifrlphzwd102ih4t2d2c"}  # 使用固定session ID
    
    try:
        url = "https://www.tbc.net.tw/EPG"
        response = await asyncio.to_thread(requests.get, url, headers=headers, cookies=cookies, timeout=10)
        response.encoding = "utf-8"
        soup = bs(response.text, "html.parser")
        
        for li in soup.select("ul.list_tv > li"):
            name = li.get("title", "").strip()
            if not name:
                continue
                
            channel_id = li.get("id", "")
            img = li.find("img")["src"] if li.find("img") else ""
            
            channels.append({
                "name": name,  # 修改為"name"以保持一致性
                "id": [channel_id],
                "url": li.find("a")["href"] if li.find("a") else "",
                "source": "tbc",
                "logo": img,
                "desc": "",
                "sort": "海外",
            })
            
    except Exception as e:
        logger.error(f"獲取TBC頻道清單失敗: {str(e)}")
    
    return channels

def generate_xmltv(channels, programs, filename="tbc.xml"):
    """生成XMLTV格式的EPG文件"""
    logger.info(f"開始生成XMLTV文件: {filename}")
    
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
    
    # 寫入文件
    with open(filename, "w", encoding="utf-8") as f:
        f.write(reparsed.toprettyxml(indent="  "))
    
    logger.success(f"已生成XMLTV文件: {filename}, 包含{len(channels)}個頻道, {len(programs)}個節目")

# 主函數
async def main():
    # 確保輸出目錄存在
    output_dir = "epg_output"
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "tbc.xml")
    
    # 獲取EPG數據並生成XML
    channels, programs = await get_tbc_epg()
    generate_xmltv(channels, programs, output_file)

if __name__ == '__main__':
    asyncio.run(main())
