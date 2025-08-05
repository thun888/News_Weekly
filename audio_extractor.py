import os
import sys
from moviepy import VideoFileClip
import argparse

def extract_audio_from_video(video_path, audio_path=None, audio_format='mp3'):
    """
    从视频文件中提取音频
    
    Args:
        video_path (str): 输入视频文件路径
        audio_path (str): 输出音频文件路径，如果为None则自动生成
        audio_format (str): 音频格式，默认为'mp3'
    
    Returns:
        bool: 提取是否成功
    """
    try:
        # 检查输入文件是否存在
        if not os.path.exists(video_path):
            print(f"错误: 视频文件 '{video_path}' 不存在")
            return False
        
        # 如果未指定输出路径，则自动生成
        if audio_path is None:
            base_name = os.path.splitext(video_path)[0]
            audio_path = f"{base_name}.{audio_format}"
        
        print(f"正在从视频文件提取音频...")
        print(f"输入文件: {video_path}")
        print(f"输出文件: {audio_path}")
        
        # 加载视频文件
        video = VideoFileClip(video_path)
        
        # 提取音频
        audio = video.audio
        
        if audio is None:
            print("错误: 视频文件没有音频轨道")
            video.close()
            return False
        
        # 保存音频文件
        audio.write_audiofile(audio_path, logger="bar",bitrate="36k")
        
        # 关闭文件
        audio.close()
        video.close()
        
        print(f"✅ 音频提取成功！")
        print(f"输出文件: {audio_path}")
        
        # 显示文件大小信息
        if os.path.exists(audio_path):
            file_size = os.path.getsize(audio_path)
            file_size_mb = file_size / (1024 * 1024)
            print(f"音频文件大小: {file_size_mb:.2f} MB")
        
        return True
        
    except Exception as e:
        print(f"❌ 音频提取失败: {str(e)}")
        return False

def main():
    """主函数，处理命令行参数"""
    parser = argparse.ArgumentParser(description='从视频文件中提取音频')
    parser.add_argument('video_path', help='输入视频文件路径')
    parser.add_argument('-o', '--output', help='输出音频文件路径')
    parser.add_argument('-f', '--format', default='mp3', choices=['mp3', 'wav', 'aac', 'ogg'], 
                       help='音频格式 (默认: mp3)')
    
    args = parser.parse_args()
    
    # 执行音频提取
    success = extract_audio_from_video(args.video_path, args.output, args.format)
    
    if success:
        print("🎉 音频分离完成！")
        sys.exit(0)
    else:
        print("💥 音频分离失败！")
        sys.exit(1)

if __name__ == "__main__":
    # 如果没有命令行参数，使用默认设置
    if len(sys.argv) == 1:
        # 默认处理 output.mp4
        video_file = "downloads/output.mp4"
        if os.path.exists(video_file):
            print("使用默认设置: 从 downloads/output.mp4 提取音频到 downloads/output.mp3")
            success = extract_audio_from_video(video_file, "downloads/output.mp3")
            if success:
                print("🎉 音频分离完成！")
            else:
                print("💥 音频分离失败！")
        else:
            print(f"错误: 默认视频文件 '{video_file}' 不存在")
            print("请使用命令行参数指定视频文件路径")
            print("示例: python audio_extractor.py downloads/output.mp4")
    else:
        main() 