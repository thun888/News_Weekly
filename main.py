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
from moviepy.config import change_settings
change_settings({"FFMPEG_BINARY": "/usr/bin/ffmpeg"}) 

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

def get_video_info(video_guid):
    """
    获取视频信息
    """
    fingerprint = os.getenv("FINGERPRINT")
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
    response = requests.get(url, params=params)
    # print(response.json())
    title = response.json()['title']
    target_url = response.json()['manifest']['hls_enc_url']
    target_url_response = requests.get(target_url)
    # print(target_url_response.text)
    """
    #EXTM3U
    #EXT-X-STREAM-INF:PROGRAM-ID=1, BANDWIDTH=460800, RESOLUTION=480x270
    /asp/hlsaudio/hls/450/0303000a/3/default/32209ab71a794674ab965ae7b6ff1d7e/450.m3u8
    #EXT-X-STREAM-INF:PROGRAM-ID=1, BANDWIDTH=870400, RESOLUTION=640x360
    /asp/hlsaudio/hls/850/0303000a/3/default/32209ab71a794674ab965ae7b6ff1d7e/850.m3u8
    #EXT-X-STREAM-INF:PROGRAM-ID=1, BANDWIDTH=1228800, RESOLUTION=1280x720
    /asp/hlsaudio/hls/1200/0303000a/3/default/32209ab71a794674ab965ae7b6ff1d7e/1200.m3u8
    #EXT-X-STREAM-INF:PROGRAM-ID=1, BANDWIDTH=2048000, RESOLUTION=1280x720
    /asp/hlsaudio/hls/2000/0303000a/3/default/32209ab71a794674ab965ae7b6ff1d7e/2000.m3u8

    """    
    # target_host = target_url.split('/')[2]
    target_host = "hls.cntv.lxdns.com"
    # print(target_host)
    # https://hls.cntv.lxdns.com/asp/hls/450/0303000a/3/default/32209ab71a794674ab965ae7b6ff1d7e/450.m3u8
    url = "https://" + target_host + target_url_response.text.split('\n')[2].replace("/enc","")
    return url, title

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
    audio_data = open(path, 'rb').read()
    base64_audio_data = base64.b64encode(audio_data).decode('utf-8')
    json_data = {
        'audio': base64_audio_data
    }
    response = requests.post(url, headers=headers, json=json_data)
    if response.status_code == 200:
        # print(response.text)
        segments = response.json()['result']['segments']
        srt = convert_words_to_srt(segments)
        with open(os.path.join("sub_output", path.split('/')[-1].split('.')[0] + ".srt"), 'w', encoding='utf-8') as f:
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


if __name__ == "__main__":
    # 判断是否为东8区的星期天早上4点
    now = datetime.now(timezone(timedelta(hours=8)))
    if not (now.weekday() == 6 and now.hour == 21):
        print("当前时间不是东8区的星期天早上4点，跳过运行")
        exit(1)
    
    print("正在请求CCTV的API...")
    data = get_cctv_news_weekly()
    latest_video_guid = data['data']['list'][0]['guid']
    print(f"最新视频ID: {latest_video_guid}")
    video_url, title = get_video_info(latest_video_guid)
    print(f"视频URL: {video_url}")
    print(f"视频标题: {title}")

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
    if success:
        print("下载成功！")
        
        # 分离音频
        print("=" * 50)
        print("开始分离音频...")
        
        try: 
            video_path = f"downloads/{title}.mp4"
            audio_path = f"downloads/{title}.mp3"
            
            if os.path.exists(video_path):
                audio_success = extract_audio_from_video(video_path, audio_path)
                if audio_success:
                    print("🎉 音频分离完成！")
                else:
                    print("💥 音频分离失败！")
            else:
                print(f"错误: 视频文件 '{video_path}' 不存在")
                
        except ImportError:
            print("警告: 无法导入 audio_extractor 模块")
            print("请确保已安装 moviepy: pip install moviepy")
        except Exception as e:
            print(f"音频分离过程中出现错误: {e}")

    # 生成字幕
    # audio_path = "downloads/《新闻周刊》 20250802.mp3"
    print("=" * 50)
    print("开始生成字幕...")
    status = False
    while not status:
        status = get_sub_from_ai(audio_path)
        if status:
            print("字幕生成完成！")
        else:
            print("字幕生成失败！")


    
    