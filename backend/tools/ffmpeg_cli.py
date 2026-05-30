import os
import stat

import platform
from .common_tools import merge_big_file_if_not_exists
from backend.config import BASE_DIR

class FFmpegCLI:
    
    """
    进程管理器类，用于管理子进程的生命周期
    使用弱引用避免内存泄漏
    """
    _instance = None
    
    @classmethod
    def instance(cls):
        """单例模式获取实例"""
        if cls._instance is None:
            cls._instance = FFmpegCLI()
        return cls._instance
    
    def __init__(self):
        os.chmod(self.ffmpeg_path, stat.S_IRWXU + stat.S_IRWXG + stat.S_IRWXO)
        
    @property
    def ffmpeg_path(self):
        system = platform.system()
        if system == "Windows":
            ffmpeg_dir = os.path.join(BASE_DIR, 'backend', 'ffmpeg', 'win_x64')
            print(f"[FFmpegCLI] BASE_DIR={BASE_DIR}")
            print(f"[FFmpegCLI] ffmpeg_dir={ffmpeg_dir}, exists={os.path.exists(ffmpeg_dir)}")
            merge_big_file_if_not_exists(ffmpeg_dir, 'ffmpeg.exe')
            result = os.path.join(ffmpeg_dir, 'ffmpeg.exe')
            print(f"[FFmpegCLI] ffmpeg_path={result}, exists={os.path.exists(result)}")
            return result
        elif system == "Linux":
            return os.path.join(BASE_DIR, 'backend', 'ffmpeg', 'linux_x64', 'ffmpeg')
        else:
            return os.path.join(BASE_DIR, 'backend', 'ffmpeg', 'macos', 'ffmpeg')