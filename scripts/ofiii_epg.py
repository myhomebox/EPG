import os
import re
import json
import time
import random
import argparse
import requests
import datetime
import pytz
from bs4 import BeautifulSoup
from xml.etree import ElementTree as ET
from xml.dom import minidom

# 全局時區設置
TAIPEI_TZ = pytz.timezone('Asia/Taipei')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def parse_channel_list():
    """解析頻道列表檔案內容"""
    channels = []
    channel_list = [
        "中天新聞台 ==> 4gtv-4gtv009",
        "台視 ==> 4gtv-4gtv066",
        "中視 ==> 4gtv-4gtv040",
        "華視 ==> 4gtv-4gtv041",
        "台視新聞 ==> 4gtv-4gtv051",
        "華視新聞 ==> 4gtv-4gtv052",
        "中視新聞 ==> 4gtv-4gtv074",
        "國會頻道1台 ==> 4gtv-4gtv084",
        "國會頻道2台 ==> 4gtv-4gtv085",
        "亞洲旅遊台 ==> 4gtv-4gtv076",
        "東森購物1台 ==> 4gtv-4gtv102",
        "東森購物2台 ==> 4gtv-4gtv103",
        "第1商業台 ==> 4gtv-4gtv104",
        "寰宇新聞台灣台 ==> 4gtv-4gtv156",
        "寰宇財經台 ==> 4gtv-4gtv158",
        "好消息 ==> litv-ftv16",
        "好消息2台 ==> litv-ftv17",
        "龍華卡通台 ==> litv-longturn01",
        "龍華洋片台 ==> litv-longturn02",
        "龍華電影台 ==> litv-longturn03",
        "龍華日韓台 ==> litv-longturn11",
        "龍華偶像台 ==> litv-longturn12",
        "寰宇新聞台 ==> litv-longturn14",
        "龍華戲劇台 ==> litv-longturn18",
        "Smart知識台 ==> litv-longturn19",
        "ELTV生活英語台 ==> litv-longturn20",
        "龍華經典台 ==> litv-longturn21",
        "台灣戲劇台 ==> litv-longturn22",
        "三立新聞iNEWS ==> iNEWS",
        "倪珍播新聞 ==> nnews-zh",
        "倪珍報氣象 ==> nnews-wf",
        "倪珍越南語新聞 ==> nnews-vn"
    ]
    
    for line in channel_list:
        if '==>' in line:
            parts = line.split('==>')
            if len(parts) == 2:
                channel_name = parts[0].strip()
                channel_id = parts[1].strip()
                channels.append((channel_name, channel_id))
    return channels

def fetch_epg_data(channel_id, max_retries=3):
    """獲取指定頻道的EPG數據"""
    url = f"https://www.ofiii.com/channel/watch/{channel_id}"
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            script_tag = soup.find('script', id='__NEXT_DATA__')
            
            if script_tag:
                json_data = json.loads(script_tag.string)
                return json_data
            else:
                print(f"❌ 未找到__NEXT_DATA__標簽: {channel_id}")
                return None
                
        except (requests.RequestException, json.JSONDecodeError) as e:
            wait_time = random.uniform(1, 3) * (attempt + 1)
            print(f"⚠️ 請求失敗 (嘗試 {attempt+1}/{max_retries}), 等待 {wait_time:.2f}秒: {str(e)}")
            time.sleep(wait_time)
    
    print(f"❌ 無法獲取EPG數據: {channel_id}")
    return None

def parse_epg_data(json_data, channel_name):
    """解析EPG JSON數據"""
    if not json_data:
        return []
    
    programs = []
    try:
        schedule = json_data['props']['pageProps']['channel']['Schedule']
        
        for item in schedule:
            # 解析開始時間 (UTC時間)
            start_utc = datetime.datetime.strptime(
                item['AirDateTime'], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=pytz.utc)
            
            # 轉換為台北時區
            start_taipei = start_utc.astimezone(TAIPEI_TZ)
            
            # 計算結束時間
            duration = datetime.timedelta(seconds=item['Duration'])
            end_taipei = start_taipei + duration
            
            program_info = item.get('program', {})
            
            programs.append({
                "channelName": channel_name,
                "programName": program_info.get('Title', '未知節目'),
                "description": program_info.get('Description', ''),
                "subtitle": program_info.get('SubTitle', ''),
                "start": start_taipei,
                "end": end_taipei
            })
            
    except (KeyError, TypeError, ValueError) as e:
        print(f"❌ 解析EPG數據失敗: {str(e)}")
    
    return programs

def get_ofiii_epg():
    """獲取OFIII的EPG數據"""
    print("="*50)
    print("開始獲取OFIII EPG數據")
    print("="*50)
    
    # 獲取頻道列表
    channels_info = parse_channel_list()
    if not channels_info:
        print("❌ 無法解析頻道列表")
        return [], []
    
    all_channels = []
    all_programs = []
    
    # 遍歷所有頻道
    for idx, (channel_name, channel_id) in enumerate(channels_info):
        print(f"\n處理頻道 [{idx+1}/{len(channels_info)}]: {channel_name} ({channel_id})")
        
        # 獲取EPG數據
        json_data = fetch_epg_data(channel_id)
        if not json_data:
            continue
            
        # 解析節目數據
        programs = parse_epg_data(json_data, channel_name)
        
        # 添加頻道信息
        try:
            channel_data = json_data['props']['pageProps']['channel']
            logo = channel_data.get('picture', '')
            if not logo:
                logo = json_data['props']['pageProps']['introduction'].get('image', '')
            
            # 確保logo是完整URL
            if logo and not logo.startswith('http'):
                logo = f"https://p-cdnstatic.svc.litv.tv/pics/{logo}"
            
            all_channels.append({
                "name": channel_name,
                "channelName": channel_name,
                "id": channel_id,
                "url": f"https://www.ofiii.com/channel/watch/{channel_id}",
                "source": "ofiii",
                "logo": logo,
                "desc": json_data['props']['pageProps']['introduction'].get('description', '')
            })
        except (KeyError, TypeError) as e:
            print(f"❌ 解析頻道信息失敗: {channel_name}, {str(e)}")
            continue
            
        # 添加節目數據
        all_programs.extend(programs)
        
        # 隨機延遲 (1-3秒)
        if idx < len(channels_info) - 1:
            delay = random.uniform(1, 3)
            print(f"⏱️ 隨機延遲 {delay:.2f}秒")
            time.sleep(delay)
    
    # 統計結果
    print("\n" + "="*50)
    print(f"✅ 成功獲取 {len(all_channels)} 個頻道")
    print(f"✅ 成功獲取 {len(all_programs)} 個節目")
    
    # 按頻道名稱分組顯示節目數量
    channel_counts = {}
    for program in all_programs:
        channel_counts[program["channelName"]] = channel_counts.get(program["channelName"], 0) + 1
    
    for channel, count in channel_counts.items():
        print(f"📺 頻道 {channel}: {count} 個節目")
    
    print("="*50)
    return all_channels, all_programs

def generate_xmltv(channels, programs, output_file="ofiii.xml"):
    """生成XMLTV格式的EPG數據"""
    print(f"\n生成XMLTV檔案: {output_file}")
    
    # 建立XML根元素
    root = ET.Element("tv", generator="OFIII-EPG-Generator", source="www.ofiii.com")
    
    # 添加頻道信息
    for channel in channels:
        channel_elem = ET.SubElement(root, "channel", id=channel['id'])
        ET.SubElement(channel_elem, "display-name").text = channel['name']
        
        if channel['logo']:
            ET.SubElement(channel_elem, "icon", src=channel['logo'])
    
    # 添加節目信息
    for program in programs:
        # XMLTV要求頻道ID作為屬性
        channel_id = next((ch['id'] for ch in channels if ch['name'] == program['channelName']), None)
        if not channel_id:
            continue
            
        # 格式化時間 (XMLTV格式: YYYYMMDDHHMMSS +TZ)
        start_time = program['start'].strftime('%Y%m%d%H%M%S %z')
        end_time = program['end'].strftime('%Y%m%d%H%M%S %z')
        
        # 建立節目元素
        program_elem = ET.SubElement(
            root, 
            "programme", 
            start=start_time, 
            stop=end_time, 
            channel=channel_id
        )
        
        # 添加節目信息
        ET.SubElement(program_elem, "title", lang="zh").text = program['programName']
        
        if program.get('subtitle'):
            ET.SubElement(program_elem, "sub-title", lang="zh").text = program['subtitle']
        
        if program.get('description'):
            ET.SubElement(program_elem, "desc", lang="zh").text = program['description']
    
    # 生成XML字符串
    xml_str = ET.tostring(root, encoding='utf-8').decode('utf-8')
    
    # 美化XML格式
    parsed = minidom.parseString(xml_str)
    pretty_xml = parsed.toprettyxml(indent="  ", encoding='utf-8')
    
    # 儲存到檔案
    with open(output_file, 'wb') as f:
        f.write(pretty_xml)
    
    print(f"✅ XMLTV檔案已生成: {output_file}")
    print(f"📺 頻道數: {len(channels)}")
    print(f"📺 節目數: {len(programs)}")
    print(f"💾 檔案大小: {os.path.getsize(output_file) / 1024:.2f} KB")

def main():
    """主函數，處理命令行參數"""
    parser = argparse.ArgumentParser(description='OFIII EPG 生成器')
    parser.add_argument('--output', type=str, default='output/ofiii.xml', 
                       help='輸出XML檔案路徑 (默認: output/ofiii.xml)')
    
    args = parser.parse_args()
    
    # 確保輸出目錄存在
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"建立輸出目錄: {output_dir}")
    
    # 獲取EPG數據
    channels, programs = get_ofiii_epg()
    
    # 生成XMLTV檔案
    generate_xmltv(channels, programs, args.output)

if __name__ == "__main__":
    main()
