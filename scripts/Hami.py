import asyncio
import os
import pytz
import requests
from datetime import datetime, timedelta
from loguru import logger

UA = "HamiVideo/7.12.806(Android 11;GM1910) OKHTTP/3.12.2"
headers = {
    'X-ClientSupport-UserProfile': '1',
    'User-Agent': UA
}

async def request_channel_list():
    params = {
        "appVersion": "7.12.806",
        "deviceType": "1",
        "appOS": "android",
        "menuId": "162"
    }

    url = "https://apl-hamivideo.cdn.hinet.net/HamiVideo/getUILayoutById.php"
    channel_list = []
    response = requests.get(url, params=params, headers=headers)
    if response.status_code == 200:
        data = response.json()
        elements = []

        for info in data["UIInfo"]:
            if info["title"] == "頻道一覽":
                elements = info['elements']
                break
        for element in elements:
            channel_list.append({"channelName": element['title'], "contentPk": element['contentPk']})
    return channel_list

async def get_programs_with_retry(channel):
    max_retries = 5
    retries = 0

    while retries < max_retries:
        try:
            programs = await request_epg(channel['channelName'], channel['contentPk'])
            return programs
        except Exception as e:
            retries += 1
            print(f"請求 電視節目表 時出錯 {channel['channelName']}: {e}")
            print(f"重試 {retries}/{max_retries} 於30秒後...")

            if retries < max_retries:
                await asyncio.sleep(30)
            else:
                logger.info(f"Max retries reached for {channel['channelName']}, skipping...")
                return []

async def request_all_epg():
    rawChannels = await request_channel_list()
    channel_programs = {}
    
    for channel in rawChannels:
        programs = await get_programs_with_retry(channel)
        if programs:
            # 按開始時間排序節目
            programs.sort(key=lambda x: x['start'])
            channel_programs[channel['channelName']] = programs
    
    return rawChannels, channel_programs

async def request_epg(channel_name: str, content_pk: str):
    url = "https://apl-hamivideo.cdn.hinet.net/HamiVideo/getEpgByContentIdAndDate.php"
    print(f"正在生成電視節目表：{content_pk},{channel_name}")
    epgResult = []
    for i in range(7):
        date = datetime.now() + timedelta(days=i)
        formatted_date = date.strftime('%Y-%m-%d')
        params = {
            "deviceType": "1",
            "Date": formatted_date,
            "contentPk": content_pk,
        }
        response = requests.get(url, params=params, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if len(data['UIInfo'][0]['elements']) > 0:
                for element in data['UIInfo'][0]['elements']:
                    if len(element['programInfo']) > 0:
                        program_info = element['programInfo'][0]
                        start_time_with_tz, end_time_with_tz = hami_time_to_datetime(program_info['hintSE'])
                        epgResult.append(
                            {"channelName": element['title'], "programName": program_info['programName'],
                             "description": "",
                             "start": start_time_with_tz, "end": end_time_with_tz
                             }
                        )

    return epgResult

def hami_time_to_datetime(time_range: str):
    start_time_str, end_time_str = time_range.split('~')
    start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
    end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
    shanghai_tz = pytz.timezone('Asia/Taipei')
    start_time_shanghai = shanghai_tz.localize(start_time)
    end_time_shanghai = shanghai_tz.localize(end_time)
    return start_time_shanghai, end_time_shanghai

def generate_epg_file(channels, channel_programs):
    # 獲取目前日期用於檔案名
    today = datetime.now().strftime("%Y%m%d")
    output_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    
    # 確保輸出目錄存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 建立輸出檔案路徑
    output_file = os.path.join(output_dir, f"hami_epg_{today}.txt")
    
    with open(output_file, "w", encoding="utf-8") as f:
        for channel in channels:
            channel_name = channel["channelName"]
            f.write(f"{channel_name}\n")
            
            # 獲取該頻道的節目
            programs = channel_programs.get(channel_name, [])
            
            for program in programs:
                # 格式化時間 (HH:MM)
                start_time = program["start"].strftime("%H:%M")
                program_name = program["programName"]
                f.write(f"{start_time} {program_name}\n")
    
    print(f"電視節目表檔案已生成: {output_file}")
    return output_file

async def main():
    print("開始獲取頻道清單...")
    channels, channel_programs = await request_all_epg()
    print(f"共獲取 {len(channels)} 個頻道的電視節目表")
    
    output_file = generate_epg_file(channels, channel_programs)
    print(f"電視節目表生成完成，儲存至: {output_file}")

if __name__ == '__main__':
    asyncio.run(main())
