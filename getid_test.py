import requests
import json
import re
from datetime import datetime

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

def parse_video_list(data):
    """
    解析视频列表数据
    """
    if not data or 'data' not in data:
        print("数据格式错误")
        return
    
    video_list = data['data'].get('list', [])
    total = data['data'].get('total', 0)
    
    print(f"总共找到 {total} 个视频")
    print("=" * 80)
    
    for i, video in enumerate(video_list, 1):
        print(f"\n{i}. 视频信息:")
        print(f"   标题: {video.get('title', 'N/A')}")
        print(f"   时间: {video.get('time', 'N/A')}")
        print(f"   时长: {video.get('length', 'N/A')}")
        print(f"   视频ID: {video.get('id', 'N/A')}")
        print(f"   GUID: {video.get('guid', 'N/A')}")
        print(f"   链接: {video.get('url', 'N/A')}")
        print(f"   简介: {video.get('brief', 'N/A')[:100]}...")
        print(f"   图片: {video.get('image', 'N/A')}")
        print("-" * 60)

def main():
    """
    主函数
    """
    print("正在请求CCTV新闻周刊API...")
    data = get_cctv_news_weekly()
    
    if data:
        print("请求成功！")
        parse_video_list(data)
    else:
        print("请求失败")

if __name__ == "__main__":
    main()


