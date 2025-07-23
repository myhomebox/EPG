import asyncio
import os
import pytz
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from xml.dom import minidom

UA = "HamiVideo/7.12.806(Android 11;GM1910) OKHTTP/3.12.2"
headers = {
    'X-ClientSupport-UserProfile': '1',
    'User-Agent': UA
}

# 設置超時時間（秒）
REQUEST_TIMEOUT = 45  # 增加超时时间
MAX_RETRIES = 3
RETRY_DELAY = 15

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
            
            print(f"找到 {len(elements)} 个频道")
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
    
    print(f"{channel['channelName']} 達到最大重試次數，跳過...")
    return []

async def request_all_epg():
    print("開始獲取頻道列表...")
    rawChannels = await request_channel_list()
    print(f"找到 {len(rawChannels)} 個頻道")
    
    all_programs = []
    
    # 分批處理，避免一次性請求過多
    BATCH_SIZE = 10  # 每批處理10個頻道
    for i in range(0, len(rawChannels), BATCH_SIZE):
        batch = rawChannels[i:i+BATCH_SIZE]
        tasks = [get_programs_with_retry(channel) for channel in batch]
        results = await asyncio.gather(*tasks)
        
        for programs in results:
            if programs:
                all_programs.extend(programs)
        
        print(f"已完成 {min(i+BATCH_SIZE, len(rawChannels))}/{len(rawChannels)} 個頻道")
        await asyncio.sleep(5)  # 批次間休息5秒
    
    print(f"共獲取 {len(all_programs)} 個節目")
    return rawChannels, all_programs

async def request_epg(channel_name: str, content_pk: str):
    url = "https://apl-hamivideo.cdn.hinet.net/HamiVideo/getEpgByContentIdAndDate.php"
    print(f"獲取 {channel_name} 的節目表...")
    
    epgResult = []
    today = datetime.now(pytz.timezone('Asia/Taipei'))
    
    # 只獲取未來3天的節目，減少請求量
    for i in range(3):
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
                            try:
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
                                print(f"解析時間失敗: {e}")
        except requests.exceptions.Timeout:
            print(f"獲取 {channel_name} 在 {formatted_date} 的節目表超時")
        except Exception as e:
            print(f"獲取 {channel_name} 在 {formatted_date} 的節目表時出錯: {e}")
    
    return epgResult

def hami_time_to_datetime(time_range: str):
    try:
        start_time_str, end_time_str = time_range.split('~')
        start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
        shanghai_tz = pytz.timezone('Asia/Taipei')
        start_time_shanghai = shanghai_tz.localize(start_time)
        end_time_shanghai = shanghai_tz.localize(end_time)
        return start_time_shanghai, end_time_shanghai
    except Exception as e:
        print(f"時間格式錯誤: {time_range}")
        # 返回默認時間避免崩潰
        default_time = shanghai_tz.localize(datetime.now())
        return default_time, default_time + timedelta(hours=1)

def generate_xml_epg(channels, programs):
    print("開始生成XML EPG...")
    
    # 建立XML結構
    root = ET.Element("tv")
    root.set("generator-info-name", "Hami EPG Generator")
    root.set("generator-info-url", "")
    
    # 添加頻道信息
    channel_id_map = {}
    for channel in channels:
        channel_id = channel["channelId"]
        channel_name = channel["channelName"]
        channel_id_map[channel_id] = channel_name
        
        channel_elem = ET.SubElement(root, "channel")
        channel_elem.set("id", channel_id)
        
        display_name = ET.SubElement(channel_elem, "display-name")
        display_name.text = channel_name
    
    # 添加節目信息
    for program in programs:
        if program["channelId"] in channel_id_map:
            try:
                programme = ET.SubElement(root, "programme")
                programme.set("start", program["start"].strftime("%Y%m%d%H%M%S %z"))
                programme.set("stop", program["end"].strftime("%Y%m%d%H%M%S %z"))
                programme.set("channel", program["channelId"])
                
                title = ET.SubElement(programme, "title")
                title.set("lang", "zh")
                title.text = program["programName"]
                
                if program["description"]:
                    desc = ET.SubElement(programme, "desc")
                    desc.set("lang", "zh")
                    desc.text = program["description"]
            except Exception as e:
                print(f"添加節目失敗: {e}")
    
    # 建立XML字符串
    xml_str = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode()
    
    # 美化XML輸出
    pretty_xml = minidom.parseString(xml_str).toprettyxml(indent="  ")
    
    # 移除多餘的空行
    pretty_xml = "\n".join([line for line in pretty_xml.split("\n") if line.strip()])
    
    return pretty_xml

async def main():
    print("開始生成Hami電視節目表...")
    
    # 建立輸出目錄 - 直接在根目錄下建立output
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)  # 獲取項目根目錄
    output_dir = os.path.join(project_root, "output")
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"輸出目錄: {output_dir}")
    
    # 獲取頻道和節目數據
    channels, programs = await request_all_epg()
    
    # 生成XML EPG
    xml_str = generate_xml_epg(channels, programs)
    output_file = os.path.join(output_dir, "hami.xml")
    
    # 儲存到檔案
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(xml_str)
    
    print(f"電視節目表已成功生成: {output_file}")
    print(f"檔案大小: {os.path.getsize(output_file) / 1024:.2f} KB")

if __name__ == '__main__':
    asyncio.run(main())
