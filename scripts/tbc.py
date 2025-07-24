import asyncio
import datetime
import re
import random
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime, timedelta
import time

import pytz
import requests
from bs4 import BeautifulSoup as bs
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 全局時區設置
TAIPEI_TZ = pytz.timezone('Asia/Taipei')
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    'Connection': 'keep-alive',
    'Referer': 'https://www.tbc.net.tw/EPG'
}

def create_session_with_retry():
    """建立帶有重試機制的會話"""
    session = requests.Session()
    retry_strategy = Retry(
        total=5,  # 最大重試次數
        backoff_factor=1,  # 重試等待時間因子
        status_forcelist=[429, 500, 502, 503, 504],  # 需要重試的HTTP狀態碼
        allowed_methods=["GET", "POST"]  # 需要重試的HTTP方法
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

async def get_tbc_epg():
    """獲取台灣大寬頻所有頻道的電視節目表 (跳過頻道ID 300-329)"""
    print("正在獲取 台灣大寬頻 電視節目表")
    channels = await get_channels_tbc()
    programs = []
    
    if not channels:
        print("❌錯誤:無法獲取頻道清單，中止電視節目表獲取")
        return [], []
    
    # 需要跳過的頻道ID列表（包括300-329和其他指定ID）
    skip_ids = [str(i) for i in range(300, 330)]  # 300-329
    
    # 獲取今天和未來6天的節目表
    total_days = 6
    print(f"🚨開始獲取 {total_days} 天的電視節目表...")
    
    for day_offset in range(total_days):
        dt = datetime.now(TAIPEI_TZ) + timedelta(days=day_offset)
        date_str = dt.strftime('%Y/%m/%d')
        
        # 一次性獲取所有頻道的節目表
        tasks = []
        valid_channels = []  # 用於記錄這一天有效的頻道
        
        # 過濾需要跳過的頻道
        for idx, channel in enumerate(channels):
            channel_id = channel["id"][0]
            
            # 檢查頻道ID是否需要跳過
            if channel_id in skip_ids:
                continue
            
            valid_channels.append(channel['name'])
        
        # 如果沒有有效頻道則跳過
        if not valid_channels:
            print(f"⚠️警告:日期 {date_str} 沒有可獲取的頻道")
            continue
        
        # 顯示目前工作狀態
        print(f"📅 正在獲取 {date_str} 的電視節目表，頻道數量: {len(valid_channels)}")
        if len(valid_channels) > 5:
            print(f"  包括: {', '.join(valid_channels[:5])} ... 等 {len(valid_channels)} 個頻道")
        else:
            print(f"  包括: {', '.join(valid_channels)}")
        
        # 為每個有效頻道建立任務
        for idx, channel in enumerate(channels):
            channel_id = channel["id"][0]
            
            if channel_id in skip_ids:
                continue
            
            # 顯示頻道獲取進度
            print(f"  🚨正在獲取頻道: {channel['name']} (進度: {idx+1}/{len(valid_channels)})")
            tasks.append(
                get_epgs_tbc(channel_id, date_str, channel['name'], channel['id'][0])
            )
        
        # 使用asyncio.gather一次性執行所有任務
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 處理結果
        for result in results:
            if isinstance(result, Exception):
                print(f"❌錯誤:獲取電視節目表失敗: {str(result)}")
            elif result:  # 確保result不是None
                programs.extend(result)
    
    # 統計每個頻道成功獲取的節目數量
    channel_counts = {}
    for program in programs:
        channel_counts[program["channelName"]] = channel_counts.get(program["channelName"], 0) + 1
    
    for channel, count in channel_counts.items():
        print(f"✅頻道 {channel} 成功獲取 {count} 個電視節目表")
    
    print(f"✅所有頻道共成功獲取 {len(programs)} 個電視節目表")
    return channels, programs

async def get_epgs_tbc(channel_id, date_str, channel_name, channel_real_id):
    """獲取指定頻道和日期的節目表"""
    url = f"https://www.tbc.net.tw/EPG/Channel?channelId={channel_id}"
    programs = []
    
    try:
        # 建立新會話（帶重試機制）
        session = create_session_with_retry()
        
        # 一次性獲取所有節目資料
        response = await asyncio.to_thread(
            session.get, url, 
            headers=headers, 
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"❌錯誤:頻道 {channel_id} 請求失敗: HTTP {response.status_code}")
            return programs
            
        response.encoding = "utf-8"
        soup = bs(response.text, "html.parser")
        
        # 找到所有節目清單
        uls = soup.find_all("ul", class_="list_program2")
        if not uls:
            print(f"❌錯誤:頻道 {channel_name} 無電視節目表")
            return programs
        
        # 定義需要特殊處理的頻道ID範圍 (404-420)
        special_channel_ids = [str(i) for i in range(404, 421)]
        
        for ul in uls:
            for li in ul.find_all("li"):
                # 獲取節目的日期
                program_date = li.get("date", "").strip()
                if not program_date:
                    continue
                
                # 只處理指定日期的節目
                if program_date != date_str:
                    continue
                
                # 獲取時間範圍
                time_range = li.get("time", "").strip()
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
                    # 對於特殊頻道ID (404-420) 直接使用data-name屬性
                    if channel_id in special_channel_ids:
                        title = li.get("data-name", "").strip()
                    else:
                        title = li.get("title", "").strip()
                    
                    # 如果節目名稱仍為空，嘗試從p標籤獲取
                    if not title:
                        p_tag = li.find("p")
                        if p_tag:
                            title = p_tag.get_text(strip=True)
                    
                    # 獲取節目描述
                    desc = li.get("desc", "").strip()
                    
                    # 如果節目名稱有效，則添加到列表
                    if title:
                        programs.append({
                            "channelId": channel_real_id,  # 使用頻道真實ID
                            "channelName": channel_name,
                            "programName": title,
                            "description": desc,
                            "start": start_time,
                            "end": end_time
                        })
                    else:
                        print(f"❌錯誤:在頻道 {channel_name} 發現無名稱節目: {time_range}")
                        
                except ValueError as e:
                    print(f"❌錯誤:時間格式解析失敗: {program_date} {time_range} - {str(e)}")
                except Exception as e:
                    print(f"❌錯誤:處理電視節目表時發生錯誤: {str(e)}")
                
    except Exception as e:
        print(f"❌錯誤:解析頻道 {channel_id} 電視節目表失敗: {str(e)}")
    
    return programs

async def get_channels_tbc():
    """獲取TBC所有頻道清單"""
    channels = []
    
    try:
        # 建立帶重試機制的會話
        session = create_session_with_retry()
        
        # 首次訪問獲取Session Cookie
        init_url = "https://www.tbc.net.tw/EPG"
        
        # 使用異步線程執行請求
        response = await asyncio.to_thread(
            session.get, init_url, 
            headers=headers, 
            timeout=15
        )
        
        if response.status_code != 200:
            print(f"❌錯誤:頻道清單請求失敗: HTTP {response.status_code}")
            return []
        
        response.encoding = "utf-8"
        soup = bs(response.text, "html.parser")
        
        channel_list = soup.select("ul.list_tv > li")
        if not channel_list:
            print("❌錯誤:頻道清單解析失敗，未找到列表元素")
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
            
        print(f"✅成功獲取 {len(channels)} 個頻道")
            
    except Exception as e:
        print(f"❌獲取 台灣大寬頻 頻道清單失敗: {str(e)}")
    
    return channels

def generate_xmltv(channels, programs, output_path):
    """生成XMLTV格式的EPG數據"""
    # 建立XML根元素
    root = ET.Element("tv")
    root.set("generator-info-name", "tbc_epg")
    root.set("source-info-name", "tbc.net.tw")
    
    # 頻道映射表：name -> id
    channel_id_map = {channel['name']: channel['id'][0] for channel in channels}
    
    # 按頻道分組節目
    channel_programs = {}
    for program in programs:
        channel_id = program["channelId"]
        if channel_id not in channel_programs:
            channel_programs[channel_id] = []
        channel_programs[channel_id].append(program)
    
    # 按頻道順序生成XML
    for channel in channels:
        channel_id = channel['id'][0]
        channel_name = channel['name']
        
        # 添加頻道元素
        channel_elem = ET.SubElement(root, "channel", id=channel_id)
        
        # 添加display-name
        display_name = ET.SubElement(channel_elem, "display-name")
        display_name.set("lang", "zh")
        display_name.text = channel_name
        
        # 添加logo
        if channel.get('logo'):
            icon_elem = ET.SubElement(channel_elem, "icon")
            icon_elem.set("src", channel['logo'])
        
        # 添加該頻道的節目
        if channel_id in channel_programs:
            for program in channel_programs[channel_id]:
                # 建立programme元素
                programme = ET.SubElement(root, "programme")
                programme.set("channel", channel_id)
                programme.set("start", program['start'].strftime("%Y%m%d%H%M%S %z"))
                programme.set("stop", program['end'].strftime("%Y%m%d%H%M%S %z"))
                
                # 添加標題
                title = ET.SubElement(programme, "title")
                title.set("lang", "zh")
                title.text = program['programName'] or "未知節目"
                
                # 添加描述
                desc = ET.SubElement(programme, "desc")
                desc.set("lang", "zh")
                desc.text = program['description'] or ""
    
    # 美化XML輸出
    rough_string = ET.tostring(root, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ", encoding="utf-8")
    
    # 寫入檔案
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(pretty_xml)
    
    print(f"XMLTV檔案已生成: {output_path}")

async def main():
    """主函數，用於自動化執行"""
    # 獲取當前腳本所在目錄
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 設置輸出路徑：項目根目錄下的output目錄
    output_dir = os.path.join(script_dir, '../output')
    output_path = os.path.join(output_dir, 'tbc.xml')
    
    print(f"🎬 開始執行台灣大寬頻EPG抓取，輸出位置: {output_path}")
    
    # 添加隨機延遲，避免請求過於頻繁
    delay = random.uniform(0.5, 2.0)
    print(f"⏳ 隨機延遲 {delay:.2f} 秒以降低服務器壓力...")
    await asyncio.sleep(delay)
    
    # 獲取EPG數據
    try:
        channels, programs = await get_tbc_epg()
    except Exception as e:
        print(f"❌ EPG抓取失敗: {str(e)}")
        # 嘗試建立空XML檔案
        if not os.path.exists(output_path):
            empty_channels = []
            empty_programs = []
            generate_xmltv(empty_channels, empty_programs, output_path)
        return
    
    if channels and programs:
        # 生成XMLTV檔案
        generate_xmltv(channels, programs, output_path)
        print("✅ 電視節目表抓取完成並已生成XML檔案")
    else:
        print("⚠️ 未獲取到有效數據，生成空XML檔案")
        generate_xmltv([], [], output_path)

if __name__ == '__main__':
    asyncio.run(main())
