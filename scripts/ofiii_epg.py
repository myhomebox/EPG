import os
import sys
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

# 全域時區設置
TAIPEI_TZ = pytz.timezone('Asia/Taipei')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def human_like_delay(min_seconds=1, max_seconds=5):
    """人類仿真延遲"""
    delay = random.uniform(min_seconds, max_seconds)
    print(f"⏱️ 隨機延遲 {delay:.2f}秒")
    time.sleep(delay)

def human_like_typing_effect(text, delay=0.03):
    """人類仿真打字效果"""
    for char in text:
        print(char, end='', flush=True)
        time.sleep(delay)
    print()

def parse_channel_list():
    """解析頻道清單檔案內容（硬編碼部分頻道 + 大量自動生成 ofiii 頻道）"""
    other_channels = [
        "4gtv-4gtv009", "4gtv-4gtv040", "4gtv-4gtv041", "4gtv-4gtv052",
        "4gtv-4gtv074", "4gtv-4gtv084", "4gtv-4gtv085", "4gtv-4gtv076",
        "4gtv-4gtv102", "4gtv-4gtv103", "4gtv-4gtv104", "4gtv-4gtv156",
        "4gtv-4gtv158", "litv-ftv16", "litv-ftv17", "litv-xinchuang01",
        "litv-xinchuang02", "litv-xinchuang03", "litv-xinchuang11",
        "litv-xinchuang12", "litv-longturn14", "litv-xinchuang18",
        "litv-xinchuang19", "litv-xinchuang20", "litv-xinchuang21",
        "litv-xinchuang22", "iNEWS", "daystar", "setnews"
    ]
    ofiii_channels = [f"ofiii{i}" for i in range(13, 256)]
    channel_list = other_channels + ofiii_channels
    print(f"📡 總共 {len(channel_list)} 個頻道")
    print(f"   - 非ofiii頻道: {len(other_channels)} 個")
    print(f"   - ofiii頻道: {len(ofiii_channels)} 個 (ofiii13~ofiii255)")
    return channel_list

def fetch_epg_data(channel_id, max_retries=1):
    """獲取指定頻道的電視節目表數據（解析 __NEXT_DATA__ JSON）"""
    url = f"https://www.ofiii.com/channel/watch/{channel_id}"
    for attempt in range(max_retries):
        try:
            if attempt == 0:
                human_like_delay(0.5, 1.5)
            print(f"   🔍 嘗試 {attempt+1}/{max_retries}: 獲取 {channel_id}")
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            if not response.text.strip():
                print(f"   ⚠️ 響應內容為空: {channel_id}")
                return None
            soup = BeautifulSoup(response.text, 'html.parser')
            script_tag = soup.find('script', id='__NEXT_DATA__')
            if script_tag and script_tag.string:
                try:
                    data = json.loads(script_tag.string)
                    print(f"   ✅ 成功獲取 {channel_id} 的數據")
                    return data
                except json.JSONDecodeError as e:
                    print(f"   ⚠️ JSON解析失敗: {channel_id}, {str(e)}")
                    return None
            else:
                print(f"   ⚠️ 未找到__NEXT_DATA__標簽: {channel_id}")
                return None
        except requests.RequestException as e:
            wait_time = random.uniform(1, 3) * (attempt + 1)
            print(f"   ⚠️ 請求失敗 (嘗試 {attempt+1}/{max_retries}), 等待 {wait_time:.2f}秒: {str(e)}")
            time.sleep(wait_time)
    print(f"   ❌ 無法獲取 電視節目表 數據: {channel_id}")
    return None

def parse_timestamp(ts):
    """處理秒或毫秒的 Unix 時間戳，返回秒級 float"""
    if ts > 9999999999:  # 大於 10^10 視為毫秒
        return ts / 1000.0
    return float(ts)

def parse_schedule_data(json_data, channel_id):
    """解析直播頻道的 schedule 資料"""
    if not json_data:
        return []
    programs = []
    try:
        channel_data = json_data['props']['pageProps']['channel']
        schedule = channel_data.get('schedule', [])
        channel_name = channel_data.get('title', channel_id)
        for item in schedule:
            try:
                start_ts = item.get('startTime')
                end_ts = item.get('endTime')
                if not start_ts or not end_ts:
                    continue
                start_taipei = datetime.datetime.fromtimestamp(start_ts, TAIPEI_TZ)
                end_taipei = datetime.datetime.fromtimestamp(end_ts, TAIPEI_TZ)
                programs.append({
                    "channelId": channel_id,
                    "channelName": channel_name,
                    "programName": item.get('title', '未知節目'),
                    "description": item.get('description', ''),
                    "subtitle": item.get('subtitle', ''),
                    "start": start_taipei,
                    "end": end_taipei
                })
            except (KeyError, ValueError, TypeError) as e:
                print(f"   ⚠️ 跳過無效節目數據: {channel_id}, {str(e)}")
                continue
    except Exception as e:
        print(f"   ❌ 解析直播節目表失敗: {str(e)}")
    return programs

def parse_playout_schedule_data(json_data, channel_id):
    """解析排程點播頻道的 vodChannelSchedule，節目已有確切 startTime / endTime"""
    if not json_data:
        return []
    programs = []
    try:
        channel_data = json_data['props']['pageProps']['channel']
        vod_schedule = channel_data.get('vodChannelSchedule')
        if not vod_schedule:
            print(f"   ⚠️ 排程點播頻道 {channel_id} 沒有 vodChannelSchedule")
            return []
        vod_programs = vod_schedule.get('programs', [])
        if not vod_programs:
            return []
        channel_name = channel_data.get('title', channel_id)
        for item in vod_programs:
            try:
                start_ts = parse_timestamp(item.get('startTime', 0))
                end_ts = parse_timestamp(item.get('endTime', 0))
                if start_ts == 0 or end_ts == 0:
                    continue
                start_taipei = datetime.datetime.fromtimestamp(start_ts, TAIPEI_TZ)
                end_taipei = datetime.datetime.fromtimestamp(end_ts, TAIPEI_TZ)
                programs.append({
                    "channelId": channel_id,
                    "channelName": channel_name,
                    "programName": item.get('title', '未知節目'),
                    "description": item.get('description', ''),
                    "subtitle": item.get('subtitle', ''),
                    "start": start_taipei,
                    "end": end_taipei
                })
            except (KeyError, ValueError, TypeError) as e:
                print(f"   ⚠️ 跳過無效節目數據: {channel_id}, {str(e)}")
                continue
    except Exception as e:
        print(f"   ❌ 解析排程點播節目表失敗: {str(e)}")
    return programs

def parse_vod_schedule_data(json_data, channel_id):
    """解析動態輪播點播頻道的 vodChannelSchedule，根據當前時間計算相對時間"""
    if not json_data:
        return []
    programs = []
    try:
        channel_data = json_data['props']['pageProps']['channel']
        vod_schedule = channel_data.get('vodChannelSchedule')
        if not vod_schedule:
            print(f"   ⚠️ 動態點播頻道 {channel_id} 沒有 vodChannelSchedule")
            return []
        vod_programs = vod_schedule.get('programs', [])
        if not vod_programs:
            return []
        focus_index = vod_schedule.get('focusIndex', 0)
        elapsed_ms = vod_schedule.get('time', 0)
        if focus_index < 0 or focus_index >= len(vod_programs):
            focus_index = 0
        channel_name = channel_data.get('title', channel_id)
        now = datetime.datetime.now(TAIPEI_TZ)
        current_prog = vod_programs[focus_index]
        length_sec = current_prog.get('length', 0)
        start_current = now - datetime.timedelta(milliseconds=elapsed_ms)
        end_current = start_current + datetime.timedelta(seconds=length_sec)
        time_map = {}
        time_map[focus_index] = (start_current, end_current)
        prev_end = start_current
        for i in range(focus_index - 1, -1, -1):
            l_sec = vod_programs[i].get('length', 0)
            start_time = prev_end - datetime.timedelta(seconds=l_sec)
            end_time = prev_end
            time_map[i] = (start_time, end_time)
            prev_end = start_time
        next_start = end_current
        for i in range(focus_index + 1, len(vod_programs)):
            l_sec = vod_programs[i].get('length', 0)
            end_time = next_start + datetime.timedelta(seconds=l_sec)
            time_map[i] = (next_start, end_time)
            next_start = end_time
        for i, item in enumerate(vod_programs):
            if i in time_map:
                start, end = time_map[i]
                programs.append({
                    "channelId": channel_id,
                    "channelName": channel_name,
                    "programName": item.get('title', '未知節目'),
                    "description": item.get('description', ''),
                    "subtitle": item.get('subtitle', ''),
                    "start": start,
                    "end": end
                })
    except Exception as e:
        print(f"   ❌ 解析動態點播節目表失敗: {str(e)}")
    return programs

def parse_epg_data(json_data, channel_id):
    """分派給正確的解析器（直播 / 排程點播 / 動態點播）"""
    if not json_data:
        return []
    try:
        channel_data = json_data['props']['pageProps']['channel']
        # 優先判斷直播頻道（具有 schedule）
        if 'schedule' in channel_data:
            print(f"   📺 檢測到直播頻道: {channel_id}")
            return parse_schedule_data(json_data, channel_id)
        # 其次判斷點播頻道 (vodChannelSchedule)
        vod_schedule = channel_data.get('vodChannelSchedule')
        if vod_schedule:
            programs = vod_schedule.get('programs', [])
            if programs and programs[0].get('startTime', 0) > 0:
                # 具有確切時間戳的排程點播
                print(f"   🗓️ 檢測到排程點播頻道: {channel_id}")
                return parse_playout_schedule_data(json_data, channel_id)
            else:
                # 動態輪播點播
                print(f"   📹 檢測到動態點播頻道: {channel_id}")
                return parse_vod_schedule_data(json_data, channel_id)
        else:
            print(f"   ⚠️ 頻道 {channel_id} 無 schedule 或 vodChannelSchedule")
            return []
    except Exception as e:
        print(f"   ❌ 判斷頻道類型失敗: {str(e)}")
        return []

def get_channel_info(json_data, channel_id):
    """提取頻道資訊，logo 新舊格式相容，introduction 可能為 null"""
    if not json_data:
        return None
    try:
        page_props = json_data.get('props', {}).get('pageProps', {})
        channel_data = page_props.get('channel', {})
        # introduction 可能為 None
        introduction = page_props.get('introduction') or {}
        channel_name = channel_data.get('title', channel_id)

        logo = channel_data.get('picture', '')
        if logo:
            if not logo.startswith('http'):
                logo = f"https://p-cdnstatic.svc.litv.tv/{logo}"
                if '_tv' in logo:
                    logo = logo.replace('_tv', '_mobile')

        description = introduction.get('description', '')
        return {
            "channelName": channel_name,
            "id": channel_id,
            "logo": logo,
            "description": description
        }
    except Exception as e:
        print(f"   ❌ 提取頻道信息失敗: {channel_id}, {str(e)}")
        return None

def get_ofiii_epg():
    """主流程：獲取所有頻道的節目表"""
    print("=" * 50)
    human_like_typing_effect("開始獲取歐飛電視節目表")
    print("=" * 50)
    channels = parse_channel_list()
    if not channels:
        print("❌ 無法解析頻道清單")
        return [], []
    all_channels_info = []
    all_programs = []
    failed_channels = []
    for idx, channel_id in enumerate(channels):
        print(f"\n📡 處理頻道 [{idx+1}/{len(channels)}]: {channel_id}")
        json_data = fetch_epg_data(channel_id)
        if not json_data:
            failed_channels.append(channel_id)
            continue
        channel_info = get_channel_info(json_data, channel_id)
        if channel_info:
            all_channels_info.append(channel_info)
            print(f"   ✅ 成功提取頻道信息: {channel_info['channelName']}")
        else:
            print(f"   ⚠️ 無法提取頻道信息: {channel_id}")
        programs = parse_epg_data(json_data, channel_id)
        all_programs.extend(programs)
        print(f"   📺 解析到 {len(programs)} 個節目")
        if idx < len(channels) - 1:
            human_like_delay(1, 3)
    print("\n" + "=" * 50)
    human_like_typing_effect("數據獲取完成，生成統計信息...")
    print(f"✅ 成功獲取 {len(all_channels_info)} 個頻道信息")
    print(f"✅ 成功獲取 {len(all_programs)} 個節目")
    if failed_channels:
        print(f"⚠️ 失敗頻道 ({len(failed_channels)}): {', '.join(failed_channels[:10])}{'...' if len(failed_channels) > 10 else ''}")
    channel_counts = {}
    for program in all_programs:
        cn = program["channelName"]
        channel_counts[cn] = channel_counts.get(cn, 0) + 1
    print("\n📊 各頻道節目統計:")
    for channel, count in list(channel_counts.items())[:10]:
        print(f"   📺 {channel}: {count} 個節目")
    if len(channel_counts) > 10:
        print(f"   ... 還有 {len(channel_counts) - 10} 個頻道")
    print("=" * 50)
    return all_channels_info, all_programs

def generate_xmltv(channels_info, programs, output_file="ofiii.xml"):
    """生成 XMLTV 格式的 EPG 檔案"""
    print(f"\n📄 生成XMLTV檔案: {output_file}")
    human_like_typing_effect("正在生成XML格式的節目表數據...")
    root = ET.Element("tv", generator="OFIII-EPG-Generator", source="www.ofiii.com")
    programs_by_channel = {}
    for program in programs:
        cn = program['channelName']
        programs_by_channel.setdefault(cn, []).append(program)
    sorted_channel_names = sorted(programs_by_channel.keys())
    program_count = 0
    channel_count = 0
    for channel_name in sorted_channel_names:
        channel_info = next((info for info in channels_info if info['channelName'] == channel_name), None)
        if not channel_info:
            continue
        channel_elem = ET.SubElement(root, "channel", id=channel_name)
        ET.SubElement(channel_elem, "display-name", lang="zh").text = channel_name
        if channel_info.get('logo'):
            ET.SubElement(channel_elem, "icon", src=channel_info['logo'])
        if channel_info.get('description'):
            ET.SubElement(channel_elem, "desc", lang="zh").text = channel_info['description']
        channel_count += 1
        channel_programs = sorted(programs_by_channel[channel_name], key=lambda x: x['start'])
        for prog in channel_programs:
            try:
                start_str = prog['start'].strftime('%Y%m%d%H%M%S %z')
                end_str = prog['end'].strftime('%Y%m%d%H%M%S %z')
                prog_elem = ET.SubElement(root, "programme", channel=channel_name, start=start_str, stop=end_str)
                title = prog.get('programName', '未知節目')
                ET.SubElement(prog_elem, "title", lang="zh").text = title
                if prog.get('subtitle'):
                    ET.SubElement(prog_elem, "sub-title", lang="zh").text = prog['subtitle']
                if prog.get('description'):
                    ET.SubElement(prog_elem, "desc", lang="zh").text = prog['description']
                program_count += 1
            except Exception as e:
                print(f"⚠️ 跳過無效的節目數據: {str(e)}")
                continue
    xml_str = ET.tostring(root, encoding='utf-8').decode('utf-8')
    try:
        parsed = minidom.parseString(xml_str)
        pretty_xml = parsed.toprettyxml(indent="  ", encoding='utf-8')
    except Exception as e:
        print(f"⚠️ XML美化失敗, 使用原始XML: {str(e)}")
        pretty_xml = xml_str.encode('utf-8')
    try:
        with open(output_file, 'wb') as f:
            f.write(pretty_xml)
        print(f"✅ XMLTV檔案已生成: {output_file}")
        print(f"📺 頻道數: {channel_count}")
        print(f"📺 節目數: {program_count}")
        print(f"💾 檔案大小: {os.path.getsize(output_file) / 1024:.2f} KB")
        return True
    except Exception as e:
        print(f"❌ 儲存XML檔案失敗: {str(e)}")
        return False

def generate_json_file(channels_info, output_file="ofiii.json"):
    """生成 JSON 格式的頻道資訊備份"""
    print(f"\n📄 生成JSON檔案: {output_file}")
    human_like_typing_effect("正在生成JSON格式的頻道數據...")
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(channels_info, f, ensure_ascii=False, indent=2)
        print(f"✅ JSON檔案已生成: {output_file}")
        print(f"📺 頻道數: {len(channels_info)}")
        print(f"💾 檔案大小: {os.path.getsize(output_file) / 1024:.2f} KB")
        return True
    except Exception as e:
        print(f"❌ 儲存JSON檔案失敗: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description='歐飛電視節目表')
    parser.add_argument('--output', type=str, default='output/ofiii.xml',
                        help='輸出XML檔案路徑 (默認: output/ofiii.xml)')
    args = parser.parse_args()
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"📁 建立輸出目錄: {output_dir}")
    try:
        channels_info, programs = get_ofiii_epg()
        if not channels_info:
            print("❌ 未獲取到有效頻道信息，無法生成檔案")
            sys.exit(1)
        if not generate_xmltv(channels_info, programs, args.output):
            sys.exit(1)
        json_output = os.path.join(output_dir, "ofiii.json")
        if not generate_json_file(channels_info, json_output):
            print("⚠️ JSON檔案生成失敗，但XML已成功生成")
        print("\n🎉 所有操作完成！")
    except Exception as e:
        print(f"❌ 主程序錯誤: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
