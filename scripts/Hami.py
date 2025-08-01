import asyncio
import os
import pytz
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from loguru import logger

UA = "HamiVideo/7.12.806(Android 11;GM1910) OKHTTP/3.12.2"
headers = {
    'X-ClientSupport-UserProfile': '1',
    'User-Agent': UA
}

# 設置超時時間（秒）
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 10

async def request_channel_list():
    params = {
        "appVersion": "7.12.806",
        "deviceType": "1",
        "appOS": "android",
        "menuId": "162"
    }

    url = "https://apl-hamivideo.cdn.hinet.net/HamiVideo/getUILayoutById.php"
    channel_list = []
    try:
        response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            elements = []

            for info in data.get("UIInfo", []):
                if info.get("title") == "頻道一覽":
                    elements = info.get('elements', [])
                    break
            
            for element in elements:
                channel_list.append({
                    "channelId": element.get('contentPk', ''), 
                    "channelName": element.get('title', ''),
                    "contentPk": element.get('contentPk', '')
                })
    except Exception as e:
        print(f"獲取頻道列表時出錯: {e}")
    
    return channel_list

async def get_programs_with_retry(channel):
    retries = 0

    while retries < MAX_RETRIES:
        try:
            programs = await request_epg(channel['channelName'], channel['contentPk'])
            return programs
        except Exception as e:
            retries += 1
            print(f"請求 {channel['channelName']} 的EPG時出錯: {e}")
            print(f"將在 {RETRY_DELAY} 秒後重試 ({retries}/{MAX_RETRIES})")
            await asyncio.sleep(RETRY_DELAY)
    
    logger.warning(f"{channel['channelName']} 達到最大重試次數，跳過...")
    return []

async def request_all_epg():
    print("開始獲取頻道列表...")
    rawChannels = await request_channel_list()
    print(f"找到 {len(rawChannels)} 個頻道")
    
    all_programs = []
    
    # 使用asyncio.gather並行獲取所有頻道的節目
    tasks = []
    for channel in rawChannels:
        tasks.append(get_programs_with_retry(channel))
    
    results = await asyncio.gather(*tasks)
    
    for programs in results:
        if programs:
            all_programs.extend(programs)
    
    print(f"共獲取 {len(all_programs)} 個節目")
    return rawChannels, all_programs

async def request_epg(channel_name: str, content_pk: str):
    url = "https://apl-hamivideo.cdn.hinet.net/HamiVideo/getEpgByContentIdAndDate.php"
    print(f"獲取 {channel_name} 的節目表...")
    
    epgResult = []
    today = datetime.now(pytz.timezone('Asia/Taipei'))
    
    for i in range(7):
        date = today + timedelta(days=i)
        formatted_date = date.strftime('%Y-%m-%d')
        params = {
            "deviceType": "1",
            "Date": formatted_date,
            "contentPk": content_pk,
        }
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                ui_info = data.get('UIInfo', [])
                if ui_info:
                    elements = ui_info[0].get('elements', [])
                    for element in elements:
                        program_info_list = element.get('programInfo', [])
                        if program_info_list:
                            program_info = program_info_list[0]
                            start_time, end_time = hami_time_to_datetime(program_info['hintSE'])
                            
                            epgResult.append({
                                "channelId": content_pk,
                                "channelName": element.get('title', ''),
                                "programName": program_info.get('programName', ''),
                                "description": program_info.get('description', ''),
                                "start": start_time,
                                "end": end_time
                            })
        except Exception as e:
            print(f"獲取 {channel_name} 在 {formatted_date} 的節目表時出錯: {e}")
    
    return epgResult

def hami_time_to_datetime(time_range: str):
    start_time_str, end_time_str = time_range.split('~')
    start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
    end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
    shanghai_tz = pytz.timezone('Asia/Taipei')
    start_time_shanghai = shanghai_tz.localize(start_time)
    end_time_shanghai = shanghai_tz.localize(end_time)
    return start_time_shanghai, end_time_shanghai

def generate_xml_epg(channels, programs):
    # 建立XML結構
    root = ET.Element("tv")
    root.set("info-name", "Hami電視節目表")
    root.set("info-url", "https://hamivideo.hinet.net/")
    
    channel_name_map = {}
    for channel in channels:
        channel_name_map[channel["contentPk"]] = channel["channelName"]
    
    # 按頻道順序處理
    for channel in channels:
        # 使用頻道名稱作為ID
        channel_id = channel["channelName"]
        
        # 添加頻道元素
        channel_elem = ET.SubElement(root, "channel")
        channel_elem.set("id", channel_id)
        
        display_name = ET.SubElement(channel_elem, "display-name")
        display_name.text = channel["channelName"]
        
        channel_programs = [
            p for p in programs 
            if p["channelId"] == channel["contentPk"]
        ]
        
        # 按開始時間排序
        channel_programs.sort(key=lambda p: p["start"])
        
        for program in channel_programs:
            programme = ET.SubElement(root, "programme")
            programme.set("start", program["start"].strftime("%Y%m%d%H%M%S %z"))
            programme.set("stop", program["end"].strftime("%Y%m%d%H%M%S %z"))
            programme.set("channel", channel_id)
            
            title = ET.SubElement(programme, "title")
            title.set("lang", "zh")
            title.text = program["programName"]
            
            if program["description"]:
                desc = ET.SubElement(programme, "desc")
                desc.set("lang", "zh")
                desc.text = program["description"]
    
    # 建立XML樹
    tree = ET.ElementTree(root)
    return tree

async def main():
    print("開始生成Hami電視節目表...")
    
    # 建立輸出目錄
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    output_dir = os.path.join(project_root, "output")
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"輸出目錄: {output_dir}")
    
    # 獲取頻道和節目數據
    channels, programs = await request_all_epg()
    
    # 生成XML EPG
    xml_tree = generate_xml_epg(channels, programs)
    output_file = os.path.join(output_dir, "hami.xml")
    
    # 正確寫入XML文件
    xml_tree.write(output_file, encoding="utf-8", xml_declaration=True)
    
    print(f"電視節目表已成功生成: {output_file}")
    print(f"檔案大小: {os.path.getsize(output_file) / 1024:.2f} KB")

if __name__ == '__main__':
    asyncio.run(main())
