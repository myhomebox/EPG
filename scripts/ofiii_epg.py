import os
import sys
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
    """解析頻道列表文件內容"""
    channels = []
    channel_list = [
        "倪珍越南語新聞 ==> nnews-vn",
        "倪珍報氣象 ==> nnews-wf",
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
        "倪珍播新聞 ==> nnews-zh"
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
            
            # 檢查響應內容
            if not response.text.strip():
                print(f"⚠️ 響應內容為空: {channel_id}")
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            script_tag = soup.find('script', id='__NEXT_DATA__')
            
            if script_tag and script_tag.string:
                try:
                    return json.loads(script_tag.string)
                except json.JSONDecodeError as e:
                    print(f"⚠️ JSON解析失敗: {channel_id}, {str(e)}")
                    return None
            else:
                print(f"⚠️ 未找到__NEXT_DATA__標簽: {channel_id}")
                return None
                
        except requests.RequestException as e:
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
        # 添加安全檢查
        if not json_data.get('props') or not json_data['props'].get('pageProps') or not json_data['props']['pageProps'].get('channel'):
            print(f"❌ JSON結構無效: {channel_name}")
            return []
        
        schedule = json_data['props']['pageProps']['channel'].get('Schedule', [])
        
        for item in schedule:
            # 解析開始時間 (UTC時間)
            try:
                start_utc = datetime.datetime.strptime(
                    item['AirDateTime'], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=pytz.utc)
            except (KeyError, ValueError):
                print(f"⚠️ 跳過無效的時間格式: {channel_name}")
                continue
                
            # 轉換為台北時區
            start_taipei = start_utc.astimezone(TAIPEI_TZ)
            
            # 計算結束時間
            try:
                duration = datetime.timedelta(seconds=item.get('Duration', 0))
                end_taipei = start_taipei + duration
            except TypeError:
                print(f"⚠️ 跳過無效的持續時間: {channel_name}")
                continue
            
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
    failed_channels = []
    
    # 遍歷所有頻道
    for idx, (channel_name, channel_id) in enumerate(channels_info):
        print(f"\n處理頻道 [{idx+1}/{len(channels_info)}]: {channel_name} ({channel_id})")
        
        # 獲取EPG數據
        json_data = fetch_epg_data(channel_id)
        if not json_data:
            failed_channels.append(channel_name)
            continue
            
        # 解析節目數據
        programs = parse_epg_data(json_data, channel_name)
        
        # 添加頻道信息
        try:
            # 添加多層安全檢查
            if not json_data.get('props') or not json_data['props'].get('pageProps'):
                print(f"❌ 跳過無效的JSON結構: {channel_name}")
                failed_channels.append(channel_name)
                continue
                
            page_props = json_data['props']['pageProps']
            
            # 獲取頻道數據
            channel_data = page_props.get('channel', {})
            introduction = page_props.get('introduction', {})
            
            logo = channel_data.get('picture', '')
            if not logo:
                logo = introduction.get('image', '')
            
            # 確保logo是完整URL
            if logo and not logo.startswith('http'):
                logo = f"https://p-cdnstatic.svc.litv.tv/pics/{logo}"
            
            # 添加頻道描述
            channel_desc = introduction.get('description', '')
            if not channel_desc:
                channel_desc = channel_data.get('description', '')
            
            all_channels.append({
                "name": channel_name,
                "channelName": channel_name,
                "id": channel_id,
                "url": f"https://www.ofiii.com/channel/watch/{channel_id}",
                "source": "ofiii",
                "logo": logo,
                "desc": channel_desc,
                "sort": "海外"
            })
            
            # 添加節目數據
            all_programs.extend(programs)
            
        except Exception as e:
            print(f"❌ 解析頻道信息失敗: {channel_name}, {str(e)}")
            failed_channels.append(channel_name)
            continue
            
        # 隨機延遲 (1-3秒)
        if idx < len(channels_info) - 1:
            delay = random.uniform(1, 3)
            print(f"⏱️ 隨機延遲 {delay:.2f}秒")
            time.sleep(delay)
    
    # 統計結果
    print("\n" + "="*50)
    print(f"✅ 成功獲取 {len(all_channels)} 個頻道")
    print(f"✅ 成功獲取 {len(all_programs)} 個節目")
    
    if failed_channels:
        print(f"⚠️ 失敗頻道 ({len(failed_channels)}): {', '.join(failed_channels)}")
    
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
    print(f"\n生成XMLTV文件: {output_file}")
    
    # 創建XML根元素
    root = ET.Element("tv", generator="OFIII-EPG-Generator", source="www.ofiii.com")
    
    # 按照第六點要求：頻道1定義 -> 頻道1節目 -> 頻道2定義 -> 頻道2節目 -> ...
    program_count = 0
    for channel in channels:
        channel_name = channel['name']
        
        # 添加頻道定義
        channel_elem = ET.SubElement(root, "channel", id=channel_name)
        ET.SubElement(channel_elem, "display-name", lang="zh").text = channel_name
        
        if channel.get('logo'):
            ET.SubElement(channel_elem, "icon", src=channel['logo'])
        
        # 獲取該頻道的所有節目
        channel_programs = [p for p in programs if p['channelName'] == channel_name]
        if not channel_programs:
            print(f"⚠️ 頻道 {channel_name} 沒有節目數據")
            continue
            
        # 按開始時間排序
        channel_programs.sort(key=lambda p: p['start'])
        
        # 添加該頻道的所有節目
        for program in channel_programs:
            try:
                # 格式化時間 (XMLTV格式: YYYYMMDDHHMMSS +TZ)
                start_time = program['start'].strftime('%Y%m%d%H%M%S %z')
                end_time = program['end'].strftime('%Y%m%d%H%M%S %z')
                
                # 創建節目元素
                program_elem = ET.SubElement(
                    root, 
                    "programme", 
                    channel=channel_name,
                    start=start_time, 
                    stop=end_time
                )
                
                # 添加節目信息
                title = program.get('programName', '未知節目')
                ET.SubElement(program_elem, "title", lang="zh").text = title
                
                if program.get('subtitle'):
                    ET.SubElement(program_elem, "sub-title", lang="zh").text = program['subtitle']
                
                if program.get('description'):
                    ET.SubElement(program_elem, "desc", lang="zh").text = program['description']
                
                program_count += 1
            except Exception as e:
                print(f"⚠️ 跳過無效的節目數據: {str(e)}")
                continue
    
    # 生成XML字符串
    xml_str = ET.tostring(root, encoding='utf-8').decode('utf-8')
    
    # 美化XML格式
    try:
        parsed = minidom.parseString(xml_str)
        pretty_xml = parsed.toprettyxml(indent="  ", encoding='utf-8')
    except Exception as e:
        print(f"⚠️ XML美化失敗, 使用原始XML: {str(e)}")
        pretty_xml = xml_str.encode('utf-8')
    
    # 保存到文件
    try:
        with open(output_file, 'wb') as f:
            f.write(pretty_xml)
        
        print(f"✅ XMLTV文件已生成: {output_file}")
        print(f"📺 頻道數: {len(channels)}")
        print(f"📺 節目數: {program_count}")
        print(f"💾 文件大小: {os.path.getsize(output_file) / 1024:.2f} KB")
        return True
    except Exception as e:
        print(f"❌ 保存XML文件失敗: {str(e)}")
        return False

def main():
    """主函數，處理命令行參數"""
    parser = argparse.ArgumentParser(description='OFIII EPG 生成器')
    parser.add_argument('--output', type=str, default='output/ofiii.xml', 
                       help='輸出XML文件路徑 (默認: output/ofiii.xml)')
    
    args = parser.parse_args()
    
    # 確保輸出目錄存在
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"創建輸出目錄: {output_dir}")
    
    try:
        # 獲取EPG數據
        channels, programs = get_ofiii_epg()
        
        if not channels or not programs:
            print("❌ 未獲取到有效EPG數據，無法生成XML")
            sys.exit(1)
            
        # 生成XMLTV文件
        if not generate_xmltv(channels, programs, args.output):
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ 主程序錯誤: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
