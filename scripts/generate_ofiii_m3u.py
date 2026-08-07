import sys
import subprocess
import importlib

# 檢查並安裝所需的包
required_packages = [
    'requests',
    'beautifulsoup4',
    'lxml',
    'aiohttp',
    'asyncio'
]

for package in required_packages:
    try:
        if package == 'beautifulsoup4':
            importlib.import_module('bs4')
        elif package == 'aiohttp':
            importlib.import_module('aiohttp')
        elif package == 'asyncio':
            importlib.import_module('asyncio')
        else:
            importlib.import_module(package)
    except ImportError:
        print(f"正在安裝 {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# 現在導入其他模塊
import requests
import json
import time
import os
import random
from pathlib import Path
import zipfile
import re
import uuid
from bs4 import BeautifulSoup
import asyncio
import aiohttp

async def get_build_id():
    """動態獲取 Next.js 構建版本號"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get("https://www.ofiii.com/channel/watch/4gtv-4gtv040", 
                                 headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    return "YOQn3leN1n6vChLX_aqzq"  # 備用默認值
                
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # 從 script 標簽中查找
                candidates = soup.find_all('script', {'src': True, 'defer': True})
                for script in candidates:
                    if match := re.search(r'/_next/static/([^/]+)/_buildManifest\.js', script['src']):
                        return match.group(1)
                
                # 備用檢測方法
                script = soup.find('script', id='__NEXT_DATA__')
                if script and (build_id := re.search(r'"buildId":"([^"]+)"', script.text)):
                    return build_id.group(1)
                
                return "YOQn3leN1n6vChLX_aqzq"  # 最後備用默認值
                
    except Exception as e:
        print(f"❌ 獲取 build_id 失敗: {str(e)}")
        return "YOQn3leN1n6vChLX_aqzq"

async def get_channel_data(asset_id, build_id):
    """獲取頻道詳細數據"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        }
        
        json_url = f"https://www.ofiii.com/_next/data/{build_id}/channel/watch/{asset_id}.json"
        
        print(f"🌐 請求頻道數據: {json_url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(json_url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    print(f"⚠️ 頻道 {asset_id} 請求失敗，狀態碼: {resp.status}")
                    if resp.status == 404:
                        print(f"⚠️ 頻道 {asset_id} 不存在 (404)")
                        return None
                    return await get_channel_data_fallback(asset_id)
                
                data = await resp.json()
                
                if not data:
                    print(f"⚠️ 頻道 {asset_id} 返回的數據為空")
                    return await get_channel_data_fallback(asset_id)
                
                if 'pageProps' not in data:
                    print(f"⚠️ 頻道 {asset_id} 數據結構不完整，缺少 pageProps")
                    return await get_channel_data_fallback(asset_id)
                    
                return data
                
    except asyncio.TimeoutError:
        print(f"⚠️ 獲取頻道 {asset_id} 數據逾時")
        return await get_channel_data_fallback(asset_id)
    except aiohttp.ClientError as e:
        print(f"⚠️ 獲取頻道 {asset_id} 數據時發生網路錯誤: {str(e)}")
        return await get_channel_data_fallback(asset_id)
    except Exception as e:
        print(f"⚠️ 獲取頻道 {asset_id} 數據失敗: {str(e)}")
        return await get_channel_data_fallback(asset_id)

async def get_channel_data_fallback(asset_id):
    """備用方法獲取頻道數據 - 通過直接訪問頁面"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        }
        
        page_url = f"https://www.ofiii.com/channel/watch/{asset_id}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(page_url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return None
                
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                script_tag = soup.find('script', id='__NEXT_DATA__')
                if script_tag:
                    try:
                        data = json.loads(script_tag.string)
                        return data
                    except json.JSONDecodeError:
                        print(f"⚠️ 無法解析頻道 {asset_id} 的 JSON 數據")
                
                return None
                
    except Exception as e:
        print(f"⚠️ 備用方法獲取頻道 {asset_id} 數據失敗: {str(e)}")
        return None

def normalize_picture_url(picture_path: str) -> str:
    """補全圖片相對路徑為完整 URL"""
    if not picture_path:
        return ''
    if picture_path.startswith(('http://', 'https://')):
        return picture_path
    if picture_path.startswith('pics/'):
        return f"https://p-cdnstatic.svc.litv.tv/{picture_path}"
    elif picture_path.startswith('/'):
        return f"https://p-cdnstatic.svc.litv.tv{picture_path}"
    else:
        return f"https://p-cdnstatic.svc.litv.tv/{picture_path}"

def extract_channel_details(channel_data):
    """從頻道數據中提取詳細信息（適配新 JSON 結構）"""
    try:
        if not channel_data:
            print("❌ 頻道數據為空")
            return None
            
        if not isinstance(channel_data, dict):
            print(f"❌ 頻道數據類型錯誤: {type(channel_data)}")
            return None
            
        page_props = channel_data.get('pageProps', {})
        if not page_props:
            print("❌ pageProps 為空")
            return None
            
        channel = page_props.get('channel', {})
        if not channel:
            print("❌ channel 數據為空")
            return None
            
        introduction = page_props.get('introduction', {})
        
        # ----- 新結構字段 -----
        content_type = channel.get('contentType', '')
        if content_type in ['vod-channel', 'playout-channel']:
            channel_type = 'vod'
        else:
            channel_type = 'live'
        
        channel_name = channel.get('title', '未知頻道')
        
        # 分組（stationCategories）
        station_categories = channel.get('stationCategories', [])
        channel_group = station_categories[0].get('name', '默認分組') if station_categories else '默認分組'
        
        # 圖片（優先 channel.picture，若無則用 introduction.image）
        picture = channel.get('picture', '')
        channel_picture = normalize_picture_url(picture)
        if not channel_picture and introduction:
            intro_img = introduction.get('image', '')
            channel_picture = normalize_picture_url(intro_img)
        
        details = {
            'type': channel_type,
            'name': channel_name,
            'group': channel_group,
            'picture': channel_picture,
            'raw_data': channel_data
        }
        
        # 如果是點播類，獲取節目清單（新字段）
        if channel_type == 'vod':
            vod_schedule = channel.get('vodChannelSchedule', {})
            programs = vod_schedule.get('programs', []) if vod_schedule else []
            details['programs'] = programs
        
        return details
        
    except Exception as e:
        print(f"❌ 提取頻道詳細信息失敗: {str(e)}")
        import traceback
        print(f"❌ 詳細錯誤信息: {traceback.format_exc()}")
        return None

def save_channel_json(channel_id, channel_data, json_dir):
    """將頻道JSON資料儲存為檔案"""
    try:
        json_file = json_dir / f"{channel_id}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(channel_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"❌ 儲存頻道 {channel_id} JSON檔案失敗: {e}")
        return False

def create_channel_zip(json_dir, output_dir):
    """將所有頻道JSON檔案壓縮成ZIP"""
    try:
        zip_path = output_dir / "ofiii_channel.zip"
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for json_file in json_dir.glob("*.json"):
                zipf.write(json_file, json_file.name)
        
        print(f"✅ 成功建立壓縮檔: {zip_path}")
        return True
    except Exception as e:
        print(f"❌ 建立壓縮檔失敗: {e}")
        return False

def cleanup_json_files(json_dir):
    """清理JSON暫存檔案"""
    try:
        deleted_count = 0
        for json_file in json_dir.glob("*.json"):
            json_file.unlink()
            deleted_count += 1
        
        try:
            json_dir.rmdir()
        except OSError:
            pass
            
        print(f"🧹 已清理 {deleted_count} 個暫存JSON檔案")
        return deleted_count
    except Exception as e:
        print(f"❌ 清理JSON檔案失敗: {e}")
        return 0

def get_display_name(title, subtitle):
    """根據標題和副標題生成顯示名稱"""
    if title and subtitle:
        return f"{title}-{subtitle}"
    elif title and not subtitle:
        return title
    elif not title and subtitle:
        return subtitle
    else:
        return "未知節目"

def generate_m3u_vod_content(channel_id, channel_details, group_name):
    """生成 M3U 選集類內容（新結構：使用 assetId）"""
    content = ""
    programs = channel_details.get('programs', [])
    
    for program in programs:
        asset_id = program.get('assetId')          # 新字段
        title = program.get('title', '')
        subtitle = program.get('subtitle', '')
        
        if not asset_id:
            continue
        
        program_name = get_display_name(title, subtitle)
        
        # 節目圖片（如果沒有，使用頻道圖片）
        program_picture = channel_details.get('picture', '')
        
        content += (f'#EXTINF:-1 tvg-id="{program_name}" tvg-name="{program_name}" '
                   f'tvg-logo="{program_picture}" group-title="{group_name}",{program_name}\n'
                   f'http://localhost:5000/{channel_id}/index.m3u8?episode_id={asset_id}\n')
    
    return content

def generate_txt_vod_by_name(channels_by_name):
    """按頻道名稱生成 TXT 選集類內容（新結構）"""
    content = ""
    
    for channel_name, programs in sorted(channels_by_name.items()):
        content += f"{channel_name},#genre#\n"
        for program_info in programs:
            program_name = program_info.get("program_name", "未知節目")
            channel_id = program_info.get("channel_id")
            asset_id = program_info.get("asset_id")
            
            if asset_id:  # 點播節目
                content += f"{program_name},http://localhost:5000/{channel_id}/index.m3u8?episode_id={asset_id}\n"
            else:  # 直播頻道
                content += f"{program_name},http://localhost:5000/{channel_id}/index.m3u8\n"
    
    return content

def generate_m3u_content(channel_data, channel_id, asset_seen):
    """生成M3U內容（新結構）"""
    m3u_lines = []
    added_programs = 0
    duplicate_assets = 0
    
    try:
        channel_details = extract_channel_details(channel_data)
        if not channel_details:
            print(f"⚠️  頻道 {channel_id} 沒有有效的頻道資訊")
            return m3u_lines, added_programs, duplicate_assets
        
        name = channel_details.get('name', 'Unknown')
        picture = channel_details.get('picture', '')
        channel_type = channel_details.get('type', 'live')
        group = channel_details.get('group', '默認分組')
        
        print(f"📺 處理頻道: {name} ({channel_id}) - 類型: {channel_type} - 分組: {group}")
        
        if channel_type == 'vod':
            programs = channel_details.get('programs', [])
            
            if not programs:
                print(f"ℹ️  頻道 {name} 沒有節目列表，跳過")
                return m3u_lines, added_programs, duplicate_assets
            
            vod_content = generate_m3u_vod_content(channel_id, channel_details, group)
            if vod_content:
                vod_lines = vod_content.strip().split('\n')
                m3u_lines.extend(vod_lines)
                added_programs = len([line for line in vod_lines if line.startswith('#EXTINF:')])
                print(f"✅ 添加 {name} - {added_programs} 個節目")
            else:
                print(f"⚠️ 頻道 {name} 沒有可用的點播內容")
            
        else:
            # 直播頻道
            display_name = name
            extinf_line = (f'#EXTINF:-1 tvg-id="{name}" tvg-name="{name}" '
                          f'tvg-logo="{picture}" group-title="{group}",{display_name}')
            url_line = f'http://localhost:5000/{channel_id}/index.m3u8'
            
            m3u_lines.append(extinf_line)
            m3u_lines.append(url_line)
            added_programs = 1
            
            print(f"✅ 添加直播頻道: {name}")
            
    except Exception as e:
        print(f"❌ 處理頻道 {channel_id} 資料時發生錯誤: {e}")
        import traceback
        print(f"❌ 詳細錯誤信息: {traceback.format_exc()}")
    
    return m3u_lines, added_programs, duplicate_assets

def generate_txt_content(channel_data, channel_id, asset_seen, channels_by_name):
    """生成TXT內容，按頻道名稱組織（新結構）"""
    added_programs = 0
    duplicate_assets = 0
    
    try:
        channel_details = extract_channel_details(channel_data)
        if not channel_details:
            return added_programs, duplicate_assets
        
        name = channel_details.get('name', 'Unknown')
        channel_type = channel_details.get('type', 'live')
        
        if name not in channels_by_name:
            channels_by_name[name] = []
        
        if channel_type == 'vod':
            programs = channel_details.get('programs', [])
            
            for program in programs:
                asset_id = program.get('assetId')   # 新字段
                title = program.get('title', '')
                subtitle = program.get('subtitle', '')
                
                if not asset_id:
                    continue
                    
                if asset_id in asset_seen:
                    duplicate_assets += 1
                    continue
                    
                asset_seen.add(asset_id)
                program_name = get_display_name(title, subtitle)
                
                channels_by_name[name].append({
                    "channel_id": channel_id,
                    "program_name": program_name,
                    "asset_id": asset_id
                })
                added_programs += 1
                
        else:
            # 直播頻道
            display_name = name
            channels_by_name[name].append({
                "channel_id": channel_id,
                "program_name": display_name,
                "asset_id": None
            })
            added_programs += 1
            
    except Exception as e:
        print(f"❌ 處理頻道 {channel_id} TXT資料時發生錯誤: {e}")
    
    return added_programs, duplicate_assets

def get_channel_info(channel_data, channel_id):
    """獲取頻道基本資訊（新結構）"""
    try:
        channel_details = extract_channel_details(channel_data)
        if not channel_details:
            return None
        
        name = channel_details.get('name', 'Unknown')
        picture = channel_details.get('picture', '')
        group = channel_details.get('group', '默認分組')
        channel_type = channel_details.get('type', 'live')
        
        return {
            'name': name,
            'picture': picture,
            'group_title': group,
            'content_id': channel_id,
            'category': group,
            'type': channel_type
        }
    except Exception as e:
        print(f"❌ 獲取頻道 {channel_id} 資訊時發生錯誤: {e}")
        return None

def ensure_output_dir():
    """確保輸出目錄存在"""
    output_dir = Path('../output')
    output_dir.mkdir(exist_ok=True)
    return output_dir

def ensure_json_dir(output_dir):
    """確保JSON暫存目錄存在"""
    json_dir = output_dir / 'channel_json'
    json_dir.mkdir(exist_ok=True)
    return json_dir

def remove_duplicate_channels(channel_data):
    """去除重複的頻道資料（保持原有邏輯）"""
    unique_channels = {}
    duplicates_removed = 0
    
    for channel_id, channel_info in channel_data.items():
        channel_name = channel_info[0]
        
        if channel_name not in unique_channels:
            unique_channels[channel_name] = (channel_id, channel_info)
        else:
            duplicates_removed += 1
            print(f"🔄 移除重複頻道: {channel_name} (ID: {channel_id})")
    
    result = {channel_id: channel_info for channel_id, channel_info in unique_channels.values()}
    
    if duplicates_removed > 0:
        print(f"🔄 總共移除了 {duplicates_removed} 個重複頻道")
    
    return result

def generate_playout_channel_json(channel_ids):
    """生成ofiii_playout-channel.json檔案"""
    playout_data = {}
    for channel_id in channel_ids:
        playout_data[channel_id] = ["ofiii", channel_id]
    return playout_data

def generate_ofiii_channel_ids(start=13, end=255):
    """動態生成ofiii頻道ID列表"""
    return [f"ofiii{i}" for i in range(start, end + 1)]

async def process_channel(channel_id, json_dir, asset_seen, channels_by_name, m3u_content, exclude_from_m3u_txt):
    """處理單個頻道 - 異步版本"""
    print(f"📋 處理頻道: {channel_id}")
    
    build_id = await get_build_id()
    if not build_id:
        print(f"❌ 無法獲取 build_id，跳過頻道 {channel_id}")
        return 0, 0, 0, 0, None
    
    channel_json = await get_channel_data(channel_id, build_id)
    
    saved_json = 0
    added_programs = 0
    duplicate_assets = 0
    channel_info = None
    
    if channel_json:
        if save_channel_json(channel_id, channel_json, json_dir):
            saved_json = 1
            print(f"💾 已儲存 {channel_id}.json")
        
        channel_info = get_channel_info(channel_json, channel_id)
        
        if channel_id not in exclude_from_m3u_txt:
            channel_lines, programs_added, assets_duplicated = generate_m3u_content(channel_json, channel_id, asset_seen)
            added_programs = programs_added
            duplicate_assets = assets_duplicated
            
            if channel_lines:
                m3u_content.extend(channel_lines)
                print(f"✅ 成功添加頻道 {channel_id} 到 M3U ({added_programs} 個節目)")
            else:
                print(f"⚠️ 跳過頻道 {channel_id} (無有效節目)")
                
            txt_programs, txt_duplicates = generate_txt_content(channel_json, channel_id, asset_seen.copy(), channels_by_name)
        else:
            print(f"🚫 頻道 {channel_id} 從 M3U/TXT 中排除，但仍儲存 JSON 數據")
        
    else:
        print(f"❌ 無法獲取頻道 {channel_id} 資料")
    
    return saved_json, added_programs, duplicate_assets, 1 if channel_json else 0, channel_info

async def main():
    # 確保輸出目錄存在
    output_dir = ensure_output_dir()
    json_dir = ensure_json_dir(output_dir)
    m3u_file = output_dir / 'ofiii.m3u.txt'
    txt_file = output_dir / 'ofiii.txt.txt'
    channel_json_file = output_dir / 'ofiii_channel.json'
    playout_channel_json_file = output_dir / 'ofiii_playout-channel.json'
    
    # 動態生成ofiii頻道ID列表（13-255）
    ofiii_channels = generate_ofiii_channel_ids(13, 255)
    
    # 要從 M3U 和 TXT 中排除的頻道ID列表
    exclude_from_m3u_txt = [
        "setnews",
        "4gtv-4gtv009",
        "4gtv-4gtv040",
        "4gtv-4gtv041",
        "4gtv-4gtv052",
        "4gtv-4gtv074",
        "4gtv-4gtv084",
        "4gtv-4gtv085",
        "4gtv-4gtv076",
        "4gtv-4gtv102",
        "4gtv-4gtv103",
        "4gtv-4gtv104",
        "4gtv-4gtv156",
        "4gtv-4gtv158",
        "litv-ftv16",
        "litv-ftv17",
        "litv-xinchuang01",
        "litv-xinchuang02",
        "litv-xinchuang03",
        "litv-xinchuang11",
        "litv-xinchuang12",
        "litv-longturn14",
        "litv-xinchuang18",
        "litv-xinchuang19",
        "litv-xinchuang20",
        "litv-xinchuang21",
        "litv-xinchuang22",
        "iNEWS",
        "daystar"
    ]
    
    # 所有頻道ID列表
    all_channel_ids = ofiii_channels + [
        "setnews",
        "4gtv-4gtv009",
        "4gtv-4gtv040",
        "4gtv-4gtv041",
        "4gtv-4gtv052",
        "4gtv-4gtv074",
        "4gtv-4gtv084",
        "4gtv-4gtv085",
        "4gtv-4gtv076",
        "4gtv-4gtv102",
        "4gtv-4gtv103",
        "4gtv-4gtv104",
        "4gtv-4gtv156",
        "4gtv-4gtv158",
        "litv-ftv16",
        "litv-ftv17",
        "litv-xinchuang01",
        "litv-xinchuang02",
        "litv-xinchuang03",
        "litv-xinchuang11",
        "litv-xinchuang12",
        "litv-longturn14",
        "litv-xinchuang18",
        "litv-xinchuang19",
        "litv-xinchuang20",
        "litv-xinchuang21",
        "litv-xinchuang22",
        "iNEWS",
        "daystar"
    ]
    
    m3u_content = ['#EXTM3U']
    channels_by_name = {}
    channel_data = {}
    asset_seen = set()
    
    print("🚀 開始獲取頻道資料...")
    print(f"📊 總共 {len(all_channel_ids)} 個頻道需要處理")
    print(f"🚫 從 M3U/TXT 中排除 {len(exclude_from_m3u_txt)} 個頻道: {', '.join(exclude_from_m3u_txt)}")
    
    successful_channels = 0
    failed_channels = 0
    total_programs = 0
    total_duplicate_assets = 0
    saved_json_files = 0
    
    semaphore = asyncio.Semaphore(5)
    
    async def process_with_semaphore(channel_id):
        async with semaphore:
            return await process_channel(channel_id, json_dir, asset_seen, channels_by_name, m3u_content, exclude_from_m3u_txt)
    
    tasks = [process_with_semaphore(channel_id) for channel_id in all_channel_ids]
    
    print(f"\n🔄 開始處理所有頻道...")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for result in results:
        if isinstance(result, Exception):
            failed_channels += 1
            print(f"❌ 處理頻道時發生異常: {result}")
            continue
            
        saved_json, added_programs, duplicate_assets, success, channel_info = result
        
        saved_json_files += saved_json
        total_programs += added_programs
        total_duplicate_assets += duplicate_assets
        
        if success:
            successful_channels += 1
        else:
            failed_channels += 1
        
        if channel_info:
            channel_data[channel_info['content_id']] = [
                channel_info['name'],
                channel_info['picture'],
                channel_info['group_title']
            ]
    
    print("\n🔄 生成 TXT 檔案內容...")
    txt_content = generate_txt_vod_by_name(channels_by_name)
    
    print("\n🔄 檢查並移除重複頻道...")
    unique_channel_data = remove_duplicate_channels(channel_data)
    
    print("\n🔄 生成ofiii_playout-channel.json...")
    playout_channel_data = generate_playout_channel_json(all_channel_ids)
    
    with open(m3u_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(m3u_content))
    
    with open(txt_file, 'w', encoding='utf-8') as f:
        f.write(txt_content)
    
    with open(channel_json_file, 'w', encoding='utf-8') as f:
        json.dump(unique_channel_data, f, ensure_ascii=False, indent=2)
    
    with open(playout_channel_json_file, 'w', encoding='utf-8') as f:
        json.dump(playout_channel_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n🗜️ 建立頻道JSON壓縮檔...")
    if create_channel_zip(json_dir, output_dir):
        print(f"✅ 成功建立 ofiii_channel.zip，包含 {saved_json_files} 個頻道JSON檔案")
    
    print(f"\n🧹 清理暫存檔案...")
    cleaned_files = cleanup_json_files(json_dir)
    
    print(f"\n🎉 檔案生成完成！")
    print(f"📊 統計資訊:")
    print(f"   ✅ 成功處理: {successful_channels} 個頻道")
    print(f"   ❌ 處理失敗: {failed_channels} 個頻道")
    print(f"   🚫 從 M3U/TXT 中排除: {len(exclude_from_m3u_txt)} 個頻道")
    print(f"   📺 M3U/TXT 中節目數: {total_programs} 個節目")
    print(f"   🔄 唯一頻道數: {len(unique_channel_data)} 個頻道")
    print(f"   🔄 跳過重複asset_id: {total_duplicate_assets} 個")
    print(f"   💾 儲存JSON檔案: {saved_json_files} 個")
    print(f"   🧹 清理暫存檔案: {cleaned_files} 個")
    print(f"   📁 輸出檔案:")
    print(f"      - {m3u_file} (排除指定頻道)")
    print(f"      - {txt_file} (排除指定頻道)")
    print(f"      - {channel_json_file} (包含所有頻道)")
    print(f"      - {playout_channel_json_file} (包含所有頻道)")
    print(f"      - {output_dir / 'ofiii_channel.zip'} (包含所有頻道)")

if __name__ == "__main__":
    asyncio.run(main())
