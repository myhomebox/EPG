import cloudscraper
import base64
import uuid
import datetime
import hashlib
import time
import json
import sys
import re
import warnings
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import logging

# 关闭所有警告和日志
warnings.filterwarnings("ignore")

# 配置日志
logging.basicConfig(level=logging.ERROR)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
log.disabled = True

# 默认配置
DEFAULT_USER_AGENT = "%E5%9B%9B%E5%AD%A3%E7%B7%9A%E4%B8%8A/4 CFNetwork/3826.500.131 Darwin/24.5.0"
DEFAULT_TIMEOUT = 30
CHANNEL_DELAY = 1
MAX_RETRIES = 1
DEFAULT_WORKERS = 1
DEFAULT_HEADER_KEY = "7F3DD6981A72707B12A8C0CC80A3C96B75B9057AD55F1AE1"

# 默认账号（可被环境变量覆盖）
DEFAULT_USER = os.environ.get('GTV_USER', '')
DEFAULT_PASS = os.environ.get('GTV_PASS', '')

# 代理设置（从环境变量读取）
HTTP_PROXY = os.environ.get('http_proxy', '') or os.environ.get('HTTP_PROXY', '')
HTTPS_PROXY = os.environ.get('https_proxy', '') or os.environ.get('HTTPS_PROXY', '')
SOCKS_PROXY = os.environ.get('SOCKS_PROXY', '') or os.environ.get('SOCKS5_PROXY', '') or os.environ.get('ALL_PROXY', '')

# 内存缓存
cache_play_urls = {}
CACHE_EXPIRATION_TIME = 86400
thread_local = threading.local()


def is_github_actions():
    return os.environ.get('GITHUB_ACTIONS') == 'true'


def get_proxies(announce=True):
    proxies = {}

    if HTTP_PROXY:
        proxies['http'] = HTTP_PROXY
        if not HTTPS_PROXY:
            proxies['https'] = HTTP_PROXY

    if HTTPS_PROXY:
        proxies['https'] = HTTPS_PROXY
        if not HTTP_PROXY:
            proxies['http'] = HTTPS_PROXY

    if SOCKS_PROXY:
        parsed = urlparse(SOCKS_PROXY)
        if parsed.scheme in ('socks5', 'socks5h'):
            proxies['http'] = SOCKS_PROXY
            proxies['https'] = SOCKS_PROXY
        else:
            if announce:
                print(f"⚠️ SOCKS_PROXY 变量包含非 socks 协议: {SOCKS_PROXY}，已忽略")

    if announce:
        if proxies:
            proxy_types = set()
            for p in proxies.values():
                scheme = urlparse(p).scheme
                proxy_types.add(scheme)
            if is_github_actions():
                print(f"🔌 GitHub Actions 环境中使用代理: {proxies}")
            else:
                print(f"🔌 使用代理 ({', '.join(proxy_types)}): {proxies}")
        else:
            if is_github_actions():
                print("🔌 GitHub Actions 环境中未设置代理，使用直接连接")
            else:
                print("🔌 未设置代理，使用直接连接")

    return proxies if proxies else None


def test_proxy_connection(scraper, timeout=10):
    try:
        test_url = "https://httpbin.org/ip"
        response = scraper.get(test_url, timeout=timeout)
        if response.status_code == 200:
            print("✅ 代理连接测试成功")
            return True
        else:
            print(f"⚠️ 代理连接测试失败，状态码: {response.status_code}")
            return False
    except Exception as e:
        print(f"⚠️ 代理连接测试失败: {e}")
        return False


def create_scraper_with_proxy(ua, announce=True, test_proxy=True):
    scraper = cloudscraper.create_scraper()
    scraper.headers.update({"User-Agent": ua})

    proxies = get_proxies(announce=announce)
    if proxies:
        try:
            for proxy_url in proxies.values():
                if proxy_url.startswith('socks'):
                    try:
                        import socks  # noqa
                    except ImportError:
                        print("⚠️ 使用 SOCKS 代理需要安装 PySocks，请执行: pip install pysocks")
                        proxies = None
                        break
            if proxies:
                scraper.proxies.update(proxies)

                if test_proxy and not is_github_actions():
                    if not test_proxy_connection(scraper):
                        print("⚠️ 代理连接测试失败，将使用直接连接")
                        scraper.proxies.clear()
        except Exception as e:
            print(f"⚠️ 代理设置失败: {e}，将使用直接连接")
            scraper.proxies.clear()

    return scraper


def get_thread_scraper(ua):
    scraper = getattr(thread_local, 'scraper', None)
    if scraper is None:
        scraper = create_scraper_with_proxy(ua, announce=False, test_proxy=False)
        thread_local.scraper = scraper
    return scraper


def generate_uuid(user):
    today = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    name = f"{user}-{today}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name)).upper()


def generate_4gtv_auth():
    today = datetime.datetime.utcnow().strftime('%Y%m%d')
    sha512 = hashlib.sha512((today + DEFAULT_HEADER_KEY).encode('utf-8')).digest()
    return base64.b64encode(sha512).decode('ascii')

def sign_in_4gtv(user, password, fsenc_key, auth_val, ua, timeout, scraper=None):
    url = "https://api2.4gtv.tv/AppAccount/SignIn"
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "fsenc_key": fsenc_key,
        "fsdevice": "iOS",
        "fsversion": "3.2.8",
        "4gtv_auth": auth_val,
        "User-Agent": ua
    }
    payload = {"fsUSER": user, "fsPASSWORD": password, "fsENC_KEY": fsenc_key}
    scraper = scraper or create_scraper_with_proxy(ua)

    resp = scraper.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data.get("Data") if data.get("Success") else None


def get_all_channels(ua, timeout, scraper=None, include_fast_live=False):
    """获取全部频道，并根据开关决定是否包含 fs4GTV_ID 以 fast-live 开头的频道。"""
    all_channels = []

    print("📡 正在获取全部频道...")
    url = "https://api2.4gtv.tv/Channel/GetAllChannel2/mobile"
    headers = {
        "accept": "*/*",
        "origin": "https://www.4gtv.tv",
        "referer": "https://www.4gtv.tv/",
        "User-Agent": ua
    }
    active_scraper = scraper or create_scraper_with_proxy(ua)

    try:
        resp = active_scraper.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("Success"):
            print(f"   ❌ 获取频道列表失败: {data.get('ErrMessage')}")
            return all_channels

        channels = data.get("Data", [])
        for channel in channels:
            channel_id = str(channel.get("fs4GTV_ID", ""))
            channel_name = channel.get("fsNAME", "未知")

            # 判定 fs4GTV_ID 是否以 fast-live 开头
            if channel_id.lower().startswith("fast-live") and not include_fast_live:
                print(f"   ⏭️  跳过 fast-live 频道: {channel_name} ({channel_id})")
                continue

            # 若是 fast-live 频道，统一分类名并清理频道名称
            if channel_id.startswith("fast-live"):
                channel_type = "FastTV飛速看"
                channel_name = channel.get("fsNAME", "")
                channel_name = re.sub(r"[-－]?FastTV[飛速看]*", "", channel_name)
                channel_name = re.sub(r"[-－]?飛速看", "", channel_name)
                channel_name = re.sub(r"^[-－\s]+|[-－\s]+$", "", channel_name)
                channel["fsNAME"] = channel_name

            all_channels.append(channel)
            print(f"   ✅ 添加频道: {channel_name} ({channel_id})")

    except Exception as e:
        print(f"   ❌ 获取频道列表失败: {e}")

    return all_channels


def get_4gtv_channel_url_with_retry(channel_id, fnCHANNEL_ID, fsVALUE, fsenc_key, auth_val, ua, timeout, max_retries=MAX_RETRIES, scraper=None):
    max_retries = max(1, int(max_retries))

    current_time = time.time()
    cache_key = f"{channel_id}_{fnCHANNEL_ID}"
    if cache_key in cache_play_urls:
        cache_time, url = cache_play_urls[cache_key]
        if current_time - cache_time < CACHE_EXPIRATION_TIME:
            return url

    for attempt in range(max_retries):
        try:
            headers = {
                "content-type": "application/json; charset=utf-8",
                "fsenc_key": fsenc_key,
                "accept": "*/*",
                "fsdevice": "iOS",
                "fsvalue": "",
                "fsversion": "3.2.8",
                "4gtv_auth": auth_val,
                "Referer": "https://www.4gtv.tv/",
                "User-Agent": ua
            }
            payload = {
                "fnCHANNEL_ID": fnCHANNEL_ID,
                "clsAPP_IDENTITY_VALIDATE_ARUS": {"fsVALUE": fsVALUE, "fsENC_KEY": fsenc_key},
                "fsASSET_ID": channel_id,
                "fsDEVICE_TYPE": "mobile"
            }
            active_scraper = scraper or get_thread_scraper(ua)

            resp = active_scraper.post('https://api2.4gtv.tv/App/GetChannelUrl2', headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            print(f"频道 {channel_id} 响应: {json.dumps(data, ensure_ascii=False)[:200]}")
            response_data = data.get('Data', {}) if isinstance(data, dict) else {}
            raw_urls = response_data.get('flstURLs', []) if isinstance(response_data, dict) else []
            urls = raw_urls if isinstance(raw_urls, list) else []
            if isinstance(data, dict) and data.get('Success') and urls:
                url = urls[1] if len(urls) > 1 else urls[0]
                cache_play_urls[cache_key] = (current_time, url)
                return url
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"⚠️ 获取频道 {channel_id} 失败，正在重试 ({attempt + 1}/{max_retries})")
                time.sleep(2)
            else:
                print(f"❌ 获取频道 {channel_id} 失败，已达到最大重试次数")
                return None
    return None


def get_highest_bitrate_url(master_url, channel_id="", log=True):
    """根据频道 ID 前缀尝试获取更高质量的 URL。"""
    if master_url.startswith("https://4gtvfree-mozai.4gtv.tv") and 'index.m3u8' in master_url:
        new_filename = None

        if channel_id.startswith("media-live"):
            new_filename = "1080p_35.m3u8"
        elif channel_id.startswith("4gtv-live") or channel_id.startswith("fast-live"):
            new_filename = "1080.m3u8"

        if new_filename:
            if log:
                print(f"   📶 尝试获取高质量URL ({new_filename})...")
            return master_url.replace('index.m3u8', new_filename)

    if log:
        print(f"   📶 使用原始URL（非 4gtvfree-mozai 域名或未匹配频道前缀）")
    return master_url


def print_progress_bar(iteration, total, prefix='', suffix='', decimals=1, length=50, fill='█', print_end="\r"):
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}', end=print_end)
    if iteration == total:
        print()


def get_channel_metadata(channel):
    """提取频道元数据，并统一处理频道分类。"""
    channel_id = channel.get("fs4GTV_ID", "")
    channel_name = channel.get("fsNAME", "")
    channel_type = channel.get("fsTYPE_NAME", "其他")
    channel_logo = channel.get("fsLOGO_MOBILE", "")
    fnCHANNEL_ID = channel.get("fnID", "")

    if channel_type:
        channel_type = channel_type.split(',')[0]

    if channel_id.startswith('fast-live'):
        channel_type = "FastTV飛速看"

    return channel_id, channel_name, channel_type, channel_logo, fnCHANNEL_ID


def build_channel_playlist_entry(channel, fsVALUE, fsenc_key, auth_val, ua, timeout, retries, delay=0, scraper=None):
    """获取单个频道 URL 并组装 M3U 条目。"""
    channel_id, channel_name, channel_type, channel_logo, fnCHANNEL_ID = get_channel_metadata(channel)

    if delay > 0:
        time.sleep(delay)

    stream_url = get_4gtv_channel_url_with_retry(
        channel_id,
        fnCHANNEL_ID,
        fsVALUE,
        fsenc_key,
        auth_val,
        ua,
        timeout,
        retries,
        scraper=scraper
    )
    if not stream_url:
        return False, channel_name, channel_type, "", "无法获取URL"

    highest_url = get_highest_bitrate_url(stream_url, channel_id=channel_id, log=False)
    entry = (
        f'#EXTINF:-1 tvg-id="{channel_name}" tvg-name="{channel_name}" '
        f'tvg-logo="{channel_logo}" group-title="{channel_type}",{channel_name}\n'
        f"{highest_url}\n"
    )
    return True, channel_name, channel_type, entry, ""


def generate_m3u_playlist(user, password, ua, timeout, output_dir="playlist", delay=CHANNEL_DELAY, retries=MAX_RETRIES, workers=DEFAULT_WORKERS, include_fast_live=False):
    """生成M3U播放列表"""
    try:
        os.makedirs(output_dir, exist_ok=True)

        print("🔑 正在生成认证信息...")
        fsenc_key = generate_uuid(user)
        auth_val = generate_4gtv_auth()
        scraper = create_scraper_with_proxy(ua)
        fsVALUE = sign_in_4gtv(user, password, fsenc_key, auth_val, ua, timeout, scraper=scraper)

        if not fsVALUE:
            print("❌ 登录失败")
            return False

        print("📡 正在获取频道列表...")
        channels = get_all_channels(ua, timeout, scraper=scraper, include_fast_live=include_fast_live)

        if not channels:
            print("❌ 无法获取频道列表")
            return False

        print(f"📺 共找到 {len(channels)} 个频道")

        m3u_content = "#EXTM3U\n"
        successful_channels = 0
        failed_channels = 0
        failed_list = []

        workers = max(1, int(workers))
        delay = max(0, float(delay))
        print(f"🚀 开始处理频道: workers={workers}, delay={delay}s")
        total_channels = len(channels)
        playlist_entries = [""] * total_channels

        if workers == 1:
            for index, channel in enumerate(channels):
                _, channel_name, channel_type, _, _ = get_channel_metadata(channel)

                print(f"\n[{index+1}/{total_channels}] 处理频道: {channel_name}")
                print(f"   📺 频道类型: {channel_type}")

                try:
                    print(f"   🔗 获取频道URL...")
                    ok, channel_name, _, entry, error = build_channel_playlist_entry(
                        channel,
                        fsVALUE,
                        fsenc_key,
                        auth_val,
                        ua,
                        timeout,
                        retries,
                        delay=delay,
                        scraper=scraper
                    )
                    if not ok:
                        print(f"   ❌ 无法获取频道 {channel_name} 的URL")
                        failed_channels += 1
                        failed_list.append((channel_name, error))
                        continue

                    playlist_entries[index] = entry
                    print(f"   ✅ 已添加频道: {channel_name}")
                    successful_channels += 1

                except Exception as e:
                    print(f"   ❌ 处理频道 {channel_name} 时出错: {e}")
                    failed_channels += 1
                    failed_list.append((channel_name, str(e)))
                    continue

                print_progress_bar(index + 1, total_channels, prefix='进度:', suffix=f'完成 {index+1}/{total_channels}')
        else:
            completed_channels = 0
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {}
                for index, channel in enumerate(channels):
                    future = executor.submit(
                        build_channel_playlist_entry,
                        channel,
                        fsVALUE,
                        fsenc_key,
                        auth_val,
                        ua,
                        timeout,
                        retries,
                        delay=delay
                    )
                    futures[future] = index

                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        ok, channel_name, _, entry, error = future.result()
                        if ok:
                            playlist_entries[index] = entry
                            successful_channels += 1
                        else:
                            failed_channels += 1
                            failed_list.append((channel_name, error))
                    except Exception as e:
                        channel_name = channels[index].get("fsNAME", "未知")
                        failed_channels += 1
                        failed_list.append((channel_name, str(e)))

                    completed_channels += 1
                    print_progress_bar(completed_channels, total_channels, prefix='进度:', suffix=f'完成 {completed_channels}/{total_channels}')

        m3u_content += "".join(playlist_entries)

        output_path = os.path.join(output_dir, "4gtv.m3u")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(m3u_content)

        print(f"\n🎉 播放列表生成完成: {output_path}")
        print(f"✅ 成功处理: {successful_channels} 个频道")
        print(f"❌ 失败处理: {failed_channels} 个频道")

        if failed_list:
            print("\n📋 失败频道清单:")
            for channel_name, error in failed_list:
                print(f"   - {channel_name}: {error}")

        return True

    except Exception as e:
        print(f"❌ 生成播放列表时出错: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description='4GTV 流媒体获取工具')
    parser.add_argument('--generate-playlist', action='store_true', help='生成M3U播放列表')
    parser.add_argument('--user', type=str, default=DEFAULT_USER, help='用户名')
    parser.add_argument('--password', type=str, default=DEFAULT_PASS, help='密码')
    parser.add_argument('--ua', type=str, default=DEFAULT_USER_AGENT, help='用户代理')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT, help='超时时间(秒)')
    parser.add_argument('--output-dir', type=str, default="playlist", help='输出目录')
    parser.add_argument('--delay', type=float, default=CHANNEL_DELAY, help='频道之间的延迟时间(秒)')
    parser.add_argument('--retries', type=int, default=MAX_RETRIES, help='最大重试次数')
    parser.add_argument('--workers', type=int, default=1, help='并发处理频道数量')
    parser.add_argument('--verbose', action='store_true', help='显示详细处理信息')
    parser.add_argument('--proxy', type=str, help='代理服务器（例如: http://username:password@proxy.com:port 或 socks5://127.0.0.1:1080）')
    parser.add_argument('--no-proxy', action='store_true', help='强制不使用代理')
    parser.add_argument('--include-fast-live', action='store_true', default=True,
                        help='包含 fs4GTV_ID 以 fast-live 开头的频道（默认包含）')

    args = parser.parse_args()

    global HTTP_PROXY, HTTPS_PROXY, SOCKS_PROXY

    if args.no_proxy:
        HTTP_PROXY = ''
        HTTPS_PROXY = ''
        SOCKS_PROXY = ''
        print("🔌 强制禁用代理")
    elif args.proxy:
        parsed = urlparse(args.proxy)
        if parsed.scheme in ('http', 'https'):
            HTTP_PROXY = args.proxy
            HTTPS_PROXY = args.proxy
            SOCKS_PROXY = ''
            print(f"🔌 使用命令行指定的 HTTP(S) 代理: {args.proxy}")
        elif parsed.scheme in ('socks5', 'socks5h'):
            HTTP_PROXY = ''
            HTTPS_PROXY = ''
            SOCKS_PROXY = args.proxy
            print(f"🔌 使用命令行指定的 SOCKS 代理: {args.proxy}")
        else:
            print(f"⚠️ 不支持的代理协议: {parsed.scheme}，将使用环境变量或直接连接")

    if args.generate_playlist:
        success = generate_m3u_playlist(
            args.user,
            args.password,
            args.ua,
            args.timeout,
            args.output_dir,
            args.delay,
            args.retries,
            args.workers,
            args.include_fast_live
        )
        return 0 if success else 1
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
