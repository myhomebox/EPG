import asyncio
import os
import re
import random
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pytz
import requests
from bs4 import BeautifulSoup as bs

TAIPEI_TZ = pytz.timezone('Asia/Taipei')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def log(message, level="info"):
    """日誌功能"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}] {message}")

def clean_invalid_xml_chars(text):
    """清除XML中的非法字符"""
    if not text:
        return ""
    return re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]', '', text)

def time_stamp_to_timezone_str(dt, target_tz):
    """轉換時間格式為XMLTV要求的格式"""
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(target_tz).strftime('%Y%m%d%H%M%S %z')

def ensure_directory(file_path):
    """確保目錄存在"""
    directory = os.path.dirname(file_path)
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        log(f"建立目錄: {directory}")

def get_epg_file_path():
    """獲取EPG檔案路徑"""
    return os.path.join("output", "tbc_epg.xml")

async def get_epg_data():
    """主函數：獲取並生成EPG數據"""
    log("開始獲取TBC電子節目表")
    
    # 1. 獲取頻道列表
    channels = await get_channels_tbc()
    if not channels:
        log("無法獲取頻道列表，中止節目表獲取", "error")
        return False
    
    # 2. 獲取所有節目數據
    programs = []
    for day_offset in range(1):  # 只獲取今天的數據
        dt = datetime.now(TAIPEI_TZ) + timedelta(days=day_offset)
        date_str = dt.strftime('%Y/%m/%d')
        
        for channel in channels:
            channel_id = channel["id"][0]
            channel_name = channel["name"]
            
            # 添加隨機延遲防止被封
            delay = random.uniform(1, 3)
            log(f"等待 {delay:.2f} 秒後獲取頻道 {channel_name}")
            await asyncio.sleep(delay)
            
            try:
                channel_programs = await get_epgs_tbc(channel_id, date_str, channel_name)
                programs.extend(channel_programs)
                log(f"頻道 {channel_name} 成功獲取 {len(channel_programs)} 條節目")
            except Exception as e:
                log(f"獲取頻道 {channel_name} 節目表失敗: {str(e)}", "error")
    
    log(f"所有頻道共成功獲取 {len(programs)} 條節目信息")
    
    # 3. 生成EPG XML
    epg_xml = await generate_epg_xml(channels, programs)
    
    # 4. 儲存到檔案
    file_path = get_epg_file_path()
    ensure_directory(file_path)
    with open(file_path, "wb") as file:
        file.write(epg_xml)
    log(f"EPG檔案已儲存到: {file_path}")
    return True

async def generate_epg_xml(channels, programs):
    """生成EPG XML檔案"""
    tv = ET.Element("tv", {"info-name": "TBC電子節目表", "info-url": "https://www.tbc.net.tw/EPG"})
    
    # 建立頻道元素
    for channel_info in channels:
        channel_name = channel_info["channelName"]
        channel_elem = ET.SubElement(tv, "channel", id=channel_name)
        ET.SubElement(channel_elem, "display-name", lang="zh").text = channel_name
    
    # 建立節目元素
    for program in programs:
        start_time = time_stamp_to_timezone_str(program["start"], TAIPEI_TZ)
        end_time = time_stamp_to_timezone_str(program["end"], TAIPEI_TZ)
        
        programme = ET.SubElement(
            tv, "programme", 
            channel=program["channelName"], 
            start=start_time, 
            stop=end_time
        )
        ET.SubElement(programme, "title", lang="zh").text = program["programName"]
        
        if program["description"]:
            desc_text = clean_invalid_xml_chars(program["description"])
            desc_text = html.escape(desc_text)
            ET.SubElement(programme, "desc", lang="zh").text = desc_text

    return ET.tostring(tv, encoding='utf-8')

async def get_epgs_tbc(channel_id, date_str, channel_name):
    """獲取指定頻道和日期的節目表"""
    url = f"https://www.tbc.net.tw/EPG/Channel?channelId={channel_id}"
    programs = []
    
    try:
        # 建立新會話
        with requests.Session() as session:
            # 添加隨機延遲
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            # 使用線程池執行同步請求
            response = await asyncio.to_thread(
                session.get, url, 
                headers=HEADERS, 
                timeout=30
            )
            
        if response.status_code != 200:
            log(f"頻道 {channel_id} 請求失敗: HTTP {response.status_code}", "error")
            return programs
            
        response.encoding = "utf-8"
        soup = bs(response.text, "html.parser")
        
        # 找到所有節目清單
        uls = soup.find_all("ul", class_="list_program2")
        if not uls:
            log(f"頻道 {channel_name} 無節目表", "warning")
            return programs
        
        # 遍歷所有節目清單，查找匹配日期的
        target_ul = None
        for ul in uls:
            # 獲取清單中第一個節目的日期
            first_li = ul.find("li")
            if not first_li:
                continue
                
            program_date = first_li.get("date", "").strip()
            if program_date == date_str:
                target_ul = ul
                break
                
        if not target_ul:
            log(f"頻道 {channel_name} 無 {date_str} 的節目表", "warning")
            return programs
            
        # 從ul標簽獲取實際頻道名稱
        actual_channel_name = target_ul.get("channelname", channel_name)
        
        for li in target_ul.find_all("li"):
            # 獲取節目的日期和時間範圍
            program_date = li.get("date", "").strip() or date_str
            time_range = li.get("time", "").strip()
            
            # 解析時間範圍
            time_match = re.search(r"(\d+:\d+)~(\d+:\d+)", time_range)
            if not time_match:
                continue
                
            start_str, end_str = time_match.groups()
            
            try:
                # 建立日期時間對象
                start_time = datetime.strptime(f"{program_date} {start_str}", "%Y/%m/%d %H:%M")
                end_time = datetime.strptime(f"{program_date} {end_str}", "%Y/%m/%d %H:%M")
                
                # 處理跨天節目（結束時間在次日）
                if end_time <= start_time:
                    end_time += timedelta(days=1)
                
                # 添加時區信息
                start_time = TAIPEI_TZ.localize(start_time)
                end_time = TAIPEI_TZ.localize(end_time)
                
                # 獲取節目名稱
                title = li.get("title", "").strip()
                if not title:
                    # 備用方案：從p標簽獲取
                    p_tag = li.find("p")
                    if p_tag:
                        title = p_tag.get_text(strip=True)
                
                # 獲取節目描述
                desc = li.get("desc", "").strip()
                
                # 如果節目名稱有效，則添加到列表
                if title:
                    programs.append({
                        "channelName": actual_channel_name,
                        "programName": title,
                        "description": desc,
                        "start": start_time,
                        "end": end_time
                    })
                else:
                    log(f"在頻道 {actual_channel_name} 發現無名稱節目: {time_range}", "warning")
                    
            except ValueError as e:
                log(f"時間格式解析失敗: {program_date} {time_range} - {str(e)}", "warning")
                continue
            except Exception as e:
                log(f"處理節目條目時發生錯誤: {str(e)}", "error")
                continue
                
    except Exception as e:
        log(f"解析頻道 {channel_id} 節目表失敗: {str(e)}", "error")
    
    return programs

async def get_channels_tbc():
    """獲取TBC所有頻道清單"""
    channels = []
    
    try:
        # 使用會話管理獲取動態Session ID
        with requests.Session() as session:
            # 首次訪問獲取Session Cookie
            init_url = "https://www.tbc.net.tw/EPG"
            init_response = await asyncio.to_thread(
                session.get, init_url, 
                headers=HEADERS, 
                timeout=10
            )
            
            if init_response.status_code != 200:
                log(f"頻道列表請求失敗: HTTP {init_response.status_code}", "error")
                return []
            
            # 添加請求間延遲
            delay = random.uniform(0.5, 1.5)
            log(f"頻道列表請求間延遲 {delay:.2f} 秒")
            await asyncio.sleep(delay)
            
            # 使用同會話獲取頻道列表
            response = await asyncio.to_thread(
                session.get, init_url, 
                headers=HEADERS, 
                timeout=10
            )
            
        response.encoding = "utf-8"
        soup = bs(response.text, "html.parser")
        
        channel_list = soup.select("ul.list_tv > li")
        if not channel_list:
            log("頻道列表解析失敗，未找到列表元素", "error")
            return []
            
        for li in channel_list:
            name = li.get("title", "").strip()
            if not name:
                continue
                
            channel_id = li.get("id", "")
            img = li.find("img")
            img_src = img["src"] if img and "src" in img.attrs else ""
            
            channels.append({
                "name": name,
                "channelName": name,
                "id": [channel_id],
                "url": li.find("a")["href"] if li.find("a") else "",
                "source": "tbc",
                "logo": img_src,
                "desc": "",
                "sort": "海外",
            })
            
        log(f"成功獲取 {len(channels)} 個頻道")
            
    except Exception as e:
        log(f"獲取TBC頻道清單失敗: {str(e)}", "error")
    
    return channels

def main():
    log("TBC EPG抓取工具啟動")
    asyncio.run(get_epg_data())
    log("TBC EPG抓取完成")

if __name__ == "__main__":
    main()
