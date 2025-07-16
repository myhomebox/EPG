import json
import requests
import datetime
import pytz
from datetime import datetime, timedelta
from loguru import logger

async def get_4gtv_epg():
    logger.info("正在獲取 四季線上 電子節目表")
    channels = await get_4gtv_channels()
    programs = []
    
    for channel in channels:
        channel_id = channel['channelId']
        channel_name = channel['channelName']
        channel_programs = await get_4gtv_programs(channel_id, channel_name)
        programs.extend(channel_programs)
    
    return channels, programs

async def get_4gtv_channels():
    url = "https://raw.githubusercontent.com/myhomebox/tv/refs/heads/main/fourgtv.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.encoding = "utf-8"
        data = response.json()
        
        channels = []
        for item in data: 
            channels.append({
                "channelName": item["fsNAME"],
                "channelId": item["fs4GTV_ID"],
                "logo": item["fsLOGO_MOBILE"],
                "description": item.get("fsDESCRIPTION", "")
            })
        return channels
    
    except Exception as e:
        logger.error(f"獲取頻道列表失敗: {e}")
        return []

async def get_4gtv_programs(channel_id, channel_name):
    url = f"https://www.4gtv.tv/ProgList/{channel_id}.txt"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.encoding = "utf-8"
        data = response.json()
        
        programs = []
        for item in data:
            start_time = datetime.strptime(
                f"{item['sdate']} {item['stime']}", 
                "%Y-%m-%d %H:%M:%S"
            )
            end_time = datetime.strptime(
                f"{item['edate']} {item['etime']}", 
                "%Y-%m-%d %H:%M:%S"
            )
            
            tz = pytz.timezone('Asia/Taipei')
            start_time = tz.localize(start_time)
            end_time = tz.localize(end_time)
            
            programs.append({
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
