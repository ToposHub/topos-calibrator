"""
ArgyllController - ArgyllCMS spotread 的 Python 封装
用于控制校色仪进行测量
"""

import subprocess
import re
import threading
import time
import os
import sys
import platform
import shlex
import atexit
import signal
import queue
from pathlib import Path
from typing import Optional, Tuple, Callable, List, Dict
from enum import Enum


class ProbeType(Enum):
    """探头类型 - ArgyllCMS 支持的所有仪器"""
    # ========== X-Rite / Calibrite 色度计 ==========
    I1_DISPLAY_PRO = "i1d3"      # i1 Display Pro / i1 Display Studio / ColorMunki Display
    I1_DISPLAY_2 = "i1d2"        # Eye-One Display 1/2/LT
    DTP94 = "dtp94"              # DTP94 "Optix XR/XR2/Pro"
    HUEY = "huey"                # Gretag-Macbeth Huey
    MONACO = "monaco"            # MonacoOPTIX (Sequel Imaging)

    # ========== X-Rite / Calibrite 分光光度计 ==========
    I1_PRO = "i1pro"             # Eye-One Pro (EFI ES-1000)
    I1_PRO_2 = "i1pro2"          # i1 Pro 2 (EFI ES-2000)
    I1_PRO_3 = "i1pro3"          # i1 Pro 3 / i1 Pro 3 Plus
    COLOR_MUNKI = "colormunki"   # ColorMunki Design/Photo/i1Studio
    COLOR_MUNKI_SMILE = "colormunki_smile"  # ColorMunki Create/Smile

    # ========== Datacolor / ColorVision 色度计 ==========
    SPYDERX = "spydx"            # SpyderX
    SPYDERX2 = "spydx2"          # SpyderX2
    SPYDER = "spyder"            # Spyder / SpyderPRO (2024)
    SPYDER5 = "spyd5"            # Spyder 5
    SPYDER4 = "spyd4"            # Spyder 4
    SPYDER3 = "spyd3"            # Spyder 3
    SPYDER2 = "spyd2"            # Spyder 2
    SPYDER1 = "spyd1"            # Spyder 1

    # ========== Klein 色度计 ==========
    K10A = "k10a"                # Klein K10-A (及 K-1, K-8, K-10)

    # ========== 其他设备 ==========
    COLORHUG = "colorhug"        # ColorHug / ColorHug2
    HCFR = "hcfr"                # Colorimètre HCFR
    CUBE = "cube"                # Palette/SwatchMate Cube
    EX1 = "ex1"                  # Image Engineering EX1

    # ========== JETI 分光光度计 ==========
    SPECBOS = "specbos"          # JETI specbos 1211, 1201, 2501
    SPECTRAVAL = "spectraval"    # JETI spectraval 1511, 1501

    # ========== Gretag-Macbeth 分光光度计 ==========
    SPECTROLINO = "spectro"      # Spectrolino
    SPECTROSCAN = "spectroscan"  # SpectroScan / SpectroScanT

    # ========== X-Rite DTP 系列 ==========
    DTP20 = "dtp20"              # DTP20 "Pulse"
    DTP22 = "dtp22"              # DTP22 Digital Swatchbook
    DTP41 = "dtp41"              # DTP41 / DTP41T
    DTP51 = "dtp51"              # DTP51
    DTP92 = "dtp92"              # DTP92
    CHROMA = "chroma"            # Sequel Chroma 4/5


class DisplayType(Enum):
    """显示器类型（ArgyllCMS ccxxmake -t 官方参数）

    常见类型排在前面，详细类型排在后面。
    参数说明：
    - 小写字母为通用类型
    - 数字和大写字母为具体背光/面板类型
    """
    # ========== 最常见类型 ==========
    LCD = "l"                   # LCD 通用（最常用）
    LCD_WHITE_LED = "e"         # LCD White LED（常见笔记本/显示器）
    LCD_RGB_LED = "b"           # LCD RGB LED（广色域显示器）
    OLED = "o"                  # OLED 显示器
    CRT = "c"                   # CRT 显示器

    # ========== 其他常见类型 ==========
    PLASMA = "m"                # 等离子显示器
    PROJECTOR = "p"             # DLP 投影仪

    # ========== LCD 细分类型（按背光） ==========
    LCD_CCFL = "1"              # LCD CCFL（老式冷阴极荧光灯）
    LCD_CCFL_IPS = "2"          # LCD CCFL IPS
    LCD_CCFL_PVA = "3"          # LCD CCFL PVA
    LCD_CCFL_TFT = "4"          # LCD CCFL TFT
    LCD_CCFL_WIDE = "L"         # LCD CCFL Wide Gamut（大写L）
    LCD_CCFL_WIDE_IPS = "5"     # LCD CCFL Wide Gamut IPS
    LCD_CCFL_WIDE_PVA = "6"     # LCD CCFL Wide Gamut PVA
    LCD_CCFL_WIDE_TFT = "7"     # LCD CCFL Wide Gamut TFT

    LCD_WHITE_LED_IPS = "8"     # LCD White LED IPS
    LCD_WHITE_LED_PVA = "9"     # LCD White LED PVA
    LCD_WHITE_LED_TFT = "a"     # LCD White LED TFT

    LCD_RGB_LED_IPS = "c"       # LCD RGB LED IPS（注意与CRT冲突，实际使用时区分）
    LCD_RGB_LED_PVA = "d"       # LCD RGB LED PVA
    LCD_RGB_LED_TFT = "b"       # LCD RGB LED TFT

    # ========== LCD RG Phosphor（红绿荧光粉） ==========
    LCD_RG_PHOSPHOR = "h"       # LCD RG Phosphor
    LCD_RG_PHOSPHOR_IPS = "e"   # LCD RG Phosphor IPS
    LCD_RG_PHOSPHOR_PVA = "f"   # LCD RG Phosphor PVA
    LCD_RG_PHOSPHOR_TFT = "g"   # LCD RG Phosphor TFT

    # ========== LCD PFS Phosphor（PFS荧光粉） ==========
    LCD_PFS_PHOSPHOR = "r"      # LCD PFS Phosphor
    LCD_PFS_PHOSPHOR_IPS = "s"  # LCD PFS Phosphor IPS
    LCD_PFS_PHOSPHOR_PVA = "t"  # LCD PFS Phosphor PVA
    LCD_PFS_PHOSPHOR_TFT = "v"  # LCD PFS Phosphor TFT

    # ========== LCD GB-R Phosphor（绿蓝红荧光粉） ==========
    LCD_GB_R_PHOSPHOR = "i"     # LCD GB-R Phosphor
    LCD_GB_R_PHOSPHOR_IPS = "x" # LCD GB-R Phosphor IPS
    LCD_GB_R_PHOSPHOR_PVA = "y" # LCD GB-R Phosphor PVA
    LCD_GB_R_PHOSPHOR_TFT = "z" # LCD GB-R Phosphor TFT

    # ========== OLED 细分类型 ==========
    AMOLED = "a"                # LED AMOLED
    WOLED = "w"                 # LED WOLED（LG OLED电视）

    # ========== 投影仪细分类型 ==========
    DLP_PROJECTOR = "p"         # DLP Projector
    DLP_RGB_WHEEL = "h"         # DLP Projector RGB Filter Wheel


# ========== 探头推荐测量延迟（毫秒） ==========
# 在屏幕显示色块后需要等待一段时间让像素稳定，否则会测到过渡色
# 这些值基于各探头的响应速度和常见显示器特性硬编码
PROBE_RECOMMENDED_DELAYS = {
    # ========== 高速色度计（响应快，约 200-300ms） ==========
    ProbeType.I1_DISPLAY_PRO: 250,    # i1 Display Pro / Studio
    ProbeType.I1_DISPLAY_2: 300,      # Eye-One Display 1/2
    ProbeType.SPYDERX: 250,           # SpyderX
    ProbeType.SPYDERX2: 250,          # SpyderX2
    ProbeType.SPYDER: 250,            # Spyder / SpyderPRO (2024)
    ProbeType.K10A: 200,              # Klein K10-A（专业高速）
    ProbeType.EX1: 250,               # EX1
    ProbeType.DTP94: 300,             # DTP94
    ProbeType.COLORHUG: 300,          # ColorHug

    # ========== 分光光度计（精度高但速度稍慢，约 400-500ms） ==========
    ProbeType.I1_PRO: 400,            # Eye-One Pro
    ProbeType.I1_PRO_2: 400,          # i1 Pro 2
    ProbeType.I1_PRO_3: 400,          # i1 Pro 3
    ProbeType.COLOR_MUNKI: 500,       # ColorMunki Design/Photo
    ProbeType.COLOR_MUNKI_SMILE: 500, # ColorMunki Smile
    ProbeType.SPECTROLINO: 500,       # Spectrolino
    ProbeType.SPECTROSCAN: 500,       # SpectroScan
    ProbeType.SPECBOS: 400,           # JETI specbos
    ProbeType.SPECTRAVAL: 400,        # JETI spectraval

    # ========== 老款色度计（响应较慢，约 500ms+） ==========
    ProbeType.SPYDER5: 500,           # Spyder 5
    ProbeType.SPYDER4: 500,           # Spyder 4
    ProbeType.SPYDER3: 600,           # Spyder 3
    ProbeType.SPYDER2: 700,           # Spyder 2
    ProbeType.SPYDER1: 800,           # Spyder 1
    ProbeType.HUEY: 600,              # Huey
    ProbeType.MONACO: 500,            # MonacoOPTIX
    ProbeType.HCFR: 500,              # HCFR
    ProbeType.CUBE: 500,              # Cube

    # ========== DTP 系列 ==========
    ProbeType.DTP20: 500,             # DTP20
    ProbeType.DTP22: 500,             # DTP22
    ProbeType.DTP41: 400,             # DTP41
    ProbeType.DTP51: 400,             # DTP51
    ProbeType.DTP92: 400,             # DTP92
    ProbeType.CHROMA: 500,            # Chroma 4/5

    # 默认/未知探头: 保守值
    "default": 500,
}


# ========== macOS 干扰进程黑名单 ==========
# 这些进程可能会占用 USB 端口，导致 spotread 无法连接探头
MACOS_CONFlicting_PROCESSES = [
    'XRiteDevice',           # X-Rite Device Services 主进程
    'i1Profiler',            # i1Profiler 软件
    'Calibrite',             # Calibrite 相关进程
    'xrd',                   # X-Rite daemon
    'ColorMunki',            # ColorMunki 软件
    'i1Share',               # i1 Share 软件
    'XRGDiag',               # X-Rite 诊断工具
    'XRiteService',          # X-Rite 服务进程
    'XRiteDaemon',           # X-Rite daemon 进程
    'i1Display',             # i1 Display 相关进程
]

# ========== spotread 硬件错误关键词 ==========
# 这些关键词表示硬件状态错误，需要立即停止测量并通知用户
SPOTREAD_ERROR_KEYWORDS = [
    'spot read failed',                    # 测量失败
    'sensor being in the wrong position',  # 传感器位置错误
    'wrong position',                      # 位置错误
    'ambient filter should be removed',    # 柔光罩需要移除
    'ambient filter',                      # 柔光罩相关
    'filter should be',                    # 滤镜相关
    'no instrument found',                 # 未找到仪器
    'instrument not found',                # 仪器未找到
    'communication error',                 # 通信错误
    'usb error',                           # USB 错误
    'device not found',                    # 设备未找到
    'access denied',                       # 访问被拒绝
    'permission denied',                   # 权限被拒绝
    'failed to open',                      # 打开失败
    'calibration failed',                  # 校准失败
    'readpipeasync failed',                # USB 管道读取失败（设备断开）
    'read pipe',                           # 管道读取错误
]

# ========== USB 断开关键词（需要自动断开连接） ==========
USB_DISCONNECT_KEYWORDS = [
    'readpipeasync failed',
    'read pipe async',
    'no instrument found',
    'instrument not found',
    'usb error',
    'communication error',
    'device not found',
]

# ========== 错误消息友好提示映射 ==========
ERROR_MESSAGE_MAP = {
    'ambient filter should be removed': '柔光罩未移除，请确保柔光罩已打开或移除后再进行测量',
    'ambient filter': '柔光罩状态错误，请检查柔光罩是否正确设置',
    'sensor being in the wrong position': '传感器位置错误，请将探头正确放置在被测区域',
    'wrong position': '探头位置不正确，请调整探头位置',
    'no instrument found': '未检测到探头，请检查探头连接',
    'instrument not found': '未检测到探头，请检查探头连接',
    'communication error': '探头通信错误，请重新连接探头',
    'usb error': 'USB 连接错误，请检查探头 USB 连接',
    'spot read failed': '测量失败，请检查探头状态',
    'calibration failed': '校准失败，请重新校准探头',
    'readpipeasync failed': 'USB 设备已断开，探头已被拔出',
    'read pipe': 'USB 管道通信失败，设备可能已断开',
}


class ArgyllController:
    """
    ArgyllCMS spotread 控制器
    通过 subprocess 与 spotread 交互式命令行程序通信
    """

    # ========== 设备枚举参数 ==========
    # 枚举会探测所有串口（含蓝牙串口，实测单次可达 20+ 秒），超时必须给足
    _ENUMERATE_TIMEOUT = 45.0
    # 枚举结果缓存时长（秒）
    _ENUMERATE_CACHE_TTL = 60.0

    # spotread 输出中提取测量结果的正则表达式
    # 实际输出格式: "Result is XYZ: 0.033364 0.029912 0.062078, D50 Lab: ..."
    # 或者旧格式: "CIE x,y,Y = x.xxx, y.xxx, Y.xxx"

    # XYZ 格式正则：匹配 "Result is XYZ: X Y Z"（空格分隔）
    XYZ_PATTERN = re.compile(
        r'Result is XYZ:\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)',
        re.IGNORECASE
    )

    # Yxy 格式正则（备用）：匹配 "Yxy: Y=..., x=..., y=..."
    YXY_PATTERN = re.compile(
        r'Yxy:\s*Y\s*=\s*([\d.]+),\s*x\s*=\s*([\d.]+),\s*y\s*=\s*([\d.]+)',
        re.IGNORECASE
    )

    # CIE x,y,Y 格式正则（备用）：匹配 "CIE x,y,Y = x, y, Y"
    CIE_XYY_PATTERN = re.compile(
        r'CIE\s*x,y,Y\s*=\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)',
        re.IGNORECASE
    )

    # 通用正则：匹配任意格式的 XYZ 输出
    MEASURE_PATTERN = re.compile(
        r'Result is XYZ:\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)',
        re.IGNORECASE
    )

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._output_buffer: str = ""
        self._last_measurement: Optional[Tuple[float, float, float]] = None
        self._is_connected: bool = False
        self._is_measuring: bool = False
        self._error_message: str = ""
        self._on_measurement_callback: Optional[Callable] = None
        self._on_error_callback: Optional[Callable] = None
        self._on_status_callback: Optional[Callable] = None

        # ========== dispcal 进程管理 ==========
        self._dispcal_process: Optional[subprocess.Popen] = None

        # 配置参数
        self._probe_type: ProbeType = ProbeType.I1_DISPLAY_PRO
        self._display_type: DisplayType = DisplayType.LCD
        self._argyll_path: str = ""  # ArgyllCMS bin 目录路径
        self._instrument_port: Optional[int] = None  # 指定的仪器端口序号 (-c 参数)

        # 当前待测色块的 RGB 值（用于暗场延迟判断）
        self._current_patch_rgb: Optional[Tuple[int, int, int]] = None

        # 光谱校正文件路径 (CCSS/CCMX)
        self._correction_file_path: str = ""

        # 输出读取锁
        self._buffer_lock = threading.Lock()

        # ========== 设备枚举缓存 ==========
        # 枚举需要探测所有串口（含蓝牙串口时实测可达 20+ 秒），
        # 缓存结果避免 connect 流程内重复枚举
        self._enumerate_cache: Optional[List[Dict[str, any]]] = None
        self._enumerate_cache_time: float = 0.0

        # ========== 线程安全控制 ==========
        # 用于安全退出后台线程，避免 daemon thread 在 Python shutdown 时崩溃
        self._shutdown_event = threading.Event()
        # 用于通知等待线程检测到硬件错误
        self._hardware_error_event = threading.Event()
        # 最后检测到的硬件错误信息
        self._last_detected_error: str = ""

        # ========== 测量结果同步 ==========
        # 用于通知主线程测量结果已就绪
        self._result_event = threading.Event()
        # 当前测量结果 (x, y, Y)
        self._current_result: Optional[Tuple[float, float, float]] = None

        # ========== 断点续测与容错机制 ==========
        # 测量超时时间（秒）- 超过此时间无响应视为探头断开
        self._measurement_timeout: float = 30.0
        # 上次成功测量的时间戳
        self._last_measurement_time: Optional[float] = None
        # 重连最大尝试次数
        self._max_reconnect_attempts: int = 3
        # 当前重连尝试次数
        self._current_reconnect_attempt: int = 0
        # 重连间隔时间（秒）
        self._reconnect_interval: float = 2.0
        # 是否处于重连状态
        self._is_reconnecting: bool = False

        # ========== 僵尸进程防护（生产级加固） ==========
        # 注册 atexit 回调，确保主程序崩溃或被强制终止时子进程也能被清理
        self._atexit_registered: bool = False
        self._register_atexit_handler()

        # 自动检测 ArgyllCMS 路径
        self._auto_detect_argyll_path()

        # 清理残留的 ArgyllCMS 进程（防止上次异常退出导致的设备占用）
        self._cleanup_orphaned_processes()

    def _register_atexit_handler(self):
        """
        注册 atexit 回调，确保主程序异常退出时子进程被清理

        这是生产级加固的关键措施：
        - 当 Python 正常退出时，atexit 回调会被执行
        - 当 Python 发生致命异常崩溃时，atexit 仍有机会执行
        - 当用户通过任务管理器强制杀进程时，atexit 可能无法执行
          （这种情况需要操作系统层面的进程组绑定，如 Windows Job Object）

        注意：atexit 回调在 Python 解释器 shutdown 阶段执行，
        此时应避免导入新模块或创建新对象。
        """
        if self._atexit_registered:
            return

        # 使用弱引用风格的回调注册
        # atexit 按注册顺序逆序执行，确保子进程在最后被清理
        atexit.register(self._cleanup_on_exit)
        self._atexit_registered = True

    def _cleanup_on_exit(self):
        """
        atexit 回调：在程序退出时强制清理子进程

        这个方法会在以下场景执行：
        1. 程序正常退出（sys.exit() 或自然结束）
        2. 程序发生未捕获的异常导致崩溃
        3. 收到 SIGTERM 信号（但 SIGKILL 无法捕获）

        不会执行的场景：
        1. 收到 SIGKILL（任务管理器强制终止）
        2. 段错误（segfault）导致的即时崩溃
        """
        # 清理 spotread 进程
        if self._process and self._process.poll() is None:
            try:
                # 首先尝试优雅终止
                self._process.terminate()
                # 等待最多 0.5 秒
                self._process.wait(timeout=0.5)
            except Exception:
                # 优雅终止失败，强制杀死
                try:
                    self._process.kill()
                except Exception:
                    pass  # 进程可能已经不存在

        # 清理 dispcal 进程（修复残留进程问题）
        if self._dispcal_process and self._dispcal_process.poll() is None:
            try:
                self._dispcal_process.terminate()
                self._dispcal_process.wait(timeout=0.5)
            except Exception:
                try:
                    self._dispcal_process.kill()
                except Exception:
                    pass

        # 清理线程事件
        if hasattr(self, '_shutdown_event'):
            self._shutdown_event.set()

    def stop_dispcal(self):
        """
        停止正在运行的 dispcal 进程

        当用户在校准过程中点击"停止"按钮时调用。
        会优雅终止 dispcal 进程，然后强制杀死（如果必要）。
        """
        if self._dispcal_process and self._dispcal_process.poll() is None:
            self._log_status("正在停止 dispcal 校准...")
            try:
                # 首先尝试优雅终止
                self._dispcal_process.terminate()
                # 等待最多 1 秒
                self._dispcal_process.wait(timeout=1.0)
                self._log_status("dispcal 已正常退出")
            except subprocess.TimeoutExpired:
                # 优雅终止失败，强制杀死
                try:
                    self._dispcal_process.kill()
                    self._log_status("dispcal 已被强制终止")
                except Exception as e:
                    self._log_error(f"强制终止 dispcal 失败: {e}")
            except Exception as e:
                self._log_error(f"终止 dispcal 失败: {e}")

            # 清理进程引用
            self._dispcal_process = None
        else:
            self._log_status("dispcal 未在运行")

    # ========== 配置方法 ==========

    def _auto_detect_argyll_path(self):
        """
        自动检测 ArgyllCMS 路径

        检测顺序：
        1. PyInstaller 打包环境（sys._MEIPASS）
        2. 项目目录下的 ArgyllCMS/bin/
        3. 系统 PATH

        注意：PyInstaller 打包后，所有资源文件会被解压到临时目录 sys._MEIPASS，
        因此必须优先检查此路径，否则打包后的应用会找不到 ArgyllCMS 工具。
        """
        # ========== PyInstaller 打包路径支持 ==========
        # PyInstaller 运行时会将打包的资源文件解压到临时目录 sys._MEIPASS
        # 必须优先检查此路径，否则打包后的应用无法找到 ArgyllCMS
        if hasattr(sys, '_MEIPASS'):
            pyinstaller_root = Path(sys._MEIPASS)
            pyinstaller_paths = [
                pyinstaller_root / "ArgyllCMS" / "bin",
                pyinstaller_root / "ArgyllCMS",
            ]
            for path in pyinstaller_paths:
                if path.exists() and path.is_dir():
                    self._argyll_path = str(path)
                    self._log_status(f"PyInstaller 环境检测到 ArgyllCMS: {path}")
                    return

        # ========== 源码运行环境 ==========
        # 获取项目根目录
        project_root = Path(__file__).parent.parent

        # 可能的 ArgyllCMS bin 目录位置
        possible_paths = [
            project_root / "ArgyllCMS" / "bin",
            project_root / "ArgyllCMS",  # 如果用户直接把 bin 内容放在 ArgyllCMS 文件夹
        ]

        # 根据操作系统确定可执行文件名
        system = platform.system()
        spotread_name = "spotread.exe" if system == "Windows" else "spotread"

        # 检查项目目录下的 ArgyllCMS
        for path in possible_paths:
            if path.exists() and path.is_dir():
                spotread_path = path / spotread_name
                if spotread_path.exists():
                    self._argyll_path = str(path)
                    self._log_status(f"自动检测到 ArgyllCMS: {path}")
                    return

        # 检查系统 PATH
        try:
            result = subprocess.run(
                ["which", "spotread"] if system != "Windows" else ["where", "spotread"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # spotread 在 PATH 中
                self._argyll_path = ""  # 使用系统 PATH
                self._log_status("使用系统 PATH 中的 ArgyllCMS")
                return
        except Exception:
            pass

        # 未找到，但保持空路径，后续连接时会报错
        self._log_status("未检测到 ArgyllCMS，请将 ArgyllCMS 文件放入项目目录的 ArgyllCMS 文件夹")

    # ========== 设备枚举与选择 ==========

    def enumerate_instruments(self) -> List[Dict[str, any]]:
        """
        枚举当前连接的所有仪器设备

        Returns:
            List[Dict]: 设备列表，每个元素包含：
                - 'index': 设备序号 (int)
                - 'port': 设备端口标识 (str)
                - 'name': 设备名称 (str)
                - 'probe_type': 匹配的探头类型 (ProbeType 或 None)
        """
        system = platform.system()
        spotread_name = "spotread.exe" if system == "Windows" else "spotread"

        if self._argyll_path:
            spotread_path = str(Path(self._argyll_path) / spotread_name)
        else:
            spotread_path = spotread_name

        # 命中缓存直接返回（枚举开销大，见 __init__ 注释）
        now = time.monotonic()
        if (self._enumerate_cache is not None
                and now - self._enumerate_cache_time < self._ENUMERATE_CACHE_TTL):
            return self._enumerate_cache

        devices = []

        try:
            # 运行 spotread -D -c ? 来获取设备列表
            # -D 开启调试模式，-c ? 列出设备
            # 注意：枚举会探测所有串口（含蓝牙），实测可达 20+ 秒，超时必须给足
            result = subprocess.run(
                [spotread_path, "-D", "-c", "?"],
                capture_output=True,
                text=True,
                timeout=self._ENUMERATE_TIMEOUT
            )

            # 合并 stdout 和 stderr
            output = result.stdout + result.stderr

            # 解析设备列表
            # 格式: "    1 = 'hid321: (X-Rite i1 DisplayPro, ColorMunki Display)'"
            # 或: "    1 = 'hid:nnn (Device Name)'"
            device_pattern = re.compile(
                r"^\s*(\d+)\s*=\s*['\"]?([^'\"\n]+)['\"]?\s*$",
                re.MULTILINE
            )

            for match in device_pattern.finditer(output):
                index = int(match.group(1))
                device_info = match.group(2).strip()

                # 解析设备信息
                # 格式通常是: "hid321: (X-Rite i1 DisplayPro, ColorMunki Display)"
                # 或: "/dev/cu.serial0"
                name = device_info
                port = device_info

                # 提取括号内的设备名称
                name_match = re.search(r'\(([^)]+)\)', device_info)
                if name_match:
                    name = name_match.group(1)
                    # 提取端口标识 (hid321 等)
                    port_match = re.match(r'^([^:]+):', device_info)
                    if port_match:
                        port = port_match.group(1)
                else:
                    # 串口设备
                    port = device_info
                    name = device_info

                # 匹配探头类型
                probe_type = self._match_probe_type(name)

                devices.append({
                    'index': index,
                    'port': port,
                    'name': name,
                    'full_info': device_info,
                    'probe_type': probe_type
                })

            if devices:
                self._log_status(f"检测到 {len(devices)} 个仪器设备")
                for dev in devices:
                    type_str = dev['probe_type'].value if dev['probe_type'] else "未知"
                    self._log_status(f"  [{dev['index']}] {dev['name']} ({type_str})")
            else:
                self._log_status("未检测到任何仪器设备")

        except subprocess.TimeoutExpired:
            self._log_error("枚举设备超时")
        except FileNotFoundError:
            self._log_error(f"未找到 spotread: {spotread_path}")
        except Exception as e:
            self._log_error(f"枚举设备失败: {str(e)}")

        self._enumerate_cache = devices
        self._enumerate_cache_time = time.monotonic()
        return devices

    def _match_probe_type(self, device_name: str) -> Optional['ProbeType']:
        """
        根据设备名称匹配探头类型

        Args:
            device_name: 设备名称字符串

        Returns:
            ProbeType 或 None
        """
        name_lower = device_name.lower()

        # ========== X-Rite / Calibrite 色度计 ==========
        # i1 Display Pro / i1 Display Studio / ColorMunki Display
        if 'i1 display' in name_lower or 'i1d3' in name_lower:
            return ProbeType.I1_DISPLAY_PRO
        if 'colormunki display' in name_lower:
            return ProbeType.I1_DISPLAY_PRO

        # Eye-One Display 1/2/LT (i1d2)
        if 'eye-one display' in name_lower or 'i1d2' in name_lower or 'i1 display' in name_lower and 'pro' not in name_lower:
            return ProbeType.I1_DISPLAY_2

        # DTP94 / Optix XR
        if 'dtp94' in name_lower or 'optix' in name_lower:
            return ProbeType.DTP94

        # Huey
        if 'huey' in name_lower:
            return ProbeType.HUEY

        # MonacoOPTIX
        if 'monaco' in name_lower or 'monacooptix' in name_lower:
            return ProbeType.MONACO

        # ========== X-Rite / Calibrite 分光光度计 ==========
        # i1 Pro (原版 Eye-One Pro)
        if 'eye-one pro' in name_lower and '2' not in name_lower and '3' not in name_lower:
            return ProbeType.I1_PRO

        # i1 Pro 2
        if 'i1 pro 2' in name_lower or 'i1pro2' in name_lower or 'es-2000' in name_lower:
            return ProbeType.I1_PRO_2

        # i1 Pro 3
        if 'i1 pro 3' in name_lower or 'i1pro3' in name_lower or 'es-3000' in name_lower:
            return ProbeType.I1_PRO_3

        # 通用 i1 Pro 匹配（如果包含 i1pro 但没有指定版本）
        if 'i1pro' in name_lower:
            # 检查是否有版本号
            if 'pro 3' in name_lower or 'pro3' in name_lower:
                return ProbeType.I1_PRO_3
            elif 'pro 2' in name_lower or 'pro2' in name_lower:
                return ProbeType.I1_PRO_2
            else:
                return ProbeType.I1_PRO  # 默认为原版

        # ColorMunki Design/Photo/i1Studio (分光光度计版本)
        if 'colormunki' in name_lower:
            if 'display' in name_lower:
                return ProbeType.I1_DISPLAY_PRO  # ColorMunki Display 是色度计
            elif 'smile' in name_lower or 'create' in name_lower:
                return ProbeType.COLOR_MUNKI_SMILE
            else:
                return ProbeType.COLOR_MUNKI  # Design/Photo/i1Studio

        # ========== Datacolor / ColorVision 色度计 ==========
        # SpyderX / SpyderX2
        if 'spyderx' in name_lower:
            if 'x2' in name_lower or 'spydx2' in name_lower:
                return ProbeType.SPYDERX2
            return ProbeType.SPYDERX

        # Spyder (2024 新版)
        if 'spyderpro' in name_lower or ('spyder' in name_lower and 'x' not in name_lower and any(v in name_lower for v in ['1', '2', '3', '4', '5']) is False):
            return ProbeType.SPYDER

        # Spyder 5
        if 'spyder 5' in name_lower or 'spyder5' in name_lower or 'spyd5' in name_lower:
            return ProbeType.SPYDER5

        # Spyder 4
        if 'spyder 4' in name_lower or 'spyder4' in name_lower or 'spyd4' in name_lower:
            return ProbeType.SPYDER4

        # Spyder 3
        if 'spyder 3' in name_lower or 'spyder3' in name_lower or 'spyd3' in name_lower:
            return ProbeType.SPYDER3

        # Spyder 2
        if 'spyder 2' in name_lower or 'spyder2' in name_lower or 'spyd2' in name_lower:
            return ProbeType.SPYDER2

        # Spyder 1
        if 'spyder 1' in name_lower or 'spyder1' in name_lower or 'spyd1' in name_lower:
            return ProbeType.SPYDER1

        # ========== Klein 色度计 ==========
        if 'klein' in name_lower or 'k10' in name_lower or 'k10a' in name_lower:
            return ProbeType.K10A

        # ========== 其他设备 ==========
        # ColorHug
        if 'colorhug' in name_lower:
            return ProbeType.COLORHUG

        # HCFR
        if 'hcfr' in name_lower:
            return ProbeType.HCFR

        # Cube (Palette/SwatchMate)
        if 'cube' in name_lower or 'palette' in name_lower or 'swatchmate' in name_lower:
            return ProbeType.CUBE

        # EX1 (Image Engineering)
        if 'ex1' in name_lower:
            return ProbeType.EX1

        # ========== JETI 分光光度计 ==========
        if 'specbos' in name_lower or 'jeti' in name_lower:
            return ProbeType.SPECBOS
        if 'spectraval' in name_lower:
            return ProbeType.SPECTRAVAL

        # ========== Gretag-Macbeth 分光光度计 ==========
        if 'spectrolino' in name_lower:
            return ProbeType.SPECTROLINO
        if 'spectroscan' in name_lower:
            return ProbeType.SPECTROSCAN

        # ========== X-Rite DTP 系列 ==========
        if 'dtp20' in name_lower or 'pulse' in name_lower:
            return ProbeType.DTP20
        if 'dtp22' in name_lower or 'swatchbook' in name_lower:
            return ProbeType.DTP22
        if 'dtp41' in name_lower:
            return ProbeType.DTP41
        if 'dtp51' in name_lower:
            return ProbeType.DTP51
        if 'dtp92' in name_lower:
            return ProbeType.DTP92
        if 'chroma' in name_lower:
            return ProbeType.CHROMA

        return None

    def auto_detect_probe_type(self) -> Optional['ProbeType']:
        """
        自动检测连接的探头类型

        如果只有一个已知探头连接，自动返回该探头类型。
        如果有多个探头连接，返回 None（需要用户手动选择）。

        Returns:
            ProbeType 或 None
        """
        devices = self.enumerate_instruments()

        # 过滤掉未知类型的设备（如串口设备）
        known_devices = [d for d in devices if d['probe_type'] is not None]

        if len(known_devices) == 1:
            # 只有一个已知探头，自动选择
            detected_type = known_devices[0]['probe_type']
            self._log_status(f"自动检测到探头类型: {detected_type.value} ({known_devices[0]['name']})")
            return detected_type

        elif len(known_devices) == 0:
            self._log_status("未检测到已知探头设备")
            return None

        else:
            # 多个探头连接，需要用户选择
            device_list = ", ".join([f"{d['probe_type'].value}" for d in known_devices])
            self._log_status(f"检测到多个探头 ({device_list})，请手动选择探头类型")
            return None

    def _find_instrument_port(self) -> Optional[int]:
        """
        根据当前设置的探头类型查找对应的设备端口序号

        Returns:
            int: 设备端口序号，如果未找到匹配类型返回 None
        """
        devices = self.enumerate_instruments()

        if not devices:
            return None

        # 精确匹配当前探头类型
        for dev in devices:
            if dev['probe_type'] == self._probe_type:
                self._log_status(f"找到匹配的探头设备: [{dev['index']}] {dev['name']}")
                return dev['index']

        # 如果有多个设备但找不到匹配类型，列出可用设备供用户参考
        self._log_status(
            f"未找到 {self._probe_type.value} 类型的设备。"
            f"当前可用设备: " + ", ".join([f"[{d['index']}] {d['probe_type'].value if d['probe_type'] else '未知'}" for d in devices])
        )
        return None

    # ========== macOS 环境清理 ==========

    def _cleanup_macos_processes(self) -> Dict[str, bool]:
        """
        macOS 专属：扫描并清理可能占用探头 USB 端口的干扰进程

        Returns:
            Dict[str, bool]: 清理结果，键为进程名，值为是否成功清理
        """
        if platform.system() != 'Darwin':
            # 非 macOS 系统，跳过清理
            return {}

        self._log_status("正在扫描可能占用探头的后台进程...")
        cleanup_results: Dict[str, bool] = {}
        failed_processes: List[str] = []

        # 1. 扫描正在运行的干扰进程
        running_conflicts = self._scan_conflicting_processes()

        if not running_conflicts:
            self._log_status("未发现冲突的后台进程")
            return {}

        # 2. 尝试清理每个冲突进程
        for process_info in running_conflicts:
            process_name = process_info['name']
            pid = process_info['pid']

            self._log_status(f"发现冲突的后台服务 [{process_name}] (PID: {pid})，正在尝试自动结束以释放探头...")

            success = self._terminate_process(process_name, pid)
            cleanup_results[process_name] = success

            if not success:
                failed_processes.append(process_name)

        # 3. 处理清理失败的情况
        if failed_processes:
            self._handle_cleanup_failure(failed_processes)

        return cleanup_results

    def _cleanup_orphaned_processes(self):
        """
        清理残留的 ArgylCMS 进程（dispcal, spotread, dispread）

        这些进程可能是上次程序异常退出时残留的，会占用仪器设备。
        """
        try:
            system = platform.system()
            if system == "Darwin":
                # macOS: 使用 ps 和 grep
                result = subprocess.run(
                    ["ps", "aux"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
            elif system == "Linux":
                result = subprocess.run(
                    ["ps", "aux"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
            else:
                # Windows: 使用 tasklist
                result = subprocess.run(
                    ["tasklist"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

            orphaned = []
            current_pid = os.getpid()
            argyll_bin_path = getattr(self, '_argyll_path', '')

            for line in result.stdout.splitlines():
                line_lower = line.lower()
                # 检查是否包含 dispcal, spotread, 或 dispread
                if any(cmd in line_lower for cmd in ['dispcal', 'spotread', 'dispread']):
                    # 排除当前进程本身
                    if str(current_pid) in line:
                        continue
                    # 排除 grep 命令本身
                    if 'grep' in line or 'defunct' in line_lower:
                        continue

                    # 解析 PID
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                            # 检查是否是来自我们 ArgyllCMS bin 目录的进程
                            if argyll_bin_path and argyll_bin_path in line:
                                orphaned.append((pid, line.strip()))
                            elif not argyll_bin_path:
                                # 如果没有设置路径，也清理（可能是手动运行的）
                                orphaned.append((pid, line.strip()))
                        except (ValueError, IndexError):
                            continue

            if orphaned:
                self._log_status(f"发现 {len(orphaned)} 个残留的 ArgyllCMS 进程，正在清理...")
                for pid, cmd in orphaned:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        self._log_status(f"已终止残留进程 (PID: {pid})")
                    except ProcessLookupError:
                        pass  # 进程已经不存在
                    except PermissionError:
                        self._log_status(f"无权限终止进程 (PID: {pid})")
                    except Exception as e:
                        self._log_status(f"终止进程失败 (PID: {pid}): {e}")

                # 等待进程清理
                time.sleep(0.5)

        except Exception as e:
            # 清理失败不应该阻止程序启动
            pass

    def _scan_conflicting_processes(self) -> List[Dict[str, any]]:
        """
        扫描系统中正在运行的干扰进程

        Returns:
            List[Dict]: 发现的冲突进程列表，每个元素包含 {'name': 进程名, 'pid': PID}
        """
        conflicts: List[Dict[str, any]] = []

        try:
            # 使用 ps -ef 获取所有进程列表
            result = subprocess.run(
                ['ps', '-ef'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                self._log_error(f"执行 ps -ef 失败: {result.stderr}")
                return conflicts

            # 解析输出，查找冲突进程
            lines = result.stdout.strip().split('\n')

            for line in lines:
                # ps -ef 输出格式: UID PID PPID C STIME TTY TIME CMD
                parts = line.split()
                if len(parts) < 8:
                    continue

                # 获取 PID 和命令名
                pid = parts[1]
                cmd = parts[7]  # 命令路径或名称

                # 提取进程名（从命令路径中获取）
                process_name = cmd.split('/')[-1] if '/' in cmd else cmd

                # 不区分大小写的模糊匹配
                for blacklisted in MACOS_CONFlicting_PROCESSES:
                    if blacklisted.lower() in process_name.lower():
                        # 避免重复添加同一个进程
                        if not any(c['name'] == process_name for c in conflicts):
                            conflicts.append({
                                'name': process_name,
                                'pid': pid,
                                'cmd': cmd
                            })
                        break

        except subprocess.TimeoutExpired:
            self._log_error("扫描进程超时")
        except Exception as e:
            self._log_error(f"扫描进程时发生错误: {str(e)}")

        return conflicts

    def _terminate_process(self, process_name: str, pid: str) -> bool:
        """
        尝试终止指定进程

        Args:
            process_name: 进程名称
            pid: 进程 PID

        Returns:
            bool: 是否成功终止
        """
        try:
            # 首先尝试使用 killall（按进程名）
            result = subprocess.run(
                ['killall', process_name],
                capture_output=True,
                text=True,
                timeout=5
            )

            # 检查是否成功
            if result.returncode == 0:
                self._log_status(f"成功结束进程 [{process_name}]")
                time.sleep(0.5)  # 等待进程完全退出
                return True

            # killall 失败，尝试使用 kill -9（按 PID）
            result = subprocess.run(
                ['kill', '-9', pid],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                self._log_status(f"成功结束进程 [{process_name}] (PID: {pid})")
                time.sleep(0.5)
                return True

            # 检查错误信息
            stderr = result.stderr.strip().lower()

            if 'permission denied' in stderr or 'operation not permitted' in stderr:
                self._log_error(f"权限不足，无法结束进程 [{process_name}]（可能以 root 权限运行）")
                return False
            elif 'no such process' in stderr:
                # 进程已经不存在了，视为成功
                return True
            else:
                self._log_error(f"结束进程 [{process_name}] 失败: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            self._log_error(f"结束进程 [{process_name}] 超时")
            return False
        except Exception as e:
            self._log_error(f"结束进程 [{process_name}] 时发生异常: {str(e)}")
            return False

    def _handle_cleanup_failure(self, failed_processes: List[str]):
        """
        处理清理失败的情况，生成用户提示

        Args:
            failed_processes: 清理失败的进程名列表
        """
        # 构建详细的用户提示
        process_list = ', '.join(failed_processes)

        # 生成手动清理命令示例
        manual_commands = []
        for process_name in failed_processes:
            manual_commands.append(f"sudo killall {process_name}")

        manual_cmd_str = ' 或 '.join(manual_commands) if len(manual_commands) > 1 else manual_commands[0]

        error_message = (
            f"无法自动结束占用探头的进程 [{process_list}]。\n"
            f"这些进程可能以 root 权限运行。\n"
            f"请打开终端手动执行以下命令:\n"
            f"  {manual_cmd_str}\n"
            f"或在「活动监视器」中强制退出相关官方校色软件（如 X-Rite Device Services、i1Profiler），\n"
            f"然后再点击连接。"
        )

        self._error_message = error_message
        self._log_error(error_message)

        # 发送用户提示到前端（如果有回调）
        if self._on_error_callback:
            self._on_error_callback(error_message)

    def set_probe_type(self, probe_type: ProbeType):
        """设置探头类型"""
        self._probe_type = probe_type

    def set_display_type(self, display_type: DisplayType):
        """设置显示器类型"""
        self._display_type = display_type

    def set_current_patch_rgb(self, rgb: Tuple[int, int, int]):
        """
        设置当前待测色块的 RGB 值（用于暗场延迟判断）

        Args:
            rgb: 色块的 RGB 值元组 (r, g, b)
        """
        self._current_patch_rgb = rgb

    def set_argyll_path(self, path: str):
        """设置 ArgyllCMS bin 目录路径"""
        self._argyll_path = path

    def set_correction_file(self, path: str):
        """
        设置光谱校正文件路径 (CCSS/CCMX)

        色度计（如 i1 Display Pro）需要此文件来匹配显示器背光类型。
        分光光度计（如 i1 Pro 2）不需要此文件。

        Args:
            path: 校正文件的绝对路径，空字符串表示清除
        """
        self._correction_file_path = path

    def set_callbacks(self,
                      on_measurement: Callable = None,
                      on_error: Callable = None,
                      on_status: Callable = None):
        """设置回调函数"""
        self._on_measurement_callback = on_measurement
        self._on_error_callback = on_error
        self._on_status_callback = on_status

    # ========== 状态查询 ==========

    def is_connected(self) -> bool:
        """检查探头是否已连接"""
        return self._is_connected and self._process is not None and self._process.poll() is None

    def is_measuring(self) -> bool:
        """检查是否正在测量"""
        return self._is_measuring

    def get_last_measurement(self) -> Optional[Tuple[float, float, float]]:
        """获取最后一次测量结果 (x, y, Y)"""
        return self._last_measurement

    def get_error_message(self) -> str:
        """获取错误消息"""
        return self._error_message

    def get_recommended_delay(self) -> int:
        """
        获取当前探头类型的推荐测量延迟（毫秒）

        在屏幕显示色块后需要等待一段时间让像素稳定，
        否则会测到过渡色。不同探头有不同的响应速度。

        Returns:
            int: 推荐延迟时间（毫秒）
        """
        return PROBE_RECOMMENDED_DELAYS.get(
            self._probe_type,
            PROBE_RECOMMENDED_DELAYS["default"]
        )

    def get_probe_type(self) -> ProbeType:
        """
        获取当前设置的探头类型

        Returns:
            ProbeType: 当前探头类型
        """
        return self._probe_type

    def get_instrument_port(self) -> Optional[int]:
        """
        获取当前仪器端口序号

        Returns:
            Optional[int]: 仪器端口序号，未设置时返回 None
        """
        return self._instrument_port

    def get_display_type(self) -> DisplayType:
        """
        获取当前显示器类型

        Returns:
            DisplayType: 当前显示器类型
        """
        return self._display_type

    def get_correction_file_path(self) -> str:
        """
        获取当前光谱校正文件路径

        Returns:
            str: 校正文件路径，未设置时返回空字符串
        """
        return self._correction_file_path

    # ========== 断点续测与容错方法 ==========

    def set_reconnect_config(self, max_attempts: int = 3, interval: float = 2.0, timeout: float = 30.0):
        """
        设置重连配置参数

        Args:
            max_attempts: 最大重连尝试次数
            interval: 重连间隔时间（秒）
            timeout: 测量超时时间（秒）
        """
        self._max_reconnect_attempts = max_attempts
        self._reconnect_interval = interval
        self._measurement_timeout = timeout

    def is_reconnecting(self) -> bool:
        """
        检查是否正在重连

        Returns:
            bool: 是否处于重连状态
        """
        return self._is_reconnecting

    def get_reconnect_attempt(self) -> int:
        """
        获取当前重连尝试次数

        Returns:
            int: 当前重连尝试次数
        """
        return self._current_reconnect_attempt

    def get_max_reconnect_attempts(self) -> int:
        """
        获取最大重连尝试次数

        Returns:
            int: 最大重连尝试次数
        """
        return self._max_reconnect_attempts

    def check_measurement_timeout(self) -> bool:
        """
        检查测量是否超时

        如果从上次成功测量到现在超过了 `_measurement_timeout` 秒，
        则认为测量超时，探头可能已断开。

        Returns:
            bool: 是否超时
        """
        if self._last_measurement_time is None:
            # 还没有成功测量过，使用连接时间作为基准
            return False

        elapsed = time.time() - self._last_measurement_time
        return elapsed > self._measurement_timeout and self._is_measuring

    def reconnect(self) -> bool:
        """
        尝试重新连接探头（自动重连机制）

        流程：
        1. 安全断开当前连接（清理进程和线程）
        2. 等待 `_reconnect_interval` 秒
        3. 尝试重新连接
        4. 如果失败，重复步骤 1-3，最多 `_max_reconnect_attempts` 次

        Returns:
            bool: 是否成功重连
        """
        if self._is_reconnecting:
            self._log_status("已在重连中，跳过重复重连请求")
            return False

        self._is_reconnecting = True
        self._current_reconnect_attempt = 0

        # 保存当前配置，重连后恢复
        saved_probe_type = self._probe_type
        saved_display_type = self._display_type
        saved_correction_file = self._correction_file_path
        saved_instrument_port = self._instrument_port

        self._log_status(f"开始自动重连流程，最大尝试次数: {self._max_reconnect_attempts}")

        while self._current_reconnect_attempt < self._max_reconnect_attempts:
            self._current_reconnect_attempt += 1
            attempt_num = self._current_reconnect_attempt
            max_attempts = self._max_reconnect_attempts

            # 发送重连状态通知
            if self._on_status_callback:
                try:
                    self._on_status_callback(f"探头已断开，正在尝试重连 ({attempt_num}/{max_attempts})...")
                except Exception:
                    pass

            self._log_status(f"重连尝试 {attempt_num}/{max_attempts}")

            # 安全断开当前连接
            self._safe_disconnect_for_reconnect()

            # 等待 USB 端口释放
            self._log_status(f"等待 {self._reconnect_interval} 秒...")
            time.sleep(self._reconnect_interval)

            # 尝试重新连接
            # 恢复之前保存的配置
            self._probe_type = saved_probe_type
            self._display_type = saved_display_type
            self._correction_file_path = saved_correction_file

            # 清除错误状态
            self._error_message = ""
            self._shutdown_event.clear()
            self._hardware_error_event.clear()

            success = self.connect()

            if success:
                self._log_status(f"重连成功（尝试 {attempt_num}/{max_attempts}）")
                self._is_reconnecting = False
                self._current_reconnect_attempt = 0
                # 重置测量时间戳
                self._last_measurement_time = time.time()
                return True

            self._log_status(f"重连失败（尝试 {attempt_num}/{max_attempts}）: {self._error_message}")

        # 所有尝试都失败
        self._is_reconnecting = False
        self._current_reconnect_attempt = 0

        error_msg = f"自动重连失败，已尝试 {self._max_reconnect_attempts} 次。请检查 USB 连接后手动恢复测量。"
        self._error_message = error_msg
        self._log_error(error_msg)

        # 发送挂起状态通知
        if self._on_status_callback:
            try:
                self._on_status_callback("测量已挂起，请检查 USB 连接")
            except Exception:
                pass

        return False

    def _safe_disconnect_for_reconnect(self):
        """
        为重连目的的安全断开（不清理配置）

        相比完整的 disconnect()，此方法：
        1. 不清除 `_probe_type`、`_display_type` 等配置
        2. 不清除 `_instrument_port`
        3. 只清理进程和线程
        """
        # 设置 shutdown 事件
        self._shutdown_event.set()
        self._hardware_error_event.set()

        if self._process:
            try:
                # 发送退出命令
                if self._process.poll() is None:
                    try:
                        self._process.stdin.write("q\n")
                        self._process.stdin.flush()
                    except Exception:
                        pass

                # 等待后台线程退出
                if self._reader_thread and self._reader_thread.is_alive():
                    self._reader_thread.join(timeout=2.0)

                # 等待进程退出
                time.sleep(0.5)

                # 强制终止进程
                if self._process.poll() is None:
                    if platform.system() == 'Windows' and self._process.pid:
                        try:
                            subprocess.run(
                                ['taskkill', '/F', '/PID', str(self._process.pid), '/T'],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                        except Exception:
                            self._process.terminate()
                    else:
                        self._process.terminate()

                    time.sleep(0.5)
                    if self._process.poll() is None:
                        self._process.kill()

            except Exception as e:
                self._log_error(f"安全断开时发生错误: {str(e)}")

            finally:
                self._process = None
                self._reader_thread = None
                self._is_connected = False
                self._is_measuring = False

                # 清空输出缓冲区
                with self._buffer_lock:
                    self._output_buffer = ""

                self._log_status("已安全断开（准备重连）")

    # ========== 核心方法 ==========

    def connect(self) -> bool:
        """
        连接探头：启动 spotread 进程

        流程：
        1. macOS 系统下先清理可能占用 USB 端口的干扰进程
        2. 启动 spotread 进程
        3. 等待探头初始化完成

        Returns:
            bool: 是否成功启动
        """
        self._log_status(f"[DEBUG] connect() 被调用，当前 _shutdown_event={self._shutdown_event.is_set()}")
        if self.is_connected():
            self._log_status("探头已连接")
            return True

        # ========== macOS 环境清理 ==========
        # 在连接前清理可能占用探头的后台进程
        if platform.system() == 'Darwin':
            self._log_status("macOS 系统：执行环境清理...")
            cleanup_results = self._cleanup_macos_processes()

            # 检查是否有清理失败的进程
            failed_cleanups = [name for name, success in cleanup_results.items() if not success]

            if failed_cleanups:
                # 有无法清理的进程，提示用户手动处理
                # 注意：这里不直接返回 False，而是让用户决定是否继续尝试连接
                # 因为有时候即使有这些进程，spotread 也可能能连接（取决于具体占用情况）
                self._log_status("部分进程清理失败，建议手动处理后再尝试连接")
                # 继续尝试连接，让 spotread 自己判断是否能访问探头

            # 等待 USB 端口释放
            if cleanup_results:
                self._log_status("等待 USB 端口释放...")
                time.sleep(1.0)

        # ========== 设备查找与选择 ==========
        if self._instrument_port is not None:
            # 本次会话已成功定位过设备：直接复用端口，跳过耗时的设备枚举
            # （spotread -c ? 会探测所有串口含蓝牙，实测 20+ 秒）。
            # 若探头已被拔掉，spotread 启动会报 no instrument，由失败分支清除缓存，
            # 下次连接重新枚举。
            self._log_status(f"复用已知的仪器端口 [{self._instrument_port}]，跳过设备枚举")
            found_port = self._instrument_port
        else:
            # 首先尝试用当前设置的探头类型查找设备
            self._log_status(f"查找 {self._probe_type.value} 类型设备...")
            found_port = self._find_instrument_port()

            if found_port is None:
                # 当前探头类型不匹配，尝试自动检测
                self._log_status("当前探头类型不匹配，尝试自动检测...")
                detected_type = self.auto_detect_probe_type()

                if detected_type is not None:
                    # 检测到探头类型，自动切换
                    self._log_status(f"自动切换探头类型: {self._probe_type.value} -> {detected_type.value}")
                    self._probe_type = detected_type

                    # 再次查找设备端口
                    found_port = self._find_instrument_port()

                    if found_port is None:
                        self._error_message = f"自动检测后仍无法找到匹配设备"
                        self._log_error(self._error_message)
                        return False
                else:
                    # 无法自动检测（多设备或无设备）
                    self._error_message = f"未找到 {self._probe_type.value} 类型的设备，请手动选择正确的探头类型"
                    self._log_error(self._error_message)
                    return False

        self._instrument_port = found_port

        try:
            # ========== 清除事件状态 ==========
            # 在连接前清除所有事件，确保干净的状态
            self._shutdown_event.clear()
            self._hardware_error_event.clear()
            self._result_event.clear()  # 清除结果事件
            self._last_detected_error = ""
            self._current_result = None  # 清除上次结果

            # 清空输出缓冲区
            with self._buffer_lock:
                self._output_buffer = ""

            # ========== 等待旧的读取线程退出 ==========
            # 如果存在旧的读取线程，等待它完全退出后再创建新线程
            if self._reader_thread and self._reader_thread.is_alive():
                self._log_status("等待旧的读取线程退出...")
                # 设置 shutdown 事件通知旧线程退出
                self._shutdown_event.set()
                # 等待最多 5 秒（增加超时时间）
                self._reader_thread.join(timeout=5.0)
                if self._reader_thread.is_alive():
                    self._log_status("警告: 旧的读取线程未能在超时内退出")
                # 确保线程引用被清除
                self._reader_thread = None

            # ========== 再次清除事件状态（确保干净状态） ==========
            # 如果刚才设置了 shutdown_event，现在必须清除
            # 注意：只有在确认旧线程已经退出后才能清除
            self._shutdown_event.clear()
            self._hardware_error_event.clear()

            # 构建 spotread 命令
            cmd = self._build_command()

            self._log_status(f"启动 spotread: {cmd}")

            # 启动进程
            # 注意：stderr=subprocess.STDOUT 将标准错误合并到标准输出
            # 统一由 _read_output 守护线程读取，避免 stderr 缓冲区满后导致死锁
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1  # 行缓冲
            )

            # 启动输出读取线程
            # 注意：设置为 daemon=True，但线程内部会检查 shutdown 事件安全退出
            self._reader_thread = threading.Thread(
                target=self._read_output,
                name="spotread-output-reader",
                daemon=True
            )
            self._reader_thread.start()

            # 等待进程初始化
            time.sleep(1)

            # 检查进程是否正常运行
            if self._process.poll() is not None:
                # 由于 stderr 被合并到 stdout (stderr=subprocess.STDOUT)，
                # self._process.stderr 是 None，需要从缓冲区读取输出
                time.sleep(0.5)  # 给读取线程时间收集输出
                with self._buffer_lock:
                    output = self._output_buffer
                self._error_message = f"spotread 启动失败，退出码={self._process.returncode}"
                if output:
                    self._error_message += f"，输出: {output[:200]}"
                self._log_error(self._error_message)
                # self._is_connected = False # 注释掉，让上层决定是否需要重连
                # 端口缓存可能已失效（如探头被拔掉），清除以便下次重新枚举
                self._instrument_port = None
                return False

            # 等待探头初始化完成（读取输出直到看到就绪提示）
            ready = self._wait_for_ready()

            if ready:
                self._is_connected = True
                self._log_status(f"[DEBUG] 探头连接成功，_shutdown_event={self._shutdown_event.is_set()}，即将返回 True")
                return True
            else:
                self._error_message = "探头初始化超时"
                self._log_error(self._error_message)
                # 端口缓存可能已失效（如探头被拔掉），清除以便下次重新枚举
                self._instrument_port = None
                self.disconnect()
                return False

        except FileNotFoundError:
            self._error_message = "找不到 spotread 命令，请确保 ArgyllCMS 已安装并添加到 PATH"
            self._log_error(self._error_message)
            return False
        except Exception as e:
            self._error_message = f"连接探头时发生错误: {str(e)}"
            self._log_error(self._error_message)
            return False

    def disconnect(self):
        """
        断开探头：安全退出 spotread 进程和后台线程

        流程：
        1. 设置 shutdown 事件，通知后台线程安全退出
        2. 向 spotread 发送退出命令
        3. 等待后台线程退出
        4. 强制终止进程（如果需要）
        5. 清理状态
        """
        # 添加调用栈跟踪，帮助定位谁调用了 disconnect
        import traceback
        self._log_status(f"[DEBUG] disconnect() 被调用，调用栈:\n{''.join(traceback.format_stack()[-4:])}")

        # ========== 设置 shutdown 事件 ==========
        # 通知所有等待的线程和后台读取线程安全退出
        self._shutdown_event.set()
        self._hardware_error_event.set()  # 也设置错误事件，打断任何等待

        if self._process:
            try:
                # 发送退出命令
                if self._process.poll() is None:
                    try:
                        self._process.stdin.write("q\n")
                        self._process.stdin.flush()
                    except Exception:
                        # stdin 可能已关闭
                        pass

                # 等待后台线程退出（最多等待 2 秒）
                if self._reader_thread and self._reader_thread.is_alive():
                    self._reader_thread.join(timeout=2.0)
                    if self._reader_thread.is_alive():
                        self._log_status("后台线程未能在超时内退出")

                # 等待进程退出（最多等待 1 秒）
                time.sleep(0.5)

                # 如果进程还在运行，强制终止
                if self._process.poll() is None:
                    # ========== Windows 平台：使用 taskkill 更强硬 ==========
                    if platform.system() == 'Windows' and self._process.pid:
                        try:
                            import subprocess as _subproc
                            _subproc.run(
                                ['taskkill', '/F', '/PID', str(self._process.pid), '/T'],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            self._log_status("已使用 taskkill 强制终止 spotread 进程树")
                        except Exception as e:
                            self._log_status(f"taskkill 失败，尝试常规终止: {e}")
                            self._process.terminate()
                    else:
                        self._process.terminate()

                    time.sleep(0.5)
                    if self._process.poll() is None:
                        self._process.kill()
                        self._log_status("强制终止 spotread 进程 (SIGKILL)")

            except Exception as e:
                self._log_error(f"断开探头时发生错误: {str(e)}")

            finally:
                self._process = None
                self._reader_thread = None
                # self._is_connected = False # 注释掉，让上层决定是否需要重连
                self._is_measuring = False

                # 清除事件状态
                self._shutdown_event.clear()
                self._hardware_error_event.clear()
                self._last_detected_error = ""

                # 清空输出缓冲区
                with self._buffer_lock:
                    self._output_buffer = ""

                self._log_status("探头已断开")

    def calibrate(self) -> bool:
        """
        校准探头（需要将探头放在校准板上）

        Returns:
            bool: 是否校准成功
        """
        if not self.is_connected():
            self._error_message = "探头未连接"
            self._log_error(self._error_message)
            return False

        try:
            self._log_status("开始校准探头...")
            self._is_measuring = True

            # 发送校准命令（通常是 'c'）
            self._process.stdin.write("c\n")
            self._process.stdin.flush()

            # 等待校准完成
            time.sleep(2)

            # 检查输出中是否有校准成功的提示
            with self._buffer_lock:
                output = self._output_buffer

            if "calibration" in output.lower() or "calibrated" in output.lower():
                self._log_status("探头校准成功")
                self._is_measuring = False
                return True
            else:
                self._log_status("探头校准完成")
                self._is_measuring = False
                return True

        except Exception as e:
            self._error_message = f"校准探头时发生错误: {str(e)}"
            self._log_error(self._error_message)
            self._is_measuring = False
            return False

    def measure(self) -> bool:
        """
        执行一次测量（非阻塞模式 / Fire-and-Forget）

        流程：
        1. 检查进程状态
        2. 清除之前的结果和错误状态
        3. 向 spotread 发送换行符触发测量
        4. 立即返回，不等待结果

        **重要**：
        - 此方法是非阻塞的，只发送命令并立即返回
        - 测量结果由后台线程 `_read_output` 捕获，并通过 `_on_measurement_callback` 回调传递
        - 不会阻塞 PyQt 主事件循环，避免 macOS IMKCFRunLoopWakeUpReliable 错误
        - 上层（如 backend.py）需要在回调中处理结果并触发下一个测量

        Returns:
            bool: 是否成功发送测量命令
        """
        # ========== 检查进程状态 ==========
        if not self.is_connected():
            self._error_message = "探头未连接，请先调用 connect()"
            self._log_error(self._error_message)
            return False

        if self._is_measuring:
            self._log_status("正在测量中，请等待...")
            return False

        try:
            self._is_measuring = True
            self._log_status("触发测量...")

            # ========== 动态延迟补偿：暗场 LCD 额外等待 ==========
            # LCD 面板在暗场灰阶切换时液晶分子偏转较慢，
            # 需要在探头推荐延迟基础上额外等待，确保测到稳定颜色而非"拖影"
            if (self._display_type == DisplayType.LCD and
                self._current_patch_rgb is not None):

                r, g, b = self._current_patch_rgb

                # 判断是否为暗场（RGB 均小于 50）
                if r < 50 and g < 50 and b < 50:
                    # 额外等待 150ms，等待液晶分子偏转到位
                    extra_delay = 0.150  # 150ms
                    self._log_status(
                        f"暗场色块 RGB({r},{g},{b})，"
                        f"额外等待 {extra_delay*1000:.0f}ms 等待液晶偏转"
                    )
                    time.sleep(extra_delay)

            # ========== 清除之前的状态 ==========
            self._result_event.clear()
            self._hardware_error_event.clear()
            self._current_result = None
            self._last_detected_error = ""

            # 清空输出缓冲区
            with self._buffer_lock:
                self._output_buffer = ""

            # ========== 检查进程状态（发送前） ==========
            # 必须在写入 stdin 前检查，避免 BrokenPipeError
            if self._process.poll() is not None:
                self._error_message = "spotread 进程已终止，无法发送测量命令"
                self._log_error(self._error_message)
                self._is_measuring = False
                return False

            # ========== 发送换行符触发测量 ==========
            # 注意：在管道（PIPE）模式下，必须发送换行符才能正确触发 spotread 测量
            # 缺少换行符会导致 spotread 内部流状态异常并退出
            try:
                self._process.stdin.write("\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self._error_message = f"发送测量命令失败: 进程可能已终止 ({str(e)}"
                self._log_error(self._error_message)
                self._is_measuring = False
                return False

            # ========== 非阻塞模式：立即返回 ==========
            # 测量结果由后台线程 _read_output 捕获，并通过回调传递
            self._log_status("测量命令已发送，等待后台线程捕获结果...")
            return True

        except Exception as e:
            self._error_message = f"测量时发生错误: {str(e)}"
            self._log_error(self._error_message)
            self._is_measuring = False
            return False

    def measure_sync(self, timeout: float = 30.0) -> Optional[Tuple[float, float, float]]:
        """
        同步测量：触发一次测量并阻塞等待结果

        供 AutoCal 等后台工作流线程使用（不占用 Qt 主线程）。
        结果同时会照常触发 on_measurement 回调（UI 实时显示不受影响）。

        Args:
            timeout: 等待结果超时（秒）

        Returns:
            (x, y, Y) 测量结果，超时或失败返回 None
        """
        if not self.measure():
            return None

        if not self._result_event.wait(timeout=timeout):
            self._error_message = f"同步测量超时 ({timeout}s)"
            self._log_error(self._error_message)
            self._is_measuring = False
            return None

        return self.get_last_measurement()

    # ========== 内部方法 ==========

    def _build_command(self) -> list:
        """
        构建 spotread 命令

        基础命令: spotread -e
        -e: 使用 emissive（自发光）模式（交互模式，按键触发连续测量）

        可选参数：
        -c: 仪器端口序号（多设备时用于选择特定设备）
        -y: 显示器类型（spotread 仅接受 n|l=非刷新型、r|c=刷新型）
        -X: 光谱校正文件路径 (CCSS/CCMX)，仅色度计需要
        """
        # 根据操作系统确定可执行文件名
        system = platform.system()
        spotread_name = "spotread.exe" if system == "Windows" else "spotread"

        # 构建命令
        if self._argyll_path:
            cmd = [str(Path(self._argyll_path) / spotread_name)]
        else:
            cmd = [spotread_name]

        # 基础参数：自发光模式（不能用 -O，-O 表示测量一次后退出）
        cmd.extend(["-e"])

        # ========== 仪器端口选择 ==========
        # 如果指定了仪器端口，使用 -c 参数
        if self._instrument_port is not None:
            cmd.extend(["-c", str(self._instrument_port)])
            self._log_status(f"使用仪器端口: {self._instrument_port}")

        # 显示器类型：spotread 的 -y 参数仅接受 n|l（非刷新型）与 r|c（刷新型）
        # 注意：-d 是"显示密度值"开关，不接收类型参数——误用会把类型字母当作日志文件名
        # （DisplayType 的细分字母来自 dispcal/ccxxmake，spotread 无对应选项，此处归一化）
        refresh_letters = {"c", "m"}  # CRT / 等离子为刷新型显示
        y_letter = "c" if self._display_type.value in refresh_letters else "l"
        cmd.extend(["-y", y_letter])

        # ========== 光谱校正文件 (CCSS/CCMX) ==========
        # 如果传入了校正文件路径，使用 Path.resolve() 确保路径绝对且有效
        if self._correction_file_path:
            try:
                resolved_path = Path(self._correction_file_path).resolve()
                if resolved_path.exists():
                    cmd.extend(["-X", str(resolved_path)])
                    self._log_status(f"已加载光谱校正文件: {resolved_path}")
                else:
                    self._log_error(f"光谱校正文件不存在: {resolved_path}")
            except Exception as e:
                self._log_error(f"解析光谱校正文件路径失败: {str(e)}")

        return cmd

    def _read_output(self):
        """
        后台线程：持续读取 spotread 的 stdout 输出（永不退出模式）

        核心原则：
        1. **只有** `_shutdown_event` 被设置时才退出循环
        2. 检测到测量结果后，设置 `_result_event` 通知主线程，然后继续循环
        3. 检测到硬件错误后，设置 `_hardware_error_event`，然后继续循环
        4. 进程终止不会导致线程退出，而是等待 reconnect

        此设计确保"一次连接，连续测量，最后断开"的常驻模式。
        """
        last_lines = []  # 用于检测重复输出
        repeat_count = 0
        max_repeat = 5  # 相同内容重复5次后触发警告

        self._log_status("输出读取线程启动，进入常驻模式")

        while True:
            # ========== 唯一的退出条件 ==========
            # 只有 shutdown 事件被设置时才退出
            if self._shutdown_event.is_set():
                self._log_status("输出读取线程收到退出信号，正在安全退出...")
                break

            # ========== 进程状态检查（不退出，只跳过） ==========
            # 如果进程不存在或已终止，等待一下再检查
            # 这允许 reconnect 后继续使用同一个线程
            if self._process is None:
                time.sleep(0.1)
                continue

            if self._process.poll() is not None:
                # 进程已终止，但不要退出线程
                # 等待可能的 reconnect
                time.sleep(0.1)
                continue

            try:
                # ========== 读取输出 ==========
                line = self._process.stdout.readline()

                if not line:
                    # 空行，继续
                    time.sleep(0.05)
                    continue

                # ========== 存储到缓冲区 ==========
                with self._buffer_lock:
                    self._output_buffer += line

                stripped = line.strip()

                if not stripped:
                    continue

                # ========== 测量结果检测 ==========
                # 检查是否包含 XYZ 测量结果
                xyz_match = self.XYZ_PATTERN.search(stripped)

                if xyz_match:
                    # 提取 X, Y, Z 值
                    try:
                        X = float(xyz_match.group(1))
                        Y = float(xyz_match.group(2))
                        Z = float(xyz_match.group(3))

                        # XYZ 转换为 xyY
                        result = self._xyz_to_xyy(X, Y, Z)

                        if result:
                            # 存储结果
                            self._current_result = result
                            self._last_measurement = result
                            # 设置事件通知主线程
                            self._result_event.set()

                            # ========== 更新测量时间戳（用于超时检测） ==========
                            self._last_measurement_time = time.time()

                            self._log_status(
                                f"测量结果已就绪: x={result[0]:.4f}, y={result[1]:.4f}, Y={result[2]:.6f}"
                            )

                            # ========== 非阻塞模式：直接调用回调 ==========
                            # 重置测量状态，允许下一次测量
                            self._is_measuring = False

                            # 调用测量回调，通知上层（如 backend.py）
                            if self._on_measurement_callback:
                                try:
                                    self._on_measurement_callback(result)
                                except Exception as e:
                                    self._log_error(f"测量回调执行失败: {str(e)}")

                            # 清空缓冲区，为下一次测量做准备
                            with self._buffer_lock:
                                self._output_buffer = ""

                            # 重置重复计数
                            repeat_count = 0
                            last_lines.clear()

                            # 继续循环，等待下一次测量
                            continue
                    except (ValueError, ZeroDivisionError) as e:
                        self._log_error(f"解析测量结果失败: {str(e)}")

                # ========== 硬件错误检测 ==========
                line_lower = stripped.lower()
                detected_error = None

                for error_keyword in SPOTREAD_ERROR_KEYWORDS:
                    if error_keyword.lower() in line_lower:
                        detected_error = error_keyword
                        break

                if detected_error:
                    self._set_hardware_error(stripped, detected_error)
                    # 如果是 USB 断开类型的错误，立即退出循环避免刷屏
                    keyword_lower = detected_error.lower()
                    is_usb_disconnect = any(
                        usb_keyword in keyword_lower
                        for usb_keyword in USB_DISCONNECT_KEYWORDS
                    )
                    if is_usb_disconnect:
                        self._log_status("检测到 USB 断开，停止读取输出...")
                        break
                    # 其他错误继续循环，不退出

                # ========== 重复输出检测 ==========
                if len(last_lines) > 5:
                    last_lines.pop(0)
                last_lines.append(stripped)

                if len(last_lines) >= 3:
                    recent = last_lines[-3:]
                    if len(last_lines) >= 6 and recent == last_lines[-6:-3]:
                        repeat_count += 1
                        if repeat_count >= max_repeat:
                            self._set_hardware_error(
                                "重复输出检测：探头可能处于错误状态",
                                "wrong position"
                            )
                            repeat_count = 0
                            last_lines.clear()
                    else:
                        repeat_count = 0

                # ========== 打印输出 ==========
                # 过滤掉 macOS GUI 应用下的终端 ioctl 警告（无害）
                if 'tcgetattr failed' in stripped or 'tcsetattr failed' in stripped:
                    continue  # 不打印这些无害警告

                try:
                    sys.stdout.write(f"[spotread] {stripped}\n")
                    sys.stdout.flush()
                except (ValueError, AttributeError):
                    pass

            except Exception as e:
                # 检查是否是 shutdown 导致的异常
                if self._shutdown_event.is_set():
                    break
                # 记录异常但继续
                try:
                    sys.stderr.write(f"[spotread reader error] {str(e)}\n")
                    sys.stderr.flush()
                except (ValueError, AttributeError):
                    pass
                time.sleep(0.1)

        self._log_status("输出读取线程已退出")

    def _set_hardware_error(self, raw_message: str, detected_keyword: str):
        """
        设置硬件错误状态

        此方法设置错误事件和消息，通知等待线程有错误发生。
        如果检测到 USB 断开关键词，会自动断开连接。

        Args:
            raw_message: 原始错误消息
            detected_keyword: 检测到的关键词
        """
        # 获取友好的错误提示
        friendly_message = ERROR_MESSAGE_MAP.get(
            detected_keyword.lower(),
            f"硬件错误: {raw_message}"
        )

        self._last_detected_error = friendly_message
        self._error_message = friendly_message

        # 设置硬件错误事件，通知等待线程
        self._hardware_error_event.set()

        # ========== 重置测量状态 ==========
        # 允许后续测量请求，避免因错误状态导致无法继续测量
        self._is_measuring = False

        # 记录错误
        self._log_error(f"检测到硬件错误: {friendly_message}")

        # ========== 检查是否是 USB 断开 ==========
        # 如果检测到 USB 断开关键词，自动断开连接
        keyword_lower = detected_keyword.lower()
        is_usb_disconnect = any(
            usb_keyword in keyword_lower
            for usb_keyword in USB_DISCONNECT_KEYWORDS
        )

        if is_usb_disconnect:
            self._log_error("检测到 USB 设备断开，正在自动断开连接...")
            self._is_connected = False
            # 清理进程和线程（异步方式，避免在后台线程中直接操作）
            self._shutdown_event.set()

        # 触发错误回调
        if self._on_error_callback:
            try:
                self._on_error_callback(friendly_message)
            except Exception as e:
                self._log_error(f"错误回调执行失败: {str(e)}")

    def _wait_for_ready(self, timeout: float = 60.0) -> bool:
        """
        等待 spotread 就绪

        Args:
            timeout: 超时时间（秒）

        Returns:
            bool: 是否就绪
        """
        start_time = time.time()
        check_interval = 0.3  # 检查间隔（秒）

        # 清除之前的错误事件
        self._hardware_error_event.clear()

        while time.time() - start_time < timeout:
            # ========== 检查硬件错误事件 ==========
            # 如果后台线程检测到硬件错误，立即返回
            if self._hardware_error_event.is_set():
                self._error_message = self._last_detected_error or "硬件错误"
                self._log_error(f"等待就绪时检测到硬件错误: {self._error_message}")
                return False

            # ========== 检查 shutdown 事件 ==========
            if self._shutdown_event.is_set():
                return False

            with self._buffer_lock:
                output = self._output_buffer

            # 检查是否有就绪提示（通常是 "Place on measurement area" 或类似提示）
            # 或者检查是否有错误（如 "No instrument found"）
            if "no instrument" in output.lower():
                self._error_message = "未检测到探头，请检查探头是否正确连接"
                return False

            if "wrong position" in output.lower() or "sensor being in the wrong position" in output.lower():
                # 探头已连接但位置不正确 - 这是正常的，表示探头已就绪
                # 用户需要在测量时将探头放在正确位置
                return True

            if "place" in output.lower() or "ready" in output.lower() or "hit" in output.lower():
                return True

            # 检查进程是否还在运行
            if self._process is None or self._process.poll() is not None:
                return False

            time.sleep(check_interval)

        return False

    def _wait_for_measurement(self, timeout: float = 30.0) -> Optional[Tuple[float, float, float]]:
        """
        等待测量完成并解析结果

        Args:
            timeout: 超时时间（秒）

        Returns:
            Optional[Tuple[float, float, float]]: (x, y, Y) 或 None
        """
        start_time = time.time()
        check_interval = 0.2  # 检查间隔（秒）

        # 清除之前的错误事件
        self._hardware_error_event.clear()

        while time.time() - start_time < timeout:
            # ========== 检查硬件错误事件 ==========
            # 如果后台线程检测到硬件错误，立即返回
            if self._hardware_error_event.is_set():
                self._error_message = self._last_detected_error or "硬件错误"
                self._log_error(f"等待测量时检测到硬件错误: {self._error_message}")
                return None

            # ========== 检查 shutdown 事件 ==========
            if self._shutdown_event.is_set():
                return None

            with self._buffer_lock:
                output = self._output_buffer

            # 尝试解析测量结果
            result = self._parse_measurement(output)

            if result:
                return result

            # 检查进程是否还在运行
            if self._process is None or self._process.poll() is not None:
                return None

            time.sleep(check_interval)

        return None

    def _parse_measurement(self, output: str) -> Optional[Tuple[float, float, float]]:
        """
        从 spotread 输出中解析测量结果

        支持的格式：
        1. XYZ 格式: "Result is XYZ: 0.033364 0.029912 0.062078"
           - 需要转换为 xyY: x = X/(X+Y+Z), y = Y/(X+Y+Z), Y 保持不变
        2. Yxy 格式: "Yxy: Y=..., x=..., y=..."
        3. CIE x,y,Y 格式: "CIE x,y,Y = x, y, Y"

        Args:
            output: spotread 的输出文本

        Returns:
            Optional[Tuple[float, float, float]]: (x, y, Y) 或 None
        """
        # ========== 优先尝试 XYZ 格式（当前 spotread 实际输出） ==========
        xyz_match = self.XYZ_PATTERN.search(output)

        if xyz_match:
            # 提取 X, Y, Z 值
            X = float(xyz_match.group(1))
            Y = float(xyz_match.group(2))
            Z = float(xyz_match.group(3))

            # XYZ 转换为 xyY
            result = self._xyz_to_xyy(X, Y, Z)
            if result:
                self._log_status(f"解析 XYZ: X={X:.6f}, Y={Y:.6f}, Z={Z:.6f} -> x={result[0]:.4f}, y={result[1]:.4f}, Y={result[2]:.6f}")
                return result

        # ========== 备用：尝试 Yxy 格式 ==========
        yxy_match = self.YXY_PATTERN.search(output)

        if yxy_match:
            Y = float(yxy_match.group(1))
            x = float(yxy_match.group(2))
            y = float(yxy_match.group(3))
            return (x, y, Y)

        # ========== 备用：尝试 CIE x,y,Y 格式 ==========
        cie_match = self.CIE_XYY_PATTERN.search(output)

        if cie_match:
            x = float(cie_match.group(1))
            y = float(cie_match.group(2))
            Y = float(cie_match.group(3))
            return (x, y, Y)

        # ========== 最后备用：通用 MEASURE_PATTERN ==========
        match = self.MEASURE_PATTERN.search(output)

        if match:
            X = float(match.group(1))
            Y = float(match.group(2))
            Z = float(match.group(3))
            result = self._xyz_to_xyy(X, Y, Z)
            if result:
                return result

        return None

    def _xyz_to_xyy(self, X: float, Y: float, Z: float) -> Optional[Tuple[float, float, float]]:
        """
        将 XYZ 三刺激值转换为 CIE xyY 色度坐标

        色彩学公式：
        - x = X / (X + Y + Z)  -- 色度坐标 x
        - y = Y / (X + Y + Z)  -- 色度坐标 y
        - Y 保持不变           -- 亮度值（绝对值）

        Args:
            X: X 三刺激值
            Y: Y 三刺激值（亮度）
            Z: Z 三刺激值

        Returns:
            Optional[Tuple[float, float, float]]: (x, y, Y) 或 None（零除保护）
        """
        xyz_sum = X + Y + Z

        # 零除保护：如果 XYZ 总和为 0 或负数，返回 None
        if xyz_sum <= 0:
            self._log_error(f"XYZ 总值异常 (sum={xyz_sum:.6f})，无法转换为 xyY")
            return None

        # 计算色度坐标
        x = X / xyz_sum
        y = Y / xyz_sum

        # Y 值保持不变（这是绝对亮度值）
        # 注意：spotread 输出的 Y 值范围取决于测量模式
        # 在 emissive 模式下，Y 通常在 0-1 范围（相对值）或实际 cd/m²

        return (x, y, Y)

    def _log_status(self, message: str):
        """记录状态消息"""
        # 使用 sys.stdout 直接写入，避免 print 在 shutdown 时崩溃
        try:
            sys.stdout.write(f"[ArgyllController] {message}\n")
            sys.stdout.flush()
        except (ValueError, AttributeError):
            # stdout 可能已在 shutdown 时关闭
            pass

        if self._on_status_callback:
            try:
                self._on_status_callback(message)
            except Exception:
                pass

    def _log_error(self, message: str):
        """记录错误消息"""
        # 使用 sys.stderr 直接写入，避免 print 在 shutdown 时崩溃
        try:
            sys.stderr.write(f"[ArgyllController ERROR] {message}\n")
            sys.stderr.flush()
        except (ValueError, AttributeError):
            # stderr 可能已在 shutdown 时关闭
            pass

        if self._on_error_callback:
            try:
                self._on_error_callback(message)
            except Exception:
                pass

    def __del__(self):
        """
        对象销毁时的清理方法

        确保：
        1. 设置 shutdown 事件
        2. 终止 spotread 进程
        3. 避免 daemon thread 在 Python shutdown 时崩溃
        """
        try:
            # 设置 shutdown 事件
            self._shutdown_event.set()
            self._hardware_error_event.set()

            # 终止进程
            if self._process and self._process.poll() is None:
                try:
                    self._process.terminate()
                except Exception:
                    pass
        except Exception:
            # 在 __del__ 中忽略所有异常
            pass

    # ========== CCMX 矩阵制作 ==========

    def make_ccmx(self, ref_ti3_path: str, target_ti3_path: str, output_ccmx_path: str, display_tech: str = 'l') -> bool:
        """生成 CCMX 校正矩阵（含反交互式死锁机制）

        Args:
            ref_ti3_path: 基准探头（分光仪）测量的 ti3 文件路径
            target_ti3_path: 目标探头（色度计）测量的 ti3 文件路径
            output_ccmx_path: 输出的 CCMX 文件路径
            display_tech: 显示技术类型（ArgyllCMS 官方参数值）
        """
        # 检查输入文件是否存在
        if not os.path.exists(ref_ti3_path):
            self._log_error(f"基准 ti3 文件不存在: {ref_ti3_path}")
            return False
        if not os.path.exists(target_ti3_path):
            self._log_error(f"目标 ti3 文件不存在: {target_ti3_path}")
            return False

        # 构建 ccxxmake 路径
        system = platform.system()
        ccxxmake_name = "ccxxmake.exe" if system == "Windows" else "ccxxmake"
        if self._argyll_path:
            ccxxmake_path = str(Path(self._argyll_path) / ccxxmake_name)
        else:
            ccxxmake_path = ccxxmake_name

        # 根据显示器类型决定刷新模式
        # CRT (c) 是刷新型显示器，其他都是非刷新型
        refresh_mode = "r" if display_tech == "c" else "n"

        cmd = [
            ccxxmake_path,
            "-v",
            "-t", display_tech,          # 目标显示器类型
            "-y", display_tech,          # 色度计底层基准模式
            "-z", display_tech,          # 分光仪底层基准模式
            "-Y", refresh_mode,          # 刷新模式：r=CRT刷新型, n=LCD/OLED非刷新型
            "-f", f"{ref_ti3_path},{target_ti3_path}",
            output_ccmx_path
        ]
        self._log_status(f"执行 ccxxmake: {' '.join(cmd)}")

        try:
            # 使用 Popen 以便进行异步延迟输入
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # 启动延迟注入线程：破解 ArgyllCMS 的"清空缓存后等待"机制
            def auto_confirm():
                for _ in range(6):
                    time.sleep(0.5)
                    if process.poll() is not None:
                        break
                    try:
                        process.stdin.write("y\n")
                        process.stdin.flush()
                    except Exception:
                        break

            t = threading.Thread(target=auto_confirm, daemon=True)
            t.start()

            # 等待进程完成
            stdout, stderr = process.communicate(timeout=60)

            # 过滤掉 ArgyllCMS 烦人的 TTY ioctl 报错刷屏
            clean_lines = []
            for line in (stdout + "\n" + stderr).splitlines():
                if "tcgetattr failed" not in line and "tcsetattr failed" not in line and line.strip():
                    clean_lines.append(line)
            clean_output = "\n".join(clean_lines)

            if process.returncode == 0:
                self._log_status(f"ccxxmake 成功:\n{clean_output}")
                return True
            else:
                self._log_error(f"ccxxmake 执行失败 (返回码 {process.returncode}):\n{clean_output}")
                return False

        except subprocess.TimeoutExpired:
            process.kill()
            self._log_error("ccxxmake 执行超时 (60秒)")
            return False
        except FileNotFoundError:
            self._log_error("找不到 ccxxmake 命令，请确保 ArgyllCMS 已正确安装")
            return False
        except Exception as e:
            self._log_error(f"生成 CCMX 时出错: {str(e)}")
            return False

    # ========== 显示器校准流程：dispcal ==========

    def calibrate_display(self,
                          output_path: str,
                          white_point_x: Optional[float] = None,
                          white_point_y: Optional[float] = None,
                          white_temp: Optional[int] = None,
                          gamma: float = 2.2,
                          brightness: Optional[float] = None,
                          display_index: int = 1,
                          instrument_index: int = 1,
                          quality: str = "m",
                          use_web_server: bool = False,
                          web_port: int = 9292,
                          on_progress: Callable[[int, int, str], None] = None,
                          on_patch_change: Callable[[int, int, int, str], None] = None,
                          on_instrument_ready: Callable[[], None] = None,
                          on_web_server_url: Callable[[str], None] = None) -> bool:
        """
        使用 dispcal 校准显示器（生成 .cal 文件）

        这是显示器校准的核心步骤，会生成 1D LUT / VCGT（Video Card Gamma Table），
        强制显卡输出目标白点和灰阶曲线。

        Args:
            output_path: 输出的 .cal 文件路径（不含扩展名）
            white_point_x: 目标白点 x 坐标（感知匹配功能）
            white_point_y: 目标白点 y 坐标（感知匹配功能）
            white_temp: 目标色温（K），如 6500, 5000, 7500
                        如果设置了 white_point_x/y，则忽略此参数
            gamma: 目标 Gamma 值，默认 2.2
            brightness: 目标白场亮度（cd/m²），None 表示不限制
            display_index: 显示器索引（从 1 开始）
            instrument_index: 仪器索引（从 1 开始）
            quality: 校准质量 (l/m/h)
            use_web_server: 是否使用 Web Server 模式（-d web:port），
                           启用后 dispcal 不显示自己的测试窗口，
                           而是通过 HTTP API 下发色块指令
            web_port: Web Server 端口号（默认 9292）
            on_progress: 进度回调函数
            on_patch_change: 色块变化回调函数，参数为 (r, g, b, name)

        Returns:
            bool: 是否成功生成 .cal 文件

        感知匹配工作流：
            1. 肉眼调整 OSD 使两个显示器看起来一致
            2. 测量当前显示器白点，得到 x, y
            3. 调用此方法，传入 white_point_x/y
            4. dispcal 会生成 .cal 文件，强制显卡输出该白点
            5. 后续测量使用 dispread 加载 .cal
        """
        # 构建 dispcal 路径
        system = platform.system()
        dispcal_name = "dispcal.exe" if system == "Windows" else "dispcal"
        if self._argyll_path:
            dispcal_path = str(Path(self._argyll_path) / dispcal_name)
        else:
            dispcal_path = dispcal_name

        # dispcal 参数说明：
        # -v: 详细输出模式
        # -d {n|web:port}: 显示器索引 或 web:port（Web Server 模式）
        # -c {n}: 仪器索引
        # -q {l/m/h}: 校准质量
        # -w x,y: 目标白点坐标（感知匹配核心参数）
        # -t {temp}: 目标色温（Daylight locus）
        # -g {gamma}: 目标 Gamma
        # -b {brightness}: 目标白场亮度
        # -m: 跳过显示器控制调整（纯软件校准）
        cmd = [
            dispcal_path,
            "-v",
            "-m",  # 跳过显示器控制调整提示
        ]

        # ========== 显示器参数：Web Server 或 传统模式 ==========
        if use_web_server:
            # Web Server 模式：dispcal 启动 HTTP 服务器，不显示自己的窗口
            # 外部程序通过 HTTP API 获取色块指令并显示
            # 注意：参数格式必须是 -dweb:port（不能有空格）
            cmd.append(f"-dweb:{web_port}")
            # -Y p: 跳过放置仪器确认（Web Server 模式下需要）
            # 在 Web Server 模式下，dispcal 等待客户端连接后才显示色块，
            # 使用 -Y p 可以跳过 "Place instrument on test window" 提示，
            # 让客户端连接后直接开始测量流程
            cmd.extend(["-Y", "p"])
            self._log_status(f"使用 Web Server 模式: 端口 {web_port}")
        else:
            # 传统模式：dispcal 自己显示测试窗口
            cmd.extend(["-d", str(display_index)])

        cmd.extend([
            "-c", str(instrument_index),
            "-q", quality,
        ])

        # 设置白点
        if white_point_x is not None and white_point_y is not None:
            # 使用自定义白点坐标（感知匹配）
            cmd.extend(["-w", f"{white_point_x:.4f},{white_point_y:.4f}"])
            self._log_status(f"目标白点（感知匹配）: x={white_point_x:.4f}, y={white_point_y:.4f}")
        elif white_temp is not None:
            # 使用色温
            cmd.extend(["-t", str(white_temp)])
            self._log_status(f"目标色温: {white_temp}K")

        # 设置 Gamma
        cmd.extend(["-g", str(gamma)])

        # 设置亮度（可选）
        if brightness is not None:
            cmd.extend(["-b", str(brightness)])
            self._log_status(f"目标亮度: {brightness} cd/m²")

        # 添加输出路径
        cmd.append(output_path)

        self._log_status(f"执行 dispcal: {' '.join(cmd)}")

        if on_progress:
            on_progress(0, 100, "正在校准显示器...")

        try:
            # dispcal 是交互式程序，需要处理交互
            # 使用 Popen 以便实时读取输出
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,  # 需要 stdin 传递交互
                text=True,
                bufsize=1
            )

            # ========== 存储进程引用，以便外部可以终止 ==========
            self._dispcal_process = process

            # 使用 Queue 和线程同时读取 stdout 和 stderr，避免阻塞
            output_queue = queue.Queue()
            stdout_lines = []
            stderr_lines = []

            def read_stdout():
                """线程函数：读取 stdout"""
                try:
                    for line in process.stdout:
                        output_queue.put(('stdout', line))
                except Exception:
                    pass

            def read_stderr():
                """线程函数：读取 stderr"""
                try:
                    for line in process.stderr:
                        output_queue.put(('stderr', line))
                except Exception:
                    pass

            # 启动读取线程
            stdout_thread = threading.Thread(target=read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()

            # 处理输出的辅助函数
            def process_line(stream_type: str, line: str):
                """处理单行输出"""
                if stream_type == 'stdout':
                    stdout_lines.append(line)
                else:
                    stderr_lines.append(line)

                stripped = line.strip()

                # 过滤 TTY 错误和 macOS IMK 警告
                if "tcgetattr" in line or "tcsetattr" in line or "IMKInputSession" in line:
                    return

                if not stripped:
                    return

                # 详细调试：显示原始内容和 stream 类型
                self._log_status(f"[dispcal][{stream_type}] {repr(stripped)}")

                # 解析进度
                if "Setting up" in stripped or "Initial" in stripped:
                    if on_progress:
                        on_progress(10, 100, "初始化校准...")

                # ========== 仪器初始化完成检测 ==========
                if "Serial Number" in stripped:
                    self._log_status("仪器初始化完成")
                    # 在 Web Server 模式下，仪器初始化完成后应立即启动客户端
                    # 因为 dispcal 需要客户端连接后才会输出 "Created web server" 消息
                    if use_web_server:
                        self._log_status("Web Server 模式：触发仪器就绪回调...")
                        if on_instrument_ready:
                            try:
                                self._log_status("调用 on_instrument_ready 回调...")
                                on_instrument_ready()
                            except Exception as e:
                                self._log_error(f"仪器就绪回调错误: {e}")
                        else:
                            self._log_error("on_instrument_ready 回调为空！")

                elif "Commencing display calibration" in stripped:
                    if on_progress:
                        on_progress(15, 100, "开始显示校准...")
                    self._log_status("开始显示校准")

                # ========== Web Server URL 解析 ==========
                # dispcal 会输出实际监听的 URL，例如：
                # "Created web server at 'http://192.168.1.20:9292/', now waiting for browser to connect"
                elif "Created web server at" in stripped:
                    import re as re_mod
                    url_match = re_mod.search(r"'(http://[^']+)'", stripped)
                    if url_match:
                        actual_url = url_match.group(1)
                        self._log_status(f"dispcal Web Server 监听在: {actual_url}")
                        if on_web_server_url:
                            try:
                                on_web_server_url(actual_url)
                            except Exception as e:
                                self._log_error(f"Web Server URL 回调错误: {e}")

                # ========== 关键交互点：放置探头后按空格键 ==========
                # dispcal 在显示 "Place instrument on test window." 后等待用户确认
                # 等待几秒让用户放置探头，然后自动发送空格键继续
                elif "Place instrument on test window" in stripped:
                    self._log_status("请将探头放置在测试窗口上...")
                    self._log_status("等待 3 秒后自动继续...")
                    # 启动一个延迟发送线程，避免阻塞输出读取
                    def send_continue():
                        time.sleep(3)  # 给用户时间放置探头
                        try:
                            self._log_status("自动发送继续命令...")
                            process.stdin.write(" ")
                            process.stdin.flush()
                            self._log_status("已发送继续命令，开始校准...")
                        except Exception as e:
                            self._log_error(f"发送命令失败: {e}")
                    threading.Thread(target=send_continue, daemon=True).start()

                elif "Hit Esc or Q" in stripped or "any other key to continue" in stripped:
                    # 如果已经发送了空格键，这行可能不会再出现，但保留处理以防万一
                    self._log_status("检测到继续提示，发送继续命令...")
                    try:
                        process.stdin.write(" ")
                        process.stdin.flush()
                    except Exception:
                        pass

                elif "Reading" in stripped or "Measuring" in stripped:
                    if on_progress:
                        on_progress(30, 100, "正在测量色块...")

                # ========== 解析进度 ==========
                patch_match = re.search(r'patch\s+(\d+)\s+of\s+(\d+)', stripped, re.IGNORECASE)
                if patch_match:
                    current_patch = int(patch_match.group(1))
                    total_patches = int(patch_match.group(2))
                    progress = 15 + int(55 * current_patch / total_patches)  # 15-70%
                    if on_progress:
                        on_progress(progress, 100, f"测量色块 {current_patch}/{total_patches}")

                    if on_patch_change:
                        patch_info = self._get_dispcal_patch_info(current_patch, total_patches, quality)
                        if patch_info:
                            on_patch_change(patch_info['r'], patch_info['g'], patch_info['b'], patch_info['name'])

                elif "Computing" in stripped or "Creating" in stripped:
                    if on_progress:
                        on_progress(70, 100, "正在计算校准曲线...")
                    self._log_status("正在计算校准曲线...")

                elif "Written" in stripped and ".cal" in stripped:
                    if on_progress:
                        on_progress(100, 100, "校准文件已保存")
                    self._log_status(f"校准文件已保存: {stripped}")

                # ========== 检测完成 ==========
                elif "instrument can be removed" in stripped.lower():
                    self._log_status("校准完成，可以移除探头")

            # 主循环：从队列读取输出
            while True:
                try:
                    # 使用超时避免无限阻塞
                    stream_type, line = output_queue.get(timeout=0.1)
                    process_line(stream_type, line)
                except queue.Empty:
                    # 检查进程是否结束
                    if process.poll() is not None:
                        # 进程已结束，读取队列中剩余内容
                        while not output_queue.empty():
                            try:
                                stream_type, line = output_queue.get_nowait()
                                process_line(stream_type, line)
                            except queue.Empty:
                                break
                        break

            # 合并输出
            full_output = "".join(stdout_lines + stderr_lines)

            # 过滤 TTY 错误
            clean_lines = []
            for line in full_output.splitlines():
                if "tcgetattr failed" not in line and "tcsetattr failed" not in line and line.strip():
                    clean_lines.append(line)
            clean_output = "\n".join(clean_lines)

            if process.returncode == 0:
                # 清理进程引用
                self._dispcal_process = None

                # 检查生成的 .cal 文件
                cal_file = output_path + ".cal"
                if os.path.exists(cal_file):
                    file_size = os.path.getsize(cal_file)
                    self._log_status(f"dispcal 成功: 校准文件已生成 ({file_size} bytes)")
                    if on_progress:
                        on_progress(100, 100, "校准完成")
                    return True
                else:
                    self._log_error(f"dispcal 执行成功但未生成 .cal 文件: {cal_file}")
                    return False
            else:
                # 清理进程引用
                self._dispcal_process = None
                self._log_error(f"dispcal 执行失败 (返回码 {process.returncode}):\n{clean_output}")
                return False

        except subprocess.TimeoutExpired:
            process.kill()
            self._dispcal_process = None  # 清理进程引用
            self._log_error("dispcal 执行超时")
            return False
        except FileNotFoundError:
            self._dispcal_process = None  # 清理进程引用
            self._log_error("找不到 dispcal 命令，请确保 ArgyllCMS 已正确安装")
            return False
        except Exception as e:
            self._dispcal_process = None  # 清理进程引用
            self._log_error(f"校准显示器时出错: {str(e)}")
            return False

    def _get_dispcal_patch_info(self, patch_num: int, total_patches: int, quality: str) -> Optional[Dict]:
        """
        根据 dispcal 色块编号推断 RGB 值和名称

        dispcal 的色块序列通常是：
        1. 黑场 (RGB 0, 0, 0)
        2. 灰阶色块（从低到高）
        3. 白场 (RGB 255, 255, 255)
        4. 颜色色块（高质量模式）

        Args:
            patch_num: 当前色块编号（从 1 开始）
            total_patches: 总色块数量
            quality: 校准质量 (l/m/h)

        Returns:
            Dict: 包含 'r', 'g', 'b', 'name' 的字典，如果无法推断返回 None
        """
        # 根据质量确定灰阶数量
        gray_count_map = {'l': 5, 'm': 7, 'h': 11}
        gray_count = gray_count_map.get(quality, 7)

        # 高质量模式额外颜色色块
        extra_color_count = 6 if quality == 'h' else 0

        # 预计总色块数：黑场 + 灰阶 + 白场 + 额外颜色
        expected_total = 1 + (gray_count - 2) + 1 + extra_color_count
        # 黑场(1) + 灰阶(gray_count-2，不含黑白) + 白场(1) + 额外颜色(6)

        # 第一个色块：黑场
        if patch_num == 1:
            return {'r': 0, 'g': 0, 'b': 0, 'name': '黑场'}

        # 最后一个灰阶之前的色块：白场
        # 实际位置取决于 dispcal 的具体实现，这里做近似推断
        white_patch_position = gray_count - 1 + 1  # 黑场 + 灰阶（不含白）
        if quality != 'h':
            white_patch_position = total_patches  # 低/中质量模式下白场通常是最后一个

        # 尝试推断灰阶位置
        if patch_num <= gray_count:
            # 灰阶色块（包含黑和白）
            level = int(255 * (patch_num - 1) / (gray_count - 1))
            if patch_num == gray_count:
                # 最后一个灰阶是白场
                return {'r': 255, 'g': 255, 'b': 255, 'name': '白场'}
            elif patch_num == 1:
                # 第一个是黑场
                return {'r': 0, 'g': 0, 'b': 0, 'name': '黑场'}
            else:
                # 中间灰阶
                return {'r': level, 'g': level, 'b': level, 'name': f'灰阶{patch_num}'}

        # 高质量模式下的额外颜色色块
        if quality == 'h' and patch_num > gray_count:
            color_patches = [
                {'r': 255, 'g': 0, 'b': 0, 'name': '红校准'},
                {'r': 0, 'g': 255, 'b': 0, 'name': '绿校准'},
                {'r': 0, 'g': 0, 'b': 255, 'name': '蓝校准'},
                {'r': 0, 'g': 255, 'b': 255, 'name': '青校准'},
                {'r': 255, 'g': 255, 'b': 0, 'name': '黄校准'},
                {'r': 255, 'g': 0, 'b': 255, 'name': '紫校准'},
            ]
            color_index = patch_num - gray_count - 1  # -1 因为白场在 gray_count 位置
            if 0 <= color_index < len(color_patches):
                return color_patches[color_index]

        # 无法推断时返回近似灰阶
        level = int(255 * patch_num / total_patches)
        return {'r': level, 'g': level, 'b': level, 'name': f'色块{patch_num}'}

    def load_calibration(self, cal_path: str, display_index: int = 1) -> bool:
        """
        加载校准文件到显卡 LUT

        使用 dispwin 加载 .cal 文件，使校准立即生效。

        Args:
            cal_path: .cal 文件路径
            display_index: 显示器索引（从 1 开始）

        Returns:
            bool: 是否成功加载
        """
        if not os.path.exists(cal_path):
            self._log_error(f"校准文件不存在: {cal_path}")
            return False

        # 构建 dispwin 路径
        system = platform.system()
        dispwin_name = "dispwin.exe" if system == "Windows" else "dispwin"
        if self._argyll_path:
            dispwin_path = str(Path(self._argyll_path) / dispwin_name)
        else:
            dispwin_path = dispwin_name

        # dispwin -d {n} -L {cal_file} 加载校准文件
        cmd = [
            dispwin_path,
            "-d", str(display_index),
            "-L",  # 加载校准
            cal_path
        ]

        self._log_status(f"加载校准文件: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                self._log_status(f"校准文件已加载: {cal_path}")
                return True
            else:
                self._log_error(f"加载校准文件失败: {result.stderr}")
                return False

        except Exception as e:
            self._log_error(f"加载校准文件时出错: {str(e)}")
            return False

    def clear_calibration(self, display_index: int = 1) -> bool:
        """
        清除显卡 LUT（恢复默认）

        Args:
            display_index: 显示器索引（从 1 开始）

        Returns:
            bool: 是否成功清除
        """
        system = platform.system()
        dispwin_name = "dispwin.exe" if system == "Windows" else "dispwin"
        if self._argyll_path:
            dispwin_path = str(Path(self._argyll_path) / dispwin_name)
        else:
            dispwin_path = dispwin_name

        # dispwin -d {n} -c 清除 LUT
        cmd = [
            dispwin_path,
            "-d", str(display_index),
            "-c"  # 清除校准
        ]

        self._log_status(f"清除校准: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                self._log_status("校准已清除")
                return True
            else:
                self._log_error(f"清除校准失败: {result.stderr}")
                return False

        except Exception as e:
            self._log_error(f"清除校准时出错: {str(e)}")
            return False

    # ========== 3D LUT 制作流程：targen / colprof / collink ==========

    def generate_target(self,
                        patch_count: int,
                        output_path: str,
                        on_progress: Callable[[int, int, str], None] = None) -> bool:
        """
        使用 targen 生成测试色块序列（.ti1 文件）

        生成的 ti1 文件包含离散色块的 RGB 值，用于后续的测量流程。

        Args:
            patch_count: 色块数量（常用：512、1024、2048）
            output_path: 输出的 .ti1 文件路径（不含扩展名，targen 会自动添加）
            on_progress: 进度回调函数 (current, total, message)

        Returns:
            bool: 是否成功生成

        常用色块数量说明：
            - 512: 适合快速校准，精度一般
            - 1024: 平衡精度和时间，推荐
            - 2048: 高精度，耗时较长
        """
        # 构建 targen 路径
        system = platform.system()
        targen_name = "targen.exe" if system == "Windows" else "targen"
        if self._argyll_path:
            targen_path = str(Path(self._argyll_path) / targen_name)
        else:
            targen_path = targen_name

        # targen 参数说明：
        # -v: 详细输出模式
        # -d3: 显示器设备（3 = emissive/display）
        # -f{patch_count}: 色块数量（使用自适应优化算法）
        # -s: 灰阶级数（默认自动）
        cmd = [
            targen_path,
            "-v",
            "-d3",
            "-f" + str(patch_count),
            output_path  # 输出文件名（不含扩展名）
        ]

        self._log_status(f"执行 targen: {' '.join(cmd)}")

        if on_progress:
            on_progress(0, 100, "正在生成测试色块序列...")

        try:
            # 使用 Popen 以便实时读取进度
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.path.dirname(output_path) if os.path.dirname(output_path) else None
            )

            # 实时读取输出并解析进度
            stdout_lines = []
            stderr_lines = []

            while True:
                # 读取 stdout
                stdout_line = process.stdout.readline()
                if stdout_line:
                    stdout_lines.append(stdout_line)

                    # 过滤 TTY 错误
                    if "tcgetattr failed" not in stdout_line and "tcsetattr failed" not in stdout_line:
                        stripped = stdout_line.strip()
                        if stripped:
                            self._log_status(f"[targen] {stripped}")

                            # 解析进度（targen 通常没有进度输出，但检查可能的格式）
                            # 格式可能是 "Created XXX patches"
                            progress_match = re.search(r'Created\s+(\d+)\s+patches', stripped)
                            if progress_match and on_progress:
                                created = int(progress_match.group(1))
                                # 假设进度为已创建 / 目标数量
                                progress_pct = min(100, int(created / patch_count * 100))
                                on_progress(progress_pct, 100, f"已创建 {created} 个色块")

                # 读取 stderr
                stderr_line = process.stderr.readline()
                if stderr_line:
                    stderr_lines.append(stderr_line)

                # 检查进程是否结束
                if process.poll() is not None:
                    # 读取剩余输出
                    remaining_stdout = process.stdout.read()
                    remaining_stderr = process.stderr.read()
                    if remaining_stdout:
                        stdout_lines.append(remaining_stdout)
                    if remaining_stderr:
                        stderr_lines.append(remaining_stderr)
                    break

                time.sleep(0.05)

            # 合并输出
            full_output = "".join(stdout_lines + stderr_lines)

            # 过滤 TTY 错误
            clean_lines = []
            for line in full_output.splitlines():
                if "tcgetattr failed" not in line and "tcsetattr failed" not in line and line.strip():
                    clean_lines.append(line)
            clean_output = "\n".join(clean_lines)

            if process.returncode == 0:
                # 检查生成的文件
                ti1_file = output_path + ".ti1"
                if os.path.exists(ti1_file):
                    # 解析 ti1 文件获取色块数量
                    actual_patches = self._parse_ti1_patch_count(ti1_file)
                    self._log_status(f"targen 成功: 生成了 {actual_patches} 个色块")
                    if on_progress:
                        on_progress(100, 100, f"完成，生成 {actual_patches} 个色块")
                    return True
                else:
                    self._log_error(f"targen 执行成功但未生成 .ti1 文件: {ti1_file}")
                    return False
            else:
                self._log_error(f"targen 执行失败 (返回码 {process.returncode}):\n{clean_output}")
                return False

        except subprocess.TimeoutExpired:
            process.kill()
            self._log_error("targen 执行超时")
            return False
        except FileNotFoundError:
            self._log_error("找不到 targen 命令，请确保 ArgyllCMS 已正确安装")
            return False
        except Exception as e:
            self._log_error(f"生成色块序列时出错: {str(e)}")
            return False

    def _parse_ti1_patch_count(self, ti1_path: str) -> int:
        """
        解析 ti1 文件获取色块数量

        Args:
            ti1_path: .ti1 文件路径

        Returns:
            int: 色块数量
        """
        try:
            with open(ti1_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # ti1 格式：SAMPLES 行包含色块数量
            # 格式: "NUMBER_OF_SETS XXX" 或 "NUMBER_OF_FIELDS XXX" 后有数据行
            match = re.search(r'NUMBER_OF_SETS\s+(\d+)', content)
            if match:
                return int(match.group(1))

            # 备用：计算数据行数
            # ti1 文件中色块数据在 BEGIN_DATA 和 END_DATA 之间
            begin_match = re.search(r'BEGIN_DATA', content)
            end_match = re.search(r'END_DATA', content)
            if begin_match and end_match:
                data_section = content[begin_match.end():end_match.start()]
                data_lines = [l for l in data_section.splitlines() if l.strip() and not l.startswith('#')]
                return len(data_lines)

            return 0

        except Exception as e:
            self._log_error(f"解析 ti1 文件失败: {str(e)}")
            return 0

    def parse_ti1_to_rgb_queue(self, ti1_path: str) -> List[Tuple[int, int, int, str]]:
        """
        解析 ti1 文件，提取 RGB 色块队列

        用于将 targen 生成的色块序列转换为可供 QTimer 循环投射的队列。

        Args:
            ti1_path: .ti1 文件路径

        Returns:
            List[Tuple[int, int, int, str]]: RGB 色块队列 [(r, g, b, name), ...]

        ti1 文件格式说明：
            - CGATS 格式文本文件
            - 包含 NUMBER_OF_FIELDS、NUMBER_OF_SETS 等元信息
            - 数据在 BEGIN_DATA 和 END_DATA 之间
            - 每行格式：序号 SAMPLE_ID RGB_R RGB_G RGB_B ...（可能有其他字段）
        """
        patches = []

        try:
            with open(ti1_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            # 查找字段名行和数据区域
            field_names = []
            data_start_idx = -1
            data_end_idx = -1

            for i, line in enumerate(lines):
                stripped = line.strip()

                # 解析字段名
                if stripped.startswith('BEGIN_DATA_FORMAT'):
                    # 格式: BEGIN_DATA_FORMAT FIELD1 FIELD2 ...
                    field_line = stripped.replace('BEGIN_DATA_FORMAT', '').strip()
                    field_names = field_line.split()
                    continue

                # 数据开始标记
                if stripped == 'BEGIN_DATA':
                    data_start_idx = i + 1
                    continue

                # 数据结束标记
                if stripped == 'END_DATA':
                    data_end_idx = i
                    break

            if data_start_idx < 0 or data_end_idx < 0:
                self._log_error("ti1 文件格式无效：未找到 BEGIN_DATA/END_DATA 标记")
                return []

            # 查找 RGB 字段的索引
            rgb_r_idx = -1
            rgb_g_idx = -1
            rgb_b_idx = -1
            sample_id_idx = -1

            for idx, field in enumerate(field_names):
                if field.upper() == 'RGB_R':
                    rgb_r_idx = idx
                elif field.upper() == 'RGB_G':
                    rgb_g_idx = idx
                elif field.upper() == 'RGB_B':
                    rgb_b_idx = idx
                elif field.upper() == 'SAMPLE_ID':
                    sample_id_idx = idx

            if rgb_r_idx < 0 or rgb_g_idx < 0 or rgb_b_idx < 0:
                self._log_error(f"ti1 文件缺少 RGB 字段：{field_names}")
                return []

            # 解析数据行
            for i in range(data_start_idx, data_end_idx):
                line = lines[i].strip()
                if not line or line.startswith('#'):
                    continue

                values = line.split()
                if len(values) <= max(rgb_r_idx, rgb_g_idx, rgb_b_idx):
                    continue

                try:
                    # RGB 值通常是 0-1 范围的浮点数，需要转换为 0-255
                    r_float = float(values[rgb_r_idx])
                    g_float = float(values[rgb_g_idx])
                    b_float = float(values[rgb_b_idx])

                    # 检测值范围：可能是 0-1 或 0-100 或 0-255
                    if r_float <= 1.0 and g_float <= 1.0 and b_float <= 1.0:
                        # 0-1 范围，转换为 0-255
                        r = int(round(r_float * 255))
                        g = int(round(g_float * 255))
                        b = int(round(b_float * 255))
                    elif r_float <= 100 and g_float <= 100 and b_float <= 100:
                        # 0-100 范围，转换为 0-255
                        r = int(round(r_float * 255 / 100))
                        g = int(round(g_float * 255 / 100))
                        b = int(round(b_float * 255 / 100))
                    else:
                        # 已经是 0-255 范围
                        r = int(round(r_float))
                        g = int(round(g_float))
                        b = int(round(b_float))

                    # 获取色块名称（使用 SAMPLE_ID 或序号）
                    if sample_id_idx >= 0 and len(values) > sample_id_idx:
                        name = values[sample_id_idx]
                    else:
                        name = f"Patch_{i - data_start_idx + 1}"

                    # 确保 RGB 在有效范围
                    r = max(0, min(255, r))
                    g = max(0, min(255, g))
                    b = max(0, min(255, b))

                    patches.append((r, g, b, name))

                except (ValueError, IndexError) as e:
                    self._log_error(f"解析数据行 {i} 失败: {line} - {str(e)}")
                    continue

            self._log_status(f"解析 ti1 文件完成: 共 {len(patches)} 个色块")
            return patches

        except FileNotFoundError:
            self._log_error(f"ti1 文件不存在: {ti1_path}")
            return []
        except Exception as e:
            self._log_error(f"解析 ti1 文件时出错: {str(e)}")
            return []

    def make_icc_profile(self,
                         ti3_path: str,
                         output_path: str,
                         profile_name: str = "Display Profile",
                         quality: str = "m",
                         on_progress: Callable[[int, int, str], None] = None) -> bool:
        """
        使用 colprof 将测量数据（ti3）生成 ICC 配置文件

        这是高精度计算过程，耗时较长（可能几分钟到十几分钟），
        需要异步执行并提供进度反馈。

        Args:
            ti3_path: 测量后的 .ti3 数据文件路径
            output_path: 输出的 .icc 文件路径（不含扩展名）
            profile_name: ICC profile 描述名称
            quality: 精度等级
                - 'l': 低精度，快速
                - 'm': 中精度，推荐
                - 'h': 高精度，耗时
                - 'u': 超高精度，非常耗时
            on_progress: 进度回调函数 (current, total, message)

        Returns:
            bool: 是否成功生成

        colprof 进度输出格式：
            "Building lookup tables..."
            "Progress: XX%"
            "Creating A2B0 table..."
            等
        """
        # 检查输入文件
        if not os.path.exists(ti3_path):
            self._log_error(f"ti3 文件不存在: {ti3_path}")
            return False

        # 构建 colprof 路径
        system = platform.system()
        colprof_name = "colprof.exe" if system == "Windows" else "colprof"
        if self._argyll_path:
            colprof_path = str(Path(self._argyll_path) / colprof_name)
        else:
            colprof_path = colprof_name

        # colprof 参数说明：
        # -v: 详细输出模式
        # -q{quality}: 精度等级 (l/m/h/u)
        # -D"{profile_name}": profile 描述名称
        # -a{algorithm}: 使用算法
        #   - s: 单向 Gamma 曲线（最简单）
        #   - l: Lab 输出 profile（推荐用于显示器）
        #   - x: XYZ 输出 profile
        # 注意：colprof 没有 -y 参数（误加会导致 colprof 打印 usage 并退出）
        cmd = [
            colprof_path,
            "-v",
            "-q" + quality,
            "-D", profile_name,
            "-al",  # Lab 输出 profile，适合显示器
            output_path  # 输出文件名（不含扩展名）
        ]

        self._log_status(f"执行 colprof: {' '.join(cmd)}")

        if on_progress:
            on_progress(0, 100, "正在计算 ICC Profile...")

        try:
            # 使用 Popen 以便实时读取进度
            # colprof 需要从 ti3 文件所在目录运行（或传入完整路径）
            working_dir = os.path.dirname(ti3_path)

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=working_dir if working_dir else None
            )

            # 实时读取输出并解析进度
            stdout_lines = []
            stderr_lines = []

            while True:
                # 读取 stdout
                stdout_line = process.stdout.readline()
                if stdout_line:
                    stdout_lines.append(stdout_line)

                    # 过滤 TTY 错误
                    if "tcgetattr failed" not in stdout_line and "tcsetattr failed" not in stdout_line:
                        stripped = stdout_line.strip()
                        if stripped:
                            self._log_status(f"[colprof] {stripped}")

                            # 解析进度
                            # colprof 输出格式多样，尝试匹配常见的进度格式
                            # 格式1: "Progress: XX%" 或 "Progress XX%" 或 "XX% complete"
                            progress_match = re.search(r'(?:(?:Progress|Done)[:\s]+)?(\d+)%', stripped, re.IGNORECASE)
                            if progress_match and on_progress:
                                progress_pct = int(progress_match.group(1))
                                on_progress(progress_pct, 100, f"计算进度: {progress_pct}%")
                            else:
                                # 格式2: 阶段信息（用于估算进度）
                                # colprof 主要阶段：
                                # 1. 读取 ti3 数据 (0-5%)
                                # 2. 构建正向查找表 (5-30%)
                                # 3. 构建反向查找表 (30-70%)
                                # 4. 创建 A2B/B2A 表 (70-90%)
                                # 5. 写入 ICC 文件 (90-100%)
                                lower_stripped = stripped.lower()
                                if "reading" in lower_stripped or "loaded" in lower_stripped:
                                    if on_progress:
                                        on_progress(5, 100, "正在读取测量数据...")
                                elif "building" in lower_stripped or "computing" in lower_stripped:
                                    if "forward" in lower_stripped or "lut" in lower_stripped:
                                        if on_progress:
                                            on_progress(20, 100, "正在构建正向查找表...")
                                    elif "inverse" in lower_stripped or "reverse" in lower_stripped:
                                        if on_progress:
                                            on_progress(50, 100, "正在构建反向查找表...")
                                    else:
                                        if on_progress:
                                            on_progress(30, 100, "正在构建查找表...")
                                elif "creating" in lower_stripped or "generating" in lower_stripped:
                                    if "a2b" in lower_stripped:
                                        if on_progress:
                                            on_progress(70, 100, "正在创建 A2B 表...")
                                    elif "b2a" in lower_stripped:
                                        if on_progress:
                                            on_progress(80, 100, "正在创建 B2A 表...")
                                    else:
                                        if on_progress:
                                            on_progress(75, 100, "正在创建 ICC 表...")
                                elif "smoothing" in lower_stripped:
                                    if on_progress:
                                        on_progress(85, 100, "正在平滑曲线...")
                                elif "writing" in lower_stripped or "saving" in lower_stripped:
                                    if on_progress:
                                        on_progress(95, 100, "正在写入 ICC 文件...")

                # 读取 stderr
                stderr_line = process.stderr.readline()
                if stderr_line:
                    stderr_lines.append(stderr_line)

                # 检查进程是否结束
                if process.poll() is not None:
                    # 读取剩余输出
                    remaining_stdout = process.stdout.read()
                    remaining_stderr = process.stderr.read()
                    if remaining_stdout:
                        stdout_lines.append(remaining_stdout)
                    if remaining_stderr:
                        stderr_lines.append(remaining_stderr)
                    break

                time.sleep(0.1)  # colprof 计算密集，稍长间隔避免 CPU 占用过高

            # 合并输出
            full_output = "".join(stdout_lines + stderr_lines)

            # 过滤 TTY 错误
            clean_lines = []
            for line in full_output.splitlines():
                if "tcgetattr failed" not in line and "tcsetattr failed" not in line and line.strip():
                    clean_lines.append(line)
            clean_output = "\n".join(clean_lines)

            if process.returncode == 0:
                # 检查生成的 ICC 文件
                icc_file = output_path + ".icc"
                if os.path.exists(icc_file):
                    file_size = os.path.getsize(icc_file)
                    self._log_status(f"colprof 成功: ICC Profile 已生成 ({file_size} bytes)")
                    if on_progress:
                        on_progress(100, 100, "ICC Profile 生成完成")
                    return True
                else:
                    self._log_error(f"colprof 执行成功但未生成 .icc 文件: {icc_file}")
                    return False
            else:
                self._log_error(f"colprof 执行失败 (返回码 {process.returncode}):\n{clean_output}")
                return False

        except subprocess.TimeoutExpired:
            process.kill()
            self._log_error("colprof 执行超时")
            return False
        except FileNotFoundError:
            self._log_error("找不到 colprof 命令，请确保 ArgyllCMS 已正确安装")
            return False
        except Exception as e:
            self._log_error(f"生成 ICC Profile 时出错: {str(e)}")
            return False

    def make_3dlut(self,
                   source_space: str,
                   target_icc_path: str,
                   output_lut_path: str,
                   lut_size: int = 33,
                   intent: str = "r",
                   use_bpc: bool = True,
                   on_progress: Callable[[int, int, str], None] = None) -> bool:
        """
        使用 collink 生成 3D LUT (.cube 文件)

        将源色彩空间通过目标 ICC Profile 转换，生成可用于
        调色软件（如 DaVinci Resolve）的 3D LUT 文件。

        Args:
            source_space: 源色彩空间
                - "Rec709": BT.709 / sRGB（最常用）
                - "P3": DCI-P3
                - "Rec2020": BT.2020
                - 或传入 ICC 文件路径作为源
            target_icc_path: 目标 ICC Profile 文件路径
            output_lut_path: 输出的 .cube 文件路径
            lut_size: LUT 立方体尺寸（常用：33、65、129）
                - 33: 推荐，兼容性和性能最佳平衡点
                - 65: 精度更高，文件较大
                - 129: 高精度，文件很大
            intent: 渲染意图
                - "r": 相对色度匹配（推荐用于视频校准）
                - "p": 绝对色度匹配
                - "s": 感知匹配
            use_bpc: 黑场补偿 (Black Point Compensation)
                - True: 启用 BPC（推荐，防止暗部死黑）
                - 当 intent='r' 时，BPC 默认自动开启
                - False: 禁用 BPC
            on_progress: 进度回调函数 (current, total, message)

        Returns:
            bool: 是否成功生成
        """
        # 检查目标 ICC 文件
        if not os.path.exists(target_icc_path):
            self._log_error(f"目标 ICC 文件不存在: {target_icc_path}")
            return False

        # 构建 collink 路径
        system = platform.system()
        collink_name = "collink.exe" if system == "Windows" else "collink"
        if self._argyll_path:
            collink_path = str(Path(self._argyll_path) / collink_name)
        else:
            collink_path = collink_name

        # 源色彩空间参数映射
        # collink 使用 -i 参数指定源空间，可以是预设名称或 ICC 文件
        source_param = self._get_source_space_param(source_space)

        # ========== 黑场补偿 (BPC) 与渲染意图互斥逻辑 ==========
        # ArgyllCMS 渲染意图参数说明：
        #   - 'r': 相对色度匹配 (Relative Colorimetric) - **可以且应该启用 BPC**
        #   - 'a': 绝对色度匹配 (Absolute Colorimetric) - **不应启用 BPC**（绝对映射无需补偿）
        #   - 'p': 感知匹配 (Perceptual) - **不能启用 BPC**（感知意图已包含黑场映射，叠加会报错）
        #   - 's': 饱和匹配 (Saturation) - **不应启用 BPC**（饱和优先，非精度校准）
        #
        # 关键修复：感知意图 (intent='p') 自身已包含黑场到黑场的绝对映射，
        # 如果叠加 BPC 参数，ArgyllCMS 会直接抛出命令行报错！

        actual_use_bpc = False  # 默认禁用，按条件判断是否启用

        if intent == 'r':
            # 相对色度匹配：可以且应该启用 BPC（防止暗部死黑）
            if use_bpc:
                actual_use_bpc = True
                self._log_status("相对色度匹配 (intent='r') 模式，启用黑场补偿 (BPC)")
        elif intent == 'p':
            # 感知匹配：强制禁用 BPC（感知意图已包含黑场映射，叠加会报错）
            actual_use_bpc = False
            self._log_status("感知匹配 (intent='p') 模式，自动禁用 BPC（感知意图已包含黑场映射）")
            if use_bpc:
                self._log_status("警告: 用户请求启用 BPC，但感知意图不支持 BPC，已强制禁用")
        elif intent == 'a':
            # 绝对色度匹配：不应启用 BPC（绝对映射无需补偿）
            actual_use_bpc = False
            self._log_status("绝对色度匹配 (intent='a') 模式，禁用 BPC（绝对映射无需黑场补偿）")
        elif intent == 's':
            # 饱和匹配：不应启用 BPC（饱和优先，非精度校准场景）
            actual_use_bpc = False
            self._log_status("饱和匹配 (intent='s') 模式，禁用 BPC（饱和优先场景）")
        else:
            # 未知意图参数：保守策略，禁用 BPC
            actual_use_bpc = False
            self._log_status(f"警告: 未知渲染意图 '{intent}'，禁用 BPC")

        # collink 参数说明：
        # -v: 详细输出模式
        # -i {source}: 源色彩空间（预设名称或 ICC 文件路径）
        # -r {profile}: 目标 ICC Profile（输出 Profile）
        # -n {intent}: 渲染意图 (r/p/s/a)
        # -b: 黑场补偿 (Black Point Compensation) - 防止暗部死黑
        # -G {size}: 3D LUT 尺寸（GPU LUT 格式，常用 33/65/129）
        # -O {output}: 输出 GPU LUT 格式（.cube）
        #
        # 注意：ArgyllCMS 的 -i 参数可以直接跟预设名称（如 -i709）或 ICC 文件路径
        # 当使用 ICC 文件路径时，需要分开传递：-i /path/to/source.icc

        # 检查 source_param 是文件路径还是预设名称
        is_file_path = os.path.exists(source_param)

        # 构建命令
        if is_file_path:
            # ICC 文件路径：参数分开传递
            cmd = [
                collink_path,
                "-v",
                "-i", source_param,       # 源 ICC 文件
                "-r", target_icc_path,    # 目标 ICC Profile
                "-n" + intent,            # 渲染意图（参数紧跟选项）
            ]
        else:
            # 预设名称：参数紧跟选项（ArgyllCMS 格式）
            cmd = [
                collink_path,
                "-v",
                "-i" + source_param,      # 源预设（如 -i709, -isRGB）
                "-r", target_icc_path,    # 目标 ICC Profile
                "-n" + intent,            # 渲染意图
            ]

        # 添加黑场补偿参数（BPC）
        if actual_use_bpc:
            cmd.append("-b")
            self._log_status("启用黑场补偿 (BPC: -b 参数)")

        # 添加 LUT 尺寸和输出路径参数
        cmd.extend([
            "-G" + str(lut_size),     # LUT 尺寸（参数紧跟选项）
            "-O", output_lut_path     # 输出 .cube 文件
        ])

        self._log_status(f"执行 collink: {' '.join(cmd)}")

        if on_progress:
            on_progress(0, 100, "正在计算 3D LUT...")

        try:
            # 使用 Popen 以便实时读取进度
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # 实时读取输出并解析进度
            stdout_lines = []
            stderr_lines = []

            while True:
                # 读取 stdout
                stdout_line = process.stdout.readline()
                if stdout_line:
                    stdout_lines.append(stdout_line)

                    # 过滤 TTY 错误
                    if "tcgetattr failed" not in stdout_line and "tcsetattr failed" not in stdout_line:
                        stripped = stdout_line.strip()
                        if stripped:
                            self._log_status(f"[collink] {stripped}")

                            # 解析进度
                            # collink 输出格式："Making lookup tables - XX% done"
                            progress_match = re.search(r'(\d+)%\s*(done|complete)', stripped, re.IGNORECASE)
                            if progress_match and on_progress:
                                progress_pct = int(progress_match.group(1))
                                on_progress(progress_pct, 100, f"计算进度: {progress_pct}%")
                            elif "Making lookup" in stripped:
                                if on_progress:
                                    on_progress(10, 100, "正在构建查找表...")
                            elif "Creating" in stripped:
                                if on_progress:
                                    on_progress(50, 100, "正在创建 3D LUT...")
                            elif "Writing" in stripped:
                                if on_progress:
                                    on_progress(80, 100, "正在写入 .cube 文件...")

                # 读取 stderr
                stderr_line = process.stderr.readline()
                if stderr_line:
                    stderr_lines.append(stderr_line)

                # 检查进程是否结束
                if process.poll() is not None:
                    # 读取剩余输出
                    remaining_stdout = process.stdout.read()
                    remaining_stderr = process.stderr.read()
                    if remaining_stdout:
                        stdout_lines.append(remaining_stdout)
                    if remaining_stderr:
                        stderr_lines.append(remaining_stderr)
                    break

                time.sleep(0.1)

            # 合并输出
            full_output = "".join(stdout_lines + stderr_lines)

            # 过滤 TTY 错误
            clean_lines = []
            for line in full_output.splitlines():
                if "tcgetattr failed" not in line and "tcsetattr failed" not in line and line.strip():
                    clean_lines.append(line)
            clean_output = "\n".join(clean_lines)

            if process.returncode == 0:
                # 检查生成的 .cube 文件
                if os.path.exists(output_lut_path):
                    file_size = os.path.getsize(output_lut_path)
                    self._log_status(f"collink 成功: 3D LUT 已生成 ({file_size} bytes)")
                    if on_progress:
                        on_progress(100, 100, "3D LUT 生成完成")
                    return True
                else:
                    self._log_error(f"collink 执行成功但未生成 .cube 文件: {output_lut_path}")
                    return False
            else:
                self._log_error(f"collink 执行失败 (返回码 {process.returncode}):\n{clean_output}")
                return False

        except subprocess.TimeoutExpired:
            process.kill()
            self._log_error("collink 执行超时")
            return False
        except FileNotFoundError:
            self._log_error("找不到 collink 命令，请确保 ArgyllCMS 已正确安装")
            return False
        except Exception as e:
            self._log_error(f"生成 3D LUT 时出错: {str(e)}")
            return False

    def _get_source_space_param(self, source_space: str) -> str:
        """
        将源色彩空间名称转换为 collink 参数

        改进版：支持自动映射到 ArgyllCMS/ref 目录下的标准 ICC 文件

        Args:
            source_space: 源色彩空间名称或 ICC 路径
                - "Rec709" / "sRGB" -> 使用 ArgyllCMS/ref/sRGB.icm 或 Rec709.icm
                - "DCI-P3" / "DisplayP3" -> 使用 ArgyllCMS/ref/DisplayP3.icm
                - "Rec2020" -> 使用 ArgyllCMS/ref/Rec2020.icm
                - 或直接传入 ICC 文件路径

        Returns:
            str: collink -i 参数值（ICC 文件路径）
        """
        # 检查是否已经是有效的 ICC/ICM 文件路径
        if os.path.exists(source_space):
            ext = os.path.splitext(source_space)[1].lower()
            if ext in ['.icc', '.icm']:
                self._log_status(f"使用指定的 ICC 文件作为源空间: {source_space}")
                return source_space

        # ========== ArgyllCMS/ref 目录下的标准 ICC 文件映射 ==========
        # 这些文件是 ArgyllCMS 自带的标准参考 ICC，位于 ref/ 子目录
        # 使用 ICC 文件比预设名称更准确，因为预设名称可能不完全支持
        ref_icc_map = {
            # Rec709 / sRGB (两者等效，使用 sRGB.icm 更常见)
            "Rec709": "Rec709.icm",
            "BT709": "Rec709.icm",
            "rec709": "Rec709.icm",
            "bt709": "Rec709.icm",
            "sRGB": "sRGB.icm",
            "srgb": "sRGB.icm",
            "Srgb": "sRGB.icm",

            # DCI-P3 系列
            "DCI-P3": "DisplayP3.icm",      # D65 白点版本的 P3
            "DCIP3": "DisplayP3.icm",
            "DisplayP3": "DisplayP3.icm",
            "displayp3": "DisplayP3.icm",
            "P3": "DisplayP3.icm",          # 简称映射到 DisplayP3
            "p3": "DisplayP3.icm",
            "P3_D65": "DisplayP3.icm",      # D65 白点

            # SMPTE P3 (剧场 DCI-P3，D60 白点)
            "SMPTE431_P3": "SMPTE431_P3.icm",
            "SMPTEP3": "SMPTE431_P3.icm",
            "DCI-P3-D60": "SMPTE431_P3.icm",

            # Rec2020
            "Rec2020": "Rec2020.icm",
            "BT2020": "Rec2020.icm",
            "rec2020": "Rec2020.icm",
            "bt2020": "Rec2020.icm",
            "Rec.2020": "Rec2020.icm",
            "BT.2020": "Rec2020.icm",

            # Adobe RGB
            "AdobeRGB": "ClayRGB1998.icm",  # ArgyllCMS 使用 ClayRGB1998.icm
            "AdobeRGB1998": "ClayRGB1998.icm",
            "adobergb": "ClayRGB1998.icm",
            "Adobe": "ClayRGB1998.icm",

            # ProPhoto RGB
            "ProPhoto": "ProPhoto.icm",
            "ProPhotoRGB": "ProPhoto.icm",
            "prophoto": "ProPhoto.icm",
            "ROMM": "ProPhoto.icm",

            # EBU PAL
            "EBU3213": "EBU3213_PAL.icm",
            "PAL": "EBU3213_PAL.icm",
            "ebu": "EBU3213_PAL.icm",

            # SMPTE NTSC
            "SMPTE_RP145": "SMPTE_RP145_NTSC.icm",
            "NTSC": "SMPTE_RP145_NTSC.icm",
            "SMPTE145": "SMPTE_RP145_NTSC.icm",

            # ACES 系列
            "ACES": "ACES_P3.icm",          # ArgyllCMS 使用 ACES_P3.icm
            "ACES2065-1": "ACES_P3.icm",    # ACES AP0
            "aces": "ACES_P3.icm",

            # lab2lab (特殊用途)
            "Lab2Lab": "lab2lab.icm",
            "lab": "lab2lab.icm",
        }

        # 标准化输入：去除空格和连字符
        source_normalized = source_space.replace("-", "").replace(" ", "").replace(".", "")

        # 查找映射
        for key, icc_file in ref_icc_map.items():
            key_normalized = key.replace("-", "").replace(" ", "").replace(".", "")
            if key_normalized.lower() == source_normalized.lower():
                # ========== 构建 ArgyllCMS/ref 目录路径（支持 PyInstaller 打包） ==========
                # 检测顺序：
                # 1. PyInstaller 打包环境（sys._MEIPASS）
                # 2. 已检测到的 ArgyllCMS bin 目录（self._argyll_path）
                # 3. 项目源码目录

                ref_dir = None

                # 优先检查 PyInstaller 打包环境
                if hasattr(sys, '_MEIPASS'):
                    pyinstaller_root = Path(sys._MEIPASS)
                    ref_dir_candidate = pyinstaller_root / "ArgyllCMS" / "ref"
                    if ref_dir_candidate.exists() and ref_dir_candidate.is_dir():
                        ref_dir = str(ref_dir_candidate)
                        self._log_status(f"PyInstaller 环境: 使用 ref 目录 {ref_dir}")

                # 其次检查已检测到的 ArgyllCMS bin 目录
                if ref_dir is None and self._argyll_path:
                    ref_dir_candidate = Path(self._argyll_path).parent / "ref"
                    if ref_dir_candidate.exists() and ref_dir_candidate.is_dir():
                        ref_dir = str(ref_dir_candidate)

                # 最后检查项目源码目录
                if ref_dir is None:
                    project_root = Path(__file__).parent.parent
                    ref_dir_candidate = project_root / "ArgyllCMS" / "ref"
                    if ref_dir_candidate.exists() and ref_dir_candidate.is_dir():
                        ref_dir = str(ref_dir_candidate)

                # 如果所有路径都找不到 ref 目录，使用默认路径（后续会检查文件是否存在）
                if ref_dir is None:
                    if self._argyll_path:
                        ref_dir = str(Path(self._argyll_path).parent / "ref")
                    else:
                        project_root = Path(__file__).parent.parent
                        ref_dir = str(project_root / "ArgyllCMS" / "ref")

                icc_path = os.path.join(ref_dir, icc_file)

                # 检查文件是否存在
                if os.path.exists(icc_path):
                    self._log_status(f"源色彩空间 '{source_space}' 映射到: {icc_path}")
                    return icc_path
                else:
                    # 文件不存在，尝试使用预设名称作为备用
                    self._log_status(f"警告: ref 目录下的 {icc_file} 不存在，尝试使用预设名称")
                    # 返回预设名称（collink 可能支持）
                    preset_map = {
                        "Rec709": "709",
                        "sRGB": "sRGB",
                        "DCI-P3": "p3_d65",
                        "DisplayP3": "p3_d65",
                        "P3": "p3",
                        "Rec2020": "2020",
                        "AdobeRGB": "adobe",
                        "ProPhoto": "prophoto",
                    }
                    for preset_key, preset_val in preset_map.items():
                        if preset_key.lower().replace("-", "").replace(" ", "") == source_normalized.lower():
                            self._log_status(f"使用预设名称: {preset_val}")
                            return preset_val
                    break

        # 未找到映射，检查是否是有效的预设名称（collink 支持的）
        # collink 支持的预设：709, sRGB, p3, p3_d65, 2020, adobe, prophoto, aces, acescg 等
        valid_presets = ["709", "srgb", "p3", "p3_d65", "2020", "adobe", "prophoto", "aces", "acescg"]
        source_lower = source_normalized.lower()
        if source_lower in valid_presets:
            self._log_status(f"使用预设源色彩空间: {source_space}")
            return source_space

        # 最后尝试：直接使用输入值（可能是用户自定义的 ICC 或预设）
        self._log_status(f"使用自定义源色彩空间参数: {source_space}")
        return source_space


# ========== 测试代码 ==========

if __name__ == "__main__":
    """测试 ArgyllController"""

    def on_measurement(result):
        print(f"测量回调: x={result[0]:.4f}, y={result[1]:.4f}, Y={result[2]:.2f}")

    def on_error(message):
        print(f"错误回调: {message}")

    def on_status(message):
        print(f"状态回调: {message}")

    controller = ArgyllController()
    controller.set_callbacks(
        on_measurement=on_measurement,
        on_error=on_error,
        on_status=on_status
    )

    print("尝试连接探头...")
    if controller.connect():
        print("连接成功！")

        print("\n执行测量...")
        result = controller.measure()
        if result:
            print(f"测量结果: x={result[0]:.4f}, y={result[1]:.4f}, Y={result[2]:.2f}")

        print("\n断开探头...")
        controller.disconnect()
    else:
        print(f"连接失败: {controller.get_error_message()}")