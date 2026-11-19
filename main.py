import requests
import json
import re
from datetime import datetime, timezone, timedelta
import time
import hashlib
from m3u8_downloader import M3U8Downloader
import os
from audio_extractor import extract_audio_from_video
import base64
import shutil
import sys
from urllib.parse import urljoin, urlparse
from moviepy.config import change_settings
import os.path as path

ffmpeg_binary = shutil.which("ffmpeg")
if ffmpeg_binary:
    change_settings({"FFMPEG_BINARY": ffmpeg_binary})

CCTV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://tv.cctv.com/",
}

QUALITY_ORDER = ("2000", "1200", "850", "450")

# CCTV 的 CDN 域名会轮换，某些域名在部分网络环境（例如 GitHub Actions）不可用，
# 这里保留几个可互相替换的通用 CDN 域名。
FALLBACK_CDN_HOSTS = ("newcntv.qcloudcdn.com", "hls.cntv.lxdns.com")


def cdn_host_variants(url: str) -> list:
    """为同一个m3u8路径生成不同CDN域名的候选地址。"""
    parsed = urlparse(url)
    variants = [url]
    for host in FALLBACK_CDN_HOSTS:
        if parsed.netloc != host:
            variants.append(parsed._replace(netloc=host).geturl())
    return variants

def get_cctv_news_weekly():
    """
    请求CCTV新闻周刊API并解析响应
    """
    url = "https://api.cntv.cn/NewVideo/getVideoListByColumn"
    params = {
        'id': 'TOPC1451559180488841',
        'n': '20',
        'sort': 'desc',
        'p': '1',
        'd': '',
        'mode': '0',
        'serviceId': 'tvcctv',
        'callback': 'lanmu_0'
    }
    
    try:
        # 发送请求
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        # 获取响应文本
        response_text = response.text
        
        # 解析JSONP响应 - 提取JSON部分
        # 响应格式: lanmu_0({...})
        json_match = re.search(r'lanmu_0\((.*)\)', response_text)
        if not json_match:
            raise ValueError("无法解析JSONP响应")
        
        json_str = json_match.group(1)
        data = json.loads(json_str)
        
        return data
        
    except requests.RequestException as e:
        print(f"请求错误: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}")
        return None
    except Exception as e:
        print(f"其他错误: {e}")
        return None
def generate_vtoken(fingerprint: str) -> dict:
    """
    根据JavaScript代码逻辑生成vtoken。

    Args:
        fingerprint (str): 从浏览器cookie中获取的设备指纹 (Fingerprint)。
                           通常是一个32位的十六进制字符串。

    Returns:
        dict: 包含时间戳、源字符串和最终生成的vtoken的字典。
    """
    timestamp_str = str(int(time.time()))

    salt = "2049"
    static_key = "47899B86370B879139C08EA3B5E88267"

    source_string = timestamp_str + salt + static_key + fingerprint
    md5_hash = hashlib.md5(source_string.encode('utf-8')).hexdigest()

    vtoken = md5_hash.upper()

    return {
        "timestamp": timestamp_str,
        "source_string_for_md5": source_string,
        "vtoken": vtoken
    }

def fetch_m3u8(url: str, timeout: int = 30) -> str:
    """
    请求 m3u8 地址并确认返回的确实是播放列表，而不是防盗链/地区限制的 HTML 页面。
    """
    response = requests.get(url, headers=CCTV_HEADERS, timeout=timeout)
    response.raise_for_status()
    text = response.text.lstrip("\ufeff").strip()
    if not text.startswith("#EXTM3U"):
        snippet = text[:120].replace("\n", " ")
        raise ValueError(f"返回内容不是m3u8（可能被防盗链或地区限制）: {snippet!r}")
    return text

def parse_variants(master_url: str, master_text: str) -> list:
    """
    从 master playlist 生成候选媒体播放列表地址。

    CCTV 的 master 往往只列出一种清晰度（450），但只要路径符合
    /asp/hls/<quality>/<...>/<quality>.m3u8 的模式，更高清晰度的文件也可以
    直接请求到，因此先按 QUALITY_ORDER 的顺序生成各清晰度候选，
    再补充 master 中实际列出的变体。
    """
    parsed = urlparse(master_url)
    query = f"?{parsed.query}" if parsed.query else ""
    candidates = []

    match = re.match(r"^(.*?/)(\d+)/(.*/)(\d+)\.m3u8$", parsed.path)
    if match:
        prefix, _, middle, _ = match.groups()
        for quality in QUALITY_ORDER:
            candidates.append(
                f"{parsed.scheme}://{parsed.netloc}{prefix}{quality}/{middle}{quality}.m3u8{query}"
            )

    for raw_line in master_text.splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            candidates.append(urljoin(master_url, line))

    unique = []
    for url in candidates:
        if url not in unique:
            unique.append(url)
    return unique

def unencrypted_candidates(url: str) -> list:
    """
    生成可尝试的播放列表地址：
    1. 去掉 CCTV 的加密路径 (/asp/enc/hls -> /asp/hls)；
    2. 尝试 2000/1200/850/450 各清晰度，优先高清；
    3. 同一路径在多个 CDN 域名上重试。
    """
    normalized = url
    for marker in ("/asp/enc2/hls/", "/asp/enc/hls/", "/asp/h5e/hls/"):
        if marker in normalized:
            normalized = normalized.replace(marker, "/asp/hls/", 1)
            break

    parsed = urlparse(normalized)
    paths = []
    match = re.match(r"^(.*?/)(\d+)/(.*/)(\d+)\.m3u8$", parsed.path)
    if match:
        prefix, _, middle, _ = match.groups()
        for quality in QUALITY_ORDER:
            paths.append(f"{prefix}{quality}/{middle}{quality}.m3u8")
    paths.append(parsed.path)

    # 去重并保持顺序
    unique_candidates = []
    for candidate_path in paths:
        candidate_url = parsed._replace(path=candidate_path).geturl()
        for host_variant in cdn_host_variants(candidate_url):
            if host_variant not in unique_candidates:
                unique_candidates.append(host_variant)
    return unique_candidates

def resolve_media_playlist(master_url: str, master_text: str):
    """
    从 master playlist 中选出可用的最高清晰度媒体播放列表。
    返回 (媒体播放列表地址, 内容)，找不到时返回 (None, None)。
    """
    variants = parse_variants(master_url, master_text) or [master_url]
    tried = set()

    for variant_url in variants:
        for candidate_url in unencrypted_candidates(variant_url):
            if candidate_url in tried:
                continue
            tried.add(candidate_url)

            try:
                content = fetch_m3u8(candidate_url)
            except Exception as e:
                print(f"清晰度探测失败: {candidate_url} ({e})")
                continue

            if "#EXTINF" not in content:
                continue
            if "#EXT-X-KEY" in content and "METHOD=NONE" not in content:
                print(f"跳过加密播放列表: {candidate_url}")
                continue

            return candidate_url, content

    return None, None

def get_video_info(video_guid):
    """
    获取视频信息
    """
    fingerprint = os.getenv("FINGERPRINT")
    if not fingerprint:
        fingerprint = "ABCD"
    vtoken = generate_vtoken(fingerprint)
    # https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?pid=98818820526f4fad8eb896022ad4b6b7&client=flash&im=0&tsp=1754358909&vn=2049&vc=7BA8ACCDA118481B230086E6730A49A6&uid=AB2BCC96F1DA979C99C5C4212F93172C&wlan=
    url = f"https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do"
    params = {
        'pid': video_guid,
        'client': 'flash',
        'im': '0',
        'tsp': vtoken['timestamp'],
        'vn': '2049',
        'vc': vtoken['vtoken'],
        'uid': fingerprint,
        'wlan': ''
    }
    response = requests.get(url, params=params, headers=CCTV_HEADERS, timeout=30)
    response.raise_for_status()

    try:
        info = response.json()
    except ValueError:
        print(f"视频信息接口返回异常内容: {response.text[:200]!r}")
        raise

    with open("response.json", "w", encoding="utf-8") as f:
        f.write(response.text)

    title = info['title']
    segments = info.get('segments', [])
    tag = info['tag']

    manifest = info.get('manifest') or {}
    source_urls = []
    for source_url in (
        info.get('hls_url'),
        manifest.get('hls_enc_url'),
        manifest.get('hls_enc2_url'),
        manifest.get('hls_h5e_url'),
    ):
        if not source_url:
            continue
        for candidate in cdn_host_variants(source_url):
            if candidate not in source_urls:
                source_urls.append(candidate)

    if not source_urls:
        raise RuntimeError("视频信息接口没有返回可用的m3u8地址")

    errors = []
    for master_url in source_urls:
        print(f"尝试m3u8源: {master_url}")
        try:
            master_text = fetch_m3u8(master_url)
        except Exception as e:
            errors.append(f"{master_url}: {e}")
            print(f"该m3u8源不可用: {e}")
            continue

        video_url, _ = resolve_media_playlist(master_url, master_text)
        if video_url:
            print(f"已选择播放地址: {video_url}")
            return video_url, title, segments, tag

        errors.append(f"{master_url}: 未找到可用的清晰度")

    raise RuntimeError("无法获取可用的m3u8地址:\n" + "\n".join(errors))

def get_sub_from_ai(path: str) -> bool:
    """从AI获取字幕
    
    Args:
        path: 音频文件路径
    Returns:
        text: 文本
    """
    os.makedirs("sub_output", exist_ok=True)
    user_id = os.getenv("CLOUDFLARE_USER_ID")
    api_key = os.getenv("CLOUDFLARE_API_KEY")
    url = f'https://api.cloudflare.com/client/v4/accounts/{user_id}/ai/run/@cf/openai/whisper-large-v3-turbo'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
        'Content-Type': 'application/octet-stream',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Authorization': f'Bearer {api_key}'
    }
    with open(path, 'rb') as audio_file:
        audio_data = audio_file.read()
    base64_audio_data = base64.b64encode(audio_data).decode('utf-8')
    json_data = {
        'audio': base64_audio_data
    }
    response = requests.post(url, headers=headers, json=json_data, timeout=600)
    if response.status_code == 200:
        # print(response.text)
        segments = response.json()['result']['segments']
        srt = convert_words_to_srt(segments)
        srt_name = os.path.splitext(os.path.basename(path))[0] + ".srt"
        with open(os.path.join("sub_output", srt_name), 'w', encoding='utf-8') as f:
            f.write(srt)
        return True
    else:
        print(f'从AI获取字幕失败: {path}, 错误信息: {response.text}')
        return False

def format_srt_time(seconds: float) -> str:
    """
    将秒数转换为 SRT 时间格式 (HH:MM:SS,mmm)
    """
    ms = int((seconds % 1) * 1000)
    total_seconds = int(seconds)
    s = total_seconds % 60
    m = (total_seconds // 60) % 60
    h = total_seconds // 3600

    return f"{pad(h)}:{pad(m)}:{pad(s)},{pad(ms, 3)}"

def pad(num: int, size: int = 2) -> str:
    """
    数字补零，默认宽度为 2。如果需要毫秒则传入 size=3。
    """
    return str(num).zfill(size)

def convert_words_to_srt(segments: list) -> str:
    """
    将包含 start/end/text 字段的 segments 列表转换为 SRT 格式字符串。
    """
    if not segments:
        return "No transcription data."

    lines = []
    for idx, segment in enumerate(segments, start=1):
        start_ts = format_srt_time(segment["start"])
        end_ts = format_srt_time(segment["end"])
        text = segment["text"]
        lines.append(f"{idx}")
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(text)
        lines.append("")  # 空行分隔

    return "\n".join(lines)


def read_passed_file():
    with open(passed_file, 'r', encoding='utf-8') as fp:
        return json.load(fp)

def write_passed_file(data):
    with open(passed_file, 'w', encoding='utf-8') as fp:
        json.dump(data, fp)

if __name__ == "__main__":
    if os.getenv("FORCE_RUN") == "true":
        force_run = True
    else:
        force_run = False
    print("强制运行： ", force_run)
    # 判断是否已获取过
    
    passed_file = path.join(path.dirname(__file__), 'passed.json')

    passed = {'video_title': ''}
    if not path.exists(passed_file):
        write_passed_file(passed)
    else:
        passed = read_passed_file()

    print('passed: ', passed)

    
    print("正在请求CCTV的API...")
    data = get_cctv_news_weekly()
    if not data or not data.get('data', {}).get('list'):
        print("未获取到视频列表，终止本次任务")
        with open("status.txt", "w", encoding="utf-8") as f:
            f.write("false")
        sys.exit(1)
    latest_video_guid = data['data']['list'][0]['guid']



    video_url, title,segments, tag = get_video_info(latest_video_guid)
    print(f"视频URL: {video_url}")
    print(f"视频标题: {title}")

    if title == passed['video_title'] and not force_run:
        print("已获取过，跳过")
        with open("status.txt", "w", encoding="utf-8") as f:
            f.write("false")
        exit(0)

    # 写入提交信息
    with open("release_info.txt", "w", encoding="utf-8") as f:
        f.write(f"---\n\n")
        f.write(f"视频标题: {title}\n\n")
        f.write(f"视频标签: {tag}\n\n")
        f.write(f"---\n\n")
        f.write(f"视频内容如下：\n\n")
        for segment in segments:
            f.write(f"- {segment['title']}\n\n")
        f.write(f"---\n\n")

    time_tag = title.split()[-1]
    with open("time.txt", "w", encoding="utf-8") as f:
        f.write(time_tag)

    # 创建下载器实例
    downloader = M3U8Downloader(
        max_workers = 20,      # 20个并发线程
        timeout = 30,         # 30秒超时
        retry_times = 3       # 重试3次
    )
        
    print("=" * 50)
    
    success = downloader.download_m3u8(
        m3u8_url=video_url,
        output_dir="downloads",
        filename=title
    )
    # success = True
    if not success:
        print("下载失败，终止本次任务")
        with open("status.txt", "w", encoding="utf-8") as f:
            f.write("false")
        sys.exit(1)

    print("下载成功！")

    # 分离音频
    print("=" * 50)
    print("开始分离音频...")

    video_path = os.path.join("downloads", f"{title}.mp4")
    audio_path = os.path.join("downloads", f"{title}.mp3")
    audio_success = False
    try:
        if os.path.exists(video_path):
            audio_success = extract_audio_from_video(video_path, audio_path)
        else:
            print(f"错误: 视频文件 '{video_path}' 不存在")
    except ImportError:
        print("警告: 无法导入 audio_extractor 模块")
        print("请确保已安装 moviepy: pip install moviepy")
    except Exception as e:
        print(f"音频分离过程中出现错误: {e}")

    if not audio_success or not os.path.exists(audio_path):
        print("音频分离失败，无法生成字幕")
        with open("status.txt", "w", encoding="utf-8") as f:
            f.write("false")
        sys.exit(1)

    print("🎉 音频分离完成！")

    # 生成字幕
    print("=" * 50)
    print("开始生成字幕...")
    status = False
    total_try_times = 10
    while not status and total_try_times > 0:
        status = get_sub_from_ai(audio_path)
        if status:
            print("字幕生成完成！")
        else:
            total_try_times -= 1
            if total_try_times > 0:
                print(f"字幕生成失败！正在重试... 剩余尝试次数: {total_try_times}")
                time.sleep(300)
            else:
                print("字幕生成失败，已达到最大重试次数")

    if not status:
        with open("status.txt", "w", encoding="utf-8") as f:
            f.write("false")
        sys.exit(1)

    # 保存到passed.json
    passed['video_title'] = title
    write_passed_file(passed)
    with open("status.txt", "w", encoding="utf-8") as f:
        f.write("true")

    
    