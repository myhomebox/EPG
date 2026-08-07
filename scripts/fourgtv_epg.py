import os
import sys
import json
import asyncio
import random
import ssl
from datetime import datetime
from xml.etree import ElementTree as ET

import aiohttp
import pytz
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

CHANNEL_API_URL = "https://api2.4gtv.tv/Channel/GetAllChannel/pc/L"
LOCAL_CHANNEL_FILE = os.path.join(OUTPUT_DIR, "fourgtv.json")
PROG_URL_TEMPLATE = "https://www.4gtv.tv/ProgList/{channel_id}.txt"
MAX_CONCURRENT_REQUESTS = 5

# 不抓取這些頻道ID
SKIP_CHANNEL_IDS = {
    "4gtv-4gtv038",
}

def create_ssl_context():
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = True
    return ctx

# 解析頻道數據（支持 API 或本地 JSON），返回簡潔頻道列表
def parse_channel_data(data):
    if isinstance(data, dict):
        items = data.get("Data", [data])
    elif isinstance(data, list):
        items = data
    else:
        return []

    channels = []
    for item in items:
        ch_id = item.get("fs4GTV_ID")
        if not ch_id or ch_id in SKIP_CHANNEL_IDS:
            continue
        name = item.get("fsNAME")
        if not name:
            continue
        channels.append({
            "channelName": name,
            "channelId": ch_id,
            "logo": item.get("fsLOGO_MOBILE", ""),
            "description": item.get("fsDESCRIPTION", "")
        })
    return channels

async def fetch_channels_from_api(session):
    """
    從 4GTV API 取得所有頻道，過濾不抓取的 ID，並依 fsNAME 去重。
    成功時回傳去重後的頻道列表，失敗則回傳 None。
    同時會將去重後的資料寫入本地的 fourgtv.json。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        async with session.get(CHANNEL_API_URL, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.error(f"API 返回狀態碼 {resp.status}")
                return None
            text = await resp.text()
            data = json.loads(text)
            if not data.get("Success", False):
                logger.error("API 返回 Success=false")
                return None

            all_items = data["Data"]

            # 第一步：過濾要跳過的頻道 ID
            filtered_items = [item for item in all_items
                              if item.get("fs4GTV_ID") not in SKIP_CHANNEL_IDS]

            # 第二步：根據 fsNAME 去重（保留先出現的，跳過缺少 fsNAME 的項目）
            seen_names = set()
            deduped_items = []
            for item in filtered_items:
                name = item.get("fsNAME")
                if name and name not in seen_names:
                    seen_names.add(name)
                    deduped_items.append(item)

            # 將去重後的清單寫入本地 fourgtv.json（結構與原 API 一致）
            try:
                with open(LOCAL_CHANNEL_FILE, "w", encoding="utf-8") as f:
                    json.dump({"Success": True, "Data": deduped_items},
                              f, ensure_ascii=False, indent=2)
                logger.success(f"已更新本地頻道檔案，保存 {len(deduped_items)} 個頻道")
            except Exception as e:
                logger.error(f"寫入本地頻道檔案失敗: {e}")

            # 解析為簡潔的頻道列表
            channels = parse_channel_data({"Data": deduped_items})
            if not channels:
                logger.warning("過濾後頻道列表為空")
                return None

            logger.success(
                f"從 API 獲取到 {len(channels)} 個頻道"
                f"（原始 {len(all_items)}，跳過 ID {len(all_items) - len(filtered_items)}，"
                f"名稱去重後 {len(deduped_items)}）"
            )
            return channels

    except Exception as e:
        logger.error(f"通過 API 獲取頻道列表失敗: {e}")
        return None

def load_channels_from_local():
    if not os.path.exists(LOCAL_CHANNEL_FILE):
        logger.error(f"本地頻道檔案不存在: {LOCAL_CHANNEL_FILE}")
        return None
    try:
        with open(LOCAL_CHANNEL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        channels = parse_channel_data(data)
        if channels:
            logger.success(f"從本地檔案讀取到 {len(channels)} 個頻道")
        else:
            logger.error("本地檔案中沒有有效頻道")
        return channels or None
    except Exception as e:
        logger.error(f"讀取本地頻道檔案失敗: {e}")
        return None

async def fetch_single_program(session, sem, channel, ssl_context, retries=3):
    ch_id = channel["channelId"]
    ch_name = channel["channelName"]
    url = PROG_URL_TEMPLATE.format(channel_id=ch_id)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.4gtv.tv/",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.4gtv.tv",
    }

    async with sem:
        await asyncio.sleep(random.uniform(0.1, 0.5))
        for attempt in range(1, retries + 1):
            try:
                async with session.get(url, headers=headers, ssl=ssl_context,
                                       timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        raise aiohttp.ClientError(f"狀態碼 {resp.status}")
                    text = await resp.text()
                    if not text.strip().startswith(('[', '{')):
                        raise ValueError("返回的不是有效 JSON")
                    data = json.loads(text)
                    return parse_programs(data, ch_id, ch_name)
            except Exception as e:
                logger.warning(f"{ch_name} 第 {attempt} 次嘗試失敗: {e}")
                if attempt < retries:
                    await asyncio.sleep(1 * attempt)
                else:
                    logger.error(f"{ch_name} 最終獲取失敗")
                    return None

def parse_programs(raw_data, channel_id, channel_name):
    programs = []
    tz = pytz.timezone("Asia/Taipei")
    for item in raw_data:
        start = tz.localize(datetime.strptime(
            f"{item['sdate']} {item['stime']}", "%Y-%m-%d %H:%M:%S"))
        end = tz.localize(datetime.strptime(
            f"{item['edate']} {item['etime']}", "%Y-%m-%d %H:%M:%S"))
        programs.append({
            "channelId": channel_id,
            "channelName": channel_name,
            "programName": item.get("title", ""),
            "description": item.get("content", ""),
            "start": start,
            "end": end
        })
    return programs

async def fetch_all_programs(channels):
    ssl_ctx = create_ssl_context()
    sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    connector = aiohttp.TCPConnector(ssl=ssl_ctx, limit=MAX_CONCURRENT_REQUESTS * 2)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_single_program(session, sem, ch, ssl_ctx) for ch in channels]
        results = await asyncio.gather(*tasks)
    programs = []
    for ch, prog_list in zip(channels, results):
        if prog_list:
            programs.extend(prog_list)
        else:
            logger.warning(f"未能獲取 {ch['channelName']} 的節目單")
    return programs

def generate_xml(channels, programs, filename):
    tv = ET.Element("tv")
    tv.set("source-info-name", "4gtv EPG")
    tv.set("source-info-url", "https://www.4gtv.tv")
    tv.set("generator-info-name", "4gtv EPG Generator")

    prog_by_ch = {}
    for p in programs:
        ch = p["channelName"]
        prog_by_ch.setdefault(ch, []).append(p)

    for ch in channels:
        ch_name = ch["channelName"]
        ch_elem = ET.SubElement(tv, "channel", id=ch_name)
        dn = ET.SubElement(ch_elem, "display-name", lang="zh")
        dn.text = ch_name
        if ch.get("logo"):
            icon = ET.SubElement(ch_elem, "icon")
            icon.set("src", ch["logo"])
        if ch.get("description"):
            desc = ET.SubElement(ch_elem, "desc", lang="zh")
            desc.text = ch["description"]

        if ch_name in prog_by_ch:
            sorted_progs = sorted(prog_by_ch[ch_name], key=lambda x: x["start"])
            for prog in sorted_progs:
                start_str = prog["start"].strftime("%Y%m%d%H%M%S +0800")
                end_str = prog["end"].strftime("%Y%m%d%H%M%S +0800")
                pr_elem = ET.SubElement(tv, "programme",
                                        start=start_str,
                                        stop=end_str,
                                        channel=ch_name)
                title = ET.SubElement(pr_elem, "title", lang="zh")
                title.text = prog["programName"]
                if prog.get("description"):
                    desc = ET.SubElement(pr_elem, "desc", lang="zh")
                    desc.text = prog["description"]

    tree = ET.ElementTree(tv)
    tree.write(filename, encoding="utf-8", xml_declaration=True)
    logger.info(f"電子節目單已生成: {filename}")

async def main_async():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    log_file = os.path.join(OUTPUT_DIR, "epg_generator.log")
    logger.add(log_file, rotation="1 day", retention="7 days", encoding="utf-8",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

    logger.info("=" * 50)
    logger.info("開始生成四季線上電子節目單")
    logger.info(f"輸出目錄: {OUTPUT_DIR}")

    # 1. 優先 API，失敗回退本地
    channels = None
    async with aiohttp.ClientSession() as session:
        try:
            channels = await fetch_channels_from_api(session)
        except Exception:
            pass
    if not channels:
        logger.warning("API 獲取失敗，嘗試讀取本地檔案")
        channels = load_channels_from_local()
    if not channels:
        logger.critical("無法獲取任何頻道信息，流程終止")
        sys.exit(1)

    logger.info(f"成功加載 {len(channels)} 個頻道")

    # 2. 併發抓取節目表
    programs = await fetch_all_programs(channels)
    logger.info(f"共獲取 {len(programs)} 個節目")

    # 3. 生成 XML
    xml_file = os.path.join(OUTPUT_DIR, "4g.xml")
    generate_xml(channels, programs, xml_file)
    logger.success("EPG 生成完成")

if __name__ == "__main__":
    asyncio.run(main_async())
