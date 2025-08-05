import requests
import os
import re
import time
import threading
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import sys

class M3U8Downloader:
    def __init__(self, max_workers=10, timeout=30, retry_times=3):
        """
        初始化M3U8下载器
        
        Args:
            max_workers: 最大并发下载线程数
            timeout: 请求超时时间（秒）
            retry_times: 重试次数
        """
        self.max_workers = max_workers
        self.timeout = timeout
        self.retry_times = retry_times
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
    def download_m3u8(self, m3u8_url, output_dir="downloads", filename=None):
        """
        下载m3u8文件并解析
        
        Args:
            m3u8_url: m3u8文件URL
            output_dir: 输出目录
            filename: 输出文件名（不含扩展名）
        """
        print(f"开始下载: {m3u8_url}")
        
        # 创建输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        # 获取m3u8内容
        m3u8_content = self._fetch_m3u8_content(m3u8_url)
        if not m3u8_content:
            print("无法获取m3u8内容")
            return False
            
        # 解析m3u8文件
        ts_urls = self._parse_m3u8(m3u8_url, m3u8_content)
        if not ts_urls:
            print("未找到ts片段")
            return False
            
        print(f"找到 {len(ts_urls)} 个ts片段")
        
        # 设置输出文件名
        if not filename:
            filename = self._generate_filename(m3u8_url)
            
        # 下载所有ts片段
        ts_files = self._download_ts_segments(ts_urls, output_dir)
        if not ts_files:
            print("下载ts片段失败")
            return False
            
        # 合并ts文件
        output_path = os.path.join(output_dir, f"{filename}.mp4")
        if self._merge_ts_files(ts_files, output_path):
            print(f"下载完成: {output_path}")
            
            # 清理临时ts文件
            self._cleanup_ts_files(ts_files)
            return True
        else:
            print("合并文件失败")
            return False
    
    def _fetch_m3u8_content(self, url):
        """获取m3u8文件内容"""
        for i in range(self.retry_times):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                return response.text
            except Exception as e:
                print(f"获取m3u8内容失败 (尝试 {i+1}/{self.retry_times}): {e}")
                if i < self.retry_times - 1:
                    time.sleep(1)
        return None
    
    def _parse_m3u8(self, base_url, content):
        """解析m3u8文件，提取ts片段URL"""
        ts_urls = []
        lines = content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                # 处理相对URL
                if not line.startswith('http'):
                    line = urljoin(base_url, line)
                ts_urls.append(line)
                
        return ts_urls
    
    def _generate_filename(self, url):
        """根据URL生成文件名"""
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        if filename.endswith('.m3u8'):
            filename = filename[:-5]
        if not filename:
            filename = f"video_{int(time.time())}"
        return filename
    
    def _download_ts_segments(self, ts_urls, output_dir):
        """并发下载ts片段"""
        ts_files = []
        total = len(ts_urls)
        
        print(f"开始下载 {total} 个ts片段...")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有下载任务
            future_to_url = {
                executor.submit(self._download_single_ts, url, output_dir, i): url 
                for i, url in enumerate(ts_urls)
            }
            
            # 处理完成的任务
            completed = 0
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    ts_file = future.result()
                    if ts_file:
                        ts_files.append(ts_file)
                    completed += 1
                    print(f"进度: {completed}/{total} ({completed/total*100:.1f}%)")
                except Exception as e:
                    print(f"下载失败 {url}: {e}")
                    completed += 1
                    
        return sorted(ts_files, key=lambda x: int(x.split('_')[-1].split('.')[0]))
    
    def _download_single_ts(self, url, output_dir, index):
        """下载单个ts片段"""
        for i in range(self.retry_times):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                
                # 保存ts文件
                ts_filename = f"segment_{index:06d}.ts"
                ts_path = os.path.join(output_dir, ts_filename)
                
                with open(ts_path, 'wb') as f:
                    f.write(response.content)
                    
                return ts_path
                
            except Exception as e:
                if i < self.retry_times - 1:
                    time.sleep(1)
                    continue
                else:
                    print(f"下载失败 {url}: {e}")
                    return None
        return None
    
    def _merge_ts_files(self, ts_files, output_path):
        """合并ts文件为mp4"""
        try:
            print("正在合并ts文件...")
            
            with open(output_path, 'wb') as outfile:
                for ts_file in ts_files:
                    if os.path.exists(ts_file):
                        with open(ts_file, 'rb') as infile:
                            outfile.write(infile.read())
                            
            return True
        except Exception as e:
            print(f"合并文件失败: {e}")
            return False
    
    def _cleanup_ts_files(self, ts_files):
        """清理临时ts文件"""
        print("清理临时文件...")
        for ts_file in ts_files:
            try:
                if os.path.exists(ts_file):
                    os.remove(ts_file)
            except Exception as e:
                print(f"删除文件失败 {ts_file}: {e}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='M3U8下载器')
    parser.add_argument('url', help='M3U8文件URL')
    parser.add_argument('-o', '--output', default='downloads', help='输出目录 (默认: downloads)')
    parser.add_argument('-f', '--filename', help='输出文件名 (不含扩展名)')
    parser.add_argument('-w', '--workers', type=int, default=10, help='并发下载线程数 (默认: 10)')
    parser.add_argument('-t', '--timeout', type=int, default=30, help='请求超时时间 (默认: 30秒)')
    parser.add_argument('-r', '--retry', type=int, default=3, help='重试次数 (默认: 3)')
    
    args = parser.parse_args()
    
    # 创建下载器
    downloader = M3U8Downloader(
        max_workers=args.workers,
        timeout=args.timeout,
        retry_times=args.retry
    )
    
    # 开始下载
    success = downloader.download_m3u8(
        args.url,
        output_dir=args.output,
        filename=args.filename
    )
    
    if success:
        print("下载完成！")
        sys.exit(0)
    else:
        print("下载失败！")
        sys.exit(1)

if __name__ == "__main__":
    # 如果没有命令行参数，提供交互式界面
    if len(sys.argv) == 1:
        print("M3U8下载器")
        print("=" * 50)
        url = input("请输入M3U8文件URL: ").strip()
        if not url:
            print("URL不能为空")
            sys.exit(1)
            
        output_dir = input("输出目录 (默认: downloads): ").strip() or "downloads"
        filename = input("输出文件名 (可选): ").strip() or None
        
        downloader = M3U8Downloader()
        success = downloader.download_m3u8(url, output_dir, filename)
        
        if success:
            print("下载完成！")
        else:
            print("下载失败！")
    else:
        main() 