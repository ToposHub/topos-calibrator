"""
Backend - QWebChannel 后端类
实现 Python 与 Web UI 之间的双向通信

Backend 瘦身重构 (P1-C Phase 1):
- PreflightService facade: 预检功能委托
- ReportService facade: 报告生成委托
- StorageFacade: 数据存储统一入口
- Backend 保留 Qt signals/slots 和 service wiring
"""

import json
import os
import platform
import sys
from pathlib import Path
import threading
import time
import atexit
import signal
import subprocess
import shutil
from datetime import datetime
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional, List, Dict, Tuple, Callable, Any, Set
from dataclasses import dataclass, field
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer, QMetaObject, Qt

from .argyll_controller import ArgyllController, ProbeType, DisplayType
from . import i18n
from .measurement_analyzer import MeasurementAnalyzer
from .data_storage import DataStorage, MeasurementData, CGATSExporter, SessionStorage, SessionData
from .display_lut_controller import DisplayLUTController, _get_refresh_script_path, _force_macos_display_refresh
from .sleep_preventer import SystemSleepPreventer
from .lab_sampler import LABSampler  # CIELAB 色块采样器（已废弃）
from .color_science.gamut_sampling import GamutSampler, SamplingStrategy  # 新采样器
from .patch_window import DispcalWebClient  # dispcal Web Server 客户端
from .instruments.corrections import CorrectionManager, CorrectionFileParser, CorrectionMetadata, CCMXCreationWizard
# P5-C: 报告生成模块
from .reports import ReportGenerator, ReportConfig, ReportType, generate_html_report
from .reports.report_service import ReportService  # 报告 facade
# P7-B: 日志与诊断模块
from .diagnostics import (
    get_logger, get_session_logger, init_session_logger,
    close_session_logger, set_log_level, DiagnosticsCollector,
    export_diagnostics_pack, get_export_options
)
# Session state and checkpoint (extracted to avoid circular imports)
from .core.session import MeasurementSessionState, MeasurementCheckpoint
# P0-B: MeasurementService feature flag integration
from .workflows.backend_measurement_bridge import BackendMeasurementBridge, BridgeConfig
from .workflows.preflight_service import PreflightService  # 预检 facade
# P1 集成: AutoCal 自动校准闭环 + DDC/CI 显示器控制
from .workflows.autocal_service import AutoCalService, AutoCalServiceError
from .workflows.autocal_workflow import MeasurementPoint as AutoCalMeasurementPoint
# P4-B: ICC Workflow integration
from .workflows.icc_workflow import (
    ICCWorkflow,
    ICCWorkflowConfig,
    ICCWorkflowSession,
    ICCWorkflowState,
    ICCWorkflowCheckpoint,
    ICCWorkflowError,
    ProfilePreset,
    get_available_presets,
    list_recoverable_sessions,
)
# Storage facade - 统一存储入口
from .storage.storage_facade import StorageFacade


# ========== 硬件刷新遮罩组件（macOS 专用） ==========
class HardwareRefreshOverlay:
    """
    全屏遮罩组件：将"黑屏闪烁"包装为专业 UX 特性

    **设计理念**：
    - 在执行 Swift 物理刷新脚本前显示全屏半透明遮罩
    - 显示科技感十足的加载动画和提示文字
    - 让用户感知这是一个"极其专业的底层硬件操作"，而非 Bug
    - Swift 脚本执行完毕后自动消失

    **提示文案**：
    - "正在接管底层图形管线..."
    - "正在重置显示器硬件通道..."
    - "硬件通道已全开"

    **注意**：仅在 macOS 上使用，Windows 不需要此组件。
    """

    def __init__(self, parent_widget=None):
        """
        初始化遮罩组件

        Args:
            parent_widget: 父窗口（用于获取屏幕几何信息）
        """
        self._overlay = None
        self._parent_widget = parent_widget
        self._animation_frame = 0
        self._animation_timer = None

    def show(self, message: str = "正在接管底层图形管线..."):
        """
        显示全屏遮罩

        Args:
            message: 显示的提示文字
        """
        from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtGui import QFont, QColor

        # 创建全屏遮罩窗口
        self._overlay = QWidget()
        self._overlay.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        # 设置半透明黑色背景
        self._overlay.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 0.85);
            }
        """)
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # 获取屏幕几何信息
        if self._parent_widget:
            screen = QApplication.primaryScreen()
            geometry = screen.geometry()
        else:
            geometry = QApplication.primaryScreen().geometry()

        self._overlay.setGeometry(geometry)
        self._overlay.move(geometry.topLeft())

        # 创建布局
        layout = QVBoxLayout(self._overlay)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 加载动画标签（使用 Unicode 符号模拟动画）
        self._animation_label = QLabel("◉ ◉ ◉")
        self._animation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._animation_label.setStyleSheet("""
            QLabel {
                color: #00d4ff;
                font-size: 48px;
                font-weight: bold;
                background: transparent;
            }
        """)
        layout.addWidget(self._animation_label)

        # 提示文字标签
        self._message_label = QLabel(message)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 24px;
                font-weight: bold;
                background: transparent;
                margin-top: 20px;
            }
        """)
        layout.addWidget(self._message_label)

        # 次级提示文字
        self._sub_label = QLabel("显示器硬件通道正在重置...")
        self._sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_label.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 16px;
                background: transparent;
                margin-top: 10px;
            }
        """)
        layout.addWidget(self._sub_label)

        # 启动动画
        self._animation_frame = 0
        self._animation_timer = QTimer(self._overlay)
        self._animation_timer.timeout.connect(self._update_animation)
        self._animation_timer.start(150)  # 150ms 更换一次动画帧

        # 显示遮罩
        self._overlay.show()

    def _update_animation(self):
        """更新加载动画"""
        frames = ["◉ ◉ ◉", "◉ ◉ ●", "◉ ● ◉", "● ◉ ◉"]
        self._animation_frame = (self._animation_frame + 1) % len(frames)
        self._animation_label.setText(frames[self._animation_frame])

    def hide(self):
        """隐藏并销毁遮罩"""
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer = None

        if self._overlay:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None

    def is_visible(self) -> bool:
        """检查遮罩是否可见"""
        return self._overlay is not None and self._overlay.isVisible()

    def update_message(self, message: str, sub_message: str = None):
        """更新提示文字"""
        if self._message_label:
            self._message_label.setText(message)
        if self._sub_label and sub_message:
            self._sub_label.setText(sub_message)


# ========== 全局临时文件清理机制（极端中断兜底） ==========
# 用于在程序异常退出或被强制终止时清理临时文件
# 这些变量在模块级别定义，确保异常钩子可以访问

# 全局临时文件路径集合（跟踪当前工作流产生的临时文件）
_global_temp_files: Set[str] = set()

# 全局 Backend 实例引用（用于异常钩子调用清理方法）
_global_backend_instance: Optional['Backend'] = None

# 原始 sys.excepthook（用于在处理后恢复默认行为）
_original_excepthook = sys.excepthook


def _register_global_cleanup_handlers():
    """
    注册全局清理处理器：atexit + sys.excepthook + SIGTERM

    这是生产级加固的关键措施，确保以下场景下临时文件都能被清理：
    1. 程序正常退出：atexit 回调会执行
    2. 程序发生未捕获异常：sys.excepthook 会调用清理
    3. 收到 SIGTERM 信号（但 SIGKILL 无法捕获）

    注意：atexit 在 Python 解释器 shutdown 阶段执行，
    应避免在此阶段导入新模块或创建新对象。
    """
    # 注册 atexit 回调（正常退出时清理）
    atexit.register(_global_cleanup_on_exit)

    # 注册自定义异常钩子（未捕获异常时清理）
    sys.excepthook = _global_excepthook

    # 注册 SIGTERM 信号处理（进程被终止时清理）
    # 注意：Windows 不支持 signal.SIGTERM，需要检查
    if hasattr(signal, 'SIGTERM'):
        try:
            signal.signal(signal.SIGTERM, _global_sigterm_handler)
        except (ValueError, OSError):
            # 信号只能在主线程注册，子线程会失败
            pass


def _global_cleanup_on_exit():
    """
    atexit 回调：程序正常退出时清理全局临时文件

    清理策略：
    - 首先清理全局临时文件集合中的所有文件
    - 然后调用 Backend 实例的清理方法（如果存在）
    """
    global _global_temp_files, _global_backend_instance

    # 清理全局临时文件集合中的所有文件
    logger = get_logger("cleanup")
    for temp_file in list(_global_temp_files):
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                logger.info(f"已清理临时文件: {temp_file}")
        except Exception as e:
            logger.warning(f"清理临时文件失败: {temp_file} - {e}")

    # 清空集合
    _global_temp_files.clear()

    # 调用 Backend 实例的清理方法（如果存在）
    if _global_backend_instance is not None:
        try:
            # 调用内部清理方法
            if hasattr(_global_backend_instance, '_cleanup_all_temp_files'):
                _global_backend_instance._cleanup_all_temp_files()
        except Exception as e:
            logger.error(f"Backend 清理失败: {e}")


def _global_excepthook(exc_type, exc_value, exc_traceback):
    """
    自定义异常钩子：未捕获异常时清理临时文件

    这个方法会在以下场景被调用：
    - 代码中发生未捕获的异常（如除零错误、空指针等）
    - 测量流程中途崩溃（如探头通信错误导致的异常）

    注意：此钩子会先执行清理，再调用原始异常处理流程。
    """
    global _global_temp_files, _original_excepthook

    # 先执行清理（确保临时文件被删除）
    logger = get_logger("cleanup")
    for temp_file in list(_global_temp_files):
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                logger.info(f"已清理临时文件: {temp_file}")
        except Exception:
            pass  # 清理失败不影响异常报告

    _global_temp_files.clear()

    # 调用原始异常钩子（显示错误信息）
    _original_excepthook(exc_type, exc_value, exc_traceback)


def _global_sigterm_handler(signum, frame):
    """
    SIGTERM 信号处理：进程被终止时清理临时文件

    注意：SIGKILL 无法捕获，任务管理器强制终止时此处理不会执行。
    """
    global _global_temp_files

    # 快速清理临时文件
    for temp_file in list(_global_temp_files):
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass

    _global_temp_files.clear()

    # 正常退出（让 atexit 有机会执行）
    sys.exit(0)


# 在模块加载时注册全局清理处理器
_register_global_cleanup_handlers()


# ========== 信号节流器（生产级加固：防止 QWebChannel 洪峰阻塞） ==========
class SignalThrottler:
    """
    信号节流器：防止高频信号阻塞 QWebChannel 事件循环

    问题背景：
    - QWebChannel 通过 JSON 序列化传递数据
    - 高频测量时，logMessage/measurementResult 信号可能在毫秒级发射
    - 大量 IPC 跨进程调用会阻塞主线程事件循环，导致 UI 卡顿

    解决方案：
    - 对高频信号使用节流（Throttle）机制
    - 在指定时间窗口内只发射最后一次信号
    - 对于批量数据，合并后一次性发送

    使用方式：
    throttler = SignalThrottler(signal_obj.emit, interval_ms=30)
    throttler.emit(data)  # 节流发射
    throttler.flush()     # 强制立即发送缓冲数据
    """

    def __init__(self, emit_func: Callable, interval_ms: int = 30):
        """
        初始化节流器

        Args:
            emit_func: 信号发射函数（如 signal.emit）
            interval_ms: 节流间隔（毫秒），默认 30ms（约 33fps）
        """
        self._emit_func = emit_func
        self._interval_ms = interval_ms

        # 缓冲区：存储待发送的数据
        self._buffer: Optional[Any] = None
        # 上次发送时间戳
        self._last_emit_time: float = 0.0
        # 线程锁（确保线程安全）
        self._lock = threading.Lock()
        # 是否有待发送数据
        self._has_pending: bool = False
        # QTimer 用于延迟发送（主线程安全）
        self._timer: Optional[QTimer] = None
        # QObject 引用（用于创建 QTimer）
        self._parent: Optional[QObject] = None

    def set_parent(self, parent: QObject):
        """
        设置父对象（用于创建 QTimer）

        Args:
            parent: QObject 对象（如 Backend）
        """
        self._parent = parent

    def emit(self, data: Any):
        """
        节流发射信号

        如果距离上次发送时间小于 interval_ms，则缓冲数据，
        等待下次定时器触发时发送。

        Args:
            data: 要发送的数据
        """
        with self._lock:
            current_time = time.time() * 1000  # 转换为毫秒
            elapsed = current_time - self._last_emit_time

            # 如果距离上次发送超过间隔，立即发送
            if elapsed >= self._interval_ms:
                self._emit_func(data)
                self._last_emit_time = current_time
                self._buffer = None
                self._has_pending = False
            else:
                # 否则缓冲数据，等待定时器触发
                self._buffer = data
                self._has_pending = True

                # 如果定时器未启动，启动定时器
                if self._timer is None and self._parent is not None:
                    self._timer = QTimer(self._parent)
                    self._timer.timeout.connect(self._on_timer_timeout)

                if self._timer is not None and not self._timer.isActive():
                    # 计算剩余等待时间
                    remaining_ms = int(self._interval_ms - elapsed)
                    self._timer.start(max(remaining_ms, 1))

    def _on_timer_timeout(self):
        """
        定时器触发回调：发送缓冲数据
        """
        with self._lock:
            if self._has_pending and self._buffer is not None:
                self._emit_func(self._buffer)
                self._last_emit_time = time.time() * 1000
                self._buffer = None
                self._has_pending = False

            # 停止定时器
            if self._timer is not None:
                self._timer.stop()

    def flush(self):
        """
        强制立即发送缓冲数据

        用于在关键时刻（如测量结束）确保所有数据已发送。
        """
        with self._lock:
            if self._has_pending and self._buffer is not None:
                self._emit_func(self._buffer)
                self._last_emit_time = time.time() * 1000
                self._buffer = None
                self._has_pending = False

            # 停止定时器
            if self._timer is not None:
                self._timer.stop()


class LogMessageAggregator:
    """
    日志消息聚合器：将多条日志合并发送

    对于高频日志消息（如测量进度），将多条消息合并后发送，
    减少 IPC 调用次数。

    使用方式：
    aggregator.add("消息1")
    aggregator.add("消息2")
    aggregator.flush()  # 发送合并后的消息
    """

    def __init__(self, emit_func: Callable, interval_ms: int = 100, separator: str = "\n"):
        """
        初始化聚合器

        Args:
            emit_func: 信号发射函数
            interval_ms: 聚合间隔（毫秒），默认 100ms
            separator: 消息分隔符
        """
        self._emit_func = emit_func
        self._interval_ms = interval_ms
        self._separator = separator

        # 消息缓冲列表
        self._messages: List[str] = []
        # 线程锁
        self._lock = threading.Lock()
        # QTimer
        self._timer: Optional[QTimer] = None
        self._parent: Optional[QObject] = None

    def set_parent(self, parent: QObject):
        """设置父对象"""
        self._parent = parent

    def add(self, message: str):
        """
        添加日志消息

        Args:
            message: 日志消息
        """
        with self._lock:
            self._messages.append(message)

            # 启动定时器（首次添加消息时）
            if self._timer is None and self._parent is not None:
                self._timer = QTimer(self._parent)
                self._timer.timeout.connect(self._on_timer_timeout)

            if self._timer is not None and not self._timer.isActive():
                self._timer.start(self._interval_ms)

    def _on_timer_timeout(self):
        """定时器触发回调：发送聚合消息"""
        with self._lock:
            if self._messages:
                combined = self._separator.join(self._messages)
                self._emit_func(combined)
                self._messages.clear()

            if self._timer is not None:
                self._timer.stop()

    def flush(self):
        """强制立即发送所有缓冲消息"""
        with self._lock:
            if self._messages:
                combined = self._separator.join(self._messages)
                self._emit_func(combined)
                self._messages.clear()

            if self._timer is not None:
                self._timer.stop()


# ========== 断点续测状态 ==========
# MeasurementSessionState 和 MeasurementCheckpoint 已移至 src/core/session.py
# 避免循环导入问题（backend_measurement_bridge 需使用这些类但不能导入 backend.py）


# ========== Web测量服务器 ==========

class WebMeasurementHandler(BaseHTTPRequestHandler):
    """Web测量页面的HTTP请求处理器"""

    def do_GET(self):
        """处理GET请求"""
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(self._get_html_page().encode('utf-8'))
        elif self.path == '/color':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            # 颜色实时变化，禁止任何缓存/暂存（避免中间层返回过期色块）
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            # 返回当前颜色（通过 self.server.server 访问 WebMeasurementServer 实例）
            current_color = self.server.server.get_current_color()
            self.wfile.write(current_color.encode('utf-8'))
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        """禁用默认的日志输出"""
        pass

    def _get_html_page(self) -> str:
        """返回测量页面HTML"""
        return '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>测量色块</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { width: 100%; height: 100%; overflow: hidden; }
        body { background-color: rgb(0, 0, 0); display: flex; align-items: center; justify-content: center; }
        #patch { width: 100%; height: 100%; transition: background-color 0.1s; }
        #info { position: fixed; top: 10px; left: 10px; color: white; font-family: monospace; font-size: 14px; background: rgba(0,0,0,0.7); padding: 8px; border-radius: 4px; }
    </style>
</head>
<body>
    <div id="patch"></div>
    <div id="info">RGB(0, 0, 0)</div>
    <script>
        function updateColor() {
            fetch('/color')
                .then(r => r.text())
                .then(color => {
                    document.getElementById('patch').style.backgroundColor = color;
                    document.getElementById('info').textContent = color;
                });
        }
        updateColor();
        setInterval(updateColor, 100);
    </script>
</body>
</html>'''


class WebMeasurementServer:
    """Web测量服务器 - 用于在浏览器中显示测量色块"""

    def __init__(self, port: int = 8080):
        self.port = port
        self.server = None
        self.server_thread = None
        self._current_color = "rgb(0, 0, 0)"
        self._running = False
        self.url: Optional[str] = None

    def get_current_color(self) -> str:
        """获取当前颜色"""
        return self._current_color

    def set_color(self, r: int, g: int, b: int):
        """设置当前颜色"""
        self._current_color = f"rgb({r}, {g}, {b})"

    def start(self) -> Tuple[bool, str]:
        """启动Web服务器"""
        if self._running:
            return False, i18n.t("服务器已在运行")

        try:
            # 创建服务器（线程化：避免单个慢客户端阻塞测量端取色请求）
            self.server = ThreadingHTTPServer(('0.0.0.0', self.port), WebMeasurementHandler)
            self.server.daemon_threads = True
            self.server.server = self  # 让处理器访问服务器实例

            # 在新线程中运行
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            self._running = True

            # 获取本机局域网 IP。
            # 不能只看默认路由（UDP connect 探测）或 gethostbyname：
            # 开着 VPN/代理 TUN 模式（如 Clash/Surge）时，默认路由指向虚拟网卡
            # （常见 198.18.0.0/15 基准测试段），报给用户的地址浏览器无法访问。
            # 因此枚举所有网卡地址，过滤后按"最像家用局域网"排序取最优。
            import ipaddress
            import socket

            candidates = []

            def _add_candidate(ip: str):
                try:
                    addr = ipaddress.ip_address(ip)
                except ValueError:
                    return
                if not addr.is_private or addr.is_loopback or addr.is_link_local:
                    return
                if addr in ipaddress.ip_network("198.18.0.0/15"):  # VPN TUN 基准测试段
                    return
                if ip not in candidates:
                    candidates.append(ip)

            try:
                for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                    _add_candidate(info[4][0])
            except OSError:
                pass
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect(("8.8.8.8", 80))
                    _add_candidate(s.getsockname()[0])
            except OSError:
                pass

            def _preference(ip: str) -> int:
                """越小越优先：192.168.x 最常见于家庭/办公局域网"""
                if ip.startswith("192.168."):
                    return 0
                if ip.startswith("10."):
                    return 1
                if ip.startswith("172."):
                    return 2
                return 3

            candidates.sort(key=_preference)
            local_ip = candidates[0] if candidates else "127.0.0.1"

            self.urls = [f"http://{ip}:{self.port}" for ip in candidates]
            self.url = self.urls[0] if self.urls else f"http://{local_ip}:{self.port}"
            return True, self.url
        except Exception as e:
            return False, str(e)

    def stop(self):
        """停止Web服务器"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.server_thread:
            self.server_thread.join(timeout=2.0)
            self.server_thread = None
        self._running = False


class Backend(QObject):
    """
    暴露给 Web UI 的后端对象
    通过 QWebChannel 实现前后端通信
    """

    # 定义信号
    # 注意：PyQt6 QWebChannel 对 dict/list 自动序列化可能出错
    # 所有复杂数据结构统一使用 str（JSON 字符串），前端手动 parse
    languageReady = pyqtSignal(str)  # 应用启动时的语言选择
    logMessage = pyqtSignal(str)
    measurementResult = pyqtSignal(str)  # 测量结果 JSON 字符串
    measurementStarted = pyqtSignal(str)  # 色块名称
    measurementCompleted = pyqtSignal()
    probeStatusChanged = pyqtSignal(str)  # 探头状态 JSON 字符串
    cycleMeasurementProgress = pyqtSignal(str)  # 进度 JSON 字符串
    calibrationProgress = pyqtSignal(str)  # 校准进度 JSON 字符串
    patchColorChanged = pyqtSignal(str)  # 颜色 JSON 字符串: {"r": 255, "g": 0, "b": 0}
    gamutCoverageUpdated = pyqtSignal(str)  # 色域覆盖率 JSON 字符串
    gammaUpdated = pyqtSignal(str)  # Gamma 数据 JSON 字符串
    delayConfigUpdated = pyqtSignal(int)  # 测量延迟配置更新（毫秒）
    patchListUpdated = pyqtSignal(str)  # 待测量色块列表 JSON 字符串

    # 显示器基础数据信号
    displayBasicDataUpdated = pyqtSignal(str)  # 显示器基础数据 JSON 字符串

    # 数据存储相关信号
    measurementListUpdated = pyqtSignal(str)  # 测量数据 JSON 字符串
    calFileListUpdated = pyqtSignal(str)  # cal校准文件列表 JSON 字符串
    calFileLoaded = pyqtSignal(str)  # cal文件加载结果 JSON: {"success": true, "cal_path": "..."}
    measurementSaved = pyqtSignal(str)  # 保存结果 JSON 字符串
    measurementLoaded = pyqtSignal(str)  # 加载的完整测量数据 JSON 字符串
    dataExported = pyqtSignal(str)  # 导出结果 JSON 字符串
    sessionListUpdated = pyqtSignal(str)  # 会话列表 JSON 字符串

    # ICC/LUT 文件制作相关信号
    filePathSelected = pyqtSignal(str)  # 文件路径选择结果 JSON 字符串
    fileCreated = pyqtSignal(str)  # 文件创建结果 JSON 字符串

    # 设备枚举相关信号
    instrumentsEnumerated = pyqtSignal(str)  # 设备列表 JSON 字符串
    probeTypeAutoSwitched = pyqtSignal(str)  # 自动切换探头类型通知 (探头类型字符串)
    instrumentListUpdated = pyqtSignal(str)  # 校色仪列表刷新完成 JSON: [{"index":1,"name":...,"probe_type":...}]

    # 窗口打开请求信号
    openComparisonWindowRequested = pyqtSignal()  # 请求打开数据对比窗口

    # ========== Web测量服务器相关信号 ==========
    webMeasurementServerStarted = pyqtSignal(str)  # Web测量服务器启动结果 JSON: {"success": true, "url": "http://..."}
    webMeasurementServerStopped = pyqtSignal(str)  # Web测量服务器停止结果 JSON: {"success": true}

    # ========== 3D LUT 制作流程信号 ==========
    lutGenerationProgress = pyqtSignal(str)  # LUT 生成进度 JSON: {"stage": "targen", "progress": 50, "message": "..."}
    lutGenerationCompleted = pyqtSignal(str)  # LUT 生成完成 JSON: {"success": true, "lut_path": "...", "icc_path": "..."}
    lutGenerationError = pyqtSignal(str)  # LUT 生成错误 JSON: {"stage": "...", "error": "..."}
    ti1PatchesGenerated = pyqtSignal(str)  # ti1 色块生成完成 JSON: {"patch_count": 1024, "ti1_path": "..."}

    # ========== 断点续测相关信号 ==========
    measurementSuspended = pyqtSignal(str)  # 测量挂起通知 JSON: {"reason": "原因", "canResume": true}
    measurementResumed = pyqtSignal()  # 测量恢复通知
    reconnectStatusChanged = pyqtSignal(str)  # 重连状态 JSON: {"attempt": 1, "max": 3, "status": "reconnecting"}
    checkpointUpdated = pyqtSignal(str)  # 断点状态更新 JSON: {"index": 5, "total": 200, "completed": 5}

    # 内部信号：用于跨线程安全地将测量结果从后台线程传递到主线程
    _internalMeasurementSignal = pyqtSignal(tuple)
    # 内部信号：用于跨线程安全的重连状态传递
    _internalReconnectSignal = pyqtSignal(bool)  # (reconnect_success)
    # 内部信号：用于跨线程安全的错误状态传递
    _internalErrorSignal = pyqtSignal(str)  # error_message
    # 内部信号：用于跨线程安全的校准完成后续操作
    _finishCalibrationSignal = pyqtSignal(str, int, bool)  # (cal_path, display_index, was_connected)
    # 内部信号：用于跨线程安全的校准失败后重连
    _reconnectAfterCalFailedSignal = pyqtSignal()  # 无参数
    # 内部信号：用于跨线程安全的文件创建结果传递
    _fileCreatedSignal = pyqtSignal(str)  # JSON 字符串
    # 内部信号：用于在主线程中启动 dispcal web 客户端
    _startDispcalWebClientSignal = pyqtSignal()  # 无参数
    # 内部信号：用于在主线程中清理 dispcal web 客户端
    _cleanupDispcalWebClientSignal = pyqtSignal()  # 无参数
    # 内部信号：用于跨线程安全的测量错误处理
    _measureFailureSignal = pyqtSignal(str)  # error_message
    _measureExceptionSignal = pyqtSignal(str)  # error_message

    # ========== 自动保存相关信号 ==========
    sessionAutoSaved = pyqtSignal(str)  # 自动保存完成，JSON 字符串: {"success": true, "path": "...", "files": [...]}
    calibrationListUpdated = pyqtSignal(str)  # 校准数据列表更新，JSON 字符串: {"calibrations": [...], "latest": {...}}

    # ========== 预检相关信号 (P3-C) ==========
    preflightCheckStarted = pyqtSignal()  # 预检开始
    preflightCheckCompleted = pyqtSignal(str)  # 预检完成，JSON 字符串: PreflightReport.to_json()
    preflightCheckProgress = pyqtSignal(str)  # 预检进度，JSON: {"current": 1, "total": 20, "item": "argyll_spotread"}
    preflightOverrideChanged = pyqtSignal(bool)  # 预检覆盖状态变化

    # ========== 报告导出相关信号 (P5-C) ==========
    reportGenerated = pyqtSignal(str)  # 报告生成完成，JSON: {"success": true, "path": "...", "report_id": "..."}
    reportExportStarted = pyqtSignal(str)  # 报告导出开始，JSON: {"type": "icc_validation"}
    reportExportCompleted = pyqtSignal(str)  # 报告导出完成，JSON: {"success": true, "path": "..."}

    # ========== ICC Workflow 信号 (P4-B 集成) ==========
    iccWorkflowStateChanged = pyqtSignal(str)  # 状态变化 JSON: {"state": "measuring", "previous": "generating_patches"}
    iccWorkflowProgress = pyqtSignal(str)  # 进度更新 JSON: {"percent": 50, "step": "生成测试色块"}
    iccWorkflowCompleted = pyqtSignal(str)  # 工作流完成 JSON: {"icc_path": "...", "session_dir": "...", "artifacts": [...]}
    iccWorkflowFailed = pyqtSignal(str)  # 工作流失败 JSON: {"error": "...", "error_code": "...", "recoverable": true}
    iccWorkflowSessionInfo = pyqtSignal(str)  # 会话信息 JSON: {"session_id": "...", "state": "...", "progress": ...}

    # ========== LUT Workflow 信号（参考 ICCWorkflow 命名）==========
    lutWorkflowStateChanged = pyqtSignal(str)  # 状态变化 JSON: {"state": "generating_lut", "previous": "checking_density"}
    lutWorkflowProgress = pyqtSignal(str)  # 进度更新 JSON: {"percent": 50, "step": "检查测量密度", "message": "..."}
    lutWorkflowCompleted = pyqtSignal(str)  # 工作流完成 JSON: {"success": true, "lut_path": "...", "manifest_path": "...", "report": {...}}
    lutWorkflowFailed = pyqtSignal(str)  # 工作流失败 JSON: {"error": "...", "recoverable": true, "stage": "..."}
    lutWorkflowDensityWarning = pyqtSignal(str)  # 测量密度警告 JSON: {"sufficient": false, "measurement_count": 300, "required": 500, "deficit": 200, "recommendation": "..."}
    lutWorkflowValidationRequest = pyqtSignal(str)  # 验证请求 JSON: {"patch_count": 50, "patches": [{"rgb": [...], "name": "..."}]}
    lutWorkflowSessionInfo = pyqtSignal(str)  # 会话信息 JSON: {"session_id": "...", "state": "...", "progress": ...}

    # ========== AutoCal 自动校准闭环信号 (P1 集成) ==========
    autocalStateChanged = pyqtSignal(str)   # 状态变化 JSON: {"state": "baseline", "previous": "preflight"}
    autocalProgress = pyqtSignal(str)      # 进度 JSON: {"percent": 42.5, "message": "测量 gray_3 ..."}
    autocalFinished = pyqtSignal(str)      # 完成 JSON: AutoCalSession.to_dict() + {"success": bool}
    displayControlUpdated = pyqtSignal(str)  # DDC 能力/读写结果 JSON: {"type": "connect"|"write"|..., ...}

    # 内部信号：AutoCal 工作线程请求主线程显示/隐藏色块（Qt 控件必须在主线程操作）
    _autocalShowPatchSignal = pyqtSignal(int, int, int)
    _autocalHidePatchSignal = pyqtSignal()

    # ========== JSON 序列化 Helper 函数 ==========
    # P1-D: 统一信号序列化策略 - 短期保留 JSON 字符串方案
    # 所有复杂数据结构统一使用此方法进行 JSON 序列化后发射
    # 优点：
    #   - 统一错误处理，避免散落的 try-except
    #   - 便于调试（可选日志输出）
    #   - 未来可无缝切换到 dict/list 原生传输
    def _emit_json(self, signal, payload: Any, ensure_ascii: bool = False) -> None:
        """
        统一的 JSON 序列化信号发射 Helper
        
        Args:
            signal: PyQt Signal 对象（如 self.measurementResult）
            payload: 要发射的数据（dict/list/等）
            ensure_ascii: 是否确保 ASCII 输出（默认 False，允许中文）
        
        Note:
            - 此方法封装 JSON 序列化，统一错误处理
            - 如果序列化失败，会记录日志并发射空对象
            - 当前策略为 JSON 字符串传输，未来可无缝切换到原生 dict/list
        """
        try:
            json_str = json.dumps(payload, ensure_ascii=ensure_ascii)
            signal.emit(json_str)
        except (TypeError, ValueError) as e:
            # 序列化失败时的兜底处理
            get_logger("backend").error(f"JSON 序列化失败: {e}, payload: {payload}")
            # 发射空对象，避免前端收到 undefined
            signal.emit("{}" if isinstance(payload, dict) else "[]")

    def __init__(self, parent=None):
        super().__init__(parent)

        # ========== 全局实例注册（用于异常钩子清理） ==========
        global _global_backend_instance
        _global_backend_instance = self

        # ========== P7-B: 日志系统初始化 ==========
        # 初始化会话日志，使用唯一 session ID
        self._session_id = init_session_logger()
        self._logger = get_session_logger()
        self._logger.info(f"Backend 初始化, session_id: {self._session_id}")
        self._diagnostics_collector = DiagnosticsCollector(self._session_id)

        self._patch_window = None      # 独立浮动窗口
        self._argyll_controller = None  # Argyll 控制器
        self._analyzer = None           # 测量分析器
        self._lut_controller = None     # 显示 LUT 控制器
        self._sleep_preventer = SystemSleepPreventer()  # 防休眠控制器

        # ========== 当前工作流临时文件路径集合 ==========
        # 用于跟踪当前工作流产生的临时文件，在异常退出时清理
        self._current_workflow_temp_files: Set[str] = set()

        # ========== 信号节流器（生产级加固：防止 QWebChannel 洪峰阻塞） ==========
        # 对高频信号使用节流，避免阻塞主线程事件循环
        # measurementResult: 测量结果信号（高频，约每秒数十次）
        self._measurement_result_throttler = SignalThrottler(
            self.measurementResult.emit,
            interval_ms=30  # 30ms 约 33fps
        )
        self._measurement_result_throttler.set_parent(self)

        # checkpointUpdated: 断点更新信号（高频，每次测量后）
        self._checkpoint_throttler = SignalThrottler(
            self.checkpointUpdated.emit,
            interval_ms=50  # 50ms 约 20fps
        )
        self._checkpoint_throttler.set_parent(self)

        # logMessage 聚合器：将多条日志合并发送
        self._log_aggregator = LogMessageAggregator(
            self.logMessage.emit,
            interval_ms=100  # 100ms 聚合窗口
        )
        self._log_aggregator.set_parent(self)

        # 循环测量状态
        self._cycle_timer = QTimer()
        self._cycle_timer.timeout.connect(self._cycle_next_measurement)
        self._cycle_queue = []
        self._cycle_index = 0
        self._cycle_running = False
        # 探头连接进行中标志（连接在后台线程执行，防止重复点击并发连接）
        self._probe_connecting = False
        # 校色仪列表缓存与刷新标志（枚举耗时长，get_instrument_list 同步返回缓存）
        self._last_instrument_list = []
        self._instrument_list_refreshing = False
        # 目标设置（前端测量模式面板/向导同步）
        self._target_white = "D65"
        self._target_gamma = "2.2"

        # ========== Web测量服务器 ==========
        # 用于在浏览器中显示测量色块（受系统ICC影响）
        self._web_measurement_server: Optional[WebMeasurementServer] = None
        self._web_measurement_port = 8080

        # ========== 断点续测状态 ==========
        # 当前测量会话状态
        self._session_state: str = MeasurementSessionState.IDLE
        # 断点数据（探头断开时保存）
        self._checkpoint: Optional[MeasurementCheckpoint] = None
        # 已成功测量的数据（用于断点恢复）
        self._cycle_completed_data: List[Dict] = []
        # 重连状态锁
        self._reconnect_lock = threading.Lock()
        # 当前测量名称
        self._current_measurement_name: str = ""
        # 是否允许自动重连
        self._auto_reconnect_enabled: bool = True

        # 3D LUT 工作流参数（用于多步骤流程的状态保存）
        self._lut_workflow_params: Optional[Dict] = None

        # ========== LUT Workflow 状态 ==========
        self._lut_workflow: Optional[Any] = None  # LUTWorkflow 实例
        self._lut_workflow_config: Optional[Any] = None  # LUTWorkflowConfig
        self._lut_session_dir: Optional[str] = None  # Session 目录路径
        self._lut_validation_patches: Optional[List] = None  # 验证色块列表

        # 测量延迟（自动根据探头类型设置）
        self._current_delay_ms = 300  # 当前延迟（毫秒）
        self._measure_delay = 500     # 用户可调节的延迟（保留兼容）

        # 显示器类型（用于判断是否需要增加延迟）
        self._current_display_type = DisplayType.LCD

        # 自定义白点（感知匹配功能）
        self._custom_white_point: Optional[Tuple[float, float]] = None

        # 预校准参数（ICC/LUT 测量前执行校准）
        self._calibration_params: Optional[Dict] = None

        # ========== 暗部自适应多重采样配置 ==========
        # 用于解决分光仪暗部底噪问题：低亮度时多次测量取平均值
        # Gemini 建议 #1/#2/#3：修复纯黑死循环、降低阈值、XYZ 线性平均
        self._dark_sample_threshold: float = 0.2  # 暗部阈值（Y < 此值触发多重采样，默认 0.2 nits）
        self._dark_sample_min_threshold: float = 0.001  # 极暗阈值（Y < 此值直接退出，避免死循环）
        self._dark_sample_max_retries: int = 3    # 最大重测次数（总共测量 3+1=4 次）
        self._dark_sample_measurements_xyz: List[Tuple[float, float, float]] = []  # XYZ 三刺激值数据（用于线性平均）
        self._dark_sample_current_retry: int = 0  # 当前重测计数
        self._dark_sample_enabled: bool = True    # 暗部多重采样开关（UI 可控）

        # ========== 重复测量平均配置 ==========
        # 每个色块测量 N 次取 XYZ 线性平均（1 = 关闭），降低仪器随机噪声
        self._measure_repeat_count: int = 1
        self._repeat_measurements_xyz: List[Tuple[float, float, float]] = []
        self._repeat_current_count: int = 0

        # ========== 引导式循环测量（均匀性等需人工移动探头的场景） ==========
        # True 时每个色块显示后等待用户确认（confirm_cycle_measurement）再测量
        self._cycle_guided: bool = False

        # ========== OLED 防漂移黑帧插入配置 ==========
        # 用于解决 OLED 屏幕的 ABL/ASBL 亮度漂移问题
        # Gemini 建议 #4/#5：修复时序错位、智能触发黑帧
        self._oled_mode_enabled: bool = False  # OLED 测量模式开关
        self._oled_black_frame_delay_ms: int = 1500  # 黑帧等待时间（毫秒）
        self._oled_ui_settling_delay_ms: int = 300  # UI 稳定延迟（黑帧结束后等待屏幕响应）
        self._oled_bfi_trigger_threshold: float = 20.0  # BFI 触发阈值（亮度 Y > 此值才插入黑帧）
        self._oled_bfi_trigger_rgb_avg: int = 128  # BFI 触发阈值（RGB 平均值 > 此值才插入黑帧）
        self._oled_window_size_percent: int = 100  # OLED 色块窗口大小百分比（默认 100%，建议 10%）
        self._oled_waiting_black_frame: bool = False  # 是否处于黑帧等待状态
        self._oled_last_patch_brightness: float = 0.0  # 上一个色块的亮度（用于智能触发）

        # ========== 自动保存配置 ==========
        self._auto_save_enabled: bool = True  # 默认启用自动保存
        self._auto_save_base_dir: str = "measurements/auto_save"  # 自动保存基础目录

        # ========== dispcal Web Server 客户端 ==========
        # 用于在 dispcal 校准阶段连接 Web Server 并显示色块
        self._dispcal_web_client: Optional[DispcalWebClient] = None

        # 显示模式：'web' 或 'floating'
        self._display_mode = 'web'

        # 当前显示的色块颜色和名称
        self._current_patch_color = (0, 0, 0)
        self._current_patch_name = None
        self._explicit_patch_name = None  # 前端显式设置的色块名称（优先使用）

        # 当前测量模式
        self._current_measure_mode = 'gamut'

        # 自动清除显卡 LUT 选项
        self._auto_clear_lut = True  # 默认启用（用户可在偏好设置中禁用）

        # ========== Null Profile（系统级色彩管理绕过）选项 ==========
        # 替代不稳定的 pyobjc NSColorSpace 强制转换方案
        # 如果启用，测色前会挂载线性 ICC Profile，使输出呈线性状态
        self._use_null_profile_for_measurement = False  # 默认禁用（用户可在偏好设置中启用）
        # 状态标记：当前是否已挂载 Null Profile（用于异常兜底卸载）
        self._null_profile_applied: bool = False
        # 保存测量前原始的系统 ICC Profile 路径（用于恢复）
        self._original_system_profile: Optional[str] = None
        # 线性 ICC Profile 路径
        self._linear_profile_path: Optional[str] = None

        # 测量模式参数（默认值与 UI 默认选项保持一致：向导默认 21 级标准）
        self._gray_steps = 21  # 灰阶级数
        self._icc_patch_count = 200  # ICC 测试色块数（优化为色彩均衡采样）
        self._lut_patch_count = 99   # LUT 测试色块数

        # ========== CIELAB 采样策略参数 ==========
        # 用于大数量色块（1500+）的智能采样
        self._icc_sample_strategy = 'balanced'  # ICC 采样策略
        self._lut_sample_strategy = 'balanced'  # LUT 采样策略
        # 可选策略:
        #   - 'balanced': 均衡覆盖（暗部、灰阶、高饱和均匀分配）
        #   - 'dark-focused': 暗部优先（低 L* 区域更密集采样）
        #   - 'gray-focused': 灰阶优先（L* 轴精细采样）
        #   - 'saturation-focused': 高饱和优先（色域边界密集采样）

        # 测量数据存储（旧格式，保留兼容）
        self._gamut_measurements = {}  # RGBW 测量数据
        self._gamma_measurements = []  # 灰阶测量数据
        
        # 新的数据存储系统（保留兼容，但通过 facade 访问）
        self._storage_facade = StorageFacade()  # 统一存储 facade
        self._data_storage = DataStorage()  # 保留兼容
        self._session_storage = SessionStorage()  # 会话存储管理
        self._current_measurement = MeasurementData()
        self._current_session: Optional[SessionData] = None  # 当前活动会话
        self._cgats_exporter = CGATSExporter()

        # ========== 硬件刷新遮罩（macOS 专用） ==========
        # 用于在执行 Swift 物理刷新脚本时显示专业 UX 遮罩
        self._hardware_refresh_overlay: Optional[HardwareRefreshOverlay] = None

        # ========== 预检相关属性 (P3-C) ==========
        # 预检 facade 服务（替代直接使用 PreflightChecker）
        self._preflight_service = PreflightService()
        # 预检覆盖状态（高级用户可启用以忽略 BLOCK）
        self._preflight_override_enabled = False
        # 预检是否已完成
        self._preflight_completed = False

        # ========== 报告生成相关属性 (P5-C) ==========
        # 报告 facade 服务（替代直接使用 ReportGenerator）
        self._report_service = ReportService()
        # 报告生成器实例（保留兼容，用于直接调用）
        self._report_generator = ReportGenerator()
        # 最新生成的报告路径（保留兼容）
        self._last_report_path: Optional[str] = None
        # 报告配置（保留兼容）
        self._report_config = ReportConfig()
        # 待导出的报告格式（html, json, pdf）- 用于文件对话框回调
        self._pending_export_format: Optional[str] = None

        # ========== MeasurementService Feature Flag (P0-B) ==========
        # 从环境变量读取 feature flag，控制是否使用 MeasurementService
        self._use_measurement_service: bool = os.environ.get("TOPOS_USE_MEASUREMENT_SERVICE", "0") == "1"
        # fallback 开关：当 MeasurementService 失败时是否回退到 legacy
        self._measurement_service_fallback_enabled: bool = True
        # MeasurementBridge 实例（延迟初始化，在首次测量时创建）
        self._measurement_bridge: Optional[BackendMeasurementBridge] = None

        # ========== ICC Workflow 实例 (P4-B 集成) ==========
        # ICC workflow 实例（延迟初始化）
        self._icc_workflow: Optional['ICCWorkflow'] = None
        # ICC workflow 配置参数缓存
        self._icc_workflow_config: Optional[Dict] = None
        # ICC workflow 当前会话目录
        self._icc_session_dir: Optional[str] = None

        # ========== AutoCal 自动校准闭环 (P1 集成) ==========
        # DDC/CI + 迭代校准服务门面（测量桥由 start 时注入）
        self._autocal_service = AutoCalService()
        self._autocal_service.on_state = self._on_autocal_state_change
        self._autocal_service.on_progress = self._on_autocal_progress
        # AutoCal 工作线程（daemon，随进程退出）
        self._autocal_thread: Optional[threading.Thread] = None

        # 初始化组件
        self._init_argyll_controller()
        self._init_analyzer()
        self._init_lut_controller()

        # ========== 自动创建 corrections 文件夹 ==========
        # 使用项目根目录（backend.py 所在目录的父目录）
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._corrections_dir = os.path.join(project_root, 'corrections')
        if not os.path.exists(self._corrections_dir):
            os.makedirs(self._corrections_dir)
            self.logMessage.emit(f"已创建校正文件目录: {self._corrections_dir}")

        # ========== 修正文件管理器 ==========
        # 用于解析和管理 CCSS/CCMX 修正文件
        self._correction_manager = CorrectionManager(self._corrections_dir)
        self._correction_parser = CorrectionFileParser()
        self._ccmx_wizard = CCMXCreationWizard()  # CCMX 制作向导
        # 当前使用的修正文件 hash（用于测量结果关联）
        self._current_correction_hash: str = ""
        self._current_correction_metadata: Optional[CorrectionMetadata] = None

        # 连接内部信号：将后台线程的测量结果安全地传递到主线程处理
        self._internalMeasurementSignal.connect(self._process_measurement_in_main_thread)
        # 连接内部信号：将后台线程的重连状态安全传递
        self._internalReconnectSignal.connect(self._process_reconnect_result_in_main_thread)
        # 连接内部信号：将后台线程的错误状态安全传递
        self._internalErrorSignal.connect(self._process_error_in_main_thread)
        # 连接内部信号：将后台线程的校准完成后续操作安全传递
        self._finishCalibrationSignal.connect(self._finish_calibration_after_file_created)
        # 连接内部信号：将后台线程的校准失败后重连请求安全传递
        self._reconnectAfterCalFailedSignal.connect(self._do_reconnect_after_calibration_failed)
        # 连接内部信号：将后台线程的文件创建结果安全传递
        self._fileCreatedSignal.connect(self.fileCreated.emit)
        # 连接内部信号：在主线程中启动 dispcal web 客户端
        self._startDispcalWebClientSignal.connect(self._start_dispcal_web_client)
        # 连接内部信号：在主线程中清理 dispcal web 客户端
        self._cleanupDispcalWebClientSignal.connect(self._cleanup_dispcal_web_client)
        # 连接内部信号：将后台线程的测量错误处理安全传递
        self._measureFailureSignal.connect(self._handle_measure_failure)
        self._measureExceptionSignal.connect(self._handle_measure_exception)
        # 连接内部信号：AutoCal 工作线程请求主线程显示/隐藏色块
        self._autocalShowPatchSignal.connect(self._autocal_show_patch_in_main_thread)
        self._autocalHidePatchSignal.connect(self.hide_patch)

    def _init_argyll_controller(self):
        """初始化 Argyll 控制器"""
        self._argyll_controller = ArgyllController()

        # 设置回调
        self._argyll_controller.set_callbacks(
            on_measurement=self._on_argyll_measurement,
            on_error=self._on_argyll_error,
            on_status=self._on_argyll_status
        )

    def _init_analyzer(self):
        """初始化测量分析器"""
        self._analyzer = MeasurementAnalyzer()

    def _init_lut_controller(self):
        """
        初始化显示 LUT 控制器

        跨平台色彩管理策略（重构版）：
            - 采用"系统级挂载 Null Profile"方案
            - 测色准备阶段：使用 dispwin -I 挂载线性 ICC Profile
            - 校准完成阶段：使用 dispwin -I 挂载生成的 ICC Profile
            - 降级方案：仅使用 dispwin -c 清除显卡 LUT
        """
        self.logMessage.emit(i18n.t("正在初始化 LUT 控制器..."))

        # 获取 ArgyllCMS 路径（复用 argyll_controller 的路径）
        argyll_path = None
        if self._argyll_controller and hasattr(self._argyll_controller, '_argyll_path'):
            argyll_path = self._argyll_controller._argyll_path

        try:
            self._lut_controller = DisplayLUTController(argyll_bin_path=argyll_path)
            self.logMessage.emit(f"LUT 控制器初始化成功 (auto_clear_lut={self._auto_clear_lut})")

            # ========== 获取线性 ICC Profile 路径 ==========
            self._linear_profile_path = self._lut_controller.get_linear_profile_path()
            if self._linear_profile_path:
                self.logMessage.emit(f"线性 ICC Profile 已检测: {self._linear_profile_path}")
            else:
                self.logMessage.emit(i18n.t("警告: 未检测到线性 ICC Profile，将仅使用 dispwin -c 清除 LUT"))

            # 生产级加固 #3：初始化时检查环境
            # 注意：不在这里发送 probeStatusChanged 信号，避免干扰前端连接状态
            self._check_lut_environment(silent=True)

        except Exception as e:
            # dispwin 未找到时，记录警告但不阻断程序启动
            self._lut_controller = None
            self.logMessage.emit(f"警告: DisplayLUTController 初始化失败: {e}")
            self.logMessage.emit(i18n.t("测量将不会绕过系统色彩管理，结果可能不准确"))

    def _check_lut_environment(self, silent: bool = False):
        """
        生产级加固 #3：检查 LUT 操作的环境是否满足要求

        Args:
            silent: 如果为 True，只记录日志，不发送信号到前端
        """
        if not self._lut_controller:
            return

        status = self._lut_controller.check_environment()

        # 报告检测结果
        if not status.is_valid:
            for error in status.errors:
                self.logMessage.emit(f"环境错误: {error}")
        else:
            self.logMessage.emit(f"环境检测通过: {status.details.get('platform', '未知平台')}")

        # 发送警告到 UI
        for warning in status.warnings:
            self.logMessage.emit(f"环境警告: {warning}")

        # 如果有严重问题，通过信号通知 UI
        # 注意：silent=True 时不发送信号，避免初始化时干扰前端状态
        if not status.is_valid and not silent:
            self.probeStatusChanged.emit(json.dumps({
                "connected": False,
                "status": "environment_error",
                "error": "环境检测失败，LUT 操作可能无法正常进行",
                "details": status.errors
            }))

    def set_patch_window(self, patch_window):
        """设置独立浮动窗口的引用"""
        self._patch_window = patch_window

        # 全屏测量控制条：注入测量进度信号与停止回调。
        # 全屏时主窗口被覆盖，色块窗口必须自带进度显示与停止能力
        # （单屏幕手动全屏、多屏幕副屏全屏、未来均匀度测量均适用）
        patch_window.set_stop_callback(self._stop_measure_from_patch_window)
        # 引导式测量（均匀性逐点确认）：注入确认回调
        patch_window.set_confirm_callback(self._confirm_measure_from_patch_window)
        self.measurementStarted.connect(patch_window.on_measurement_started)
        self.cycleMeasurementProgress.connect(patch_window.on_cycle_progress)
        self.measurementCompleted.connect(patch_window.on_measurement_completed)

    def _stop_measure_from_patch_window(self):
        """色块窗口全屏控制条的停止按钮：停止测量并退回窗口模式"""
        self.logMessage.emit(i18n.t("已从全屏控制条停止测量"))
        self.stop_cycle()
        if self._patch_window and self._patch_window.isVisible():
            self._patch_window.exit_fullscreen_patch()

    def _confirm_measure_from_patch_window(self):
        """色块窗口全屏控制条的确认按钮：引导式测量当前点"""
        self.confirm_cycle_measurement()

    @pyqtSlot()
    def debug_click_patch_stop(self):
        """调试：模拟点击色块窗口全屏控制条的停止按钮"""
        if self._patch_window:
            self._patch_window.btn_stop_measure.click()

    @pyqtSlot()
    def debug_simulate_overlay(self):
        """调试：注入假测量进度驱动全屏控制条（不接触硬件）"""
        if self._patch_window:
            self._patch_window.on_measurement_started("红")
            self._patch_window.on_cycle_progress(
                json.dumps({"patchName": "红", "current": 3, "total": 14}))

    @pyqtSlot(str)
    def setLanguage(self, lang: str):
        """Web UI 切换语言后同步到 Python 端（后续日志/状态消息跟随该语言）"""
        if i18n.set_language(lang):
            self.logMessage.emit(i18n.t("界面语言已切换为") + f": {lang}")

    @pyqtSlot(result=str)
    def getLanguage(self) -> str:
        """Return the language selected during application startup."""
        return i18n.get_language()

    @pyqtSlot()
    def requestLanguage(self):
        """Send the current language through a signal for WebChannel compatibility."""
        self.languageReady.emit(i18n.get_language())

    def _hide_hardware_refresh_overlay(self):
        """隐藏硬件刷新遮罩（延迟回调）"""
        if self._hardware_refresh_overlay:
            self._hardware_refresh_overlay.hide()
            self._hardware_refresh_overlay = None

    def _get_dispcal_window_position(self) -> Optional[str]:
        """
        获取 dispcal 窗口位置参数

        根据用户自定义测量窗口的位置，计算 dispcal -P 参数值。
        格式: "-P ho,vo,ss" 其中：
        - ho: 水平位置 (0.0 = 左, 0.5 = 中, 1.0 = 右)
        - vo: 垂直位置 (0.0 = 上, 0.5 = 中, 1.0 = 下)
        - ss: 缩放 (0.5 = 一半, 1.0 = 正常, 2.0 = 双倍)

        Returns:
            str: dispcal -P 参数值，如果无法计算返回 None
        """
        if self._patch_window is None or not self._patch_window.isVisible():
            return None

        try:
            # 获取窗口几何信息
            window_geometry = self._patch_window.geometry()
            window_width = window_geometry.width()
            window_height = window_geometry.height()
            window_x = window_geometry.x()
            window_y = window_geometry.y()

            # 获取窗口所在的屏幕
            screen = self._patch_window.screen()
            if screen is None:
                return None

            # 获取屏幕几何信息
            screen_geometry = screen.geometry()
            screen_width = screen_geometry.width()
            screen_height = screen_geometry.height()
            screen_x = screen_geometry.x()
            screen_y = screen_geometry.y()

            # 计算窗口在屏幕上的相对位置
            # 窗口中心点相对于屏幕的坐标
            window_center_x = window_x + window_width / 2
            window_center_y = window_y + window_height / 2

            # 相对于屏幕原点的位置
            relative_x = window_center_x - screen_x
            relative_y = window_center_y - screen_y

            # 转换为 0.0-1.0 范围
            ho = relative_x / screen_width
            vo = relative_y / screen_height

            # ========== 计算缩放比例 ==========
            # dispcal 的 ss 参数：
            # - 1.0 = 正常大小（约占屏幕 1/4）
            # - 2.0 = 双倍大小
            # 用户窗口通常较小（400x400），需要放大到合适的测量窗口
            # 直接使用一个合理的固定缩放值，确保测量窗口足够大
            ss = 1.5  # 固定使用 1.5 倍缩放，确保窗口足够大进行测量

            self.logMessage.emit(f"dispcal 窗口位置: ho={ho:.2f}, vo={vo:.2f}, ss={ss:.2f}")
            return f"{ho:.2f},{vo:.2f},{ss:.2f}"

        except Exception as e:
            self.logMessage.emit(f"计算 dispcal 窗口位置失败: {str(e)}")
            return None

    def set_argyll_controller(self, controller):
        """设置 Argyll 控制器的引用（外部注入）"""
        self._argyll_controller = controller

    def _get_patch_display_index(self) -> int:
        """
        生产级加固 #2：获取测量色块窗口所在显示器的索引（用于 dispwin）

        注意：dispwin 的显示器索引从 1 开始（1 = 主显示器），
        而 Qt 的屏幕列表从 0 开始。此方法返回 dispwin 兼容的 1-based 索引。

        用于在多显示器环境下，确保 dispwin 操作的是正确的屏幕。

        Returns:
            int: dispwin 显示器索引（1 = 主显示器）
        """
        if self._patch_window is None:
            return 1  # dispwin 默认从 1 开始

        try:
            # 获取窗口所在的屏幕
            screen = self._patch_window.screen()
            if screen is None:
                return 1

            # 获取所有屏幕列表（QApplication.screens() 可直接使用；
            # QWindow 没有 application() 方法，此前的调用必然抛 AttributeError）
            from PyQt6.QtWidgets import QApplication
            screens = QApplication.screens()

            # 查找目标屏幕在列表中的索引
            for i, s in enumerate(screens):
                if s == screen:
                    return i + 1  # dispwin 从 1 开始

            return 1  # 兜底返回主显示器

        except Exception as e:
            # 如果获取失败，返回默认索引 1（主显示器）
            self.logMessage.emit(f"获取测量窗口显示器索引失败，回退主显示器: {e}")
            return 1

    def _get_display_model(self) -> str:
        """
        获取当前测量窗口所在显示器的型号名称

        通过系统命令获取显示器型号信息（如 "PHL 439P1"、"DELL U2722D" 等）

        Returns:
            str: 显示器型号名称，获取失败时返回空字符串
        """
        import subprocess
        import platform

        try:
            # 获取测量窗口所在的屏幕索引
            display_index = self._get_patch_display_index() - 1  # Qt 从 0 开始

            system = platform.system()

            if system == 'Darwin':
                # macOS: 使用 system_profiler 获取显示器信息
                result = subprocess.run(
                    ['system_profiler', 'SPDisplaysDataType'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    output = result.stdout
                    # 解析显示器型号
                    # 结构：
                    #   Graphics/Displays:
                    #       AMD Radeon RX 6900 XT:   (缩进4空格 - 显卡)
                    #         Displays:              (缩进6空格)
                    #           PHL 439P1:           (缩进8空格 - 显示器型号)
                    displays = []
                    lines = output.split('\n')

                    for i, line in enumerate(lines):
                        # 检测显示器名称行：缩进正好8个空格且以冒号结尾
                        # 例如 "        PHL 439P1:"
                        stripped = line.rstrip()
                        if stripped.endswith(':') and not stripped.endswith('Displays:'):
                            indent = len(line) - len(line.lstrip())
                            # 显示器型号行的缩进是8个空格
                            if indent == 8:
                                name = stripped.lstrip().rstrip(':')
                                # 排除其他以冒号结尾的行
                                if name and not name.startswith('Resolution') and \
                                   not name.startswith('Chipset') and \
                                   not name.startswith('Type') and \
                                   not name.startswith('Bus') and \
                                   not name.startswith('Vendor') and \
                                   not name.startswith('Device') and \
                                   not name.startswith('Revision') and \
                                   not name.startswith('ROM') and \
                                   not name.startswith('Metal'):
                                    displays.append(name)

                    # 根据索引返回对应的显示器型号（负索引视为无效，回退第一个）
                    if 0 <= display_index < len(displays):
                        return displays[display_index]
                    elif displays:
                        return displays[0]  # 默认返回第一个显示器

            elif system == 'Windows':
                # Windows: 使用 wmic 获取显示器信息（需要管理员权限）
                # 暂时返回空字符串，后续可以扩展
                pass

            elif system == 'Linux':
                # Linux: 使用 xrandr 获取显示器信息
                result = subprocess.run(
                    ['xrandr', '--query'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    # 解析 xrandr 输出获取显示器名称
                    lines = result.stdout.split('\n')
                    for i, line in enumerate(lines):
                        if ' connected' in line:
                            name = line.split(' connected')[0].strip()
                            return name

            return ""

        except Exception as e:
            self._logger.warning(f"获取显示器型号失败: {e}")
            return ""

    # ========== Argyll 回调处理 ==========

    def _on_argyll_measurement(self, result):
        """处理 Argyll 测量结果回调（在后台线程中执行）"""
        # 此方法在后台线程中执行，只通过信号将结果传递到主线程
        # 所有业务逻辑在 _process_measurement_in_main_thread 中处理
        self._internalMeasurementSignal.emit(result)

    @pyqtSlot(tuple)
    def _process_measurement_in_main_thread(self, result):
        """在主线程中处理测量结果（通过信号从后台线程安全传递）"""
        x, y, Y = result

        # ========== 重复测量平均（每色块 N 次读数 XYZ 线性平均） ==========
        # 与暗部多重采样互斥：已完成重复平均的读数不再触发暗部采样，避免测量次数叠加
        repeat_averaged = False
        if self._measure_repeat_count > 1 and self._cycle_running:
            X = x * Y / y if y > 0 else 0
            Z = (1 - x - y) * Y / y if y > 0 else 0
            self._repeat_measurements_xyz.append((X, Y, Z))
            self._repeat_current_count += 1

            if self._repeat_current_count < self._measure_repeat_count:
                self.logMessage.emit(
                    f"重复测量 [{self._repeat_current_count}/{self._measure_repeat_count}]: "
                    f"Y={Y:.4f}，继续测量…"
                )
                intermediate_result = {
                    "patchName": self._current_patch_name or "未知",
                    "rgb": {"r": self._current_patch_color[0], "g": self._current_patch_color[1], "b": self._current_patch_color[2]},
                    "x": x, "y": y, "Y": Y,
                    "cct": self._analyzer.calculate_cct(x, y),
                    "deltaE": self._calculate_delta_e_for_patch(self._current_patch_name, x, y, Y, self._current_patch_color),
                    "isRepeatIntermediate": True,
                    "repeatIndex": self._repeat_current_count,
                    "repeatTotal": self._measure_repeat_count,
                }
                self._measurement_result_throttler.emit(json.dumps(intermediate_result))
                QTimer.singleShot(50, self._trigger_repeat_measure)
                return  # 等待本组重复测量完成

            # 已达到目标次数：XYZ 线性平均后继续正常流程
            avg_X = sum(v[0] for v in self._repeat_measurements_xyz) / len(self._repeat_measurements_xyz)
            avg_Y = sum(v[1] for v in self._repeat_measurements_xyz) / len(self._repeat_measurements_xyz)
            avg_Z = sum(v[2] for v in self._repeat_measurements_xyz) / len(self._repeat_measurements_xyz)
            total = avg_X + avg_Y + avg_Z
            if total > 0:
                x = avg_X / total
                y = avg_Y / total
                Y = avg_Y
            self.logMessage.emit(
                f"重复测量完成: {len(self._repeat_measurements_xyz)} 次平均 → "
                f"(x={x:.4f}, y={y:.4f}, Y={Y:.4f})"
            )
            self._repeat_measurements_xyz = []
            self._repeat_current_count = 0
            repeat_averaged = True

        # ========== 暗部自适应多重采样逻辑（Gemini 优化版） ==========
        # 当亮度 Y 低于阈值时，多次测量取平均值以减少分光仪底噪影响
        # 关键修复：
        #   1. 极暗值检测（Y < 0.001）直接退出，避免 OLED 纯黑死循环
        #   2. 使用 XYZ 三刺激值进行线性平均，而非非线性 xyY
        if self._dark_sample_enabled and not repeat_averaged \
                and Y < self._dark_sample_threshold and self._cycle_running:
            # Gemini 建议 #1：极暗值直接退出（避免 OLED 纯黑死循环）
            if Y < self._dark_sample_min_threshold:
                self.logMessage.emit(
                    f"极暗值检测: Y={Y:.6f} < {self._dark_sample_min_threshold}，"
                    f"已达到仪器底噪极限，跳过多重采样"
                )
                # 直接使用本次测量结果，不进行多重采样
                self._dark_sample_measurements_xyz = []
                self._dark_sample_current_retry = 0
            else:
                # Gemini 建议 #3：将 xyY 转换为 XYZ 三刺激值进行存储
                # XYZ 是线性空间，可以安全地进行算术平均
                X = x * Y / y if y > 0 else 0
                Z = (1 - x - y) * Y / y if y > 0 else 0
                self._dark_sample_measurements_xyz.append((X, Y, Z))
                self._dark_sample_current_retry += 1

                self.logMessage.emit(
                    f"暗部多重采样 [{self._dark_sample_current_retry}/{self._dark_sample_max_retries + 1}]: "
                    f"Y={Y:.4f} < {self._dark_sample_threshold}, 记录 XYZ (X={X:.4f}, Y={Y:.4f}, Z={Z:.4f})"
                )

                # 发送中间测量结果到 UI（让用户看到实时进度）
                delta_e = self._calculate_delta_e_for_patch(
                    self._current_patch_name, x, y, Y, self._current_patch_color
                )
                intermediate_result = {
                    "patchName": self._current_patch_name or "未知",
                    "rgb": {"r": self._current_patch_color[0], "g": self._current_patch_color[1], "b": self._current_patch_color[2]},
                    "x": x, "y": y, "Y": Y,
                    "cct": self._analyzer.calculate_cct(x, y),
                    "deltaE": delta_e,
                    "isDarkSampleIntermediate": True,
                    "darkSampleRetry": self._dark_sample_current_retry,
                    "darkSampleMaxRetries": self._dark_sample_max_retries + 1
                }
                # 使用节流器发送（防止高频阻塞）
                self._measurement_result_throttler.emit(json.dumps(intermediate_result))

                # 判断是否需要继续重测
                if self._dark_sample_current_retry <= self._dark_sample_max_retries:
                    self.logMessage.emit(f"触发暗部重测...")
                    # 短延迟后触发重测（探头需要准备时间）
                    QTimer.singleShot(50, self._trigger_dark_sample_retry)
                    return  # 不继续正常流程，等待重测完成
                else:
                    # 已达到最大重测次数，计算 XYZ 平均值并转换回 xyY
                    avg_X, avg_Y, avg_Z = self._calculate_dark_sample_average_xyz()
                    # 将 XYZ 转换回 xyY
                    total = avg_X + avg_Y + avg_Z
                    if total > 0:
                        avg_x = avg_X / total
                        avg_y = avg_Y / total
                    else:
                        avg_x = 0.3127  # D65 白点作为默认值
                        avg_y = 0.3290
                    self.logMessage.emit(
                        f"暗部多重采样完成: XYZ 平均 (X={avg_X:.4f}, Y={avg_Y:.4f}, Z={avg_Z:.4f}) "
                        f"→ xyY (x={avg_x:.4f}, y={avg_y:.4f}, Y={avg_Y:.4f}) "
                        f"(共 {len(self._dark_sample_measurements_xyz)} 次测量)"
                    )
                    # 使用平均值继续后续流程
                    x, y, Y = avg_x, avg_y, avg_Y
                    # 清空多重采样状态
                    self._dark_sample_measurements_xyz = []
                    self._dark_sample_current_retry = 0

        # 计算Delta E（相对于目标颜色）
        delta_e = self._calculate_delta_e_for_patch(
            self._current_patch_name,
            x, y, Y,
            self._current_patch_color
        )

        # 计算 CCT + Duv（供色温追踪图使用）
        try:
            _, duv = self._analyzer.calculate_cct_duv(x, y)
        except Exception:
            duv = 0.0

        # 发送测量结果到 Web UI
        result_data = {
            "patchName": self._current_patch_name or "未知",
            "rgb": {
                "r": self._current_patch_color[0],
                "g": self._current_patch_color[1],
                "b": self._current_patch_color[2]
            },
            "x": x,
            "y": y,
            "Y": Y,
            "cct": self._analyzer.calculate_cct(x, y),
            "duv": duv,
            "deltaE": delta_e
        }

        # 使用节流器发送测量结果（防止高频阻塞）
        self._measurement_result_throttler.emit(json.dumps(result_data))

        # 存储测量数据
        self._store_measurement(result_data)

        # ========== 断点续测：保存已完成的测量数据 ==========
        # 将本次测量结果添加到已完成数据列表
        if self._cycle_running:
            self._cycle_completed_data.append(result_data)

            # 发送断点更新信号（使用节流器）
            self._checkpoint_throttler.emit(json.dumps({
                "index": self._cycle_index,
                "total": len(self._cycle_queue),
                "completed": len(self._cycle_completed_data),
                "patchName": self._current_patch_name,
                "measurementName": self._current_measurement_name
            }))

        # ========== 事件驱动模式：区分循环测量和单次测量 ==========
        if self._cycle_running:
            # 保存当前色块的亮度用于 OLED 智能触发
            self._oled_last_patch_brightness = Y

            # ========== OLED 防漂移黑帧插入逻辑（Gemini 优化版） ==========
            # 关键修复：
            #   4. 时序错位：黑帧结束后增加 UI 稳定延迟
            #   5. 智能触发：只在高亮度色块后插入黑帧
            is_last_patch = self._cycle_index >= len(self._cycle_queue) - 1
            # Gemini 建议 #5：智能触发 - 只在高亮度色块后才插入黑帧
            should_insert_bfi = self._should_insert_oled_black_frame(Y, self._current_patch_color)

            if self._oled_mode_enabled and not self._oled_waiting_black_frame and not is_last_patch and should_insert_bfi:
                self._oled_waiting_black_frame = True
                self.logMessage.emit(
                    f"OLED 防漂移: 高亮度色块 (Y={Y:.2f}, RGB avg={sum(self._current_patch_color)/3:.0f}) "
                    f"→ 显示黑帧等待 {self._oled_black_frame_delay_ms}ms..."
                )
                # 显示纯黑色块
                self._show_color(0, 0, 0)
                self.patchColorChanged.emit(json.dumps({"r": 0, "g": 0, "b": 0}))
                # 黑帧等待后继续下一个色块（黑帧结束后会有 UI 稳定延迟）
                QTimer.singleShot(self._oled_black_frame_delay_ms, self._oled_black_frame_complete)
                return  # 不立即进入下一个色块
            elif self._oled_mode_enabled and not should_insert_bfi and not is_last_patch:
                self.logMessage.emit(
                    f"OLED 防漂移: 低亮度色块 (Y={Y:.2f})，跳过黑帧插入"
                )

            # 循环测量：测量完成后直接触发下一个色块
            # 延迟已经在色块显示后使用了（等待显示器稳定）
            # 这里只需要一个小延迟让探头准备好（50ms）
            self._cycle_index += 1

            self.logMessage.emit(f"循环测量调试: 测量完成, _cycle_index 从 {self._cycle_index-1} 增加到 {self._cycle_index}, 总共 {len(self._cycle_queue)} 个色块")

            # 使用短延迟触发下一个测量（探头需要时间准备下一次测量）
            QTimer.singleShot(50, self._cycle_next_measurement)
        else:
            # 单次测量：发送完成信号
            self.logMessage.emit(f"测量完成: x={x:.4f}, y={y:.4f}, Y={Y:.2f}")
            self.measurementCompleted.emit()

    def _should_insert_oled_black_frame(self, Y: float, rgb: tuple) -> bool:
        """
        Gemini 建议 #5：智能判断是否需要插入 OLED 黑帧

        只有高亮度色块会触发 OLED 的 ABL 机制，暗部色块无需插入黑帧。
        判断条件：亮度 Y > 阈值 或 RGB 平均值 > 阈值

        Args:
            Y: 测量亮度值 (cd/m²)
            rgb: RGB 值 (r, g, b)

        Returns:
            bool: 是否需要插入黑帧
        """
        # 计算 RGB 平均值
        r, g, b = rgb
        rgb_avg = (r + g + b) / 3

        # 亮度阈值判断（Y > 20 nits）
        brightness_trigger = Y > self._oled_bfi_trigger_threshold

        # RGB 平均值阈值判断（RGB avg > 128）
        rgb_trigger = rgb_avg > self._oled_bfi_trigger_rgb_avg

        return brightness_trigger or rgb_trigger

    def _trigger_repeat_measure(self):
        """触发重复测量的下一次读数（保持当前色块不变）"""
        if not self._cycle_running or not self._argyll_controller:
            self._repeat_measurements_xyz = []
            self._repeat_current_count = 0
            return

        self.logMessage.emit(f"重复测量: 色块 {self._current_patch_name}, RGB {self._current_patch_color}")
        thread = threading.Thread(
            target=self._measure_in_thread,
            name="backend-repeat-measure-thread",
            daemon=True
        )
        thread.start()

    def _trigger_dark_sample_retry(self):
        """触发暗部多重采样的重测"""
        if not self._cycle_running or not self._argyll_controller:
            # 重置状态
            self._dark_sample_measurements_xyz = []
            self._dark_sample_current_retry = 0
            return

        # 保持当前色块不变，直接启动新的测量
        self.logMessage.emit(f"暗部重测: 色块 {self._current_patch_name}, RGB {self._current_patch_color}")
        thread = threading.Thread(
            target=self._measure_in_thread,
            name="backend-dark-sample-retry-thread",
            daemon=True
        )
        thread.start()

    def _calculate_dark_sample_average_xyz(self) -> Tuple[float, float, float]:
        """
        Gemini 建议 #3：计算暗部多重采样的 XYZ 平均值

        XYZ 是线性空间，可以安全地进行算术平均。
        注意：不能对非线性 xyY 进行平均！

        Returns:
            Tuple[float, float, float]: 平均 (X, Y, Z) 三刺激值
        """
        if not self._dark_sample_measurements_xyz:
            return (0.0, 0.0, 0.0)

        total_X = sum(m[0] for m in self._dark_sample_measurements_xyz)
        total_Y = sum(m[1] for m in self._dark_sample_measurements_xyz)
        total_Z = sum(m[2] for m in self._dark_sample_measurements_xyz)
        count = len(self._dark_sample_measurements_xyz)

        return (total_X / count, total_Y / count, total_Z / count)

    def _oled_black_frame_complete(self):
        """
        OLED 黑帧等待完成，准备进入下一个色块

        Gemini 建议 #4：修复时序错位
        黑帧结束后，必须等待 UI 稳定延迟，确保屏幕颜色完全切换后再触发测量。
        这是因为 OLED/LCD 像素有物理响应时间。
        """
        self._oled_waiting_black_frame = False
        self.logMessage.emit(
            f"OLED 黑帧等待完成，增加 UI 稳定延迟 {self._oled_ui_settling_delay_ms}ms "
            f"(确保屏幕颜色完全切换后再测量)"
        )

        # 增加索引，进入下一个色块
        self._cycle_index += 1
        # 先触发下一个色块的显示（_cycle_next_measurement 会显示色块并等待延迟）
        # 在 OLED 模式下，需要额外的 UI 稳定延迟
        # 使用链式 QTimer：先等待 UI 稳定延迟，然后触发下一个测量
        QTimer.singleShot(self._oled_ui_settling_delay_ms, self._cycle_next_measurement)

    def _store_measurement(self, result_data):
        """存储测量数据"""
        name = result_data["patchName"]
        rgb = (
            result_data["rgb"]["r"],
            result_data["rgb"]["g"],
            result_data["rgb"]["b"]
        )
        x = result_data["x"]
        y = result_data["y"]
        Y = result_data["Y"]

        # ========== LUT 模式：存储 ti1 色块测量数据 ==========
        # 如果当前是 LUT 工作流，使用 update_lut_measurement 存储
        if self._lut_workflow_params is not None:
            self._current_measurement.update_lut_measurement(
                sample_id=name,
                rgb=rgb,
                x=x,
                y=y,
                Y=Y
            )

        # ========== ICC/custom/ccmx 模式：也存储到 lut_patches ==========
        # 这些模式测量的是自定义色块，需要存储到 lut_patches 中
        if self._current_measure_mode in ['icc', 'custom', 'ccmx']:
            self._current_measurement.update_lut_measurement(
                sample_id=name,
                rgb=rgb,
                x=x,
                y=y,
                Y=Y
            )

        # ========== 均匀性测量：存储网格测点数据 ==========
        # 色块名形如 "U-r{row}c{col}"
        if name and name.startswith("U-"):
            import re as _re
            m = _re.match(r"^U-r(\d+)c(\d+)$", name)
            if m:
                self._current_measurement.update_uniformity_measurement(
                    row=int(m.group(1)), col=int(m.group(2)),
                    x=x, y=y, Y=Y,
                    cct=result_data.get("cct"),
                )

        # 色域测量
        if name in ["红", "绿", "蓝", "白", "黑"]:
            self._gamut_measurements[name] = result_data

            # 更新新的数据结构
            self._current_measurement.update_gamut_measurement(name, rgb, x, y, Y)

            # 如果完成了 RGBW 测量，计算色域覆盖率
            if len(self._gamut_measurements) >= 4:
                self._calculate_and_emit_gamut_coverage()

            # 更新显示器基础数据
            self._calculate_and_emit_display_basic_data()

        # 灰阶测量
        if name and "%" in name:
            # 清除之前的相同灰阶数据
            existing = [d for d in self._gamma_measurements if d["patchName"] != name]
            existing.append(result_data)
            self._gamma_measurements = existing

            # 更新新的数据结构
            input_level = float(name.replace("%", ""))
            self._current_measurement.update_gamma_measurement(input_level, Y, name, rgb)

            # 如果完成了灰阶测量，计算 Gamma
            if len(self._gamma_measurements) >= 2:
                self._calculate_and_emit_gamma()

    def _calculate_and_emit_display_basic_data(self):
        """计算显示器基础数据并发送信号"""
        if not self._gamut_measurements:
            return

        # 使用分析器计算显示器基础数据
        display_data = self._analyzer.calculate_display_basic_data(
            self._gamut_measurements,
            self._gamma_measurements
        )

        # 获取白点xy值
        white_data = self._gamut_measurements.get("白")
        white_x = white_data.get("x") if white_data else None
        white_y = white_data.get("y") if white_data else None

        # 格式化数据
        formatted_data = {
            "peakLuminance": round(display_data["peak_luminance"], 2) if display_data.get("peak_luminance") else None,
            "blackLuminance": round(display_data["black_luminance"], 4) if display_data.get("black_luminance") else None,
            "contrastRatio": round(display_data["contrast_ratio"], 1) if display_data.get("contrast_ratio") else None,
            "whiteCct": round(display_data["white_cct"]) if display_data.get("white_cct") else None,
            "whiteX": round(white_x, 4) if white_x else None,
            "whiteY": round(white_y, 4) if white_y else None,
            "whiteDeviation": round(display_data["white_deviation"], 2) if display_data.get("white_deviation") else None,
            "gamma": round(display_data["gamma"], 2) if display_data.get("gamma") else None
        }

        self.displayBasicDataUpdated.emit(json.dumps(formatted_data))

    def _calculate_delta_e_for_patch(self, patch_name: str, x: float, y: float, Y: float, rgb: tuple) -> float:
        """
        计算色块的Delta E（相对于sRGB目标值）

        Args:
            patch_name: 色块名称
            x, y, Y: 测量的CIE xyY值
            rgb: 测量的RGB值

        Returns:
            float: Delta E值，如果无法计算则返回None
        """
        if not patch_name:
            return None

        # sRGB标准色块的xy坐标
        SRGB_TARGETS = {
            "红": {"x": 0.64, "y": 0.33, "Y": 21.26},  # sRGB红色
            "绿": {"x": 0.30, "y": 0.60, "Y": 71.52},  # sRGB绿色
            "蓝": {"x": 0.15, "y": 0.06, "Y": 7.22},   # sRGB蓝色
            "白": {"x": 0.3127, "y": 0.3290, "Y": 100},  # D65白点
            "黑": {"x": 0.3127, "y": 0.3290, "Y": 0},   # 黑场
        }

        # 查找目标值
        target = None
        if patch_name in SRGB_TARGETS:
            target = SRGB_TARGETS[patch_name]
        elif "%" in patch_name and "°" not in patch_name and "-" not in patch_name:
            # 灰阶：目标为D65白点
            try:
                level = float(patch_name.replace("%", ""))
                # 根据灰阶级别估算目标亮度
                target_Y = (level / 100) ** 2.2 * 100  # 假设Gamma 2.2
                target = {"x": 0.3127, "y": 0.3290, "Y": target_Y}
            except:
                pass

        # P2 集成：饱和度扫描/色相扫描等任意色块，按 sRGB 编码直接推目标 xyY
        # （色块以其 sRGB 渲染结果为参考基准）
        if target is None and rgb:
            try:
                from src.color_science.spaces import srgb_to_xyz
                X, Yt, Z = srgb_to_xyz(int(rgb[0]), int(rgb[1]), int(rgb[2]))
                total = X + Yt + Z
                if total > 0:
                    target = {"x": X / total, "y": Yt / total, "Y": Yt}
            except Exception:
                pass

        if not target:
            return None

        # 计算Delta E 2000
        measured = {"x": x, "y": y, "Y": Y}
        try:
            delta_e = self._analyzer.calculate_delta_e_2000(measured, target)
            return round(delta_e, 2)
        except Exception as e:
            # 如果Delta E 2000计算失败，使用简化方法
            return round(self._analyzer.calculate_delta_e(measured, target), 2)

    def _calculate_and_emit_gamut_coverage(self):
        """计算色域覆盖率并发送信号"""
        if not self._gamut_measurements:
            return

        # 设置分析器数据
        red = self._gamut_measurements.get("红")
        green = self._gamut_measurements.get("绿")
        blue = self._gamut_measurements.get("蓝")
        white = self._gamut_measurements.get("白")

        if red and green and blue:
            self._analyzer.set_gamut_data(red, green, blue, white or {})

            # 计算覆盖率
            coverage = {
                "sRGB": round(self._analyzer.calculate_gamut_coverage("sRGB"), 1),
                "DCI-P3": round(self._analyzer.calculate_gamut_coverage("DCI-P3"), 1),
                "AdobeRGB": round(self._analyzer.calculate_gamut_coverage("Adobe RGB"), 1),
                "Rec2020": round(self._analyzer.calculate_gamut_coverage("Rec.2020"), 1),
                "gamutTriangle": self._analyzer.get_gamut_triangle(),
                "whitePoint": self._analyzer.get_white_point()
            }

            self.gamutCoverageUpdated.emit(json.dumps(coverage))

    def _calculate_and_emit_gamma(self):
        """计算 Gamma 值并发送信号"""
        if not self._gamma_measurements:
            return

        # 设置分析器数据
        self._analyzer.set_gamma_data(self._gamma_measurements)

        # 计算 Gamma 值
        gamma_value = self._analyzer.calculate_gamma()

        # 计算 Gamma 曲线
        gamma_curve = self._analyzer.calculate_gamma_curve()

        gamma_data = {
            "gamma": round(gamma_value, 2) if gamma_value else None,
            "curve": [
                {
                    "input": round(p[0] * 100, 1),
                    "Y": round(p[1], 2),
                    "gamma": round(p[2], 2) if p[2] else None
                }
                for p in gamma_curve
            ]
        }

        self.gammaUpdated.emit(json.dumps(gamma_data))

    def _on_argyll_error(self, message):
        """
        处理 Argyll 错误回调（支持断点续测）

        当检测到 USB 断开类型的错误时：
        1. 保存当前测量状态到 checkpoint
        2. 如果开启了自动重连，启动重连流程
        3. 如果重连失败，进入挂起状态等待手动恢复

        Args:
            message: 错误消息
        """
        self.logMessage.emit(f"探头错误: {message}")

        # 检查是否是 USB 断开类型的错误
        usb_disconnect_keywords = [
            'usb 设备已断开',
            'usb 管道',
            'readpipeasync',
            '未检测到探头',
            '探头已被拔出',
            '设备可能已断开',
            'no instrument',
            'instrument not found',
            'communication error',
        ]
        is_usb_disconnect = any(
            keyword in message.lower()
            for keyword in usb_disconnect_keywords
        )

        # ========== 通过信号传递错误状态到主线程 ==========
        # 确保线程安全
        self._internalErrorSignal.emit(message)

        if is_usb_disconnect:
            # USB 断开：发送断开状态到 UI
            self.logMessage.emit(i18n.t("检测到 USB 设备断开，保存断点数据..."))

            # ========== 保存断点（Checkpoint） ==========
            if self._cycle_running:
                self._save_checkpoint(reason=message)

            # ========== 发送探头断开状态 ==========
            self.probeStatusChanged.emit(json.dumps({
                "connected": False,
                "status": "disconnected",
                "error": message,
                "canResume": self._checkpoint is not None
            }))

            # ========== 自动重连流程 ==========
            if self._cycle_running and self._auto_reconnect_enabled:
                self.logMessage.emit(i18n.t("启动自动重连流程..."))
                self._session_state = MeasurementSessionState.RECONNECTING

                # 发送重连状态信号
                self.reconnectStatusChanged.emit(json.dumps({
                    "status": "starting",
                    "message": "开始尝试自动重连..."
                }))

                # 在后台线程中执行重连（避免阻塞主线程）
                thread = threading.Thread(
                    target=self._execute_reconnect_in_thread,
                    name="backend-reconnect-thread",
                    daemon=True
                )
                thread.start()
            else:
                # 不在测量中或未开启自动重连：直接进入挂起状态
                if self._cycle_running:
                    self._enter_suspended_state(reason=message)
        else:
            # 其他硬件错误：保持实际连接状态
            actual_connected = self._argyll_controller.is_connected() if self._argyll_controller else False
            self.probeStatusChanged.emit(json.dumps({
                "connected": actual_connected,
                "error": message
            }))

            # 如果在循环测量中，停止（非 USB 断开的严重错误）
            if self._cycle_running:
                self.logMessage.emit(i18n.t("非 USB 断开错误，停止循环测量"))
                self.stop_cycle()

    def _process_error_in_main_thread(self, message: str):
        """
        在主线程中处理错误状态（通过信号从后台线程安全传递）

        Args:
            message: 错误消息
        """
        # 此方法用于线程安全的错误处理
        # 实际处理逻辑已在 _on_argyll_error 中完成
        pass

    def _on_argyll_status(self, message):
        """处理 Argyll 状态回调"""
        self.logMessage.emit(message)

    # ========== 断点续测核心方法 ==========

    def _save_checkpoint(self, reason: str = ""):
        """
        保存当前测量状态到 checkpoint

        在探头断开时保存已成功测量的数据，以便后续恢复测量。

        Args:
            reason: 保存断点的原因（通常是错误消息）
        """
        if not self._cycle_running:
            return

        self._checkpoint = MeasurementCheckpoint(
            cycle_queue=self._cycle_queue.copy(),
            completed_data=self._cycle_completed_data.copy(),
            current_index=self._cycle_index,
            measurement_name=self._current_measurement_name,
            session_state=self._session_state,
            created_at=time.time(),
            gamut_measurements=self._gamut_measurements.copy(),
            gamma_measurements=self._gamma_measurements.copy()
        )

        self.logMessage.emit(
            f"断点已保存: 已完成 {len(self._cycle_completed_data)} 个色块，"
            f"失败位置索引 {self._cycle_index}, 原因: {reason}"
        )

        # 发送断点更新信号
        self.checkpointUpdated.emit(json.dumps({
            "index": self._cycle_index,
            "total": len(self._cycle_queue),
            "completed": len(self._cycle_completed_data),
            "reason": reason,
            "measurementName": self._current_measurement_name,
            "canResume": True
        }))

    def _execute_reconnect_in_thread(self):
        """
        在后台线程中执行重连流程

        此方法由 _on_argyll_error 触发，在独立线程中执行重连，
        避免阻塞主线程。重连结果通过信号传递到主线程处理。
        """
        with self._reconnect_lock:
            if self._argyll_controller is None:
                self._internalReconnectSignal.emit(False)
                return

            # 发送重连开始状态
            attempt = self._argyll_controller.get_reconnect_attempt()
            max_attempts = self._argyll_controller.get_max_reconnect_attempts()

            # 执行重连
            success = self._argyll_controller.reconnect()

            # 通过信号传递结果到主线程
            self._internalReconnectSignal.emit(success)

    def _process_reconnect_result_in_main_thread(self, success: bool):
        """
        在主线程中处理重连结果（通过信号从后台线程安全传递）

        Args:
            success: 重连是否成功
        """
        if success:
            self.logMessage.emit(i18n.t("自动重连成功，恢复测量..."))
            self._session_state = MeasurementSessionState.RUNNING

            # 发送探头连接状态
            self.probeStatusChanged.emit(json.dumps({
                "connected": True,
                "status": "connected",
                "reconnected": True
            }))

            # 发送重连成功状态
            self.reconnectStatusChanged.emit(json.dumps({
                "status": "success",
                "message": "探头重连成功"
            }))

            # ========== 恢复测量流程 ==========
            # 从断点位置继续测量
            self._resume_from_checkpoint()
        else:
            self.logMessage.emit(i18n.t("自动重连失败，进入挂起状态..."))
            self._enter_suspended_state(
                reason="自动重连失败，请检查 USB 连接后手动恢复"
            )

    def _enter_suspended_state(self, reason: str = ""):
        """
        进入挂起状态（等待手动恢复）

        Args:
            reason: 挂起原因
        """
        self._session_state = MeasurementSessionState.SUSPENDED
        self._cycle_running = False  # 暂停循环，但不清空数据

        self.logMessage.emit(f"测量已挂起: {reason}")

        # 发送测量挂起信号
        self.measurementSuspended.emit(json.dumps({
            "reason": reason,
            "canResume": self._checkpoint is not None,
            "checkpoint": {
                "index": self._checkpoint.current_index if self._checkpoint else 0,
                "total": len(self._checkpoint.cycle_queue) if self._checkpoint else 0,
                "completed": len(self._checkpoint.completed_data) if self._checkpoint else 0,
                "measurementName": self._checkpoint.measurement_name if self._checkpoint else ""
            } if self._checkpoint else None
        }))

        # 发送重连失败状态
        self.reconnectStatusChanged.emit(json.dumps({
            "status": "failed",
            "message": reason
        }))

        # 发送探头断开状态
        self.probeStatusChanged.emit(json.dumps({
            "connected": False,
            "status": "suspended",
            "error": reason,
            "canResume": self._checkpoint is not None
        }))

    def _resume_from_checkpoint(self):
        """
        从断点恢复测量流程

        重连成功后，从上次失败的位置继续测量。
        """
        if self._checkpoint is None:
            self.logMessage.emit(i18n.t("无断点数据，无法恢复测量"))
            return

        # 恢复测量队列和索引
        self._cycle_queue = self._checkpoint.cycle_queue.copy()
        self._cycle_completed_data = self._checkpoint.completed_data.copy()
        self._cycle_index = self._checkpoint.current_index
        self._gamut_measurements = self._checkpoint.gamut_measurements.copy()
        self._gamma_measurements = self._checkpoint.gamma_measurements.copy()

        # 设置测量状态
        self._cycle_running = True
        self._session_state = MeasurementSessionState.RUNNING

        # 发送恢复信号
        self.measurementResumed.emit()

        self.logMessage.emit(
            f"从断点恢复测量: 从索引 {self._cycle_index} 继续，"
            f"已完成 {len(self._cycle_completed_data)} 个"
        )

        # 发送进度更新
        progress = {
            "current": self._cycle_index + 1,
            "total": len(self._cycle_queue),
            "patchName": self._cycle_queue[self._cycle_index][3] if self._cycle_index < len(self._cycle_queue) else "",
            "resumed": True
        }
        self.cycleMeasurementProgress.emit(json.dumps(progress))

        # 继续下一个测量
        self._cycle_next_measurement()

    @pyqtSlot()
    def resume_measurement(self):
        """
        手动恢复挂起的测量

        当自动重连失败后，用户可以重新插拔 USB 并调用此方法恢复测量。

        P0-B: 支持 MeasurementService feature flag：
        - 如果 MeasurementService 正在使用，尝试通过 bridge.resume_from_checkpoint()
        - 如果 bridge 恢复失败，fallback 到 legacy 恢复流程

        流程：
        1. 检查是否有有效的 checkpoint
        2. 尝试重新连接探头
        3. 连接成功后从断点位置继续测量

        Returns:
            通过信号反馈结果
        """
        # ========== MeasurementService Feature Flag 分支 (P0-B) ==========
        if self._use_measurement_service and self._measurement_bridge is not None:
            self.logMessage.emit("[MeasurementService] 正在尝试恢复测量...")
            try:
                # 尝试通过 bridge 恢复
                success = self._measurement_bridge.resume_from_checkpoint()

                if success:
                    self.logMessage.emit("[MeasurementService] 测量已恢复")
                    return  # MeasurementService 已接管恢复流程

                # bridge 恢复失败，fallback 到 legacy
                self._logger.warning("MeasurementService 恢复失败，fallback 到 legacy")
                self.logMessage.emit("[MeasurementService] 恢复失败，使用 legacy 恢复")

            except Exception as e:
                self._logger.error(f"MeasurementService 恢复异常: {e}")
                self.logMessage.emit(f"[MeasurementService] 恢复异常: {e}")
                # fallback 到 legacy

        # ========== Legacy 恢复流程（原有代码） ==========
        if self._checkpoint is None:
            self.logMessage.emit(i18n.t("无断点数据，无法恢复测量"))
            self.measurementSuspended.emit(json.dumps({
                "reason": "无断点数据",
                "canResume": False
            }))
            return

        if self._session_state != MeasurementSessionState.SUSPENDED:
            self.logMessage.emit(f"当前状态为 {self._session_state}，无法恢复")
            return

        self.logMessage.emit(i18n.t("正在尝试手动恢复测量..."))

        # 发送恢复尝试状态
        self.reconnectStatusChanged.emit(json.dumps({
            "status": "manual_resume",
            "message": "正在尝试恢复测量..."
        }))

        # 尝试连接探头
        self.probeStatusChanged.emit(json.dumps({
            "connected": False,
            "status": "connecting",
            "message": "正在连接探头..."
        }))

        # 在后台线程中执行连接
        thread = threading.Thread(
            target=self._execute_manual_reconnect,
            name="backend-manual-reconnect-thread",
            daemon=True
        )
        thread.start()

    def _execute_manual_reconnect(self):
        """
        在后台线程中执行手动重连
        """
        with self._reconnect_lock:
            if self._argyll_controller is None:
                self._internalReconnectSignal.emit(False)
                return

            # 重置重连计数
            self._argyll_controller._current_reconnect_attempt = 0

            # 尝试连接
            success = self._argyll_controller.connect()

            # 通过信号传递结果
            self._internalReconnectSignal.emit(success)

    @pyqtSlot(result=str)
    def get_checkpoint_info(self):
        """
        获取当前断点信息

        Returns:
            JSON 字符串，包含断点详情
        """
        if self._checkpoint is None:
            return json.dumps({
                "hasCheckpoint": False,
                "sessionState": self._session_state
            })

        return json.dumps({
            "hasCheckpoint": True,
            "sessionState": self._session_state,
            "measurementName": self._checkpoint.measurement_name,
            "currentIndex": self._checkpoint.current_index,
            "totalPatches": len(self._checkpoint.cycle_queue),
            "completedCount": len(self._checkpoint.completed_data),
            "createdAt": self._checkpoint.created_at,
            "canResume": True
        })

    @pyqtSlot()
    def cancel_suspended_measurement(self):
        """
        取消挂起的测量

        清除断点数据，彻底终止测量流程。
        """
        if self._session_state != MeasurementSessionState.SUSPENDED:
            self.logMessage.emit(i18n.t("当前没有挂起的测量"))
            return

        self.logMessage.emit(i18n.t("取消挂起的测量，清除断点数据..."))

        # 清除断点
        self._checkpoint = None
        self._cycle_completed_data = []
        self._session_state = MeasurementSessionState.IDLE

        # 恢复显卡 LUT 和卸载 Null Profile
        if self._lut_controller:
            display_index = self._get_patch_display_index()
            # 使用状态标记判断是否需要卸载 Null Profile
            if self._null_profile_applied and self._linear_profile_path:
                if self._lut_controller.uninstall_profile(display_index, self._linear_profile_path):
                    self._null_profile_applied = False
                    # 加载系统当前 Profile 的 VCGT 以刷新显示
                    self._lut_controller.load_system_profile_lut(display_index)
            else:
                # 如果没有使用 Null Profile，则恢复 LUT
                self._lut_controller.restore_lut(display_index)

        # 隐藏色块
        self.hide_patch()

        # 发送取消信号
        self.measurementSuspended.emit(json.dumps({
            "reason": "用户取消",
            "canResume": False
        }))

        self.logMessage.emit(i18n.t("挂起测量已取消"))

    @pyqtSlot(bool)
    def set_auto_reconnect_enabled(self, enabled: bool):
        """
        设置是否允许自动重连

        Args:
            enabled: 是否允许自动重连
        """
        self._auto_reconnect_enabled = enabled
        self.logMessage.emit(f"自动重连: {'已启用' if enabled else '已禁用'}")

    # ========== MeasurementService Feature Flag 配置接口 (P0-B) ==========

    @pyqtSlot(bool)
    def set_use_measurement_service(self, enabled: bool):
        """
        设置是否使用 MeasurementService

        P0-B: 通过前端或环境变量控制 feature flag。

        Args:
            enabled: True 启用 MeasurementService，False 使用 legacy
        """
        self._use_measurement_service = enabled
        self.logMessage.emit(f"MeasurementService: {'已启用' if enabled else '已禁用（使用 legacy）'}")

        # 如果禁用，清除 bridge 引用（下次启用时重新创建）
        if not enabled and self._measurement_bridge is not None:
            try:
                if self._measurement_bridge.is_active:
                    self._measurement_bridge.stop_cycle()
            except Exception:
                pass  # 忽略停止异常
            self._measurement_bridge = None

    @pyqtSlot(bool)
    def set_measurement_service_fallback_enabled(self, enabled: bool):
        """
        设置 MeasurementService 失败时是否回退到 legacy

        Args:
            enabled: True 启用 fallback，False 直接终止测量
        """
        self._measurement_service_fallback_enabled = enabled
        self.logMessage.emit(f"MeasurementService fallback: {'已启用' if enabled else '已禁用'}")

    @pyqtSlot(result=str)
    def get_measurement_service_status(self):
        """
        获取 MeasurementService 当前状态

        Returns:
            JSON 字符串: {"enabled": true, "fallback": true, "active": false}
        """
        return json.dumps({
            "enabled": self._use_measurement_service,
            "fallback": self._measurement_service_fallback_enabled,
            "active": self._measurement_bridge is not None and self._measurement_bridge.is_active,
            "bridgeState": self._measurement_bridge.state.value if self._measurement_bridge else "idle"
        })

    def _auto_configure_delay(self, patch_rgb: Optional[tuple] = None) -> int:
        """
        根据当前探头类型、显示器类型和色块亮度自动配置测量延迟

        规则：
        1. 获取探头推荐的延迟时间（基础延迟）
        2. 如果显示器类型为投影仪(Projector)，保底覆盖为至少 800ms
           （投影仪通常有较高的输入延迟）
        3. 如果显示器类型为 LCD 且当前是暗场色块（亮度 < 30%），额外增加 150ms
           （LCD 液晶分子在暗场切换时响应较慢，可能有残影）
        4. 如果显示器类型为 OLED，不需要额外延迟（OLED 响应极快 < 1ms）
        5. 更新内部延迟变量并发送信号通知前端

        Args:
            patch_rgb: 当前色块的 RGB 值 (r, g, b)，如果为 None 则不判断亮度

        Returns:
            int: 最终配置的延迟时间（毫秒）
        """
        if not self._argyll_controller:
            return self._current_delay_ms

        # 获取探头推荐的延迟时间（基础延迟）
        recommended_delay = self._argyll_controller.get_recommended_delay()

        # 初始化为推荐延迟
        final_delay = recommended_delay

        # ========== 检查显示器类型 ==========
        if self._current_display_type == DisplayType.PROJECTOR:
            # 投影仪需要更长的延迟（信号处理、光路等）
            final_delay = max(recommended_delay, 800)
            self.logMessage.emit(f"投影仪模式：测量延迟保底设置为 {final_delay}ms")

        elif self._current_display_type == DisplayType.LCD:
            # LCD 在暗场色块切换时液晶分子响应较慢，需要额外延迟
            # 典型 LCD 的 G2G 响应时间在暗场可能达到 50-150ms
            if patch_rgb is not None:
                # 计算相对亮度（使用 sRGB 亮度公式）
                r, g, b = patch_rgb
                relative_luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0

                # 如果亮度低于 30%，认为是暗场，增加额外延迟
                if relative_luminance < 0.30:
                    # 暗场额外增加 150ms，确保液晶分子完全偏转
                    dark_field_bonus = 150
                    final_delay += dark_field_bonus
                    brightness_pct = relative_luminance * 100
                    self.logMessage.emit(
                        f"LCD 暗场模式：色块亮度 {brightness_pct:.1f}%，"
                        f"增加额外延迟 {dark_field_bonus}ms，总延迟 {final_delay}ms"
                    )
            else:
                # 没有色块信息，使用基础延迟
                pass

        elif self._current_display_type == DisplayType.OLED:
            # OLED 响应极快（< 0.1ms），不需要额外延迟
            # 但探头仍然需要基础延迟来稳定测量
            self.logMessage.emit(f"OLED 模式：使用探头推荐延迟 {final_delay}ms")

        # 更新内部延迟变量
        self._current_delay_ms = final_delay
        self._measure_delay = final_delay  # 同步更新用户可调节的延迟

        # 发送信号通知前端 UI 更新
        self.delayConfigUpdated.emit(final_delay)

        return final_delay

    # ========== 基础通信 ==========

    @pyqtSlot()
    def ping(self):
        """测试通信"""
        self.logMessage.emit("Backend: 通信正常")

    # ========== 显示模式切换 ==========

    @pyqtSlot()
    def open_floating_window(self):
        """打开独立浮动窗口"""
        if self._patch_window:
            self._patch_window.show_resizable(400, 400)
            self._display_mode = 'floating'
            self.logMessage.emit(i18n.t("打开独立浮动窗口"))

    @pyqtSlot()
    def debug_window_state(self):
        """调试：把所有顶层窗口状态写入 /tmp/qt_window_state.json（含原生 NSWindow 信息）"""
        from PyQt6.QtWidgets import QApplication
        windows = []
        native_info = None
        for w in QApplication.topLevelWidgets():
            g = w.geometry()
            entry = {
                "cls": w.metaObject().className(),
                "name": w.objectName() or "",
                "title": (w.windowTitle() or "")[:30],
                "visible": w.isVisible(),
                "minimized": w.isMinimized(),
                "fullscreen": w.isFullScreen(),
                "geo": [g.x(), g.y(), g.width(), g.height()],
            }
            if w.metaObject().className() == "PatchWindow":
                try:
                    import objc
                    ns_view = objc.objc_object(c_void_p=int(w.winId()))
                    ns_win = ns_view.window()
                    native_info = {
                        "level": int(ns_win.level()),
                        "isVisible": bool(ns_win.isVisible()),
                        "occlusion": int(ns_win.occlusionState().rawValue()),
                        "frame": [int(ns_win.frame().origin.x), int(ns_win.frame().origin.y),
                                  int(ns_win.frame().size.width), int(ns_win.frame().size.height)],
                    }
                    entry["native"] = native_info
                except Exception as e:
                    entry["native_error"] = str(e)
                # 全屏测量控制条内部状态
                entry["overlay"] = {
                    "visible": w.progress_overlay.isVisible(),
                    "geo": [w.progress_overlay.x(), w.progress_overlay.y(),
                            w.progress_overlay.width(), w.progress_overlay.height()],
                    "text": w.progress_label.text(),
                    "measuring": w._measuring_active,
                }
            windows.append(entry)
        screens = []
        for s in QApplication.screens():
            sg = s.geometry()
            screens.append([sg.x(), sg.y(), sg.width(), sg.height()])
        try:
            with open('/tmp/qt_window_state.json', 'w') as f:
                json.dump({"windows": windows, "screens": screens}, f, ensure_ascii=False, indent=1)
        except Exception as e:
            logger.error(f"debug_window_state 写入失败: {e}")

    @pyqtSlot()
    def show_patch_window_fullscreen(self):
        """全屏显示测量色块窗口（循环测量开始时自动调用，便于探头对准、防止色块被遮挡）"""
        if self._patch_window:
            self._patch_window.show_fullscreen_patch()
            self._display_mode = 'floating'
            self.logMessage.emit(i18n.t("测量色块窗口已全屏显示（ESC 可退出）"))

    @pyqtSlot()
    def auto_fullscreen_for_measurement(self):
        """测量开始时的智能全屏策略：
        - 多屏幕：色块窗口已在副屏（main.py 启动时分配），直接在副屏全屏，
          主屏幕保持完整可操作，用户随时能看到进度、点击停止
        - 单屏幕：不自动全屏——全屏会盖住主窗口导致所有按钮不可点；
          确保浮动窗口打开即可（用户仍可点其右上角 ⤢ 手动全屏）
        """
        from PyQt6.QtWidgets import QApplication
        if len(QApplication.screens()) > 1:
            self.show_patch_window_fullscreen()
        else:
            if self._patch_window and not self._patch_window.isVisible():
                self.open_floating_window()
            self.logMessage.emit(i18n.t("单屏幕模式：测量窗口保持浮动（可点窗口右上角 ⤢ 手动全屏）"))

    @pyqtSlot()
    def exit_patch_window_fullscreen(self):
        """退出色块窗口全屏（测量结束/停止时自动调用），保留浮动窗口"""
        if self._patch_window and self._patch_window.isVisible():
            self._patch_window.exit_fullscreen_patch()
            self.logMessage.emit(i18n.t("测量色块窗口已恢复浮动模式"))

    @pyqtSlot()
    def close_floating_window(self):
        """关闭独立浮动窗口"""
        if self._patch_window:
            self._patch_window.hide_patch()
            self._display_mode = 'web'
            self.logMessage.emit(i18n.t("关闭独立浮动窗口"))

    @pyqtSlot()
    def open_comparison_window(self):
        """打开数据对比窗口"""
        self.openComparisonWindowRequested.emit()
        self.logMessage.emit(i18n.t("请求打开数据对比窗口"))

    @pyqtSlot(str)
    def set_display_mode(self, mode: str):
        """设置显示模式"""
        self._display_mode = mode
        self.logMessage.emit(f"显示模式: {mode}")

    # ========== 色块显示 ==========

    @pyqtSlot(int, int, int)
    def show_patch(self, r: int, g: int, b: int):
        """显示色块"""
        self._show_color(r, g, b)
        self.logMessage.emit(f"显示色块: RGB({r}, {g}, {b})")

    @pyqtSlot(int, int, int, int, int)
    def show_patch_centered(self, r: int, g: int, b: int, width: int = 400, height: int = 400):
        """显示色块（指定尺寸）"""
        self._show_color(r, g, b, width, height)
        self.logMessage.emit(f"显示色块: RGB({r}, {g}, {b}) [{width}x{height}]")

    def _show_color(self, r: int, g: int, b: int, width: int = None, height: int = None,
                    zone: tuple = None):
        """内部方法：显示颜色

        Args:
            zone: 均匀性测量的区域定位 (x, y, size_percent)，x/y 为 0-1 比例坐标
        """
        self._current_patch_color = (r, g, b)

        # 显示新色块时清空显式名称（需要前端重新设置）
        # 循环测量时会在 _cycle_next_measurement 中设置 _current_patch_name
        # 单次测量时前端需要调用 set_current_patch_name 设置
        self._explicit_patch_name = None

        # 发送信号给 Web UI 更新色块显示
        payload = {"r": r, "g": g, "b": b}
        if zone is not None:
            payload.update({"zoneX": zone[0], "zoneY": zone[1], "zoneSize": zone[2]})
        self.patchColorChanged.emit(json.dumps(payload))

        # 同时更新浮动窗口（如果可见）
        if self._patch_window and self._patch_window.isVisible():
            if zone is not None:
                self._patch_window.set_zone(zone[0], zone[1], zone[2])
            else:
                self._patch_window.clear_zone()
            self._patch_window.set_color(r, g, b)

        # 同时更新Web测量服务器（如果运行中）
        self._update_web_measurement_color(r, g, b)

    @pyqtSlot()
    def hide_patch(self):
        """隐藏色块"""
        self._show_color(0, 0, 0)
        self.logMessage.emit(i18n.t("隐藏色块"))

    @pyqtSlot(str)
    def set_current_patch_name(self, name: str):
        """
        设置当前色块的名称（用于单次测量替换循环测量数据）

        前端在点击色块按钮时，除了调用 show_patch 显示色块，
        还需要调用此方法设置色块名称，确保单次测量能正确替换循环测量数据。

        Args:
            name: 色块名称，如 "红"、"绿"、"蓝"、"白"、"黑"、"50%" 等
        """
        self._explicit_patch_name = name
        self.logMessage.emit(f"设置当前色块名称: {name}")

    def _identify_patch_name(self, rgb: tuple) -> str:
        """
        根据 RGB 值自动识别色块名称（备用方案）

        用于当前端没有显式设置色块名称时，自动推断名称。

        Args:
            rgb: RGB 值 (r, g, b)

        Returns:
            str: 识别的色块名称，如 "红"、"白"、"50%" 等
        """
        r, g, b = rgb

        # 原色识别
        if r == 255 and g == 0 and b == 0:
            return "红"
        elif r == 0 and g == 255 and b == 0:
            return "绿"
        elif r == 0 and g == 0 and b == 255:
            return "蓝"
        elif r == 255 and g == 255 and b == 255:
            return "白"
        elif r == 0 and g == 0 and b == 0:
            return "黑"

        # 灰阶识别（r == g == b 的情况）
        if r == g == b:
            # 计算灰阶级别（0-255 对应 0%-100%）
            level = round(r / 255 * 100)
            if level == 0:
                return "黑"
            elif level == 100:
                return "白"
            else:
                return f"{level}%"

        # 无法识别的色块，返回 RGB 值作为名称
        return f"RGB({r},{g},{b})"

    # ========== 探头连接 ==========

    @pyqtSlot()
    def auto_connect_probe(self):
        """应用启动时的后台自动连接探头

        目的：用户走到向导"探头/修正"步骤时探头通常已连接好，
        该步骤退化为主要用于多探头场景下的切换确认。
        枚举/握手在后台线程执行（实测首次可达 40+ 秒），失败时静默降级
        （只记日志，不发 error 状态，避免未插探头时启动就报红）。
        """
        if self._probe_connecting:
            return
        if self._argyll_controller and self._argyll_controller.is_connected():
            # 已连接（如页面刷新后重调）：重发状态供前端同步
            self.probeStatusChanged.emit(json.dumps({
                "connected": True,
                "status": "connected",
                "probeType": self._argyll_controller._probe_type.value,
            }))
            return
        self.logMessage.emit(i18n.t("正在后台自动连接探头（首次可能需要 30-60 秒）..."))
        self._connect_probe_impl(auto=True)

    @pyqtSlot()
    def connect_probe(self):
        """连接探头（后台线程执行，手动触发）"""
        self._connect_probe_impl(auto=False)

    def _connect_probe_impl(self, auto: bool = False):
        """连接探头实现（后台线程执行）

        设备枚举（spotread -c ?，实测探测串口/蓝牙可达 20+ 秒）和 spotread
        启动握手都很慢，必须放到独立线程，否则会阻塞 Qt 主线程导致整个界面
        卡死"半天才响应"。结果通过信号（线程安全）回传主线程。

        Args:
            auto: 自动连接模式（启动预热）。失败时静默降级，不发 error 状态。
        """
        if self._probe_connecting:
            self.logMessage.emit(i18n.t("正在连接中，请稍候..."))
            return

        self._probe_connecting = True
        self.logMessage.emit(i18n.t("正在连接探头（设备枚举可能需要十几秒，请留意日志）..."))
        self.probeStatusChanged.emit(json.dumps({"connected": False, "status": "connecting"}))

        def _connect_work():
            try:
                # 使用 Argyll 控制器连接
                if self._argyll_controller:
                    # 记录连接前的探头类型，用于检测自动切换
                    original_probe_type = self._argyll_controller._probe_type.value

                    success = self._argyll_controller.connect()

                    if success:
                        # 检查探头类型是否被自动切换了
                        current_probe_type = self._argyll_controller._probe_type.value
                        if current_probe_type != original_probe_type:
                            # 探头类型被自动切换，通知前端
                            self.logMessage.emit(f"探头类型已自动切换: {original_probe_type} -> {current_probe_type}")
                            self.probeTypeAutoSwitched.emit(current_probe_type)

                        self.probeStatusChanged.emit(json.dumps({
                            "connected": True,
                            "status": "connected",
                            "probeType": current_probe_type
                        }))
                        self.logMessage.emit(i18n.t("探头连接成功"))

                        # ========== 自动配置测量延迟 ==========
                        # 根据连接的探头类型自动设置最佳延迟
                        self._auto_configure_delay()
                    else:
                        error_msg = self._argyll_controller.get_error_message()
                        if auto:
                            # 自动连接失败：静默降级（常见于未插探头），不发 error
                            self.logMessage.emit(i18n.t("后台自动连接探头未成功，可稍后在探头步骤手动连接"))
                            self.probeStatusChanged.emit(json.dumps({
                                "connected": False, "status": "disconnected"
                            }))
                        else:
                            self.probeStatusChanged.emit(json.dumps({
                                "connected": False,
                                "status": "error",
                                "error": error_msg
                            }))
                            self.logMessage.emit(f"探头连接失败: {error_msg}")
                else:
                    self.logMessage.emit(i18n.t("Argyll 控制器未初始化"))
            except Exception as e:
                if not auto:
                    self.probeStatusChanged.emit(json.dumps({
                        "connected": False,
                        "status": "error",
                        "error": str(e)
                    }))
                self.logMessage.emit(f"探头连接异常: {e}")
            finally:
                self._probe_connecting = False

        threading.Thread(target=_connect_work, name="backend-connect-probe", daemon=True).start()

    @pyqtSlot(result=str)
    def get_instrument_list(self):
        """获取校色仪列表（同步返回缓存，后台刷新后通过信号推送）

        设备枚举实测可达 20+ 秒，若同步执行会冻结前端界面。
        因此本槽立即返回上次缓存（无则空数组），同时触发后台枚举，
        完成后 emit instrumentListUpdated 推送最新列表。

        Returns:
            str: JSON 数组 [{"index": 1, "name": "X-Rite i1 DisplayPro", "probe_type": "i1d3"}, ...]
        """
        self._refresh_instrument_list_async()
        return json.dumps(self._last_instrument_list)

    def _refresh_instrument_list_async(self):
        """后台枚举校色仪并推送信号（带去重，避免重复枚举）"""
        if self._instrument_list_refreshing:
            return
        if not self._argyll_controller:
            return
        self._instrument_list_refreshing = True

        def _work():
            try:
                devices = self._argyll_controller.enumerate_instruments()
                self._last_instrument_list = [{
                    "index": d["index"],
                    "name": d["name"],
                    "probe_type": d["probe_type"].value if d.get("probe_type") else None,
                } for d in devices]
                self.instrumentListUpdated.emit(json.dumps(self._last_instrument_list))
            except Exception as e:
                self.logMessage.emit(f"枚举探头设备失败: {e}")
            finally:
                self._instrument_list_refreshing = False

        threading.Thread(target=_work, name="backend-list-instruments", daemon=True).start()

    @pyqtSlot(int)
    def select_and_connect_instrument(self, port_index: int):
        """切换到指定的探头设备并连接（多探头场景）

        Args:
            port_index: spotread 枚举的设备序号（1 起始）
        """
        if self._probe_connecting:
            self.logMessage.emit(i18n.t("正在连接中，请稍候..."))
            return
        if not self._argyll_controller:
            self.logMessage.emit(i18n.t("Argyll 控制器未初始化"))
            return

        # 从缓存的设备列表中找到该端口对应的探头类型，一并切换，
        # 避免 connect() 内部按类型匹配时又走一遍枚举
        for d in self._last_instrument_list:
            if d["index"] == port_index and d.get("probe_type"):
                try:
                    self._argyll_controller._probe_type = ProbeType(d["probe_type"])
                except ValueError:
                    pass  # 未知类型名则保留当前类型，connect() 内部会再匹配
                break

        # 指定端口（connect() 命中端口缓存后跳过枚举）
        self._argyll_controller._instrument_port = port_index

        # 若当前已连接旧探头，先断开
        if self._argyll_controller.is_connected():
            self._argyll_controller.disconnect()

        self.logMessage.emit(i18n.t("正在切换到探头设备 [{index}]...", index=port_index))
        self._connect_probe_impl(auto=False)

    @pyqtSlot()
    def disconnect_probe(self):
        """断开探头"""
        if self._probe_connecting:
            self.logMessage.emit(i18n.t("正在连接中，请等待连接完成后再断开"))
            return
        if self._argyll_controller:
            self._argyll_controller.disconnect()
            self.probeStatusChanged.emit(json.dumps({"connected": False, "status": "disconnected"}))
            self.logMessage.emit(i18n.t("探头已断开"))

    @pyqtSlot()
    def calibrate_probe(self):
        """校准探头"""
        if not self._argyll_controller or not self._argyll_controller.is_connected():
            self.logMessage.emit(i18n.t("探头未连接，无法校准"))
            return

        self.logMessage.emit(i18n.t("正在校准探头，请将探头放在校准板上..."))
        success = self._argyll_controller.calibrate()

        if success:
            self.logMessage.emit(i18n.t("探头校准成功"))
        else:
            error_msg = self._argyll_controller.get_error_message()
            self.logMessage.emit(f"探头校准失败: {error_msg}")

    def _measure_in_thread(self):
        """
        在独立线程中执行测量操作，避免阻塞 Qt 事件循环

        此方法会被放入独立线程中执行，测量结果通过
        _on_argyll_measurement 回调传递到主线程处理。

        注意：
        - argyll_controller.measure() 本身是非阻塞的（只发送命令）
        - 但为了避免任何潜在的 spotread 通信阻塞，我们仍然在独立线程中调用
        - 测量结果通过回调和信号机制安全传递到主线程
        """
        try:
            success = self._argyll_controller.measure()

            if not success:
                error_msg = self._argyll_controller.get_error_message()
                # 使用信号将错误处理调度到主线程
                self._measureFailureSignal.emit(error_msg)
        except Exception as e:
            # 使用信号将异常处理调度到主线程
            self._measureExceptionSignal.emit(str(e))

    def _start_cycle_measure_thread(self):
        """延迟等待后启动循环测量线程（在主线程中被 QTimer.singleShot 调用）"""
        # 再次检查循环测量状态（可能在等待期间被停止）
        if not self._cycle_running:
            return

        self.logMessage.emit(f"显示器已稳定，开始测量...")

        # 启动测量线程
        thread = threading.Thread(
            target=self._measure_in_thread,
            name="backend-cycle-measure-thread",
            daemon=True
        )
        thread.start()

    def _handle_measure_failure(self, error_msg: str):
        """在主线程中处理测量失败"""
        self.logMessage.emit(f"测量失败: {error_msg}")

        if self._cycle_running:
            # 循环测量模式：停止循环
            self.logMessage.emit(i18n.t("停止循环测量"))
            self.stop_cycle()
        else:
            # 单次测量模式：发送完成信号
            self.measurementCompleted.emit()

    def _handle_measure_exception(self, error_msg: str):
        """在主线程中处理测量异常"""
        self.logMessage.emit(f"测量线程异常: {error_msg}")

        if self._cycle_running:
            self.stop_cycle()
        else:
            self.measurementCompleted.emit()

    # ========== 单次测量 ==========

    @pyqtSlot()
    def measure_current_patch(self):
        """
        测量当前显示的色块（异步非阻塞模式）

        流程：
        1. 检查探头连接状态
        2. 确定色块名称（优先使用前端设置的名称，否则自动识别）
        3. 自动配置延迟（根据探头类型、显示器类型、色块亮度）
        4. 使用 QTimer.singleShot 等待延迟，让显示器稳定
        5. 延迟后启动测量线程

        注意：
        - 此方法会等待显示器稳定后再测量，确保测量准确性
        - 前端应先调用 show_patch 显示色块，再调用 set_current_patch_name 设置名称
        - 如果没有设置名称，会自动根据 RGB 值识别色块名称

        单次测量替换循环测量数据的关键：
        - 色块名称决定数据存储位置
        - 名称匹配 "红"、"绿"、"蓝"、"白"、"黑" 会替换色域测量数据
        - 名称匹配 "XX%" 会替换灰阶测量数据
        """
        if not self._argyll_controller or not self._argyll_controller.is_connected():
            self.logMessage.emit(i18n.t("探头未连接，无法测量"))
            return

        if self._argyll_controller.is_measuring():
            self.logMessage.emit(i18n.t("正在测量中，请等待..."))
            return

        # ========== 确定色块名称 ==========
        # 优先使用前端显式设置的名称
        if self._explicit_patch_name:
            self._current_patch_name = self._explicit_patch_name
            self.logMessage.emit(f"使用显式设置的色块名称: {self._current_patch_name}")
        else:
            # 自动识别色块名称（根据 RGB 值）
            self._current_patch_name = self._identify_patch_name(self._current_patch_color)
            self.logMessage.emit(f"自动识别色块名称: {self._current_patch_name}")

        self.measurementStarted.emit(self._current_patch_name)
        self.logMessage.emit(f"测量当前色块: RGB{self._current_patch_color}, 名称: {self._current_patch_name}")

        # ========== 自动清除显卡 LUT / 挂载 Null Profile（单次测量） ==========
        # 与循环测量一样，根据用户设置决定是否在单次测量前清除 LUT 或挂载 Null Profile
        lut_cleared = False
        if self._lut_controller and self._auto_clear_lut:
            display_index = self._get_patch_display_index()

            # ========== Null Profile 方案（优先） ==========
            if self._use_null_profile_for_measurement and self._linear_profile_path:
                self.logMessage.emit(i18n.t("正在挂载线性 ICC Profile（单次测量）..."))
                if self._lut_controller.apply_profile(display_index, self._linear_profile_path):
                    self.logMessage.emit(i18n.t("线性 ICC Profile 已挂载"))
                    lut_cleared = True
                else:
                    # 降级：仅清除 LUT
                    self.logMessage.emit(i18n.t("挂载失败，降级清除 LUT..."))
                    if self._lut_controller.clear_lut(display_index):
                        self.logMessage.emit(i18n.t("显卡 LUT 已清除（降级方案）"))
                        lut_cleared = True
                    else:
                        self.logMessage.emit(i18n.t("警告: 清除 LUT 失败"))
            else:
                # ========== 仅清除 LUT ==========
                self.logMessage.emit(i18n.t("正在清除显卡 LUT（单次测量）..."))
                if self._lut_controller.clear_lut(display_index):
                    self.logMessage.emit(i18n.t("显卡 LUT 已清除"))
                    lut_cleared = True
                else:
                    self.logMessage.emit(i18n.t("警告: 清除 LUT 失败"))
        else:
            # 调试信息：帮助排查为什么不清除 LUT
            if not self._lut_controller:
                self.logMessage.emit(i18n.t("跳过 LUT 清除：LUT 控制器未初始化"))
            elif not self._auto_clear_lut:
                self.logMessage.emit(i18n.t("跳过 LUT 清除：自动清除选项已禁用"))

        # ========== 继续单次测量流程 ==========
        # 如果清除了 LUT，需要延迟后重新显示色块以刷新显示
        # 如果没有清除 LUT，直接继续
        if lut_cleared:
            r, g, b = self._current_patch_color
            # 稍微延迟后重新显示，确保 LUT 清除生效
            QTimer.singleShot(100, lambda: self._show_color(r, g, b))
            # 额外延迟后继续测量
            QTimer.singleShot(400, self._continue_single_measurement)
        else:
            # 直接继续测量
            self._continue_single_measurement()

    def _continue_single_measurement(self):
        """继续单次测量的流程（在清除 LUT 后或直接调用）"""
        # 该方法可能经 QTimer.singleShot 延迟调用，期间探头可能已被断开
        if self._argyll_controller is None:
            self.logMessage.emit(i18n.t("探头未连接，取消单次测量"))
            return

        # ========== 设置当前色块 RGB 值（用于暗场延迟判断） ==========
        self._argyll_controller.set_current_patch_rgb(self._current_patch_color)

        # ========== 动态配置测量延迟 ==========
        # 根据当前色块的亮度和显示器类型动态调整延迟
        self._auto_configure_delay(patch_rgb=self._current_patch_color)

        # ========== 关键修复：延迟等待后再测量 ==========
        # 和循环测量一样，先等待显示器稳定，然后再启动测量
        self.logMessage.emit(f"等待 {self._current_delay_ms}ms 让显示器稳定...")
        QTimer.singleShot(self._current_delay_ms, self._start_single_measure_thread)

    def _start_single_measure_thread(self):
        """延迟等待后启动单次测量线程（在主线程中被 QTimer.singleShot 调用）"""
        # 延迟期间探头可能已被断开
        if self._argyll_controller is None:
            self.logMessage.emit(i18n.t("探头未连接，取消单次测量"))
            return
        # 启动测量线程
        thread = threading.Thread(
            target=self._measure_in_thread,
            name="backend-measure-thread",
            daemon=True
        )
        thread.start()

    # ========== 循环测量 ==========

    @pyqtSlot()
    def start_cycle_gamut(self):
        """开始色域循环测量（RGBW）"""
        patches = [
            (255, 0, 0, "红"),
            (0, 255, 0, "绿"),
            (0, 0, 255, "蓝"),
            (255, 255, 255, "白"),
            (0, 0, 0, "黑"),
        ]
        self._start_cycle(patches, "色域测量")

    @pyqtSlot()
    def start_cycle_gamma(self):
        """开始 Gamma 循环测量（灰阶）"""
        patches = []
        for i in range(1, 11):
            level = int(255 * i / 10)
            patches.append((level, level, level, f"{i*10}%"))
        self._start_cycle(patches, "Gamma 测量")

    @pyqtSlot()
    def start_cycle_all(self):
        """开始全部循环测量（从左到右：原色→基准→灰阶）"""
        patches = [
            # 原色：红、绿、蓝
            (255, 0, 0, "红"),
            (0, 255, 0, "绿"),
            (0, 0, 255, "蓝"),
            # 基准：白、黑
            (255, 255, 255, "白"),
            (0, 0, 0, "黑"),
            # 灰阶：10%→90%
            (25, 25, 25, "10%"),
            (51, 51, 51, "20%"),
            (76, 76, 76, "30%"),
            (102, 102, 102, "40%"),
            (128, 128, 128, "50%"),
            (153, 153, 153, "60%"),
            (179, 179, 179, "70%"),
            (204, 204, 204, "80%"),
            (230, 230, 230, "90%"),
        ]
        self._start_cycle(patches, "全部测量")

    @pyqtSlot(list)
    def start_custom_cycle(self, patches):
        """
        开始自定义色块列表的循环测量（自动模式：显示色块→延迟→自动测量）

        Args:
            patches: 色块列表，格式为 [[r, g, b, name], ...]
                     均匀性测量可扩展为 [[r, g, b, name, zone_x, zone_y, zone_size], ...]
                     （zone_x/zone_y 为 0-1 比例坐标，zone_size 为面积百分比）
        """
        self._cycle_guided = False
        self._start_cycle(self._convert_custom_patches(patches), "自定义测量")

    @pyqtSlot(list)
    def start_guided_cycle(self, patches):
        """
        开始引导式循环测量：每个色块显示后暂停，等用户把探头就位并确认
        （confirm_cycle_measurement / 跳过 skip_cycle_measurement）再测量。
        适用于均匀性测量等需要人工移动探头的场景。
        """
        self._cycle_guided = True
        self._start_cycle(self._convert_custom_patches(patches), "引导式测量")

    @staticmethod
    def _convert_custom_patches(patches):
        """把前端 [[r,g,b,name(,x,y,size)], ...] 转换为内部元组列表"""
        patch_list = []
        for patch in patches:
            if len(patch) >= 4:
                r, g, b, name = patch[0], patch[1], patch[2], patch[3]
                entry = (int(r), int(g), int(b), str(name))
                if len(patch) >= 7:
                    # 均匀性 zone 信息
                    try:
                        zone = (float(patch[4]), float(patch[5]), float(patch[6]))
                        entry = entry + (zone,)
                    except (TypeError, ValueError):
                        pass
                patch_list.append(entry)
        return patch_list

    @pyqtSlot()
    def confirm_cycle_measurement(self):
        """
        引导式测量：用户确认探头已就位，触发当前色块测量
        """
        if not self._cycle_guided or not self._cycle_running:
            return
        name = self._current_patch_name or "当前色块"
        self.logMessage.emit(f"引导测量: 用户已确认，开始测量 {name}")
        self.measurementStarted.emit(name)
        # 确认后仍等一小段显示器稳定时间再测量
        QTimer.singleShot(self._current_delay_ms, self._start_cycle_measure_thread)

    @pyqtSlot()
    def skip_cycle_measurement(self):
        """
        引导式测量：跳过当前色块（不测量，直接进入下一个）
        """
        if not self._cycle_guided or not self._cycle_running:
            return
        self.logMessage.emit(f"引导测量: 跳过 {self._current_patch_name}")
        self._cycle_index += 1
        self._cycle_next_measurement()

    @pyqtSlot()
    def stop_cycle(self):
        """
        停止循环测量

        P0-B: 支持 MeasurementService feature flag：
        - 如果 bridge is active，先调用 bridge.stop_cycle()
        - Backend 只做信号转发和清理工作
        """
        # ========== MeasurementService Feature Flag 分支 (P0-B) ==========
        if self._use_measurement_service and self._measurement_bridge is not None:
            # 如果 MeasurementService 正在使用，先让 bridge 停止
            if self._measurement_bridge.is_active:
                self.logMessage.emit("[MeasurementService] 正在停止测量...")
                try:
                    self._measurement_bridge.stop_cycle()
                    self.logMessage.emit("[MeasurementService] 测量已停止")
                except Exception as e:
                    self._logger.error(f"MeasurementService 停止异常: {e}")
                    self.logMessage.emit(f"[MeasurementService] 停止异常: {e}")
            # 继续执行清理工作（确保状态同步）

        # ========== Legacy 清理工作（保留兼容） ==========
        self._cycle_running = False
        self._cycle_guided = False
        self._cycle_timer.stop()
        self._cycle_queue = []
        self._cycle_index = 0
        self.hide_patch()

        # ========== 生产级加固：刷新信号节流器缓冲 ==========
        # 确保所有缓冲的信号数据被发送到 UI
        self._measurement_result_throttler.flush()
        self._checkpoint_throttler.flush()
        self._log_aggregator.flush()

        # ========== 清理暗部多重采样状态 ==========
        self._dark_sample_measurements_xyz = []
        self._dark_sample_current_retry = 0

        # ========== 清理重复测量状态 ==========
        self._repeat_measurements_xyz = []
        self._repeat_current_count = 0

        # ========== 清理 OLED 防漂移状态 ==========
        self._oled_waiting_black_frame = False
        self._oled_last_patch_brightness = 0.0

        # ========== 停止防休眠保护和窗口置顶守护 ==========
        # 测量停止后，恢复系统默认电源管理
        if self._sleep_preventer.stop():
            self.logMessage.emit(i18n.t("防休眠保护已停止"))
        else:
            self.logMessage.emit(i18n.t("警告: 停止防休眠保护失败"))

        # 停止窗口置顶守护
        if self._patch_window:
            self._patch_window.stop_guardian()
            self.logMessage.emit(i18n.t("窗口置顶守护已停止"))

        # ========== 跨平台统一：恢复显卡 LUT 和卸载 Null Profile ==========
        # **关键原则**：消灭平台差异，统一调用 _lut_controller 的清理方法
        # 测量被取消时，也需要恢复原始状态
        if self._lut_controller:
            # 使用 _lut_controller 的状态判断是否需要清理
            if self._lut_controller.is_null_profile_applied():
                self.logMessage.emit("[跨平台] 正在清理 Null Profile...")
                if self._lut_controller.cleanup_null_profile():
                    self.logMessage.emit("[跨平台] Null Profile 已清理，显示已恢复")
                    # 同步更新 backend 层的状态标记
                    self._null_profile_applied = False
                    # cleanup_null_profile() 内部已调用 Swift刷新，无需重复
                else:
                    self.logMessage.emit(i18n.t("警告: Null Profile 清理失败"))
            elif self._null_profile_applied and self._linear_profile_path:
                # 兜底：如果 backend 层状态与 controller 层不同步
                display_index = self._get_patch_display_index()
                self.logMessage.emit(i18n.t("正在卸载线性 ICC Profile..."))

                if self._lut_controller.uninstall_profile(display_index, self._linear_profile_path):
                    self.logMessage.emit(i18n.t("线性 ICC Profile 已卸载"))
                    self._null_profile_applied = False

                    # macOS：执行 Swift 物理刷新（cleanup_null_profile 逻辑的简化版）
                    if platform.system() == 'Darwin':
                        swift_script = _get_refresh_script_path()
                        _force_macos_display_refresh(swift_script_path=swift_script)
                        self.logMessage.emit("[macOS] 显示器物理刷新完成")
                    else:
                        if self._lut_controller.load_system_profile_lut(display_index):
                            self.logMessage.emit(i18n.t("系统 Profile VCGT 已加载，显示已刷新"))
                        else:
                            self.logMessage.emit(i18n.t("警告: 加载系统 Profile VCGT 失败"))
                else:
                    self.logMessage.emit(i18n.t("警告: 卸载线性 Profile 失败"))

        self.logMessage.emit(i18n.t("循环测量已停止"))
        self.measurementCompleted.emit()

    @pyqtSlot()
    def stop_calibration(self):
        """
        停止显示器校准（dispcal）

        当用户在 dispcal 校准过程中点击"停止"按钮时调用。
        会：
        1. 终止 dispcal 进程
        2. 清理 DispcalWebClient
        3. 清理测量窗口
        4. 重新连接 spotread 以恢复校色仪连接
        5. 恢复状态
        """
        self.logMessage.emit(i18n.t("正在停止显示器校准..."))

        # ========== 清理 DispcalWebClient ==========
        if self._dispcal_web_client:
            self.logMessage.emit(i18n.t("清理 DispcalWebClient..."))
            self._dispcal_web_client.disconnect()
            self._dispcal_web_client = None

        # ========== 清理测量窗口 ==========
        if self._patch_window and self._patch_window.isVisible():
            self.logMessage.emit(i18n.t("清理测量窗口..."))
            self._patch_window.stop_guardian()
            self._patch_window.hide_patch()

        # ========== 通过 ArgyllController 终止 dispcal 进程 ==========
        if self._argyll_controller:
            self._argyll_controller.stop_dispcal()
            self.logMessage.emit(i18n.t("dispcal 进程已终止"))

            # ========== 关键：异步重新连接 spotread ==========
            # 使用 QTimer 延迟执行，避免阻塞主线程导致信号无法传递
            self.logMessage.emit(i18n.t("正在重新连接 spotread..."))
            self.probeStatusChanged.emit(json.dumps({"connected": False, "status": "connecting"}))

            # 1.5秒后开始重连
            QTimer.singleShot(1500, self._do_reconnect_after_dispcal)

        # ========== 重置状态 ==========
        isCalibrating = False  # 这个变量在前端定义，需要通过信号更新
        self.calibrationProgress.emit(json.dumps({
            "current": 0,
            "total": 100,
            "message": "校准已取消",
            "stage": "dispcal",
            "cancelled": True
        }))

        self.logMessage.emit(i18n.t("显示器校准已停止"))

    def _do_reconnect_after_dispcal(self):
        """dispcal 停止后异步重连 spotread（避免阻塞主线程）"""
        if not self._argyll_controller:
            return

        # 尝试重新连接，如果失败则重试
        max_retries = 2
        for attempt in range(max_retries):
            reconnect_success = self._argyll_controller.connect()
            if reconnect_success:
                self.logMessage.emit(i18n.t("spotread 已重新连接，校色仪可用"))
                # 发送连接成功信号，通知前端更新 UI
                current_probe_type = self._argyll_controller._probe_type.value
                status_json = json.dumps({
                    "connected": True,
                    "status": "connected",
                    "probeType": current_probe_type
                })
                self.logMessage.emit(f">>> 发送探头状态信号: {status_json}")
                self.probeStatusChanged.emit(status_json)
                return
            else:
                if attempt < max_retries - 1:
                    self.logMessage.emit(f"spotread 重连失败，1秒后重试...")
                    # 使用 QTimer 延迟重试
                    QTimer.singleShot(1000, lambda: self._do_reconnect_retry(attempt + 1))
                    return
                else:
                    error_msg = self._argyll_controller.get_error_message()
                    self.logMessage.emit(f"spotread 重连失败: {error_msg}")
                    # 发送连接失败信号
                    self.probeStatusChanged.emit(json.dumps({
                        "connected": False,
                        "status": "error",
                        "error": error_msg
                    }))

    def _do_reconnect_retry(self, attempt):
        """重试重连 spotread"""
        if not self._argyll_controller or attempt >= 2:
            return

        reconnect_success = self._argyll_controller.connect()
        if reconnect_success:
            self.logMessage.emit(i18n.t("spotread 已重新连接，校色仪可用"))
            # 发送连接成功信号，通知前端更新 UI
            current_probe_type = self._argyll_controller._probe_type.value
            status_json = json.dumps({
                "connected": True,
                "status": "connected",
                "probeType": current_probe_type
            })
            self.logMessage.emit(f">>> 发送探头状态信号: {status_json}")
            self.probeStatusChanged.emit(status_json)
        else:
            if attempt < 1:
                self.logMessage.emit(f"spotread 重连失败，1秒后重试...")
                QTimer.singleShot(1000, lambda: self._do_reconnect_retry(attempt + 1))
            else:
                error_msg = self._argyll_controller.get_error_message()
                self.logMessage.emit(f"spotread 重连失败: {error_msg}")
                # 发送连接失败信号
                self.probeStatusChanged.emit(json.dumps({
                    "connected": False,
                    "status": "error",
                    "error": error_msg
                }))

    def _start_cycle(self, patches, name):
        """
        启动循环测量

        P0-B: 支持 MeasurementService feature flag 分支：
        - 如果 flag 关闭，走 legacy（现有代码）
        - 如果 flag 开启，调用 bridge.start_cycle()
        - 如果 bridge 报错且 fallback enabled，切回 legacy
        """
        # ========== MeasurementService Feature Flag 分支 (P0-B) ==========
        if self._use_measurement_service:
            self.logMessage.emit("[Feature Flag] MeasurementService 已启用")
            try:
                # 延迟初始化 bridge（首次测量时创建）
                if self._measurement_bridge is None:
                    self.logMessage.emit(i18n.t("正在初始化 MeasurementBridge..."))
                    bridge_config = BridgeConfig(
                        use_measurement_service=True,
                        auto_sync_state=True,
                        log_transitions=True
                    )
                    self._measurement_bridge = BackendMeasurementBridge(self, bridge_config)

                # 尝试通过 bridge 启动测量
                success = self._measurement_bridge.start_cycle(patches, name)

                if success:
                    self.logMessage.emit(f"[MeasurementService] 测量已启动: {name}")
                    return  # MeasurementService 已接管，直接返回

                # bridge 启动失败
                self._logger.warning(f"MeasurementService 启动失败: {name}")

                if not self._measurement_service_fallback_enabled:
                    self.logMessage.emit(i18n.t("MeasurementService 失败，fallback 已禁用，测量终止"))
                    return

                # fallback 到 legacy
                self.logMessage.emit(i18n.t("MeasurementService 失败，回退到 legacy 测量路径"))

            except Exception as e:
                self._logger.error(f"MeasurementService 异常: {e}")
                self.logMessage.emit(f"MeasurementService 异常: {e}")

                if not self._measurement_service_fallback_enabled:
                    self.logMessage.emit(i18n.t("fallback 已禁用，测量终止"))
                    return

                # fallback 到 legacy
                self.logMessage.emit(i18n.t("回退到 legacy 测量路径"))

        # ========== Legacy 测量路径（原有代码） ==========
        # 检查探头是否连接，如果未连接则自动连接（后台线程，避免阻塞 UI）
        if not self._argyll_controller:
            self.logMessage.emit(i18n.t("Argyll 控制器未初始化"))
            return

        if not self._argyll_controller.is_connected():
            self.logMessage.emit(i18n.t("探头未连接，正在自动连接（不阻塞界面）..."))
            self.probeStatusChanged.emit(json.dumps({"connected": False, "status": "connecting"}))

            # 连接耗时可达数十秒（设备枚举/启动握手），必须放后台线程；
            # 完成后通过队列信号回到主线程继续启动循环
            self._pending_cycle_params = (patches, name)

            def _auto_connect_then_start():
                connect_success = self._argyll_controller.connect()
                if not connect_success:
                    error_msg = self._argyll_controller.get_error_message()
                    self.logMessage.emit(f"探头连接失败: {error_msg}")
                    self.probeStatusChanged.emit(json.dumps({
                        "connected": False,
                        "status": "error",
                        "error": error_msg
                    }))
                    return

                current_probe_type = self._argyll_controller._probe_type.value
                self.logMessage.emit(i18n.t("探头已自动连接"))
                self.probeStatusChanged.emit(json.dumps({
                    "connected": True,
                    "status": "connected",
                    "probeType": current_probe_type
                }))
                # 延迟让探头完全稳定（初始化、校准等）
                self.logMessage.emit(i18n.t("等待探头稳定..."))
                time.sleep(1.5)
                QMetaObject.invokeMethod(self, "_resume_pending_cycle",
                                         Qt.ConnectionType.QueuedConnection)

            threading.Thread(target=_auto_connect_then_start,
                             name="backend-auto-connect", daemon=True).start()
            return

        self._start_cycle_connected(patches, name)

    @pyqtSlot()
    def _resume_pending_cycle(self):
        """自动连接完成后（主线程）继续启动挂起的循环测量"""
        params = getattr(self, '_pending_cycle_params', None)
        if params:
            self._start_cycle_connected(params[0], params[1])

    def _start_cycle_connected(self, patches, name):
        """探头已连接状态下的循环测量启动（_start_cycle 的后半段）"""

        # ========== 检查是否处于挂起状态（恢复测量） ==========
        if self._session_state == MeasurementSessionState.SUSPENDED and self._checkpoint is not None:
            self.logMessage.emit(i18n.t("检测到挂起的测量，正在恢复..."))
            self._resume_from_checkpoint()
            return

        # ========== 跨平台：清除显卡 LUT ==========
        # 在开始显示测量色块之前，可以清空系统显卡的硬件 LUT，
        # 让输出呈线性状态，从而获取物理原生颜色。
        #
        # 对应 C++:
        #   CalibrationEngine::clearVideoCardLUT()
        #
        # 所有平台通用：Null Profile 方案（优先）或仅清除 LUT（降级）
        #
        # 根据用户设置决定是否清除 LUT 或挂载 Null Profile：
        # - ICC/LUT 模式：默认启用（确保测量显示器原生状态）
        # - 其他模式：用户可选
        #
        # 如果禁用 auto_clear_lut，将使用 Web UI 色块预览测量（受系统ICC影响）
        if self._lut_controller:
            # 生产级加固 #2：获取测量窗口所在屏幕的索引
            display_index = self._get_patch_display_index()

            if self._auto_clear_lut:
                # ========== Null Profile 方案（优先） ==========
                # 如果启用 Null Profile 方案，优先挂载线性 ICC Profile
                # 注意：如果已经在 dispcal 阶段挂载过，则跳过（避免重复挂载）
                if self._use_null_profile_for_measurement and self._linear_profile_path:
                    if self._null_profile_applied:
                        # 已在 dispcal 阶段挂载，跳过
                        self.logMessage.emit("[测量阶段] Null Profile 已在 dispcal 阶段挂载，无需重复挂载")
                    else:
                        self.logMessage.emit(i18n.t("正在挂载线性 ICC Profile（Null Profile）..."))
                        if self._lut_controller.apply_profile(display_index, self._linear_profile_path):
                            self.logMessage.emit(i18n.t("线性 ICC Profile 已挂载，输出已切换为原生状态"))
                            self.logMessage.emit("[Null Profile 方案] 系统色彩管理已被绕过")
                            # 标记 Null Profile 已挂载（用于异常兜底卸载）
                            self._null_profile_applied = True
                        else:
                            self.logMessage.emit(i18n.t("警告: 挂载线性 Profile 失败，尝试降级方案..."))
                            # 降级方案：仅清除 LUT（未使用 Null Profile）
                            self._null_profile_applied = False
                            if self._lut_controller.clear_lut(display_index):
                                self.logMessage.emit(i18n.t("显卡 LUT 已清除（降级方案）"))
                            else:
                                self.logMessage.emit(i18n.t("警告: 清除 LUT 也失败，测量结果可能受色彩管理影响"))
                else:
                    # ========== 降级方案：仅清除 LUT ==========
                    # 未启用 Null Profile 或线性 Profile 未找到
                    self.logMessage.emit(i18n.t("正在清除显卡 LUT，准备测量..."))
                    # 仅清除 LUT，未使用 Null Profile
                    self._null_profile_applied = False
                    if self._lut_controller.clear_lut(display_index):
                        self.logMessage.emit(i18n.t("显卡 LUT 已清除，输出已切换为线性状态"))
                        if not self._use_null_profile_for_measurement:
                            self.logMessage.emit("[仅 LUT 清除] Null Profile 方案已禁用")
                        elif not self._linear_profile_path:
                            self.logMessage.emit("[仅 LUT 清除] 线性 Profile 未检测")
                    else:
                        self.logMessage.emit(i18n.t("警告: 清除 LUT 失败，测量结果可能受色彩管理影响"))
            else:
                self.logMessage.emit(i18n.t("使用系统 ICC 模式：请在 Web UI 色块预览区域测量（受系统ICC影响）"))

        # 清空之前的测量数据，并重置 MeasurementData 对象
        # 这确保每次新的测量周期都有全新的测量数据容器
        self._current_measurement = MeasurementData()

        if name == "色域测量":
            self._gamut_measurements = {}
        elif name == "Gamma 测量":
            self._gamma_measurements = []
        elif name == "全部测量":
            self._gamut_measurements = {}
            self._gamma_measurements = []

        self._cycle_queue = patches
        self._cycle_index = 0
        self._cycle_running = True

        # ========== 断点续测状态初始化 ==========
        self._session_state = MeasurementSessionState.RUNNING
        self._checkpoint = None  # 清除旧断点
        self._cycle_completed_data = []  # 清空已完成数据
        self._current_measurement_name = name

        # ========== 暗部多重采样状态初始化 ==========
        self._dark_sample_measurements_xyz = []
        self._dark_sample_current_retry = 0

        # ========== 重复测量状态初始化 ==========
        self._repeat_measurements_xyz = []
        self._repeat_current_count = 0

        # ========== OLED 防漂移状态初始化 ==========
        self._oled_waiting_black_frame = False
        self._oled_last_patch_brightness = 0.0

        # ========== 防休眠保护 ==========
        # 启动系统防休眠，阻止系统和显示器在测量期间进入睡眠状态
        if self._sleep_preventer.start():
            self.logMessage.emit(i18n.t("防休眠保护已启动"))
        else:
            self.logMessage.emit(i18n.t("警告: 防休眠保护启动失败"))

        # ========== 窗口置顶守护 ==========
        # 只有在使用 PatchWindow 时才启动窗口置顶守护
        # 如果 auto_clear_lut 禁用，使用 Web UI 色块预览，不需要窗口守护
        if self._auto_clear_lut and self._patch_window:
            self._patch_window.start_guardian(interval_ms=2000)
            self.logMessage.emit(i18n.t("窗口置顶守护已启动"))
        elif not self._auto_clear_lut:
            self.logMessage.emit(i18n.t("使用 Web UI 色块预览模式（受系统ICC影响）"))
            self.logMessage.emit(i18n.t("提示：请将色度计放置在 Web UI 的色块预览区域进行测量"))

        self.logMessage.emit(f"开始 {name}: 共 {len(patches)} 个色块")
        self._cycle_next_measurement()

    def _cycle_next_measurement(self):
        """执行下一个循环测量（事件驱动模式 / 非阻塞）"""
        if not self._cycle_running:
            return

        if self._cycle_index >= len(self._cycle_queue):
            # 循环测量完成
            self._cycle_running = False
            self._cycle_timer.stop()
            self.hide_patch()

            # ========== 停止防休眠保护和窗口置顶守护 ==========
            # 测量完成后，恢复系统默认电源管理
            if self._sleep_preventer.stop():
                self.logMessage.emit(i18n.t("防休眠保护已停止"))
            else:
                self.logMessage.emit(i18n.t("警告: 停止防休眠保护失败"))

            # 停止窗口置顶守护（hide_patch 中已调用，这里显式确认）
            if self._patch_window:
                self._patch_window.stop_guardian()
                self.logMessage.emit(i18n.t("窗口置顶守护已停止"))

            # ========== 断点续测：测量完成，清除断点数据 ==========
            self._session_state = MeasurementSessionState.COMPLETED
            self._checkpoint = None
            self._cycle_completed_data = []

            self.logMessage.emit(f"循环测量完成调试: _cycle_index={self._cycle_index}, queue_len={len(self._cycle_queue)}")

            # ========== 跨平台：恢复显卡 LUT 和卸载 Null Profile ==========
            # 测量结束后，恢复之前的状态
            #
            # 对应 C++:
            #   CalibrationEngine::restoreVideoCardLUT()
            #
            if self._lut_controller:
                # 生产级加固 #2：使用与清除时相同的显示器索引
                display_index = self._get_patch_display_index()

                # ========== 如果使用了 Null Profile 方案，需要卸载线性 Profile ==========
                # 使用状态标记判断是否需要卸载
                if self._null_profile_applied and self._linear_profile_path:
                    self.logMessage.emit(i18n.t("正在卸载线性 ICC Profile，恢复原始配置..."))

                    # ========== macOS 专用：显示硬件刷新遮罩 ==========
                    # 卸载 Profile 后需要执行 Swift 物理刷新脚本
                    # 用遮罩将"黑屏闪烁"包装为专业 UX 特性
                    if platform.system() == 'Darwin':
                        self._hardware_refresh_overlay = HardwareRefreshOverlay()
                        self._hardware_refresh_overlay.show("正在释放底层图形管线...")
                        self._hardware_refresh_overlay.update_message(
                            "正在恢复系统色彩配置...",
                            "显示器硬件通道正在重置..."
                        )
                        from PyQt6.QtWidgets import QApplication
                        QApplication.processEvents()

                    if self._lut_controller.uninstall_profile(display_index, self._linear_profile_path):
                        self.logMessage.emit(i18n.t("线性 ICC Profile 已卸载，系统已恢复原始 Profile"))
                        # 标记 Null Profile 已卸载
                        self._null_profile_applied = False

                        # ========== macOS 专用：执行 Swift 物理刷新 ==========
                        # 这是解决 macOS "卸载后屏幕不刷新"问题的关键！
                        if platform.system() == 'Darwin':
                            self.logMessage.emit("[macOS] 正在执行显示器物理刷新...")
                            swift_script = _get_refresh_script_path()
                            _force_macos_display_refresh(swift_script_path=swift_script)
                            self.logMessage.emit("[macOS] 显示器物理刷新完成")

                            # 隐藏遮罩（延迟）
                            if self._hardware_refresh_overlay:
                                self._hardware_refresh_overlay.update_message(
                                    "系统色彩配置已恢复",
                                    "显示器已恢复正常显示模式"
                                )
                                QApplication.processEvents()
                                QTimer.singleShot(500, self._hide_hardware_refresh_overlay)
                        else:
                            # 非 macOS：加载系统 Profile 的 VCGT
                            self.logMessage.emit(i18n.t("正在加载系统 Profile VCGT..."))
                            if self._lut_controller.load_system_profile_lut(display_index):
                                self.logMessage.emit(i18n.t("系统 Profile VCGT 已加载，显示已刷新"))
                            else:
                                self.logMessage.emit(i18n.t("警告: 加载系统 Profile VCGT 失败"))
                    else:
                        # ========== macOS 专用：失败时隐藏遮罩 ==========
                        if self._hardware_refresh_overlay:
                            self._hardware_refresh_overlay.hide()
                            self._hardware_refresh_overlay = None
                        self.logMessage.emit(i18n.t("警告: 卸载线性 Profile 失败，请手动恢复"))

            self.logMessage.emit(i18n.t("循环测量完成"))
            self._cycle_guided = False
            self.measurementCompleted.emit()

            # 发送最终结果
            self._calculate_and_emit_gamut_coverage()
            self._calculate_and_emit_gamma()

            # ========== 自动保存测量数据 ==========
            # 根据当前测量模式保存数据
            if self._lut_workflow_params is not None:
                # LUT 工作流
                self._auto_save_measurement_session("lut")
                # 同时导出 ti3 文件供后续 ICC Profile 生成
                self._auto_export_ti3_for_lut_workflow()
            else:
                # 普通测量模式（色域或灰阶）
                # 根据当前测量模式确定保存类型
                self._auto_save_measurement_session(self._current_measure_mode)

            return

        patch = self._cycle_queue[self._cycle_index]
        r, g, b, name = patch[0], patch[1], patch[2], patch[3]
        zone = patch[4] if len(patch) >= 5 else None  # 均匀性 (x, y, size_percent)

        # 发送进度（引导模式下带 waitingConfirm，驱动全屏控制条/WebUI 显示确认按钮）
        progress = {
            "current": self._cycle_index + 1,
            "total": len(self._cycle_queue),
            "patchName": name
        }
        if self._cycle_guided:
            progress["guided"] = True
            progress["waitingConfirm"] = True
        self.cycleMeasurementProgress.emit(json.dumps(progress))

        # 显示色块（均匀性测量时定位到屏幕 zone）
        if zone is not None:
            self._show_color(r, g, b, zone=zone)
        else:
            self._show_color(r, g, b)
        self._current_patch_name = name

        # ========== 动态配置测量延迟 ==========
        # 根据当前色块的亮度和显示器类型动态调整延迟
        self._auto_configure_delay(patch_rgb=(r, g, b))

        # ========== 设置当前色块 RGB 值（用于暗场延迟判断） ==========
        self._argyll_controller.set_current_patch_rgb((r, g, b))

        if self._cycle_guided:
            # 引导模式：等待用户把探头移到目标区域并确认（confirm_cycle_measurement）
            self.logMessage.emit(
                f"引导测量 [{self._cycle_index + 1}/{len(self._cycle_queue)}]: {name}，"
                f"等待确认探头已就位…"
            )
            return

        self.measurementStarted.emit(name)
        self.logMessage.emit(f"测量 [{self._cycle_index + 1}/{len(self._cycle_queue)}]: {name}")

        # ========== 关键修复：延迟等待后再测量 ==========
        # 延迟的作用是让显示器从上一个色块切换到当前色块后稳定下来
        # 之前的错误：延迟用在"测量完成后"等待下一个色块
        # 正确做法：延迟用在"显示色块后"等待显示器稳定，然后再测量
        self.logMessage.emit(f"等待 {self._current_delay_ms}ms 让显示器稳定...")
        QTimer.singleShot(self._current_delay_ms, self._start_cycle_measure_thread)

    # ========== 参数设置 ==========

    @pyqtSlot(int)
    def set_measure_delay(self, delay_ms: int):
        """设置测量延迟"""
        self._measure_delay = delay_ms
        self.logMessage.emit(f"测量延迟: {delay_ms}ms")

    @pyqtSlot(int)
    def set_measure_repeat_count(self, count: int):
        """
        设置每个色块的重复测量次数

        1 = 关闭（默认）；>1 时对同一色块测量 N 次并取 XYZ 线性平均，
        可显著降低仪器随机噪声（测量时间成倍增加）。
        """
        self._measure_repeat_count = max(1, min(10, int(count)))
        self.logMessage.emit(
            f"重复测量次数: {self._measure_repeat_count}"
            + ("（取平均）" if self._measure_repeat_count > 1 else "（关闭）")
        )

    @pyqtSlot(bool)
    def set_dark_sample_enabled(self, enabled: bool):
        """开关暗部自适应多重采样（低亮度时多次测量取平均）"""
        self._dark_sample_enabled = bool(enabled)
        self.logMessage.emit(
            f"暗部多重采样: {'启用' if enabled else '停用'} "
            f"(阈值 {self._dark_sample_threshold} cd/m²)"
        )

    # ========== 暗部自适应多重采样配置接口 ==========

    @pyqtSlot(float)
    def set_dark_sample_threshold(self, threshold: float):
        """
        设置暗部多重采样阈值

        当测量亮度 Y 值低于此阈值时，触发多重采样取平均值，
        以减少分光仪暗部底噪影响。

        Args:
            threshold: 暗部阈值（cd/m²），默认 0.5
        """
        self._dark_sample_threshold = threshold
        self.logMessage.emit(f"暗部多重采样阈值: {threshold} cd/m²")

    @pyqtSlot(int)
    def set_dark_sample_max_retries(self, max_retries: int):
        """
        设置暗部多重采样最大重测次数

        实际测量次数 = max_retries + 1（首次测量 + 重测次数）

        Args:
            max_retries: 最大重测次数，默认 3（共测量 4 次）
        """
        self._dark_sample_max_retries = max_retries
        self.logMessage.emit(f"暗部多重采样最大重测次数: {max_retries}（共测量 {max_retries + 1} 次）")

    @pyqtSlot(result=str)
    def get_dark_sample_config(self):
        """
        获取暗部多重采样配置

        Returns:
            JSON 字符串: {"threshold": 0.2, "minThreshold": 0.001, "maxRetries": 3}
        """
        return json.dumps({
            "enabled": self._dark_sample_enabled,
            "threshold": self._dark_sample_threshold,
            "minThreshold": self._dark_sample_min_threshold,
            "maxRetries": self._dark_sample_max_retries,
            "totalMeasurements": self._dark_sample_max_retries + 1,
            "repeatCount": self._measure_repeat_count,
        })

    @pyqtSlot(float)
    def set_dark_sample_min_threshold(self, threshold: float):
        """
        设置极暗阈值（用于避免 OLED 纯黑死循环）

        Gemini 建议 #1：当 Y < 此阈值时直接退出多重采样，
        因为已达到仪器底噪极限。

        Args:
            threshold: 极暗阈值（cd/m²），默认 0.001
        """
        self._dark_sample_min_threshold = threshold
        self.logMessage.emit(f"极暗阈值: {threshold} cd/m²（避免死循环）")

    # ========== OLED 防漂移黑帧插入配置接口 ==========

    @pyqtSlot(bool)
    def set_oled_mode_enabled(self, enabled: bool):
        """
        设置 OLED 测量模式开关

        当开启此模式时，高亮度色块测量完成后会显示黑帧并等待，
        以重置 OLED 屏幕的 ABL/ASBL 机制，防止亮度漂移。

        Gemini 建议 #5：智能触发，只在高亮度色块后插入黑帧。

        Args:
            enabled: 是否开启 OLED 测量模式
        """
        self._oled_mode_enabled = enabled
        self.logMessage.emit(f"OLED 防漂移模式: {'已启用' if enabled else '已禁用'}")

    @pyqtSlot(int)
    def set_oled_black_frame_delay(self, delay_ms: int):
        """
        设置 OLED 黑帧等待时间

        Args:
            delay_ms: 黑帧等待时间（毫秒），默认 1500ms
        """
        self._oled_black_frame_delay_ms = delay_ms
        self.logMessage.emit(f"OLED 黑帧等待时间: {delay_ms}ms")

    @pyqtSlot(int)
    def set_oled_ui_settling_delay(self, delay_ms: int):
        """
        设置 OLED UI 稳定延迟（黑帧结束后的额外等待时间）

        Gemini 建议 #4：黑帧结束后必须等待 UI 稳定延迟，
        确保屏幕颜色完全切换后再测量。

        Args:
            delay_ms: UI 稳定延迟时间（毫秒），默认 300ms
        """
        self._oled_ui_settling_delay_ms = delay_ms
        self.logMessage.emit(f"OLED UI 稳定延迟: {delay_ms}ms")

    @pyqtSlot(float)
    def set_oled_bfi_trigger_threshold(self, threshold: float):
        """
        设置 OLED BFI（黑帧插入）触发阈值

        Gemini 建议 #5：只有亮度超过此阈值的色块才会触发黑帧插入，
        低亮度色块不会触发 ABL，无需插入黑帧。

        Args:
            threshold: BFI 触发阈值（cd/m²），默认 20 nits
        """
        self._oled_bfi_trigger_threshold = threshold
        self.logMessage.emit(f"OLED BFI 触发阈值: {threshold} cd/m²")

    @pyqtSlot(int)
    def set_oled_bfi_trigger_rgb_avg(self, threshold: int):
        """
        设置 OLED BFI（黑帧插入）RGB 平均值触发阈值

        Gemini 建议 #5：RGB 平均值超过此阈值时也会触发黑帧插入。

        Args:
            threshold: RGB 平均值阈值（0-255），默认 128
        """
        self._oled_bfi_trigger_rgb_avg = threshold
        self.logMessage.emit(f"OLED BFI RGB 平均值阈值: {threshold}")

    @pyqtSlot(int)
    def set_oled_window_size_percent(self, percent: int):
        """
        设置 OLED 色块窗口大小百分比

        Gemini 建议 #6：配合 OLED 模式，必须将色块显示面积缩小，
        业内标准是 10% 面积的窗口色块，其余 90% 屏幕保持纯黑。
        只有"10% 窗口面积 + 黑帧插入"双管齐下，才能真正解决 OLED 测量漂移。

        Args:
            percent: 色块窗口面积百分比（1-100），默认 100%，建议 10%
        """
        if percent < 1:
            percent = 1
        elif percent > 100:
            percent = 100
        self._oled_window_size_percent = percent
        self.logMessage.emit(f"OLED 色块窗口大小: {percent}%")

        # 如果当前正在 OLED 模式测量，立即更新窗口大小
        if self._oled_mode_enabled and self._patch_window:
            # 通知 patch_window 更新窗口大小
            self._patch_window.set_oled_window_size_percent(percent)

    @pyqtSlot(result=str)
    def get_oled_mode_config(self):
        """
        获取 OLED 防漂移配置

        Returns:
            JSON 字符串: 完整的 OLED 配置信息
        """
        return json.dumps({
            "enabled": self._oled_mode_enabled,
            "blackFrameDelayMs": self._oled_black_frame_delay_ms,
            "uiSettlingDelayMs": self._oled_ui_settling_delay_ms,
            "bfiTriggerThreshold": self._oled_bfi_trigger_threshold,
            "bfiTriggerRgbAvg": self._oled_bfi_trigger_rgb_avg,
            "windowSizePercent": self._oled_window_size_percent
        })

    # ========== 光谱校正文件 (CCSS/CCMX) ==========

    @pyqtSlot(result=str)
    def get_correction_files(self):
        """
        获取 corrections 目录中所有 .ccss 和 .ccmx 文件列表

        Returns:
            JSON 字符串，包含文件列表 [{"name": "文件名", "path": "完整路径"}, ...]
        """
        # 使用 CorrectionManager 获取详细元数据
        return self._correction_manager.get_correction_files_json()

    @pyqtSlot(result=str)
    def get_correction_files_detailed(self):
        """
        获取 corrections 目录中所有文件的详细元数据

        Returns:
            JSON 字符串，包含详细元数据列表
            [{
                "name": "文件名",
                "path": "完整路径",
                "type": "ccmx/ccss",
                "descriptor": "描述",
                "instrument": "目标探头",
                "technology": "显示技术代码",
                "technology_display": "显示技术名称",
                "created": "创建日期",
                "reference": "基准探头",
                "is_valid": true/false,
                "hash": "文件哈希"
            }, ...]
        """
        return self._correction_manager.get_correction_files_json()

    @pyqtSlot(str, result=str)
    def get_correction_metadata(self, file_path: str):
        """
        获取单个修正文件的详细元数据

        Args:
            file_path: 修正文件路径

        Returns:
            JSON 字符串，包含详细元数据
        """
        return self._correction_manager.get_detailed_metadata_json(file_path)

    @pyqtSlot(str, str, str, result=str)
    def check_correction_compatibility(
        self,
        correction_path: str,
        probe_type: str,
        display_technology: str = ""
    ):
        """
        检查修正文件与探头/显示器的兼容性

        Args:
            correction_path: 修正文件路径
            probe_type: 探头类型 (e.g., "i1d3", "i1pro2")
            display_technology: 显示技术代码或名称 (e.g., "o", "OLED", "l")

        Returns:
            JSON 字符串，包含兼容性结果
            {
                "is_compatible": true/false,
                "warnings": ["警告列表"],
                "errors": ["错误列表"],
                "suggestions": ["建议列表"]
            }
        """
        metadata = self._correction_manager.get_correction_by_path(correction_path)
        if not metadata:
            return json.dumps({
                "is_compatible": False,
                "warnings": [],
                "errors": ["无法加载修正文件元数据"],
                "suggestions": ["请检查文件是否存在且格式正确"]
            })

        result = self._correction_manager.check_compatibility(
            metadata, probe_type, display_technology
        )
        return json.dumps(result.to_dict())

    @pyqtSlot()
    def browse_correction_file(self):
        """
        弹出文件选择对话框，让用户选择 .ccss 或 .ccmx 文件
        """
        from PyQt6.QtWidgets import QFileDialog

        filepath, _ = QFileDialog.getOpenFileName(
            None,
            "选择光谱校正文件 (CCSS/CCMX)",
            "",
            "校正文件 (*.ccss *.ccmx);;所有文件 (*)"
        )

        if filepath:
            self.filePathSelected.emit(json.dumps({
                "path": filepath
            }))
            self.logMessage.emit(f"已选择光谱校正文件: {filepath}")
        else:
            self.logMessage.emit(i18n.t("已取消选择光谱校正文件"))

    def _locate_oeminst(self) -> str:
        """定位 ArgyllCMS oeminst 可执行文件路径，找不到返回空串"""
        candidates = []
        argyll_path = getattr(self._argyll_controller, "_argyll_path", "") if self._argyll_controller else ""
        if argyll_path:
            candidates.append(Path(argyll_path) / "oeminst")
            candidates.append(Path(argyll_path) / "bin" / "oeminst")
        # 项目内置 ArgyllCMS
        candidates.append(Path(__file__).resolve().parent.parent / "ArgyllCMS" / "bin" / "oeminst")
        exe = "oeminst.exe" if platform.system() == "Windows" else "oeminst"
        for base in candidates:
            if base.name.endswith(exe) and base.is_file():
                return str(base)
        # Windows 后缀兜底
        for base in candidates:
            alt = base.with_name(exe)
            if alt.is_file():
                return str(alt)
        return ""

    @pyqtSlot(result=str)
    def import_edr_file(self) -> str:
        """
        导入 X-Rite .edr 光谱校正文件：经 ArgyllCMS oeminst 转换为 .ccss
        并保存到 corrections/ 目录（i1 Display Pro / ColorMunki Display 官方校正）。

        Returns:
            JSON: {"success": bool, "added": [新增 .ccss 文件名], "error": str}
        """
        import subprocess
        from PyQt6.QtWidgets import QFileDialog

        oeminst = self._locate_oeminst()
        if not oeminst:
            msg = "未找到 ArgyllCMS oeminst 工具，无法转换 EDR 文件"
            self.logMessage.emit(msg)
            return json.dumps({"success": False, "added": [], "error": msg})

        filepaths, _ = QFileDialog.getOpenFileNames(
            None,
            "选择 EDR 光谱校正文件（i1Profiler/X-Rite 驱动光盘）",
            "",
            "EDR 校正文件 (*.edr);;所有文件 (*)"
        )
        if not filepaths:
            return json.dumps({"success": False, "added": [], "error": "cancelled"})

        before = set(os.listdir(self._corrections_dir)) if os.path.isdir(self._corrections_dir) else set()

        try:
            proc = subprocess.run(
                [oeminst, "-v", "-c"] + list(filepaths),
                cwd=self._corrections_dir,
                capture_output=True, text=True, timeout=120,
            )
        except Exception as e:
            msg = f"oeminst 执行失败: {e}"
            self.logMessage.emit(msg)
            return json.dumps({"success": False, "added": [], "error": msg})

        if proc.stdout.strip():
            self.logMessage.emit(f"oeminst: {proc.stdout.strip()[:500]}")

        after = set(os.listdir(self._corrections_dir)) if os.path.isdir(self._corrections_dir) else set()
        added = sorted(f for f in after - before if f.lower().endswith((".ccss", ".ccmx")))

        if proc.returncode != 0 and not added:
            msg = f"EDR 转换失败 (exit {proc.returncode}): {(proc.stderr or proc.stdout).strip()[:300]}"
            self.logMessage.emit(msg)
            return json.dumps({"success": False, "added": [], "error": msg})

        self.logMessage.emit(f"EDR 导入完成: 新增 {len(added)} 个校正文件 {added}")
        return json.dumps({"success": True, "added": added, "error": ""})

    @pyqtSlot(str)
    def set_correction_file_path(self, correction_path: str):
        """
        设置光谱校正文件路径，并传递给 ArgyllController

        会自动检查修正文件与当前探头/显示器的兼容性，
        不兼容时会警告用户，但不阻止设置（允许高级用户覆盖）

        Args:
            correction_path: 校正文件的绝对路径，空字符串表示清除
        """
        if self._argyll_controller:
            if correction_path:
                # 获取修正文件元数据
                metadata = self._correction_manager.get_correction_by_path(correction_path)

                if metadata:
                    # 检查兼容性
                    current_probe = self._argyll_controller._probe_type.value if hasattr(self._argyll_controller, '_probe_type') else ""
                    current_display = self._current_display_type.value if hasattr(self, '_current_display_type') else ""

                    result = self._correction_manager.check_compatibility(
                        metadata, current_probe, current_display
                    )

                    # 记录修正文件 hash 用于测量结果关联
                    self._current_correction_hash = metadata.file_hash
                    self._current_correction_metadata = metadata

                    # 输出兼容性信息
                    if not result.is_compatible:
                        self.logMessage.emit(f"⚠️ 警告：修正文件兼容性问题")
                        for error in result.errors:
                            self.logMessage.emit(f"  ❌ {error}")
                    if result.warnings:
                        for warning in result.warnings:
                            self.logMessage.emit(f"  ⚠️ {warning}")

                    # 输出修正文件信息
                    self.logMessage.emit(f"光谱校正文件已设置: {metadata.filename}")
                    if metadata.descriptor:
                        self.logMessage.emit(f"  描述: {metadata.descriptor}")
                    if metadata.instrument:
                        self.logMessage.emit(f"  目标探头: {metadata.instrument}")
                    if metadata.display_technology:
                        self.logMessage.emit(f"  目标显示技术: {metadata.display_technology.get_display_name()}")
                    if metadata.created:
                        self.logMessage.emit(f"  创建时间: {metadata.created.strftime('%Y-%m-%d %H:%M:%S')}")
                    if metadata.reference_instrument:
                        self.logMessage.emit(f"  基准探头: {metadata.reference_instrument}")
                else:
                    self.logMessage.emit(f"光谱校正文件已设置: {os.path.basename(correction_path)}")
                    self.logMessage.emit(f"⚠️ 无法解析修正文件元数据")
                    self._current_correction_hash = ""
                    self._current_correction_metadata = None

                # 设置到 ArgyllController
                self._argyll_controller.set_correction_file(correction_path)
            else:
                self._argyll_controller.set_correction_file('')
                self.logMessage.emit(i18n.t("光谱校正文件已清除"))
                self._current_correction_hash = ""
                self._current_correction_metadata = None

    @pyqtSlot(str)
    def set_probe_type(self, probe_type: str):
        """设置探头类型"""
        if self._argyll_controller:
            # ========== X-Rite / Calibrite 色度计 ==========
            if probe_type == "i1d3":
                self._argyll_controller.set_probe_type(ProbeType.I1_DISPLAY_PRO)
            elif probe_type == "i1d2":
                self._argyll_controller.set_probe_type(ProbeType.I1_DISPLAY_2)
            elif probe_type == "dtp94":
                self._argyll_controller.set_probe_type(ProbeType.DTP94)
            elif probe_type == "huey":
                self._argyll_controller.set_probe_type(ProbeType.HUEY)
            elif probe_type == "monaco":
                self._argyll_controller.set_probe_type(ProbeType.MONACO)

            # ========== X-Rite / Calibrite 分光光度计 ==========
            elif probe_type == "i1pro":
                self._argyll_controller.set_probe_type(ProbeType.I1_PRO)
            elif probe_type == "i1pro2":
                self._argyll_controller.set_probe_type(ProbeType.I1_PRO_2)
            elif probe_type == "i1pro3":
                self._argyll_controller.set_probe_type(ProbeType.I1_PRO_3)
            elif probe_type == "colormunki":
                self._argyll_controller.set_probe_type(ProbeType.COLOR_MUNKI)
            elif probe_type == "colormunki_smile":
                self._argyll_controller.set_probe_type(ProbeType.COLOR_MUNKI_SMILE)

            # ========== Datacolor / ColorVision 色度计 ==========
            elif probe_type == "spydx":
                self._argyll_controller.set_probe_type(ProbeType.SPYDERX)
            elif probe_type == "spydx2":
                self._argyll_controller.set_probe_type(ProbeType.SPYDERX2)
            elif probe_type == "spyder":
                self._argyll_controller.set_probe_type(ProbeType.SPYDER)
            elif probe_type == "spyd5":
                self._argyll_controller.set_probe_type(ProbeType.SPYDER5)
            elif probe_type == "spyd4":
                self._argyll_controller.set_probe_type(ProbeType.SPYDER4)
            elif probe_type == "spyd3":
                self._argyll_controller.set_probe_type(ProbeType.SPYDER3)
            elif probe_type == "spyd2":
                self._argyll_controller.set_probe_type(ProbeType.SPYDER2)
            elif probe_type == "spyd1":
                self._argyll_controller.set_probe_type(ProbeType.SPYDER1)

            # ========== Klein 色度计 ==========
            elif probe_type == "k10a":
                self._argyll_controller.set_probe_type(ProbeType.K10A)

            # ========== 其他设备 ==========
            elif probe_type == "colorhug":
                self._argyll_controller.set_probe_type(ProbeType.COLORHUG)
            elif probe_type == "hcfr":
                self._argyll_controller.set_probe_type(ProbeType.HCFR)
            elif probe_type == "cube":
                self._argyll_controller.set_probe_type(ProbeType.CUBE)
            elif probe_type == "ex1":
                self._argyll_controller.set_probe_type(ProbeType.EX1)

            # ========== JETI 分光光度计 ==========
            elif probe_type == "specbos":
                self._argyll_controller.set_probe_type(ProbeType.SPECBOS)
            elif probe_type == "spectraval":
                self._argyll_controller.set_probe_type(ProbeType.SPECTRAVAL)

            # ========== Gretag-Macbeth 分光光度计 ==========
            elif probe_type == "spectro":
                self._argyll_controller.set_probe_type(ProbeType.SPECTROLINO)
            elif probe_type == "spectroscan":
                self._argyll_controller.set_probe_type(ProbeType.SPECTROSCAN)

            # ========== X-Rite DTP 系列 ==========
            elif probe_type == "dtp20":
                self._argyll_controller.set_probe_type(ProbeType.DTP20)
            elif probe_type == "dtp22":
                self._argyll_controller.set_probe_type(ProbeType.DTP22)
            elif probe_type == "dtp41":
                self._argyll_controller.set_probe_type(ProbeType.DTP41)
            elif probe_type == "dtp51":
                self._argyll_controller.set_probe_type(ProbeType.DTP51)
            elif probe_type == "dtp92":
                self._argyll_controller.set_probe_type(ProbeType.DTP92)
            elif probe_type == "chroma":
                self._argyll_controller.set_probe_type(ProbeType.CHROMA)

            self.logMessage.emit(f"探头类型: {probe_type}")

            # ========== 自动配置测量延迟 ==========
            # 探头类型改变时重新计算最佳延迟
            self._auto_configure_delay()

    @pyqtSlot()
    def enumerate_instruments(self):
        """
        枚举当前连接的所有仪器设备

        通过 instrumentsEnumerated 信号发送设备列表 JSON 字符串
        格式: {"devices": [{"index": 1, "name": "...", "probe_type": "i1d3"}, ...]}
        """
        if not self._argyll_controller:
            self.instrumentsEnumerated.emit(json.dumps({"devices": [], "error": "控制器未初始化"}))
            return

        devices = self._argyll_controller.enumerate_instruments()

        # 转换为前端友好的格式
        result = {
            "devices": [
                {
                    "index": dev["index"],
                    "name": dev["name"],
                    "probe_type": dev["probe_type"].value if dev["probe_type"] else None
                }
                for dev in devices
            ]
        }

        self.instrumentsEnumerated.emit(json.dumps(result))

    @pyqtSlot(str)
    def set_display_type(self, display_type: str):
        """设置显示器类型（ArgyllCMS 官方参数值）"""
        if self._argyll_controller:
            # 显示器类型映射表（前端value -> DisplayType枚举）
            display_type_map = {
                # 常见类型
                "l": DisplayType.LCD,
                "e": DisplayType.LCD_WHITE_LED,
                "b": DisplayType.LCD_RGB_LED,
                "o": DisplayType.OLED,
                "w": DisplayType.WOLED,
                "c": DisplayType.CRT,
                # 投影仪
                "p": DisplayType.PROJECTOR,
                # LCD White LED 细分
                "8": DisplayType.LCD_WHITE_LED_IPS,
                "9": DisplayType.LCD_WHITE_LED_PVA,
                "a": DisplayType.LCD_WHITE_LED_TFT,
                # LCD RGB LED 细分
                "d": DisplayType.LCD_RGB_LED_PVA,
                # LCD CCFL
                "1": DisplayType.LCD_CCFL,
                "2": DisplayType.LCD_CCFL_IPS,
                "3": DisplayType.LCD_CCFL_PVA,
                "4": DisplayType.LCD_CCFL_TFT,
                "L": DisplayType.LCD_CCFL_WIDE,
                # LCD 荧光粉背光
                "h": DisplayType.LCD_RG_PHOSPHOR,
                "r": DisplayType.LCD_PFS_PHOSPHOR,
                "i": DisplayType.LCD_GB_R_PHOSPHOR,
                # 其他
                "m": DisplayType.PLASMA,
            }

            if display_type in display_type_map:
                dtype = display_type_map[display_type]
                self._argyll_controller.set_display_type(dtype)
                self._current_display_type = dtype
                self.logMessage.emit(f"显示器类型: {display_type}")
            else:
                # 未知类型，使用默认 LCD
                self._argyll_controller.set_display_type(DisplayType.LCD)
                self._current_display_type = DisplayType.LCD
                self.logMessage.emit(f"显示器类型未知，使用默认 LCD: {display_type}")

            # ========== 自动配置测量延迟 ==========
            # 显示器类型改变时重新计算最佳延迟（投影仪需要更长延迟）
            self._auto_configure_delay()

    # ========== 数据导出 ==========

    @pyqtSlot()
    def get_all_measurements(self):
        """获取所有测量数据（通过信号发送）"""
        data = {
            "gamut": self._gamut_measurements,
            "gamma": self._gamma_measurements,
            "gamutCoverage": {
                "sRGB": round(self._analyzer.calculate_gamut_coverage("sRGB"), 1),
                "DCI-P3": round(self._analyzer.calculate_gamut_coverage("DCI-P3"), 1),
                "AdobeRGB": round(self._analyzer.calculate_gamut_coverage("Adobe RGB"), 1)
            },
            "gammaValue": round(self._analyzer.calculate_gamma(), 2) if self._analyzer.calculate_gamma() else None
        }
        self.logMessage.emit(data)

    # ========== 测量模式 ==========

    @pyqtSlot(str)
    def set_measure_mode(self, mode: str):
        """
        设置测量模式并发送对应的色块列表

        Args:
            mode: 测量模式 ('gamut', 'icc', 'lut', 'custom')
        """
        self._current_measure_mode = mode
        self.logMessage.emit(f"测量模式: {mode}")

        # 生成并发送色块列表（JSON 字符串，避免 QWebChannel 序列化复杂 dict 出错）
        patch_list = self._generate_patch_list(mode)
        self.patchListUpdated.emit(json.dumps(patch_list))

    @pyqtSlot(str)
    def set_target_white(self, white: str):
        """
        设置目标白点（测量模式面板/向导目标设置同步用）

        Args:
            white: 白点名称（如 'D65'）
        """
        self._target_white = white
        self.logMessage.emit(f"目标白点: {white}")

    @pyqtSlot(str)
    def set_target_gamma(self, gamma: str):
        """
        设置目标 Gamma

        Args:
            gamma: Gamma 值（如 '2.2'）
        """
        self._target_gamma = gamma
        self.logMessage.emit(f"目标 Gamma: {gamma}")

    @pyqtSlot(bool)
    def set_auto_clear_lut(self, enabled: bool):
        """
        设置是否在测量前自动清除显卡 LUT

        Args:
            enabled: True 为启用自动清除，False 为禁用
        """
        self._auto_clear_lut = enabled
        self.logMessage.emit(f"自动清除 LUT: {'已启用' if enabled else '已禁用'}")

        if enabled:
            self.logMessage.emit(i18n.t("测量时将清除显卡LUT/挂载Null Profile，测量显示器原生状态"))
        else:
            self.logMessage.emit(i18n.t("将保持系统ICC配置，恢复系统色彩管理"))
            # ========== 关键：取消勾选时，卸载 Null Profile 以恢复系统 ICC ==========
            if self._lut_controller and self._null_profile_applied:
                self.logMessage.emit(i18n.t("正在卸载 Null Profile，恢复系统 ICC..."))
                display_index = self._get_patch_display_index()
                if self._lut_controller.cleanup_null_profile():
                    self._null_profile_applied = False
                    self.logMessage.emit(i18n.t("Null Profile 已卸载，系统 ICC 已恢复"))
                    # 强制刷新显示
                    self._force_refresh_display()
                else:
                    self.logMessage.emit(i18n.t("警告: 卸载 Null Profile 失败"))
            elif self._null_profile_applied:
                # 兜底：如果 controller 层状态不同步
                self.logMessage.emit(i18n.t("检测到 Null Profile 状态，尝试清理..."))
                display_index = self._get_patch_display_index()
                if self._lut_controller and self._linear_profile_path:
                    if self._lut_controller.uninstall_profile(display_index, self._linear_profile_path):
                        self._null_profile_applied = False
                        self.logMessage.emit(i18n.t("Null Profile 已卸载"))
                        self._force_refresh_display()

    def _force_refresh_display(self):
        """强制刷新显示器显示"""
        try:
            import platform
            if platform.system() == 'Darwin':
                # macOS 执行 Swift 刷新
                from .macos_display_refresh import _get_refresh_script_path, _force_macos_display_refresh
                swift_script = _get_refresh_script_path()
                _force_macos_display_refresh(swift_script_path=swift_script)
        except Exception as e:
            self.logMessage.emit(f"刷新显示失败: {e}")

    @pyqtSlot(bool)
    def set_use_null_profile_for_measurement(self, enabled: bool):
        """
        设置是否在测量前使用 Null Profile（线性 ICC Profile）绕过系统色彩管理

        这是替代不稳定 pyobjc NSColorSpace 方案的推荐做法：
        - 如果启用，测色前会通过 dispwin -I 挂载线性 ICC Profile
        - 使显示器输出呈线性状态，获取真实的原生颜色响应
        - 测量完成后恢复原始系统 Profile 或挂载新生成的 Profile

        Args:
            enabled: True 为启用 Null Profile 方案，False 为禁用
        """
        self._use_null_profile_for_measurement = enabled
        self.logMessage.emit(f"Null Profile 方案: {'已启用' if enabled else '已禁用'}")

        if enabled:
            if self._linear_profile_path:
                self.logMessage.emit(f"将使用线性 Profile: {self._linear_profile_path}")
            else:
                self.logMessage.emit(i18n.t("警告: 线性 Profile 未检测，将仅清除 LUT"))
        else:
            self.logMessage.emit(i18n.t("将仅使用 dispwin -c 清除显卡 LUT"))

    @pyqtSlot(int)
    def set_web_measurement_port(self, port: int):
        """
        设置Web测量服务器端口

        Args:
            port: 端口号 (1024-65535)
        """
        if port < 1024 or port > 65535:
            self.logMessage.emit(i18n.t("端口号必须在 1024-65535 之间"))
            return

        self._web_measurement_port = port
        self.logMessage.emit(i18n.t("Web测量服务器端口已设置为: {port}", port=port))

    @pyqtSlot()
    def get_web_measurement_port(self) -> int:
        """获取Web测量服务器端口"""
        return self._web_measurement_port

    @pyqtSlot(result=str)
    def get_web_measurement_status(self):
        """
        获取Web测量服务器状态

        Returns:
            str: JSON 字符串，包含 running / url / port
        """
        server = self._web_measurement_server
        running = bool(server and server._running)
        return json.dumps({
            "running": running,
            "url": server.url if running else None,
            "port": self._web_measurement_port,
        })

    @pyqtSlot(str)
    def copy_to_clipboard(self, text: str):
        """
        复制文本到系统剪贴板

        Web 端的 navigator.clipboard / execCommand 在无焦点窗口中不可靠，
        统一走 Qt 原生剪贴板。

        Args:
            text: 要复制的文本
        """
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)

    @pyqtSlot()
    def start_web_measurement_server(self):
        """
        启动Web测量服务器

        提供一个可在浏览器中访问的测量页面，浏览器会受系统ICC影响。
        适合用于测试ICC配置文件的效果。
        """
        try:
            self.logMessage.emit(i18n.t("正在启动Web测量服务器..."))
            if self._web_measurement_server is None:
                self._web_measurement_server = WebMeasurementServer(self._web_measurement_port)

            success, result = self._web_measurement_server.start()
            if not success and self._web_measurement_server._running:
                # 已在运行（重复开启）：按幂等处理，返回现有地址，保证菜单/偏好设置状态一致
                success = True
                result = self._web_measurement_server.url

            if success:
                self.logMessage.emit(i18n.t("Web测量服务器已启动: {url}", url=result))
                # 多网卡（含 VPN 虚拟网卡）时列出全部候选地址，主地址不可用时可换
                for alt in getattr(self._web_measurement_server, "urls", [])[1:]:
                    self.logMessage.emit(i18n.t("备用地址: {url}", url=alt))
                self.logMessage.emit(i18n.t("请在浏览器中打开上述地址进行测量"))
                self.webMeasurementServerStarted.emit(json.dumps({
                    "success": True,
                    "url": result
                }))
            else:
                self.logMessage.emit(i18n.t("Web测量服务器启动失败: {message}", message=result))
                self.webMeasurementServerStarted.emit(json.dumps({
                    "success": False,
                    "message": result
                }))
        except Exception as e:
            self.logMessage.emit(i18n.t("Web测量服务器启动异常: {message}", message=str(e)))
            self.webMeasurementServerStarted.emit(json.dumps({
                "success": False,
                "message": str(e)
            }))

    @pyqtSlot()
    def stop_web_measurement_server(self):
        """停止Web测量服务器（幂等：未运行时也发停止信号，保证所有 UI 状态同步）"""
        if self._web_measurement_server:
            self._web_measurement_server.stop()
            self._web_measurement_server = None
            self.logMessage.emit(i18n.t("Web测量服务器已停止"))
        self.webMeasurementServerStopped.emit(json.dumps({"success": True}))

    def _update_web_measurement_color(self, r: int, g: int, b: int):
        """更新Web测量服务器的颜色"""
        if self._web_measurement_server:
            self._web_measurement_server.set_color(r, g, b)

    @pyqtSlot(str)
    def apply_generated_icc_profile(self, icc_path: str):
        """
        手动挂载已生成的 ICC Profile 到系统

        用于在校准完成后或验证阶段，将新生成的 ICC Profile 应用到显示器。
        这样用户可以查看真实的校准效果。

        Args:
            icc_path: ICC Profile 文件路径
        """
        if not self._lut_controller:
            self.logMessage.emit(i18n.t("LUT 控制器未初始化，无法挂载 ICC Profile"))
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": "LUT 控制器未初始化"
            }))
            return

        if not os.path.exists(icc_path):
            self.logMessage.emit(f"ICC Profile 文件不存在: {icc_path}")
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": f"ICC Profile 文件不存在: {icc_path}"
            }))
            return

        display_index = self._get_patch_display_index()
        self.logMessage.emit(f"正在挂载 ICC Profile 到显示器 {display_index}...")

        if self._lut_controller.apply_profile(display_index, icc_path):
            self.logMessage.emit(f"ICC Profile 已成功应用到系统")
            self.logMessage.emit(i18n.t("校准效果已生效，您可以开始验证测量"))
            # 如果之前挂载了 Null Profile，现在已被新 ICC 替换
            self._null_profile_applied = False
            self.fileCreated.emit(json.dumps({
                "success": True,
                "filepath": icc_path,
                "applied": True,
                "message": "ICC Profile 已应用到系统"
            }))
        else:
            self.logMessage.emit(i18n.t("ICC Profile 挂载失败"))
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": "ICC Profile 挂载失败"
            }))

    @pyqtSlot(str)
    def update_patch_list(self, mode: str):
        """
        更新色块列表（不改变测量模式）

        用于校准完成后更新色块列表为 ICC/LUT 测量的色块。

        Args:
            mode: 测量模式 ('icc', 'lut')
        """
        self.logMessage.emit(f"更新色块列表: {mode}")
        patch_list = self._generate_patch_list(mode)
        self.patchListUpdated.emit(json.dumps(patch_list))

    @pyqtSlot(int)
    def set_gray_steps(self, steps: int):
        """设置灰阶级数"""
        self._gray_steps = steps
        self.logMessage.emit(f"灰阶级数: {steps}")

        # 如果当前是色域测量模式，更新色块列表
        if self._current_measure_mode == 'gamut':
            patch_list = self._generate_patch_list('gamut')
            self.patchListUpdated.emit(json.dumps(patch_list))

    @pyqtSlot(int)
    def set_icc_patch_count(self, count: int):
        """设置 ICC 测试色块数"""
        self._icc_patch_count = count
        self.logMessage.emit(f"ICC 测试色块数: {count}")

        # 如果当前是 ICC 模式，更新色块列表
        if self._current_measure_mode == 'icc':
            patch_list = self._generate_patch_list('icc')
            self.patchListUpdated.emit(json.dumps(patch_list))

    @pyqtSlot(str)
    def set_icc_sample_strategy(self, strategy: str):
        """
        设置 ICC 采样策略

        Args:
            strategy: 采样策略
                - 'balanced': 均衡覆盖
                - 'dark-focused': 暗部优先
                - 'gray-focused': 灰阶优先
                - 'saturation-focused': 高饱和优先
        """
        self._icc_sample_strategy = strategy
        self.logMessage.emit(f"ICC 采样策略: {strategy}")

        # 如果当前是 ICC 模式，更新色块列表
        if self._current_measure_mode == 'icc':
            patch_list = self._generate_patch_list('icc')
            self.patchListUpdated.emit(json.dumps(patch_list))

    # ========== 校准参数设置 ==========

    @pyqtSlot(str)
    def set_calibration_params(self, params_json: str):
        """
        设置预校准参数

        Args:
            params_json: JSON 格式的校准参数
                - white_point: 白点类型 (D65/D50/D75/native/custom)
                - custom_white_x: 自定义白点 x 坐标
                - custom_white_y: 自定义白点 y 坐标
                - gamma: 目标 Gamma
                - quality: 校准质量
        """
        try:
            params = json.loads(params_json)
            self._calibration_params = params
            self.logMessage.emit(f"校准参数已设置: 白点={params.get('white_point', 'D65')}, Gamma={params.get('gamma', 2.2)}")
        except json.JSONDecodeError:
            self._calibration_params = None
            self.logMessage.emit(i18n.t("校准参数解析失败"))

    @pyqtSlot()
    def clear_calibration_params(self):
        """清除校准参数（禁用预校准）"""
        self._calibration_params = None
        self.logMessage.emit(i18n.t("已禁用预校准"))

    @pyqtSlot(int)
    def set_lut_patch_count(self, count: int):
        """设置 LUT 测试色块数"""
        self._lut_patch_count = count
        self.logMessage.emit(f"LUT 测试色块数: {count}")

        # 如果当前是 LUT 模式，更新色块列表
        if self._current_measure_mode == 'lut':
            patch_list = self._generate_patch_list('lut')
            self.patchListUpdated.emit(json.dumps(patch_list))

    @pyqtSlot(str)
    def set_lut_sample_strategy(self, strategy: str):
        """设置 LUT 采样策略"""
        self._lut_sample_strategy = strategy
        self.logMessage.emit(f"LUT 采样策略: {strategy}")

        # 如果当前是 LUT 模式，更新色块列表
        if self._current_measure_mode == 'lut':
            patch_list = self._generate_patch_list('lut')
            self.patchListUpdated.emit(json.dumps(patch_list))

    def _generate_patch_list(self, mode: str) -> dict:
        """
        根据测量模式生成色块列表

        Args:
            mode: 测量模式

        Returns:
            dict: 包含分组信息的色块列表
        """
        if mode == 'gamut':
            return self._generate_gamut_patches()
        elif mode == 'icc':
            return self._generate_icc_patches()
        elif mode == 'lut':
            return self._generate_lut_patches()
        elif mode == 'custom':
            return self._generate_custom_patches()
        elif mode == 'ccmx':
            return self._generate_ccmx_patches()
        elif mode == 'saturation':
            return self._generate_saturation_patches()
        elif mode == 'hdr':
            return self._generate_hdr_patches()
        elif mode == 'uniformity':
            return self._generate_uniformity_patches()
        elif mode in ('autocal', 'lut_validation'):
            # 这些模式由各自的工作流动态生成色块，不预生成列表
            return {"mode": mode, "groups": []}
        else:
            return self._generate_gamut_patches()

    def _generate_gamut_patches(self) -> dict:
        """生成屏幕检测(色彩空间)的色块列表"""
        groups = []

        # 原色组
        primary_group = {
            "label": "原色",
            "patches": [
                {"name": "红", "rgb": [255, 0, 0]},
                {"name": "绿", "rgb": [0, 255, 0]},
                {"name": "蓝", "rgb": [0, 0, 255]}
            ]
        }
        groups.append(primary_group)

        # 基准组
        reference_group = {
            "label": "基准",
            "patches": [
                {"name": "白", "rgb": [255, 255, 255]},
                {"name": "黑", "rgb": [0, 0, 0]}
            ]
        }
        groups.append(reference_group)

        # 灰阶组（根据灰阶级数生成）
        # 注意：灰阶不包含0%（黑）和100%（白），因为它们已在基准组中
        gray_patches = []
        steps = self._gray_steps
        for i in range(1, steps):  # 改为 range(1, steps)，不包含最后一级（100%）
            level = int(255 * i / steps)
            name = f"{int(i * 100 / steps)}%"
            gray_patches.append({"name": name, "rgb": [level, level, level]})

        gray_group = {
            "label": "灰阶",
            "patches": gray_patches
        }
        groups.append(gray_group)

        total = sum(len(g["patches"]) for g in groups)
        self.logMessage.emit(f"色域测量色块列表: 共 {total} 个色块")

        return {
            "mode": "gamut",
            "groups": groups,
            "total": total
        }

    def _generate_icc_patches(self) -> dict:
        """生成 ICC 校正测量的色块列表"""
        groups = []

        # 基础色块（RGBW + 黑）
        basic_group = {
            "label": "基础",
            "patches": [
                {"name": "红", "rgb": [255, 0, 0]},
                {"name": "绿", "rgb": [0, 255, 0]},
                {"name": "蓝", "rgb": [0, 0, 255]},
                {"name": "白", "rgb": [255, 255, 255]},
                {"name": "黑", "rgb": [0, 0, 0]}
            ]
        }
        groups.append(basic_group)

        # 灰阶色块（10%-90%，共9个）
        gray_group = {
            "label": "灰阶",
            "patches": [
                {"name": "10%", "rgb": [25, 25, 25]},
                {"name": "20%", "rgb": [51, 51, 51]},
                {"name": "30%", "rgb": [76, 76, 76]},
                {"name": "40%", "rgb": [102, 102, 102]},
                {"name": "50%", "rgb": [128, 128, 128]},
                {"name": "60%", "rgb": [153, 153, 153]},
                {"name": "70%", "rgb": [179, 179, 179]},
                {"name": "80%", "rgb": [204, 204, 204]},
                {"name": "90%", "rgb": [230, 230, 230]}
            ]
        }
        groups.append(gray_group)

        # 根据色块数量生成额外的采样色块
        count = self._icc_patch_count
        basic_count = 5 + 9  # 基础色块 + 灰阶色块（共14个）
        if count > basic_count:
            # 使用 CIELAB 采样策略生成色块
            sample_patches = self._generate_sample_patches(
                count - basic_count,
                strategy=self._icc_sample_strategy
            )
            if sample_patches:
                sample_group = {
                    "label": "采样",
                    "patches": sample_patches
                }
                groups.append(sample_group)

        total = sum(len(g["patches"]) for g in groups)
        self.logMessage.emit(f"ICC 色块列表: 共 {total} 个色块")

        return {
            "mode": "icc",
            "groups": groups,
            "total": total
        }

    def _generate_lut_patches(self) -> dict:
        """生成 LUT 校正测量的色块列表"""
        groups = []

        # 基础色块（RGB + 白黑 + 灰阶）
        basic_group = {
            "label": "基础",
            "patches": [
                {"name": "红", "rgb": [255, 0, 0]},
                {"name": "绿", "rgb": [0, 255, 0]},
                {"name": "蓝", "rgb": [0, 0, 255]},
                {"name": "白", "rgb": [255, 255, 255]},
                {"name": "黑", "rgb": [0, 0, 0]},
                {"name": "10%", "rgb": [25, 25, 25]},
                {"name": "20%", "rgb": [51, 51, 51]},
                {"name": "30%", "rgb": [76, 76, 76]},
                {"name": "40%", "rgb": [102, 102, 102]},
                {"name": "50%", "rgb": [128, 128, 128]},
                {"name": "60%", "rgb": [153, 153, 153]},
                {"name": "70%", "rgb": [179, 179, 179]},
                {"name": "80%", "rgb": [204, 204, 204]},
                {"name": "90%", "rgb": [230, 230, 230]}
            ]
        }
        groups.append(basic_group)

        # 根据色块数量生成采样色块
        count = self._lut_patch_count
        basic_count = 14  # 基础色块数量（RGB+白黑+9个灰阶）
        if count > basic_count:
            # 使用 CIELAB 采样策略生成色块
            sample_patches = self._generate_sample_patches(
                count - basic_count,
                strategy=self._lut_sample_strategy
            )
            if sample_patches:
                sample_group = {
                    "label": "采样",
                    "patches": sample_patches
                }
                groups.append(sample_group)

        total = sum(len(g["patches"]) for g in groups)
        self.logMessage.emit(f"LUT 色块列表: 共 {total} 个色块")

        return {
            "mode": "lut",
            "groups": groups,
            "total": total
        }

    def _generate_custom_patches(self) -> dict:
        """生成自定义颜色模式的色块列表（空列表，用户自行输入）"""
        return {
            "mode": "custom",
            "groups": [],
            "total": 0,
            "customMode": True
        }

    # ========== 自定义色块文件管理 ==========

    @pyqtSlot(str)
    def save_custom_patches_file(self, patches_json: str):
        """
        保存自定义色块组到文件

        文件格式为 .patches（与测量数据 .json 区分）
        文件存储在 measurements 目录下

        Args:
            patches_json: JSON 格式的色块数据
                {
                    "name": "色块组名称",
                    "patches": [{"name": "色块1", "rgb": [r,g,b]}, ...]
                }
        """
        try:
            data = json.loads(patches_json)

            # 确保 measurements 目录存在
            measurements_dir = Path(self._data_storage.base_path)
            if not measurements_dir.exists():
                measurements_dir.mkdir(parents=True, exist_ok=True)

            # 生成文件名：使用时间戳和名称
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            patch_name = data.get("name", "custom")
            # 清理名称中的特殊字符
            safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in patch_name)
            filename = f"{timestamp}_{safe_name}.patches"
            filepath = measurements_dir / filename

            # 添加元数据
            file_data = {
                "format_version": "1.0",
                "software": "Topos Calibrator",
                "created_at": datetime.now().isoformat(),
                "name": data.get("name", "自定义色块组"),
                "description": data.get("description", ""),
                "patches": data.get("patches", [])
            }

            # 写入文件
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(file_data, f, indent=2, ensure_ascii=False)

            self.logMessage.emit(f"自定义色块组已保存: {filename}")
            self.fileCreated.emit(json.dumps({
                "success": True,
                "filepath": str(filepath),
                "filename": filename
            }))

            # 刷新文件列表
            self.get_custom_patches_file_list()

        except json.JSONDecodeError as e:
            self.logMessage.emit(f"保存失败: JSON 解析错误 - {e}")
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": f"JSON 解析错误: {e}"
            }))
        except Exception as e:
            self.logMessage.emit(f"保存失败: {e}")
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": str(e)
            }))

    @pyqtSlot(str)
    def load_custom_patches_file(self, filename: str):
        """
        加载自定义色块组文件

        Args:
            filename: 文件名（如 "20260407_120000_my_colors.patches"）
        """
        try:
            measurements_dir = Path(self._data_storage.base_path)

            # 处理文件名格式
            if not filename.endswith('.patches'):
                filename = f"{filename}.patches"

            filepath = measurements_dir / filename

            if not filepath.exists():
                self.logMessage.emit(f"文件不存在: {filename}")
                self.measurementLoaded.emit(json.dumps({
                    "success": False,
                    "message": "文件不存在"
                }))
                return

            # 读取文件
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 发送加载结果
            self.logMessage.emit(f"已加载色块组: {data.get('name', filename)}")
            self.measurementLoaded.emit(json.dumps({
                "success": True,
                "filename": filename,
                "filepath": str(filepath),
                "data": data
            }))

        except json.JSONDecodeError as e:
            self.logMessage.emit(f"加载失败: JSON 解析错误 - {e}")
            self.measurementLoaded.emit(json.dumps({
                "success": False,
                "message": f"JSON 解析错误: {e}"
            }))
        except Exception as e:
            self.logMessage.emit(f"加载失败: {e}")
            self.measurementLoaded.emit(json.dumps({
                "success": False,
                "message": str(e)
            }))

    @pyqtSlot()
    def get_custom_patches_file_list(self):
        """
        获取所有自定义色块组文件列表
        """
        try:
            measurements_dir = Path(self._data_storage.base_path)

            if not measurements_dir.exists():
                self.measurementListUpdated.emit(json.dumps([]))
                return

            # 获取所有 .patches 文件
            patches_files = []
            for filepath in measurements_dir.glob("*.patches"):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    patches_files.append({
                        "filename": filepath.name,
                        "filepath": str(filepath),
                        "name": data.get("name", filepath.stem),
                        "description": data.get("description", ""),
                        "patch_count": len(data.get("patches", [])),
                        "created_at": data.get("created_at", "")
                    })
                except Exception:
                    # 跳过无法解析的文件
                    continue

            # 按创建时间排序（最新的在前）
            patches_files.sort(key=lambda x: x.get("created_at", ""), reverse=True)

            self.logMessage.emit(f"找到 {len(patches_files)} 个自定义色块组文件")
            # 使用专门的信号发送文件列表
            self.calFileListUpdated.emit(json.dumps({
                "type": "custom_patches",
                "files": patches_files
            }))

        except Exception as e:
            self.logMessage.emit(f"获取文件列表失败: {e}")
            self.calFileListUpdated.emit(json.dumps({
                "type": "custom_patches",
                "files": []
            }))

    @pyqtSlot(str)
    def delete_custom_patches_file(self, filename: str):
        """
        删除自定义色块组文件

        Args:
            filename: 文件名
        """
        try:
            measurements_dir = Path(self._data_storage.base_path)

            if not filename.endswith('.patches'):
                filename = f"{filename}.patches"

            filepath = measurements_dir / filename

            if filepath.exists():
                filepath.unlink()
                self.logMessage.emit(f"已删除色块组文件: {filename}")
                self.get_custom_patches_file_list()
            else:
                self.logMessage.emit(f"文件不存在: {filename}")

        except Exception as e:
            self.logMessage.emit(f"删除失败: {e}")

    @pyqtSlot(str)
    def start_custom_patches_cycle(self, patches_json: str):
        """
        开始自定义色块组的循环测量

        Args:
            patches_json: JSON 格式的色块列表
                [{"name": "色块1", "rgb": [r, g, b]}, ...]
        """
        try:
            patches_data = json.loads(patches_json)

            # 转换为内部格式
            patch_list = []
            for patch in patches_data:
                rgb = patch.get("rgb", [0, 0, 0])
                name = patch.get("name", f"RGB({rgb[0]},{rgb[1]},{rgb[2]})")
                patch_list.append((int(rgb[0]), int(rgb[1]), int(rgb[2]), str(name)))

            if len(patch_list) == 0:
                self.logMessage.emit(i18n.t("色块列表为空，无法开始测量"))
                return

            # 设置测量模式为自定义
            self._current_measure_mode = 'custom'

            # 开始循环测量
            self._start_cycle(patch_list, "自定义色块测量")

            # 发送色块列表更新信号
            groups = [{
                "label": "自定义色块",
                "patches": [{"name": p[3], "rgb": [p[0], p[1], p[2]]} for p in patch_list]
            }]
            self.patchListUpdated.emit(json.dumps({
                "mode": "custom",
                "groups": groups,
                "total": len(patch_list),
                "customMode": True,
                "loadedPatches": True
            }))

        except json.JSONDecodeError as e:
            self.logMessage.emit(f"启动测量失败: JSON 解析错误 - {e}")
        except Exception as e:
            self.logMessage.emit(f"启动测量失败: {e}")

    def _generate_ccmx_patches(self) -> dict:
        """
        生成 CCMX 矩阵制作所需的 4 个基础色块

        Returns:
            dict: 包含白、红、绿、蓝 4 个色块
        """
        groups = []

        primary_group = {
            "label": "CCMX 基础色块",
            "patches": [
                {"name": "白", "rgb": [255, 255, 255]},
                {"name": "红", "rgb": [255, 0, 0]},
                {"name": "绿", "rgb": [0, 255, 0]},
                {"name": "蓝", "rgb": [0, 0, 255]}
            ]
        }
        groups.append(primary_group)

        total = sum(len(g["patches"]) for g in groups)
        self.logMessage.emit(f"CCMX 模式色块列表: 共 {total} 个色块")

        return {
            "mode": "ccmx",
            "groups": groups,
            "total": total
        }

    def _generate_saturation_patches(self) -> dict:
        """
        生成饱和度扫描色块列表（Calman saturation sweep 等价能力）

        使用 color_science/patch_sets.py 的饱和度扫描生成器：
        R/G/B/Y/M/C 六色 × 饱和度级别（25/50/75/100%）+ 中性灰对照。
        色块命名 "R-25%" 格式，供饱和度追踪图解析。

        Returns:
            dict: 按颜色分组的色块列表
        """
        from src.color_science.patch_sets import (
            generate_saturation_sweep_patch_set,
            generate_hue_sweep_patch_set,
        )

        color_labels = {
            "R": "红", "G": "绿", "B": "蓝",
            "Y": "黄", "M": "品红", "C": "青",
        }

        groups = []

        # 饱和度扫描：六色 × 级别
        sweep = generate_saturation_sweep_patch_set(
            levels=[25, 50, 75, 100], include_neutrals=True
        )
        by_color: Dict[str, list] = {}
        neutral_patches = []
        for patch in sweep.patches:
            meta = patch.metadata or {}
            color = meta.get("color", "")
            level = meta.get("saturation_percent", 0)
            entry = {
                "name": f"{color}-{level}%",
                "rgb": list(patch.rgb_8bit),
                "color": color,
                "saturation": level,
            }
            if color == "neutral":
                entry["name"] = f"白-{level}%"
                neutral_patches.append(entry)
            else:
                by_color.setdefault(color, []).append(entry)

        for color in ["R", "G", "B", "Y", "M", "C"]:
            if color in by_color:
                groups.append({
                    "label": f"{color_labels.get(color, color)} ({color}) 饱和度扫描",
                    "patches": by_color[color],
                })

        # 色相扫描：12 步色轮
        hue = generate_hue_sweep_patch_set(saturation=100, lightness=50, steps=12)
        hue_patches = []
        for i, patch in enumerate(hue.patches):
            angle = int(i * 360 / 12)
            hue_patches.append({
                "name": f"色相-{angle}°",
                "rgb": list(patch.rgb_8bit),
                "hue": angle,
            })
        groups.append({"label": "色相扫描 (12 步色轮)", "patches": hue_patches})

        if peak_test_total:
            groups.append({"label": "中性灰对照", "patches": neutral_patches})

        total = sum(len(g["patches"]) for g in groups)
        self.logMessage.emit(f"饱和度扫描模式色块列表: 共 {total} 个色块")

        return {
            "mode": "saturation",
            "groups": groups,
            "total": total
        }

    def _generate_hdr_patches(self) -> dict:
        """
        生成 HDR EOTF 追踪灰阶梯（P3 集成）

        按 PQ/HLG 信号编码生成 21 级灰阶，用于验证显示器 HDR 曲线追踪。
        - PQ: 信号按 ST 2084 绝对亮度编码，ramp 截止于目标峰值 nits 的码值
        - HLG: 信号 0-1 相对编码，1.0 = 目标峰值（Lw）
        色块命名 "HDR-XX%"（XX = 信号百分比），供分析端解析。

        Returns:
            dict: HDR 灰阶色块列表
        """
        from src.color_science.transfer import apply_oetf, apply_eotf

        eotf = getattr(self, "_hdr_eotf", "PQ")
        peak_nits = float(getattr(self, "_hdr_peak_nits", 1000.0))

        patches = []
        seen_codes = set()

        if eotf == "PQ":
            # PQ 为绝对亮度编码：目标亮度按对数分布 2 nits → 峰值，
            # 转为 ST 2084 码值（8-bit 去重）。注意 apply_oetf 接收绝对 nits。
            lo, hi = 2.0, min(peak_nits, 10000.0)
            n = 21
            for i in range(n):
                L = lo * (hi / lo) ** (i / (n - 1)) if i < n - 1 else hi
                V = apply_oetf(L, "PQ")
                code8 = int(round(V * 255))
                if code8 in seen_codes or code8 < 1:
                    continue
                seen_codes.add(code8)
                L_target = apply_eotf(code8 / 255.0, "PQ", L_max=10000.0)
                patches.append({
                    "name": f"HDR-{code8}",
                    "rgb": [code8, code8, code8],
                    "signal": round(code8 / 255.0, 4),
                    "target_nits": round(L_target, 2),
                })
        else:
            # HLG 为相对编码：信号 0-1 线性分布，1.0 = Lw（目标峰值）
            steps = 21
            for i in range(1, steps + 1):
                V = i / steps
                code8 = int(round(V * 255))
                L_target = apply_eotf(V, "HLG", Lw=peak_nits, Lb=0.0)
                patches.append({
                    "name": f"HDR-{code8}",
                    "rgb": [code8, code8, code8],
                    "signal": round(V, 4),
                    "target_nits": round(L_target, 2),
                })

        groups = [{
            "label": f"HDR {eotf} 灰阶追踪（目标峰值 {int(peak_nits)} nits）",
            "patches": patches,
        }]

        self.logMessage.emit(
            f"HDR 追踪模式色块列表: {len(patches)} 级 {eotf} 灰阶，峰值 {int(peak_nits)} nits"
        )
        return {
            "mode": "hdr",
            "groups": groups,
            "total": len(patches),
            "eotf": eotf,
            "peak_nits": peak_nits,
        }

    def _generate_dispcal_patches(self, quality: str = 'm') -> dict:
        """
        生成 dispcal 校准所需的色块列表

        dispcal 的色块序列取决于校准质量：
        - 低质量 (l): 4 个灰阶 (0%, 25%, 50%, 75%, 100%)
        - 中质量 (m): 6 个灰阶 + 黑白校准
        - 高质量 (h): 11 个灰阶 + 黑白校准 + 颜色色块

        Args:
            quality: 校准质量 (l/m/h)

        Returns:
            dict: 包含分组信息的色块列表
        """
        groups = []

        # 根据质量设置确定灰阶数量
        # ArgyllCMS dispcal 的典型灰阶数量：
        # - l (低): ~5 个灰阶
        # - m (中): ~7 个灰阶
        # - h (高): ~11 个灰阶
        gray_count_map = {
            'l': 5,   # 0%, 25%, 50%, 75%, 100%
            'm': 7,   # 更密集的灰阶
            'h': 11   # 高精度灰阶
        }
        gray_count = gray_count_map.get(quality, 7)

        # 黑场校准（第一个色块）
        black_group = {
            "label": "黑场校准",
            "patches": [
                {"name": "黑场", "rgb": [0, 0, 0]}
            ]
        }
        groups.append(black_group)

        # 灰阶校准（不包含 0% 和 100%，它们在黑白场中）
        gray_patches = []
        for i in range(1, gray_count - 1):
            level = int(255 * i / (gray_count - 1))
            name = f"灰阶{i}"
            gray_patches.append({"name": name, "rgb": [level, level, level]})

        gray_group = {
            "label": "灰阶校准",
            "patches": gray_patches
        }
        groups.append(gray_group)

        # 白场校准（最后一个色块）
        white_group = {
            "label": "白场校准",
            "patches": [
                {"name": "白场", "rgb": [255, 255, 255]}
            ]
        }
        groups.append(white_group)

        # 高质量模式下可能有额外的颜色校准色块
        if quality == 'h':
            color_group = {
                "label": "颜色校准",
                "patches": [
                    {"name": "红校准", "rgb": [255, 0, 0]},
                    {"name": "绿校准", "rgb": [0, 255, 0]},
                    {"name": "蓝校准", "rgb": [0, 0, 255]},
                    {"name": "青校准", "rgb": [0, 255, 255]},
                    {"name": "黄校准", "rgb": [255, 255, 0]},
                    {"name": "紫校准", "rgb": [255, 0, 255]}
                ]
            }
            groups.append(color_group)

        total = sum(len(g["patches"]) for g in groups)
        self.logMessage.emit(f"dispcal 校准色块列表: 共 {total} 个色块 (质量: {quality})")

        return {
            "mode": "dispcal",
            "groups": groups,
            "total": total,
            "quality": quality
        }

    def _generate_sample_patches(self, count: int, strategy: str = 'balanced') -> list:
        """
        生成采样色块

        对于小数量色块（<= 1024），使用 RGB 空间均匀采样。
        对于大数量色块（> 1024），使用 CIELAB 空间智能采样，
        确保暗部细节、灰阶过渡和高饱和边界都能被探头精准覆盖。

        Args:
            count: 需要生成的色块数量
            strategy: 采样策略
                - 'balanced': 均衡覆盖（暗部、灰阶、高饱和均匀分配）
                - 'dark-focused': 暗部优先（低 L* 区域更密集采样）
                - 'gray-focused': 灰阶优先（L* 轴精细采样）
                - 'saturation-focused': 高饱和优先（色域边界密集采样）

        Returns:
            list: 色块列表，每个元素包含 {"name": str, "rgb": [r, g, b]}
        """
        patches = []

        if count <= 0:
            return patches

        # ========== 大数量色块使用 GamutSampler 采样 ==========
        # 512+ 色块使用智能采样，确保关键区域覆盖
        # 新采样器修复了 Lab→RGB 转换导致的重复色块问题
        if count >= 512:
            self.logMessage.emit(f"使用 GamutSampler 采样策略: {strategy}, 色块数: {count}")

            # 映射策略名称到 SamplingStrategy
            strategy_map = {
                'balanced': SamplingStrategy.ICC_STANDARD,
                'dark-focused': SamplingStrategy.DARK_PRIORITY,
                'gray-focused': SamplingStrategy.GRAY_SCALE,
                'saturation-focused': SamplingStrategy.UNIFORM,  # 高饱和用均匀策略
            }

            selected_strategy = strategy_map.get(strategy, SamplingStrategy.ICC_STANDARD)

            # 创建新采样器
            sampler = GamutSampler(selected_strategy)
            patch_infos = sampler.generate_patches(count)

            # 转换 PatchInfo 列表到旧格式
            patches = []
            for p in patch_infos:
                patches.append({
                    "name": p.sample_id,
                    "rgb": list(p.rgb),
                    "purpose": p.purpose,
                    "priority": p.priority
                })

            self.logMessage.emit(f"GamutSampler 采样完成: 共 {len(patches)} 个色块")
            return patches

        # ========== 小数量色块使用色彩均衡采样 ==========
        # 200-511 色块使用色彩均衡采样（解决颜色分布不均问题）
        # 原RGB均匀采样导致蓝青绿占70%，红黄色仅15%
        # 新算法确保红黄绿青蓝紫各色均衡分布
        return self._generate_balanced_rgb_patches(count)

    def _generate_balanced_rgb_patches(self, count: int) -> list:
        """
        生成色彩均衡的RGB采样色块

        解决简单RGB均匀采样导致颜色分布不均的问题：
        - 原算法: R=0时G,B任意组合都是蓝色/青色，导致蓝青绿占70%
        - 新算法: 按色彩类别分配采样数，确保红黄绿青蓝紫均衡

        Args:
            count: 需要生成的色块数量

        Returns:
            list: 色块列表，每个元素包含 {"name": str, "rgb": [r, g, b]}
        """
        patches = []
        seen_rgb = set()

        # 需要跳过的色块（基础色块 + 灰阶色块）
        skip_patches = {
            (255, 0, 0), (0, 255, 0), (0, 0, 255),  # RGB原色
            (255, 255, 255), (0, 0, 0),  # 白、黑
            (25, 25, 25), (51, 51, 51), (76, 76, 76),  # 灰阶 10%-30%
            (102, 102, 102), (128, 128, 128), (153, 153, 153),  # 灰阶 40%-60%
            (179, 179, 179), (204, 204, 204), (230, 230, 230)  # 灰阶 70%-90%
        }

        def add_patch(r, g, b):
            """添加色块，跳过重复和已包含的"""
            rgb_tuple = (int(r), int(g), int(b))
            if rgb_tuple in seen_rgb or rgb_tuple in skip_patches:
                return False
            # 跳过灰阶
            if abs(r - g) < 8 and abs(g - b) < 8 and r not in [0, 255]:
                return False
            patches.append({"name": f"采样{len(patches) + 1}", "rgb": [int(r), int(g), int(b)]})
            seen_rgb.add(rgb_tuple)
            return True

        # 按颜色类别分配采样数量
        # 每种颜色约占总数的1/6，加上一些混合色
        per_color = count // 7

        # 1. 红色区域 (R高，G和B低)
        for i in range(per_color):
            r = 100 + (155 * i // per_color)  # 100-255
            g = max(0, int(r * 0.3 * (i % 5 + 1) / 5))
            b = max(0, int(r * 0.2 * (i % 5 + 1) / 5))
            add_patch(r, g, b)

        # 2. 黄色区域 (R和G高，B低)
        for i in range(per_color):
            base = 100 + (155 * i // per_color)
            r = min(255, base + (i % 3) * 10)
            g = min(255, base - (i % 3) * 5)
            b = max(0, 50 - i // 4)
            add_patch(r, g, b)

        # 3. 绿色区域 (G高，R和B低)
        for i in range(per_color):
            g = 100 + (155 * i // per_color)
            r = max(0, int(g * 0.3 * (i % 5 + 1) / 5))
            b = max(0, int(g * 0.4 * (i % 5 + 1) / 5))
            add_patch(r, g, b)

        # 4. 青色区域 (G和B高，R低)
        for i in range(per_color):
            base = 100 + (155 * i // per_color)
            g = min(255, base + (i % 3) * 10)
            b = min(255, base - (i % 3) * 5)
            r = max(0, 50 - i // 4)
            add_patch(r, g, b)

        # 5. 蓝色区域 (B高，R和G低) - 限制数量避免过多
        for i in range(per_color):
            b = 100 + (155 * i // per_color)
            r = max(0, int(b * 0.3 * (i % 5 + 1) / 5))
            g = max(0, int(b * 0.4 * (i % 5 + 1) / 5))
            add_patch(r, g, b)

        # 6. 品红区域 (R和B高，G低)
        for i in range(per_color):
            base = 100 + (155 * i // per_color)
            r = min(255, base + (i % 3) * 10)
            b = min(255, base - (i % 3) * 5)
            g = max(0, 50 - i // 4)
            add_patch(r, g, b)

        # 7. 混合色填充剩余
        remaining = count - len(patches)
        if remaining > 0:
            grid_size = int(remaining ** (1/3)) + 1
            for r_idx in range(grid_size + 1):
                for g_idx in range(grid_size + 1):
                    for b_idx in range(grid_size + 1):
                        if len(patches) >= count:
                            break
                        r = 255 * r_idx // grid_size
                        g = 255 * g_idx // grid_size
                        b = 255 * b_idx // grid_size
                        add_patch(r, g, b)
                    if len(patches) >= count:
                        break
                if len(patches) >= count:
                    break

        self.logMessage.emit(f"色彩均衡采样完成: 共 {len(patches)} 个色块")
        return patches[:count]

    # ========== 数据存储管理 ==========

    @pyqtSlot()
    def save_current_measurement(self):
        """
        保存当前测量数据到文件
        
        会自动设置元数据（探头类型、显示器类型、时间戳）
        """
        # 更新元数据
        if self._argyll_controller:
            probe_type = self._argyll_controller._probe_type.value if hasattr(self._argyll_controller, '_probe_type') else "未知"
            self._current_measurement.set_probe(probe_type)
        
        display_type_str = self._current_display_type.value if hasattr(self._current_display_type, 'value') else str(self._current_display_type)
        self._current_measurement.set_display_type(display_type_str)

        # 自动获取并设置显示器型号
        display_model = self._get_display_model()
        if display_model:
            self._current_measurement.set_display_model(display_model)

        # 设置测量模式
        self._current_measurement.set_measure_mode(self._current_measure_mode)
        self._current_measurement.set_timestamp()

        # 设置修正文件信息（如果有）
        if self._current_correction_hash and self._current_correction_metadata:
            created_str = ""
            if self._current_correction_metadata.created:
                created_str = self._current_correction_metadata.created.strftime("%Y-%m-%d %H:%M:%S")
            self._current_measurement.set_correction_file(
                correction_hash=self._current_correction_hash,
                correction_path=self._current_correction_metadata.file_path,
                correction_descriptor=self._current_correction_metadata.descriptor,
                correction_type=self._current_correction_metadata.correction_type.value,
                correction_instrument=self._current_correction_metadata.instrument,
                correction_technology=self._current_correction_metadata.technology,
                correction_reference=self._current_correction_metadata.reference_instrument,
                correction_created=created_str
            )

        # 重新生成测量ID，确保每次保存都有唯一ID
        self._current_measurement.regenerate_id()

        # 检查数据是否有效
        if not self._current_measurement.is_valid():
            self.logMessage.emit(i18n.t("没有有效的测量数据可保存"))
            self.measurementSaved.emit(json.dumps({
                "success": False,
                "message": "没有有效的测量数据"
            }))
            return
        
        # 保存数据
        filepath = self._data_storage.save_measurement(self._current_measurement)
        
        if filepath:
            self.logMessage.emit(f"测量数据已保存: {filepath}")
            self.measurementSaved.emit(json.dumps({
                "success": True,
                "filepath": filepath,
                "id": self._current_measurement.metadata["measurement_id"]
            }))
            
            # 更新测量列表
            self.refresh_measurement_list()
        else:
            self.logMessage.emit(i18n.t("保存测量数据失败"))
            self.measurementSaved.emit(json.dumps({
                "success": False,
                "message": "保存失败"
            }))

    @pyqtSlot()
    def refresh_measurement_list(self):
        """
        刷新测量数据列表并发送到前端
        使用 get_all_saved_measurements() 以支持 auto_save 子目录中的数据
        """
        # 获取所有测量数据（包括 auto_save 子目录中的）
        raw_list = self._data_storage.get_all_saved_measurements()

        # 转换为前端期望的格式
        measurements = []
        for item in raw_list:
            # 尝试从 JSON 文件中读取 metadata
            display_name = ""
            probe = ""
            has_gamut = False
            has_gamma = False
            has_lut = False
            
            json_path = item.get("json_path")
            if json_path and Path(json_path).exists():
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        metadata = data.get("metadata", {})
                        probe = metadata.get("probe", "")
                        display_name = metadata.get("display_name", "")
                        
                        # 检查数据类型
                        meas_data = data.get("measurements", {})
                        has_gamut = "gamut" in meas_data
                        has_gamma = "gamma" in meas_data
                        has_lut = "lut" in meas_data or "custom_patches" in meas_data
                except Exception as e:
                    self._logger.warning(f"读取 {json_path} 失败: {e}")
            
            # 生成 ID（使用 measurement_id 或文件名）
            measurement_id = ""
            if json_path:
                measurement_id = Path(json_path).stem
            elif ti3_path:
                measurement_id = Path(ti3_path).stem
            
            measurements.append({
                "id": measurement_id,
                "name": item.get("name", ""),
                "display_name": display_name,
                "json_path": item.get("json_path", ""),
                "ti3_path": item.get("ti3_path", ""),
                "cal_path": item.get("cal_path", ""),
                "measure_mode": item.get("measure_mode", ""),
                "timestamp": item.get("timestamp", 0),
                "filename": Path(item.get("json_path") or item.get("ti3_path") or "").name,
                "date_dir": item.get("date_dir", ""),
                "time_str": item.get("time_str", ""),
                "probe": probe,
                "has_gamut": has_gamut,
                "has_gamma": has_gamma,
                "has_lut": has_lut
            })

        # 按时间戳排序（最新的在前）
        measurements.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        # 包装在 measurements 字段中
        result = {"measurements": measurements}
        json_result = json.dumps(result, ensure_ascii=False)
        self.measurementListUpdated.emit(json_result)
        self.logMessage.emit(i18n.t("已加载 {n} 条历史测量记录", n=len(measurements)))

    @pyqtSlot()
    def refresh_cal_file_list(self):
        """
        刷新cal校准文件列表并发送到前端
        """
        cal_files = self._data_storage.list_cal_files()
        self.calFileListUpdated.emit(json.dumps(cal_files))
        self.logMessage.emit(f"已加载 {len(cal_files)} 个cal校准文件")

    @pyqtSlot()
    def get_cal_file_list(self):
        """
        获取cal校准文件列表（通过信号发送）
        """
        self.refresh_cal_file_list()

    # ========== 会话管理方法 ==========

    @pyqtSlot()
    def get_session_list(self):
        """
        获取会话列表（通过信号发送）
        """
        sessions = self._session_storage.list_sessions(include_auto_save=True)
        # 发送新信号或复用现有信号
        self.sessionListUpdated.emit(json.dumps(sessions))
        self.logMessage.emit(f"已加载 {len(sessions)} 个会话")

    @pyqtSlot(str)
    def load_session(self, session_id: str):
        """
        加载会话数据

        Args:
            session_id: 会话ID
        """
        result = self._session_storage.load_session(session_id)

        if result:
            session, measurement = result
            self._current_session = session
            self._current_measurement = measurement

            # 同步更新旧格式数据（兼容现有分析器）
            self._sync_measurement_to_legacy_format()

            # 发送加载完成信号
            self.measurementLoaded.emit(json.dumps(measurement.to_json()))

            # 重新计算并发送图表数据
            self._calculate_and_emit_gamut_coverage()
            self._calculate_and_emit_gamma()
            self._calculate_and_emit_display_basic_data()

            self.logMessage.emit(f"已加载会话: {session_id} ({session.measure_mode})")
        else:
            self.logMessage.emit(f"加载会话失败: {session_id}")

    @pyqtSlot(str)
    def delete_session(self, session_id: str):
        """
        删除会话

        Args:
            session_id: 会话ID
        """
        success = self._session_storage.delete_session(session_id)
        if success:
            self.logMessage.emit(f"已删除会话: {session_id}")
            # 刷新会话列表
            self.get_session_list()
        else:
            self.logMessage.emit(f"删除会话失败: {session_id}")

    @pyqtSlot(str)
    def archive_session(self, session_id: str):
        """
        归档会话

        Args:
            session_id: 会话ID
        """
        success = self._session_storage.archive_session(session_id)
        if success:
            self.logMessage.emit(f"已归档会话: {session_id}")
            # 刷新会话列表
            self.get_session_list()
        else:
            self.logMessage.emit(f"归档会话失败: {session_id}")

    @pyqtSlot()
    def create_new_session(self, measure_mode: str = ""):
        """
        创建新会话

        Args:
            measure_mode: 测量模式
        """
        self._current_session = self._session_storage.create_session(measure_mode)
        self.logMessage.emit(f"已创建新会话: {self._current_session.session_id}")

    # ========== 原有测量数据方法 ==========

    @pyqtSlot(str)
    def load_measurement(self, measurement_id: str):
        """
        加载历史测量数据
        
        Args:
            measurement_id: 测量ID或文件名
        """
        data = self._data_storage.load_measurement(measurement_id)
        
        if data:
            # 更新当前测量数据对象
            self._current_measurement = data
            
            # 同步更新旧格式数据（兼容现有分析器）
            self._sync_measurement_to_legacy_format()
            
            # 发送加载完成信号（包含完整数据）
            self.measurementLoaded.emit(json.dumps(data.to_json()))
            
            # 重新计算并发送图表数据
            self._calculate_and_emit_gamut_coverage()
            self._calculate_and_emit_gamma()
            self._calculate_and_emit_display_basic_data()

            self.logMessage.emit(f"已加载测量数据: {measurement_id}")
        else:
            self.logMessage.emit(f"加载测量数据失败: {measurement_id}")
            self.measurementLoaded.emit(json.dumps({
                "success": False,
                "message": "加载失败"
            }))

    def _sync_measurement_to_legacy_format(self):
        """
        将新的MeasurementData格式同步到旧格式
        以保持与现有分析器的兼容性
        """
        gamut = self._current_measurement.measurements.get("gamut", {})
        
        # 色域数据
        color_map = {
            "red": "红",
            "green": "绿",
            "blue": "蓝",
            "white": "白",
            "black": "黑"
        }
        
        self._gamut_measurements = {}
        for eng_key, chn_name in color_map.items():
            if eng_key in gamut and gamut[eng_key].get("xyY"):
                xyY = gamut[eng_key]["xyY"]
                rgb = gamut[eng_key]["RGB"]
                self._gamut_measurements[chn_name] = {
                    "patchName": chn_name,
                    "rgb": {"r": rgb[0], "g": rgb[1], "b": rgb[2]},
                    "x": xyY[0],
                    "y": xyY[1],
                    "Y": xyY[2]
                }
        
        # Gamma数据
        gamma = self._current_measurement.measurements.get("gamma", [])
        self._gamma_measurements = []
        for point in gamma:
            rgb = point.get("RGB", [128, 128, 128])
            self._gamma_measurements.append({
                "patchName": point.get("patch_name", f"{point['input']}%"),
                "rgb": {"r": rgb[0], "g": rgb[1], "b": rgb[2]},
                "x": 0.3127,  # 灰阶假设为D65白点
                "y": 0.3290,
                "Y": point["Y"]
            })

    @pyqtSlot()
    def clear_current_measurement(self):
        """
        清空当前测量数据
        """
        self._gamut_measurements = {}
        self._gamma_measurements = []
        self._current_measurement = MeasurementData()
        
        self.logMessage.emit(i18n.t("已清空当前测量数据"))

    @pyqtSlot(str)
    def delete_measurement(self, measurement_id: str):
        """
        删除历史测量数据
        
        Args:
            measurement_id: 测量ID或文件名
        """
        success = self._data_storage.delete_measurement(measurement_id)
        
        if success:
            self.logMessage.emit(f"已删除测量数据: {measurement_id}")
            self.refresh_measurement_list()
        else:
            self.logMessage.emit(f"删除测量数据失败: {measurement_id}")

    @pyqtSlot(str)
    def export_measurement_ti3(self, filepath: str):
        """
        导出当前测量数据为TI3格式
        
        Args:
            filepath: 导出文件路径
        """
        if not self._current_measurement.is_valid():
            self.logMessage.emit(i18n.t("没有有效的测量数据可导出"))
            self.dataExported.emit(json.dumps({
                "success": False,
                "message": "没有有效的测量数据"
            }))
            return
        
        success = self._cgats_exporter.export_ti3(self._current_measurement, filepath)
        
        if success:
            self.logMessage.emit(f"TI3文件已导出: {filepath}")
            self.dataExported.emit(json.dumps({
                "success": True,
                "filepath": filepath,
                "format": "TI3"
            }))
        else:
            self.logMessage.emit(i18n.t("导出TI3文件失败"))
            self.dataExported.emit(json.dumps({
                "success": False,
                "message": "导出失败"
            }))

    @pyqtSlot(str)
    def export_measurement_cgats(self, filepath: str):
        """
        导出当前测量数据为CGATS格式
        
        Args:
            filepath: 导出文件路径
        """
        if not self._current_measurement.is_valid():
            self.logMessage.emit(i18n.t("没有有效的测量数据可导出"))
            self.dataExported.emit(json.dumps({
                "success": False,
                "message": "没有有效的测量数据"
            }))
            return
        
        success = self._cgats_exporter.export_cgats(self._current_measurement, filepath)
        
        if success:
            self.logMessage.emit(f"CGATS文件已导出: {filepath}")
            self.dataExported.emit(json.dumps({
                "success": True,
                "filepath": filepath,
                "format": "CGATS"
            }))
        else:
            self.logMessage.emit(i18n.t("导出CGATS文件失败"))
            self.dataExported.emit(json.dumps({
                "success": False,
                "message": "导出失败"
            }))

    @pyqtSlot(str)
    def export_measurement(self, params_json: str):
        """
        导出测量数据（支持CSV和JSON格式）

        Args:
            params_json: JSON格式的参数
                - format: "csv" 或 "json"
                - file_path: 文件路径
                - file_name: 文件名
                - include_gamut: 是否包含色域数据
                - include_gamma: 是否包含灰阶数据
        """
        try:
            params = json.loads(params_json)
        except json.JSONDecodeError:
            self.logMessage.emit(i18n.t("参数解析失败"))
            self.dataExported.emit(json.dumps({
                "success": False,
                "message": "参数解析失败"
            }))
            return

        format_type = params.get("format", "csv")
        file_path = params.get("file_path", "")
        file_name = params.get("file_name", "export")
        include_gamut = params.get("include_gamut", True)
        include_gamma = params.get("include_gamma", True)

        from pathlib import Path
        if file_path:
            full_path = Path(file_path)
        else:
            # 默认保存到项目的 measurements 目录
            project_measurements_dir = Path(__file__).parent.parent / "measurements"
            project_measurements_dir.mkdir(parents=True, exist_ok=True)
            extension = ".csv" if format_type == "csv" else ".json"
            full_path = project_measurements_dir / (file_name + extension)

        if not self._current_measurement.is_valid():
            self.logMessage.emit(i18n.t("没有有效的测量数据可导出"))
            self.dataExported.emit(json.dumps({
                "success": False,
                "message": "没有有效的测量数据"
            }))
            return

        if format_type == "csv":
            # 导出CSV格式
            success = self._export_csv(full_path, include_gamut, include_gamma)
            format_name = "CSV"
        elif format_type == "json":
            # 导出JSON格式
            success = self._export_json(full_path, include_gamut, include_gamma)
            format_name = "JSON"
        else:
            self.logMessage.emit(f"不支持的导出格式: {format_type}")
            self.dataExported.emit(json.dumps({
                "success": False,
                "message": f"不支持的导出格式: {format_type}"
            }))
            return

        if success:
            self.logMessage.emit(f"{format_name}文件已导出: {full_path}")
            self.dataExported.emit(json.dumps({
                "success": True,
                "filepath": str(full_path),
                "format": format_name
            }))
        else:
            self.logMessage.emit(f"导出{format_name}文件失败")
            self.dataExported.emit(json.dumps({
                "success": False,
                "message": f"导出{format_name}文件失败"
            }))

    def _export_csv(self, filepath, include_gamut=True, include_gamma=True):
        """导出CSV格式数据"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                # 写入色域数据
                if include_gamut:
                    f.write("# 色域数据\n")
                    f.write("Color,RGB_R,RGB_G,RGB_B,XYZ_X,XYZ_Y,XYZ_Z,xy_x,xy_y,Y\n")
                    gamut = self._current_measurement.get_gamut()
                    for color_name, color_data in gamut.items():
                        if color_data:
                            rgb = color_data.get('RGB', [0, 0, 0])
                            xyz = color_data.get('XYZ', [0, 0, 0])
                            xyY = color_data.get('xyY', {})
                            f.write(f"{color_name},{rgb[0]},{rgb[1]},{rgb[2]},")
                            f.write(f"{xyz[0]:.4f},{xyz[1]:.4f},{xyz[2]:.4f},")
                            f.write(f"{xyY.get('x', 0):.4f},{xyY.get('y', 0):.4f},{xyY.get('Y', 0):.4f}\n")
                    f.write("\n")

                # 写入灰阶数据
                if include_gamma:
                    f.write("# 灰阶数据\n")
                    f.write("RGB_R,RGB_G,RGB_B,XYZ_X,XYZ_Y,XYZ_Z,xy_x,xy_y,Y\n")
                    gamma = self._current_measurement.get_gray_scale()
                    for gray_point in gamma:
                        rgb = gray_point.get('RGB', [0, 0, 0])
                        xyz = gray_point.get('XYZ', [0, 0, 0])
                        xyY = gray_point.get('xyY', {})
                        f.write(f"{rgb[0]},{rgb[1]},{rgb[2]},")
                        f.write(f"{xyz[0]:.4f},{xyz[1]:.4f},{xyz[2]:.4f},")
                        f.write(f"{xyY.get('x', 0):.4f},{xyY.get('y', 0):.4f},{xyY.get('Y', 0):.4f}\n")

            return True
        except Exception as e:
            self.logMessage.emit(f"导出CSV时发生错误: {str(e)}")
            return False

    def _export_json(self, filepath, include_gamut=True, include_gamma=True):
        """导出JSON格式数据"""
        try:
            data = {
                "metadata": {
                    "software": "Topos Calibrator",
                    "version": "0.1.0-preview",
                    "timestamp": datetime.now().isoformat()
                }
            }

            # 添加色域数据
            if include_gamut:
                data["gamut"] = self._current_measurement.get_gamut()

            # 添加灰阶数据
            if include_gamma:
                data["grayScale"] = self._current_measurement.get_gray_scale()

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            self.logMessage.emit(f"导出JSON时发生错误: {str(e)}")
            return False

    @pyqtSlot(result=str)
    def get_storage_path(self):
        """
        获取数据存储目录路径

        Returns:
            str: 存储目录路径
        """
        return self._data_storage.get_storage_path()

    # ========== 自动保存功能 ==========

    @pyqtSlot(bool)
    def enable_auto_save(self, enabled: bool):
        """
        启用/禁用测量完成后自动保存

        Args:
            enabled: True 启用，False 禁用
        """
        self._auto_save_enabled = enabled
        status = "启用" if enabled else "禁用"
        self.logMessage.emit(f"自动保存已{status}")

    @pyqtSlot(str)
    def set_auto_save_path(self, path: str):
        """
        设置自动保存基础目录

        Args:
            path: 保存目录路径
        """
        if path and path.strip():
            self._auto_save_base_dir = path.strip()
            self.logMessage.emit(f"自动保存目录: {self._auto_save_base_dir}")

    @pyqtSlot(result=str)
    def get_auto_save_status(self):
        """
        获取自动保存状态

        Returns:
            str: JSON 字符串，包含 enabled 和 base_dir
        """
        return json.dumps({
            "enabled": self._auto_save_enabled,
            "base_dir": self._auto_save_base_dir
        })

    @pyqtSlot(result=str)
    def get_color_management_status(self):
        """
        获取色彩管理设置状态

        Returns:
            str: JSON 字符串，包含 auto_clear_lut 和 use_null_profile
        """
        return json.dumps({
            "auto_clear_lut": self._auto_clear_lut,
            "use_null_profile": self._use_null_profile_for_measurement
        })

    @pyqtSlot(result=str)
    def get_calibration_list(self):
        """
        获取自动保存目录中的所有校准数据列表

        Returns:
            str: JSON 字符串，格式:
                {
                    "calibrations": [
                        {
                            "name": "2026-04-09 14:30:25",
                            "date_dir": "2026-04-09",
                            "time_str": "143025",
                            "cal_path": "/path/to/.../143025_dispcal.cal",
                            "ti3_path": "/path/to/.../143025_dispcal.ti3",
                            "json_path": "/path/to/.../143025_dispcal.json",
                            "timestamp": 1723207825
                        },
                        ...
                    ],
                    "latest": {...}  # 最新的校准数据，如果没有则为 null
                }
        """
        calibrations = self._data_storage.get_saved_calibration_list()
        latest = self._data_storage.get_latest_calibration()

        return json.dumps({
            "calibrations": calibrations,
            "latest": latest
        })

    @pyqtSlot(result=str)
    def get_measurement_list(self):
        """
        获取自动保存目录中的所有测量数据列表（包括 ICC、LUT、gamut 等所有模式）

        与 get_calibration_list() 不同，此方法返回所有测量模式的数据。

        Returns:
            str: JSON 字符串，格式为 {"measurements": [...]}
        """
        # 先获取文件列表
        file_list = self._data_storage.get_all_saved_measurements()

        measurements = []

        for idx, item in enumerate(file_list):
            # 优先使用 json_path，如果没有则使用 ti3_path
            json_path = item.get("json_path")
            ti3_path = item.get("ti3_path")

            if not json_path and not ti3_path:
                continue

            # 使用 get_all_saved_measurements 返回的显示名称
            display_name = item.get("name", "")

            try:
                # 如果有 JSON 文件，读取它获取完整元数据
                if json_path:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    metadata = data.get("metadata", {})
                    timestamp = metadata.get("timestamp", "")
                    probe = metadata.get("probe", "未知")
                    display_type = metadata.get("display_type", "未知")
                    display_model = metadata.get("display_model", "")
                    measure_mode = metadata.get("measure_mode", item.get("measure_mode", ""))
                    has_gamut = self._data_storage._check_has_gamut(data)
                    has_gamma = self._data_storage._check_has_gamma(data)
                    has_lut = self._data_storage._check_has_lut(data)
                else:
                    # 只有 TI3 文件，使用基本信息
                    timestamp = item.get("timestamp", 0)
                    # 将 timestamp 转换为 ISO 格式
                    if isinstance(timestamp, (int, float)):
                        from datetime import datetime
                        timestamp = datetime.fromtimestamp(timestamp).isoformat()
                    probe = "未知"
                    display_type = "未知"
                    display_model = ""
                    measure_mode = item.get("measure_mode", "")
                    has_gamut = measure_mode in ["gamut", "icc", "lut"]
                    has_gamma = measure_mode in ["gamma", "icc", "lut"]
                    has_lut = measure_mode == "lut"

                measurements.append({
                    "name": display_name,  # 添加显示名称
                    "id": json_path or ti3_path,
                    "timestamp": timestamp,
                    "probe": probe,
                    "display_type": display_type,
                    "display_model": display_model,
                    "measure_mode": measure_mode,
                    "filename": Path(json_path or ti3_path).name,
                    "has_gamut": has_gamut,
                    "has_gamma": has_gamma,
                    "has_lut": has_lut,
                    "json_path": json_path,
                    "ti3_path": ti3_path  # 添加 ti3_path
                })
            except Exception as e:
                error_msg = f"读取文件失败 {json_path or ti3_path}: {e}"
                self.logMessage.emit(error_msg)

        # 按时间排序（最新的在前）
        measurements.sort(key=lambda x: x["timestamp"], reverse=True)

        # 返回包装后的格式（与前端期望的格式一致）
        result = {"measurements": measurements}
        return json.dumps(result, ensure_ascii=False)

    def _auto_save_measurement_session(self, measure_mode: str) -> Optional[Dict]:
        """
        测量完成后自动保存所有数据

        Args:
            measure_mode: 测量类型 ('gamut', 'gamma', 'lut', 'dispcal')

        Returns:
            Dict: 保存结果，包含文件路径信息
        """
        if not self._auto_save_enabled:
            return None

        try:
            # 更新测量数据的元数据（探头、显示器型号等）
            if self._argyll_controller:
                probe_type = self._argyll_controller._probe_type.value if hasattr(self._argyll_controller, '_probe_type') else "未知"
                self._current_measurement.set_probe(probe_type)

            display_type_str = self._current_display_type.value if hasattr(self._current_display_type, 'value') else str(self._current_display_type)
            self._current_measurement.set_display_type(display_type_str)

            # 自动获取并设置显示器型号
            display_model = self._get_display_model()
            if display_model:
                self._current_measurement.set_display_model(display_model)

            # 设置测量模式
            self._current_measurement.set_measure_mode(measure_mode)
            self._current_measurement.set_timestamp()

            # 重新生成测量ID
            self._current_measurement.regenerate_id()

            # 生成显示名称：日期时间-显示器型号-测量模式
            # 例如：20260412_024412_PHL439P1_[ICC](gamut+gamma)
            timestamp_str = self._current_measurement.metadata.get("timestamp", "")
            
            # 提取日期时间部分（YYYYMMDD_HHMMSS）
            if timestamp_str:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp_str)
                    datetime_str = dt.strftime("%Y%m%d_%H%M%S")
                except:
                    datetime_str = timestamp_str.replace("-", "").replace(":", "").replace("T", "_").split(".")[0]
            else:
                datetime_str = ""
            
            # 显示器型号（去掉空格）
            display_model = self._current_measurement.metadata.get("display_model", "").replace(" ", "")
            
            # 测量模式显示名称
            mode_display_map = {
                "gamut": "[ColorSpace]",
                "icc": "[ICC]",
                "lut": "[LUT]",
                "custom": "[Custom]",
                "ccmx": "[CCMX]",
                "white_field": "[White Field]",
                "uniformity": "[Uniformity]",
            }
            mode_display = mode_display_map.get(measure_mode, f"[{measure_mode.upper()}]")
            
            # 组合显示名称
            display_name = f"{datetime_str}_{display_model}_{mode_display}"
            self._current_measurement.set_display_name(display_name)

            # 更新临时存储目录
            original_base_path = self._data_storage.base_path
            if self._auto_save_base_dir != "measurements/auto_save":
                # 用户设置了自定义路径
                from pathlib import Path
                custom_path = Path(self._auto_save_base_dir)
                if custom_path.is_absolute():
                    self._data_storage.base_path = custom_path
                else:
                    # 相对路径，基于项目目录
                    project_root = Path(__file__).parent.parent
                    self._data_storage.base_path = project_root / self._auto_save_base_dir

            # 保存测量数据包
            result = self._data_storage.save_measurement_bundle(
                self._current_measurement,
                measure_mode,
                include_ti3=True  # 始终包含 TI3 文件
            )

            # 恢复原始存储路径
            self._data_storage.base_path = original_base_path

            if result.get("success"):
                # 构建返回数据
                files = []
                if "json_path" in result:
                    files.append(result["json_path"])
                if "ti3_path" in result and result["ti3_path"]:
                    files.append(result["ti3_path"])

                # 如果是 dispcal 模式，复制 .cal 文件
                if measure_mode == 'dispcal' and self._current_cal_path:
                    cal_path = self._data_storage.copy_cal_file_to_auto_save(
                        self._current_cal_path,
                        measure_mode
                    )
                    if cal_path:
                        files.append(cal_path)

                # 发送自动保存完成信号
                self.sessionAutoSaved.emit(json.dumps({
                    "success": True,
                    "path": result["date_dir"],
                    "files": files,
                    "measure_mode": measure_mode
                }))

                self.logMessage.emit(f"自动保存完成: {result['date_dir']}")
                return result
            else:
                self.logMessage.emit(f"自动保存失败: {result.get('error', '未知错误')}")
                return None

        except Exception as e:
            self.logMessage.emit(f"自动保存异常: {str(e)}")
            return None

    # ========== ICC/LUT 文件制作 ==========

    @pyqtSlot(str)
    def browse_save_path(self, file_type: str):
        """
        打开文件保存路径选择对话框

        Args:
            file_type: 文件类型 ('icc', 'lut', 'export', 或 'auto_save')
        """
        from PyQt6.QtWidgets import QFileDialog
        from pathlib import Path

        default_dir = str(Path.home() / "Documents")

        # 生成带日期的默认文件名
        date_str = datetime.now().strftime("%Y-%m-%d")

        if file_type == 'auto_save':
            # 自动保存目录：选择文件夹
            dirpath = QFileDialog.getExistingDirectory(
                None,
                "选择自动保存目录",
                default_dir
            )

            if dirpath:
                self.filePathSelected.emit(json.dumps({
                    "type": "auto_save",
                    "path": dirpath
                }))
                self.logMessage.emit(f"选择自动保存目录: {dirpath}")
            return

        if file_type == 'icc':
            filter_str = "ICC Profile (*.icc);;TI3 文件 (*.ti3);;所有文件 (*)"
            default_name = f"display_profile_{date_str}.icc"
        elif file_type == 'lut':
            filter_str = "CUBE LUT (*.cube);;3DL LUT (*.3dl);;MGA LUT (*.mga);;CLF LUT (*.clf);;所有文件 (*)"
            default_name = f"display_lut_{date_str}.cube"
        elif file_type == 'export':
            # 统一导出：支持所有格式
            filter_str = "ICC Profile (*.icc);;CUBE LUT (*.cube);;3DL LUT (*.3dl);;MGA LUT (*.mga);;CLF LUT (*.clf);;CSV 文件 (*.csv);;JSON 文件 (*.json);;TI3 文件 (*.ti3);;CCMX 矩阵 (*.ccmx);;所有文件 (*)"
            default_name = f"display_profile_{date_str}.icc"
        else:
            # 默认fallback
            filter_str = "所有文件 (*)"
            default_name = f"export_{date_str}.txt"

        filepath, _ = QFileDialog.getSaveFileName(
            None,
            "选择保存路径",
            str(Path(default_dir) / default_name),
            filter_str
        )

        if filepath:
            self.filePathSelected.emit(json.dumps({
                "type": file_type,
                "path": filepath
            }))
            self.logMessage.emit(f"选择保存路径: {filepath}")

    @pyqtSlot(str, str)
    def select_save_path(self, default_filename: str, file_type: str):
        """
        打开文件保存路径选择对话框（用于报告导出）

        Args:
            default_filename: 默认文件名
            file_type: 文件类型 ('html', 'json', 'pdf')
        """
        from PyQt6.QtWidgets import QFileDialog
        from pathlib import Path

        default_dir = str(Path.home() / "Documents")

        if file_type == 'html':
            filter_str = "HTML 文件 (*.html);;所有文件 (*)"
        elif file_type == 'json':
            filter_str = "JSON 文件 (*.json);;所有文件 (*)"
        elif file_type == 'pdf':
            filter_str = "PDF 文件 (*.pdf);;所有文件 (*)"
        else:
            filter_str = "所有文件 (*)"

        filepath, _ = QFileDialog.getSaveFileName(
            None,
            "选择保存路径",
            str(Path(default_dir) / default_filename),
            filter_str
        )

        if filepath:
            # 如果用户选择的路径没有扩展名，自动添加
            if not filepath.endswith(f'.{file_type}'):
                filepath = f"{filepath}.{file_type}"

            self.filePathSelected.emit(json.dumps({
                "type": "report_export",
                "format": file_type,
                "path": filepath
            }))
            self.logMessage.emit(f"选择保存路径: {filepath}")

            # 如果有待导出的报告格式，立即完成导出
            if self._pending_export_format == file_type:
                self._complete_report_export(filepath, file_type)
                self._pending_export_format = None

    # ========== 显示器校准流程（dispcal） ==========

    @pyqtSlot()
    def _start_dispcal_web_client(self):
        """
        启动 DispcalWebClient（线程安全的槽方法）

        此方法由 on_instrument_ready 回调通过 QTimer.singleShot 调用，
        确保在主线程中执行，避免线程安全问题。

        用户工作流：
        1. 用户先手动打开测量窗口（通过前端按钮）
        2. 用户将窗口放到指定位置
        3. 用户点击"循环测量"按钮
        4. 程序使用已打开的窗口进行测量
        """
        # 记录到日志
        self._logger.debug("_start_dispcal_web_client 被调用")
        self.logMessage.emit(">>> _start_dispcal_web_client 被调用")
        self._logger.debug(f"_patch_window: {self._patch_window is not None}")
        self.logMessage.emit(f">>> _patch_window: {self._patch_window is not None}")

        if self._patch_window:
            is_visible = self._patch_window.isVisible()
            self.logMessage.emit(f">>> 测量窗口可见: {is_visible}")

            if not is_visible:
                # 窗口不可见，提示用户先打开
                self.logMessage.emit(">>> 提示：测量窗口未打开，请先打开测量窗口")
                # 显示提示信号，让前端知道需要打开窗口
                self.calibrationProgress.emit(json.dumps({
                    "current": 0,
                    "total": 100,
                    "message": "请先打开测量窗口",
                    "stage": "dispcal",
                    "need_patch_window": True
                }))
                return  # 不继续执行
        else:
            self.logMessage.emit(">>> 错误: _patch_window 为 None！")
            return

        if self._patch_window and not self._dispcal_web_client:
            self.logMessage.emit(">>> 创建 DispcalWebClient...")

            self._dispcal_web_client = DispcalWebClient(self._patch_window)

            def on_web_progress(current, total, message):
                self.calibrationProgress.emit(json.dumps({
                    "current": current,
                    "total": total,
                    "message": message,
                    "stage": "dispcal"
                }))

            def on_web_complete():
                self.logMessage.emit(i18n.t("DispcalWebClient: 色块显示完成，dispcal 正在生成校准文件..."))
                self._dispcal_web_client = None
                # 通知前端 Web Server 阶段完成，但 dispcal 进程还在继续
                self.calibrationProgress.emit(json.dumps({
                    "current": 0,
                    "total": 100,
                    "message": "色块测量完成，正在生成校准文件...",
                    "stage": "dispcal",
                    "web_server_complete": True
                }))

            def on_web_error(message):
                self.logMessage.emit(f"DispcalWebClient 错误: {message}")

            def on_web_color_changed(r, g, b):
                """颜色变化回调 - 同步前端色块预览"""
                self.patchColorChanged.emit(json.dumps({"r": r, "g": g, "b": b}))

            self.logMessage.emit(">>> 调用 connect_to_server...")
            self._dispcal_web_client.connect_to_server(
                port=9292,
                on_progress=on_web_progress,
                on_complete=on_web_complete,
                on_error=on_web_error,
                on_color_changed=on_web_color_changed
            )
            self.logMessage.emit(">>> connect_to_server 调用完成")

    @pyqtSlot()
    def _cleanup_dispcal_web_client(self):
        """
        清理 DispcalWebClient（线程安全的槽方法）

        此方法在主线程中执行，可以安全地停止 QTimer。
        """
        if self._dispcal_web_client:
            try:
                self._dispcal_web_client.disconnect()
                self.logMessage.emit(i18n.t("DispcalWebClient 已在主线程中清理"))
            except Exception as e:
                self.logMessage.emit(f"清理 DispcalWebClient 时出错（已忽略）: {e}")
            # 清理完成后设置为 None
            self._dispcal_web_client = None

    @pyqtSlot(str)
    def calibrate_display(self, params_json: str):
        """
        校准显示器（生成 .cal 文件）

        使用 dispcal 进行显示器校准，生成 1D LUT / VCGT。
        这是实现"感知匹配"功能的核心步骤。

        Args:
            params_json: JSON 格式的参数
                - white_point: 白点类型 ("D65", "D50", "D75", "native", "custom")
                - custom_white_x: 自定义白点 x 坐标
                - custom_white_y: 自定义白点 y 坐标
                - gamma: 目标 Gamma (默认 2.2)
                - brightness: 目标亮度 (可选)
                - quality: 校准质量 (l/m/h)
        """
        self.logMessage.emit(f"DEBUG: _patch_window = {self._patch_window is not None}")
        try:
            params = json.loads(params_json)
        except json.JSONDecodeError:
            self.logMessage.emit(i18n.t("参数解析失败"))
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": "参数解析失败"
            }))
            return

        if not self._argyll_controller:
            self.logMessage.emit(i18n.t("Argyll 控制器未初始化"))
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": "Argyll 控制器未初始化"
            }))
            return

        # 解析参数
        white_point_type = params.get("white_point", "D65")
        custom_white_x = params.get("custom_white_x")
        custom_white_y = params.get("custom_white_y")
        gamma = params.get("gamma", 2.2)
        brightness = params.get("brightness")
        quality = params.get("quality", "m")

        # 确定输出路径
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        measurements_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'measurements')
        os.makedirs(measurements_dir, exist_ok=True)
        output_path = os.path.join(measurements_dir, f"calibration_{timestamp}")

        # 获取显示器和仪器索引
        display_index = self._get_patch_display_index()

        # ========== 挂载 Null Profile（dispcal 阶段也需要） ==========
        # 在开始 dispcal 校准前，先挂载 Null Profile 绕过系统色彩管理
        # 确保 dispcal 测量的是显示器原生状态
        if self._lut_controller and self._auto_clear_lut:
            if self._use_null_profile_for_measurement and self._linear_profile_path:
                self.logMessage.emit("[dispcal] 正在挂载线性 ICC Profile（Null Profile）...")
                if self._lut_controller.apply_profile(display_index, self._linear_profile_path):
                    self.logMessage.emit("[dispcal] 线性 ICC Profile 已挂载，输出已切换为原生状态")
                    self._null_profile_applied = True
                else:
                    self.logMessage.emit("[dispcal] 警告: 挂载线性 Profile 失败")
                    self._null_profile_applied = False
            else:
                self.logMessage.emit("[dispcal] 跳过 Null Profile（未启用或线性 Profile 未找到）")

        # ========== 使用正确的仪器端口 ==========
        # 从 ArgyllController 获取已连接的仪器端口，而非硬编码 1
        if self._argyll_controller and hasattr(self._argyll_controller, '_instrument_port'):
            instrument_index = self._argyll_controller._instrument_port or 1
        else:
            instrument_index = 1  # 默认使用第一个仪器

        # ========== 关键：断开 spotread 以释放仪器 ==========
        # dispcal 需要独占访问仪器，如果 spotread 正在运行，会导致 Instrument Access Failed
        was_connected = self._argyll_controller.is_connected() if self._argyll_controller else False
        if was_connected:
            self.logMessage.emit(i18n.t("断开 spotread 以释放仪器供 dispcal 使用..."))
            self._argyll_controller.disconnect()
            # 等待仪器端口释放
            time.sleep(1.0)

        # 解析白点参数
        white_temp = None
        wp_x = None
        wp_y = None

        if white_point_type == "custom" and custom_white_x and custom_white_y:
            # 自定义白点坐标（感知匹配）
            wp_x = float(custom_white_x)
            wp_y = float(custom_white_y)
            self.logMessage.emit(f"感知匹配模式: 目标白点 x={wp_x:.4f}, y={wp_y:.4f}")
        elif white_point_type == "D65":
            white_temp = 6500
        elif white_point_type == "D50":
            white_temp = 5000
        elif white_point_type == "D75":
            white_temp = 7500
        # native 白点不设置参数

        # ========== 获取测量窗口位置参数 ==========
        # 让 dispcal 的测试窗口与用户自定义测量窗口位置一致
        window_position = self._get_dispcal_window_position()

        self.logMessage.emit(f"开始显示器校准...")
        self.logMessage.emit(f"目标 Gamma: {gamma}")
        if white_temp:
            self.logMessage.emit(f"目标色温: {white_temp}K")
        if brightness:
            self.logMessage.emit(f"目标亮度: {brightness} cd/m²")

        # 在后台线程中执行校准
        thread = threading.Thread(
            target=self._execute_dispcal_thread,
            args=(output_path, wp_x, wp_y, white_temp, gamma, brightness,
                  display_index, instrument_index, quality, was_connected, window_position),
            name="backend-dispcal-thread",
            daemon=True
        )
        thread.start()

    def _execute_dispcal_thread(self, output_path: str,
                                  white_point_x: Optional[float],
                                  white_point_y: Optional[float],
                                  white_temp: Optional[int],
                                  gamma: float,
                                  brightness: Optional[float],
                                  display_index: int,
                                  instrument_index: int,
                                  quality: str,
                                  was_connected: bool,
                                  window_position: Optional[str]):
        """
        在后台线程中执行 dispcal 命令（使用 Web Server 模式）

        Args:
            was_connected: 执行前 spotread 是否已连接，完成后需要恢复
        """
        try:
            # ========== 进度回调函数 ==========
            def on_progress(current, total, message):
                progress_data = {
                    "current": current,
                    "total": total,
                    "message": message,
                    "stage": "dispcal"
                }
                # Qt 信号是线程安全的，可以直接从后台线程发射
                self.calibrationProgress.emit(json.dumps(progress_data))

            # ========== 色块变化回调函数 ==========
            def on_patch_change(r, g, b, name):
                # Qt 信号是线程安全的，可以直接从后台线程发射
                self.patchColorChanged.emit(json.dumps({
                    "r": r, "g": g, "b": b
                }))
                self.measurementStarted.emit(name)

            # ========== 启动 DispcalWebClient ==========
            # dispcal 需要客户端连接后才会输出 "Created web server" 消息
            # 所以在仪器初始化完成后就立即启动客户端

            def on_instrument_ready():
                """仪器初始化完成，立即启动 DispcalWebClient"""
                self.logMessage.emit(">>> on_instrument_ready 回调被调用")
                # 使用信号在主线程中调用槽方法（避免在后台线程中使用 QTimer.singleShot）
                self._startDispcalWebClientSignal.emit()

            # ========== Web Server URL 回调（可选） ==========
            def on_web_server_url(url: str):
                """dispcal 报告实际监听的 URL，用于更新日志"""
                # Qt 信号是线程安全的，可以直接从后台线程发射
                self.logMessage.emit(f"dispcal Web Server 地址: {url}")
                # URL 回调主要用于日志记录，客户端已经通过 on_instrument_ready 启动
                if self._dispcal_web_client:
                    # 如果需要，可以更新客户端的 URL
                    self._dispcal_web_client.set_server_url(url)

            success = self._argyll_controller.calibrate_display(
                output_path=output_path,
                white_point_x=white_point_x,
                white_point_y=white_point_y,
                white_temp=white_temp,
                gamma=gamma,
                brightness=brightness,
                display_index=display_index,
                instrument_index=instrument_index,
                quality=quality,
                use_web_server=True,
                web_port=9292,
                on_progress=on_progress,
                on_patch_change=on_patch_change,
                on_instrument_ready=on_instrument_ready,
                on_web_server_url=on_web_server_url
            )

            self.logMessage.emit(f">>> calibrate_display 返回: success={success}")

            # ========== 清理 DispcalWebClient ==========
            if self._dispcal_web_client:
                self.logMessage.emit(f">>> 清理 DispcalWebClient...")
                try:
                    # 注意：disconnect() 中的 QTimer.stop() 必须在主线程中调用
                    # 如果从后台线程调用会触发 "QObject::killTimer" 警告
                    # 先停止轮询，然后使用信号在主线程中执行清理
                    self._dispcal_web_client._active = False
                    # 使用信号在主线程中执行清理（不在这里设置 None）
                    self._cleanupDispcalWebClientSignal.emit()
                except Exception as e:
                    self.logMessage.emit(f">>> 清理 DispcalWebClient 时出错（已忽略）: {e}")
                    # 即使出错也设置为 None
                    self._dispcal_web_client = None
            else:
                self.logMessage.emit(f">>> _dispcal_web_client 已经是 None，跳过清理")

            if success:
                self.logMessage.emit(f">>> 进入 success 分支")
                cal_path = output_path + ".cal"
                self.logMessage.emit(f"显示器校准完成: {cal_path}")

                # 存储校准文件路径，供后续测量使用
                self._current_cal_path = cal_path

                # ========== 先发送 fileCreated 信号，通知前端校准完成 ==========
                # 必须在阻塞操作之前发送信号
                file_created_json = json.dumps({
                    "success": True,
                    "type": "calibration",
                    "cal_path": cal_path,
                    "message": f"校准文件已生成: {cal_path}"
                })
                self.logMessage.emit(f">>> 发送 fileCreated 信号: {file_created_json}")
                self.fileCreated.emit(file_created_json)

                # ========== 异步处理后续操作 ==========
                # 使用内部信号跨线程安全地调用后续操作
                # 不能在后台线程中使用 QTimer.singleShot
                self._finishCalibrationSignal.emit(cal_path, display_index, was_connected)
            else:
                error_msg = self._argyll_controller.get_error_message()
                self.fileCreated.emit(json.dumps({
                    "success": False,
                    "message": error_msg
                }))

                # 即使失败也需要尝试重新连接
                if was_connected:
                    # 使用信号在主线程中执行重连
                    self._reconnectAfterCalFailedSignal.emit()

        except Exception as e:
            # 使用信号在主线程中发送文件创建结果
            self._fileCreatedSignal.emit(json.dumps({
                "success": False,
                "message": str(e)
            }))

            # 异常情况也需要尝试重新连接
            if was_connected:
                self.logMessage.emit(i18n.t("校准异常，尝试重新连接 spotread..."))
                time.sleep(0.5)
                try:
                    self._argyll_controller.connect()
                except Exception:
                    pass

    def _finish_calibration_after_file_created(self, cal_path, display_index, was_connected):
        """文件创建信号发送后，异步完成后续操作"""
        # ========== 加载校准文件到显卡 LUT ==========
        self.logMessage.emit(i18n.t("正在加载校准文件到显卡 LUT..."))
        display_index_for_cal = display_index
        cal_load_success = self._argyll_controller.load_calibration(cal_path, display_index_for_cal)
        if cal_load_success:
            self.logMessage.emit(i18n.t("校准文件已加载到显卡 LUT，校准生效"))
        else:
            self.logMessage.emit(f"警告: 加载校准文件失败: {self._argyll_controller.get_error_message()}")

        # ========== 不再自动重连 spotread ==========
        # 改为让前端控制流程：前端收到 fileCreated 信号后会调用 load_cal_file
        # load_cal_file 完成后会自动开始测量，测量时会自动检查并连接 spotread
        # 这样可以避免时序竞争问题
        self.logMessage.emit(i18n.t("校准文件已加载，等待前端加载 cal 文件并开始测量..."))

        # ========== 自动保存测量数据 ==========
        self._auto_save_measurement_session("dispcal")

    def _do_reconnect_after_calibration(self):
        """校准后异步重连 spotread"""
        if not self._argyll_controller:
            return

        reconnect_success = self._argyll_controller.connect()
        if reconnect_success:
            self.logMessage.emit(i18n.t("spotread 已重新连接"))
            # 发送探头状态信号，更新前端 UI
            current_probe_type = self._argyll_controller._probe_type.value
            self.probeStatusChanged.emit(json.dumps({
                "connected": True,
                "status": "connected",
                "probeType": current_probe_type
            }))
        else:
            self.logMessage.emit(f"spotread 重连失败: {self._argyll_controller.get_error_message()}")

    def _do_reconnect_after_calibration_failed(self):
        """校准失败后异步重连 spotread"""
        if not self._argyll_controller:
            return

        self.logMessage.emit(i18n.t("校准失败，尝试重新连接 spotread..."))
        reconnect_success = self._argyll_controller.connect()
        if reconnect_success:
            self.logMessage.emit(i18n.t("spotread 已重新连接"))
            # 发送探头状态信号
            current_probe_type = self._argyll_controller._probe_type.value
            self.probeStatusChanged.emit(json.dumps({
                "connected": True,
                "status": "connected",
                "probeType": current_probe_type
            }))
        else:
            self.logMessage.emit(f"spotread 重连失败: {self._argyll_controller.get_error_message()}")

    @pyqtSlot()
    def load_calibration(self):
        """
        加载校准文件到显卡 LUT
        """
        if not self._argyll_controller:
            self.logMessage.emit(i18n.t("Argyll 控制器未初始化"))
            return

        cal_path = getattr(self, '_current_cal_path', None)
        if not cal_path or not os.path.exists(cal_path):
            self.logMessage.emit(i18n.t("没有可用的校准文件"))
            return

        display_index = self._get_patch_display_index()
        success = self._argyll_controller.load_calibration(cal_path, display_index)

        if success:
            self.logMessage.emit(f"校准已加载到显卡 LUT")
        else:
            self.logMessage.emit(i18n.t("加载校准失败"))

    @pyqtSlot(str)
    def load_cal_file(self, cal_path: str):
        """
        加载指定的 .cal 校准文件到显卡 LUT

        由前端调用，用于 ICC 模式下加载已有的校准文件，
        加载完成后发送 calFileLoaded 信号通知前端。

        Args:
            cal_path: .cal 校准文件的完整路径
        """
        if not self._argyll_controller:
            self.logMessage.emit(i18n.t("Argyll 控制器未初始化"))
            self.calFileLoaded.emit(json.dumps({
                "success": False,
                "message": "Argyll 控制器未初始化"
            }))
            return

        # 验证文件存在
        if not cal_path or not os.path.exists(cal_path):
            self.logMessage.emit(f"校准文件不存在: {cal_path}")
            self.calFileLoaded.emit(json.dumps({
                "success": False,
                "message": f"校准文件不存在: {cal_path}"
            }))
            return

        # 保存当前校准路径（供后续使用）
        self._current_cal_path = cal_path

        # 获取显示器索引
        display_index = self._get_patch_display_index()

        self.logMessage.emit(f"正在加载校准文件: {cal_path}")

        # ========== 关键修复：先恢复系统 Profile LUT，再加载 cal 文件 ==========
        # 问题：循环测量开始时 clear_lut() 清除了显卡LUT，导致系统处于"已清除但无Profile关联"状态
        # 解决方案：加载 cal 前先恢复系统 Profile LUT，确保 dispwin 能正确识别系统 Profile
        if self._lut_controller:
            self.logMessage.emit(i18n.t("加载 cal 文件前先恢复系统 Profile LUT..."))
            if self._lut_controller.load_system_profile_lut(display_index):
                self.logMessage.emit(i18n.t("系统 Profile LUT 已恢复"))
                # 增加延迟让系统完全稳定
                time.sleep(0.5)
            else:
                self.logMessage.emit(i18n.t("警告: 恢复系统 LUT 失败，尝试直接加载 cal 文件"))

        # ========== 如果启用 Null Profile 方案，先挂载 Null Profile ==========
        if self._lut_controller and self._use_null_profile_for_measurement and self._linear_profile_path:
            self.logMessage.emit(i18n.t("加载 cal 文件前先挂载 Null Profile (Topos_Linear_Native.icc)..."))
            if self._lut_controller.apply_profile(display_index, self._linear_profile_path):
                self.logMessage.emit(i18n.t("Null Profile 已挂载"))
                self._null_profile_applied = True
                # 增加延迟让系统完全稳定
                time.sleep(0.5)
            else:
                self.logMessage.emit(i18n.t("警告: 挂载 Null Profile 失败，尝试直接加载 cal 文件"))

        # 调用 ArgyllController 加载校准到显卡 LUT
        success = self._argyll_controller.load_calibration(cal_path, display_index)

        if success:
            self.logMessage.emit(f"校准文件已加载到显卡 LUT")
            # 增加延迟让显卡 LUT 完全生效
            time.sleep(0.5)
            self.logMessage.emit(f"校准文件已加载到显卡 LUT")
            self.calFileLoaded.emit(json.dumps({
                "success": True,
                "cal_path": cal_path,
                "message": "校准文件已加载"
            }))
        else:
            error_msg = self._argyll_controller.get_error_message()
            self.logMessage.emit(f"加载校准文件失败: {error_msg}")
            self.calFileLoaded.emit(json.dumps({
                "success": False,
                "message": error_msg
            }))

    @pyqtSlot()
    def clear_calibration(self):
        """
        清除显卡 LUT（恢复默认）
        """
        if not self._argyll_controller:
            self.logMessage.emit(i18n.t("Argyll 控制器未初始化"))
            return

        display_index = self._get_patch_display_index()
        success = self._argyll_controller.clear_calibration(display_index)

        if success:
            self.logMessage.emit(i18n.t("校准已清除，显卡 LUT 恢复默认"))
        else:
            self.logMessage.emit(i18n.t("清除校准失败"))

    @pyqtSlot(str)
    def create_icc_file(self, params_json: str):
        """
        创建 ICC 文件

        Args:
            params_json: JSON 格式的参数
                - cal_path: 可选，校准文件路径
                - ti3_path: 可选，TI3 测量数据路径
                - json_path: 可选，JSON 测量数据路径
        """
        from pathlib import Path

        try:
            params = json.loads(params_json)
        except json.JSONDecodeError:
            self.logMessage.emit(i18n.t("参数解析失败"))
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": "参数解析失败"
            }))
            return

        # 检查是否使用外部校准数据
        ti3_path = params.get("ti3_path")
        json_path = params.get("json_path")
        use_external_calibration = bool(ti3_path or json_path)

        if use_external_calibration:
            # 使用外部校准数据
            if ti3_path and Path(ti3_path).exists():
                self.logMessage.emit(f"使用校准数据: {Path(ti3_path).parent.name}/{Path(ti3_path).name}")
            elif json_path and Path(json_path).exists():
                # 从 JSON 加载数据
                try:
                    # 直接从完整路径读取 JSON 文件
                    from .data_storage import MeasurementData
                    with open(json_path, 'r', encoding='utf-8') as f:
                        json_str = f.read()
                    temp_measurement = MeasurementData()
                    temp_measurement.from_json(json_str)
                    if not temp_measurement.is_valid():
                        raise ValueError("测量数据无效")

                    # 使用临时测量数据
                    original_measurement = self._current_measurement
                    self._current_measurement = temp_measurement
                    self.logMessage.emit(f"从 JSON 加载校准数据: {Path(json_path).name}")
                except Exception as e:
                    self.logMessage.emit(f"加载 JSON 数据失败: {str(e)}")
                    self.fileCreated.emit(json.dumps({
                        "success": False,
                        "message": f"加载 JSON 数据失败: {str(e)}"
                    }))
                    return
            else:
                self.logMessage.emit(i18n.t("指定的校准数据文件不存在"))
                self.fileCreated.emit(json.dumps({
                    "success": False,
                    "message": "指定的校准数据文件不存在"
                }))
                return
        elif not self._current_measurement.is_valid():
            self.logMessage.emit(i18n.t("没有有效的测量数据"))
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": "没有有效的测量数据"
            }))
            return

        format_type = params.get("format", "icc")
        file_path = params.get("file_path", "")
        file_name = params.get("file_name", "display_profile")

        if file_path:
            full_path = Path(file_path)
        else:
            # 默认保存到项目的 measurements 目录
            project_measurements_dir = Path(__file__).parent.parent / "measurements"
            project_measurements_dir.mkdir(parents=True, exist_ok=True)
            extension = ".icc" if format_type == "icc" else ".ti3"
            full_path = project_measurements_dir / (file_name + extension)

        if format_type == "ti3":
            # 如果有外部 TI3，直接复制
            if ti3_path and Path(ti3_path).exists():
                import shutil
                shutil.copy2(ti3_path, full_path)
                self.logMessage.emit(f"TI3 文件已复制: {full_path}")
                self.fileCreated.emit(json.dumps({
                    "success": True,
                    "filepath": str(full_path),
                    "format": "TI3"
                }))
            else:
                success = self._cgats_exporter.export_ti3(self._current_measurement, str(full_path))
                if success:
                    self.logMessage.emit(f"TI3 文件已创建: {full_path}")
                    self.fileCreated.emit(json.dumps({
                        "success": True,
                        "filepath": str(full_path),
                        "format": "TI3"
                    }))
                else:
                    self.logMessage.emit(i18n.t("TI3 文件创建失败"))
                    self.fileCreated.emit(json.dumps({
                        "success": False,
                        "message": "TI3 文件创建失败"
                    }))
        else:
            success = self._create_icc_profile(full_path, params)
            if success:
                self.logMessage.emit(f"ICC 文件已创建: {full_path}")

                # ========== 应用 ICC Profile 到系统 ==========
                # 如果用户勾选了"应用ICC色彩描述文件"选项
                apply_profile = params.get("apply_profile", False)
                if apply_profile:
                    display_index = self._get_patch_display_index()
                    self.logMessage.emit(i18n.t("正在安装并应用 ICC Profile 到系统..."))
                    # 清除之前的错误信息
                    self._lut_controller.clear_last_error()
                    if self._lut_controller.apply_profile(display_index, str(full_path)):
                        self.logMessage.emit(f"ICC Profile 已成功安装并应用到系统")
                        self.logMessage.emit(i18n.t("校准效果已生效"))
                        self.fileCreated.emit(json.dumps({
                            "success": True,
                            "filepath": str(full_path),
                            "format": "ICC",
                            "applied": True
                        }))
                    else:
                        # 获取详细的错误信息
                        error_type = self._lut_controller.get_last_error_type()
                        error_message = self._lut_controller.get_last_error()

                        # 如果是权限错误，使用友好提示
                        if error_type == "permission":
                            self.logMessage.emit(i18n.t("警告: ICC Profile 安装失败 - 权限不足"))
                            self.fileCreated.emit(json.dumps({
                                "success": True,
                                "filepath": str(full_path),
                                "format": "ICC",
                                "applied": False,
                                "error_type": "permission",
                                "message": error_message
                            }))
                        else:
                            # 其他错误
                            self.logMessage.emit(f"警告: ICC Profile 安装失败 - {error_message or '未知错误'}")
                            self.fileCreated.emit(json.dumps({
                                "success": True,
                                "filepath": str(full_path),
                                "format": "ICC",
                                "applied": False,
                                "error_type": error_type or "other",
                                "message": error_message or "ICC 文件已创建，但安装失败"
                            }))
                else:
                    self.fileCreated.emit(json.dumps({
                        "success": True,
                        "filepath": str(full_path),
                        "format": "ICC",
                        "applied": False
                    }))
            else:
                self.logMessage.emit(i18n.t("ICC 文件创建失败"))
                self.fileCreated.emit(json.dumps({
                    "success": False,
                    "message": "ICC 文件创建失败"
                }))

        # 恢复原始测量数据
        if use_external_calibration and json_path and 'original_measurement' in locals():
            self._current_measurement = original_measurement

    def _create_icc_profile(self, filepath, params: dict) -> bool:
        """
        使用 ArgyllCMS 创建 ICC Profile

        注意：colprof 是描述性工具，生成的是显示器当前状态的色彩描述文件。
        如果需要强制显示器输出特定白点，请先使用"显示器校准"功能（dispcal）。

        Args:
            filepath: 输出 ICC 文件路径
            params: 参数字典
                - ti3_path: 可选，外部 TI3 文件路径
                - cal_path: 可选，校准文件路径
        """
        from pathlib import Path
        import subprocess
        import shutil

        argyll_path = self._argyll_controller._argyll_path if self._argyll_controller else ""
        if not argyll_path:
            self.logMessage.emit(i18n.t("ArgyllCMS 路径未配置，导出 TI3 格式代替"))
            ti3_path = Path(filepath).with_suffix(".ti3")
            return self._cgats_exporter.export_ti3(self._current_measurement, str(ti3_path))

        # ========== 使用用户指定的输出目录 ==========
        # TI3 和 ICC 文件都在用户指定路径的目录中生成
        output_dir = Path(filepath).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        # TI3 文件使用与 ICC 相同的基础名称
        icc_basename = Path(filepath).stem
        ti3_path = output_dir / f"{icc_basename}.ti3"

        try:
            # 检查是否使用外部 TI3 文件
            external_ti3 = params.get("ti3_path")
            if external_ti3 and Path(external_ti3).exists():
                # 复制外部 TI3 到输出目录
                shutil.copy2(external_ti3, ti3_path)
                self.logMessage.emit(f"使用外部 TI3 文件: {Path(external_ti3).name}")
            else:
                # 从当前测量数据生成 TI3
                if not self._cgats_exporter.export_ti3(self._current_measurement, str(ti3_path)):
                    self.logMessage.emit(i18n.t("导出 TI3 文件失败"))
                    return False
                self.logMessage.emit(f"TI3 文件已保存: {ti3_path}")

            profile_type = params.get("profile_type", "lut")
            quality = params.get("quality", "h")  # 默认 high quality

            # ArgyllCMS 的 colprof 命令使用 -a 参数指定配置类型
            # matrix 对应 'm'，lut 对应 'l'，Lab 对应 'l'
            type_map = {"matrix": "m", "lut": "l", "lab": "l"}
            profile_flag = type_map.get(profile_type, "l")  # 默认使用 Lab

            gamut_mapping = params.get("gamut_mapping", "perceptual")
            # ArgyllCMS 使用 -Z 参数指定默认渲染意图
            mapping_map = {"perceptual": "p", "relative": "r", "saturation": "s", "absolute": "a"}
            mapping_flag = mapping_map.get(gamut_mapping, "p")

            colprof_name = "colprof" if not argyll_path else str(Path(argyll_path) / "colprof")
            # colprof 命令：最后一个参数是输出路径（不含扩展名）
            # 它会在当前目录找同名 .ti3 文件，并生成同名 .icc 文件
            output_base = str(output_dir / icc_basename)
            cmd = [
                colprof_name, "-v", "-q", quality,
                "-a" + profile_flag,   # Profile 类型（连接参数，如 -al）
                "-Z" + mapping_flag,   # 渲染意图（连接参数，如 -Zp）
                "-D", icc_basename,    # Profile 描述名称
            ]

            # 如果提供了自定义白点，使用 -c 参数
            custom_white_x = params.get("custom_white_x")
            custom_white_y = params.get("custom_white_y")
            if custom_white_x is not None and custom_white_y is not None:
                cmd.extend(["-c", f"{custom_white_x},{custom_white_y}"])
                self.logMessage.emit(f"使用自定义白点: {custom_white_x:.4f}, {custom_white_y:.4f}")

            cmd.append(output_base)  # 输出基础路径（不含扩展名）

            self.logMessage.emit(f"执行 colprof: {' '.join(cmd)}")

            # 在 TI3 文件所在目录执行 colprof
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=60, cwd=str(output_dir))

            if result.returncode != 0:
                stderr = result.stderr.strip()
                # 过滤 TTY 相关的错误信息
                if "tcgetattr" not in stderr and "tcsetattr" not in stderr:
                    self.logMessage.emit(f"colprof 执行失败: {stderr}")
                else:
                    self.logMessage.emit(i18n.t("colprof 执行失败"))
                return False

            # colprof 会生成与输出路径同名的 .icc 文件
            generated_icc = Path(output_base + ".icc")
            if generated_icc.exists():
                self.logMessage.emit(f"ICC 文件已创建: {filepath}")
                self.logMessage.emit(f"TI3 文件保存在: {ti3_path}")
                return True
            else:
                self.logMessage.emit(i18n.t("未找到生成的 ICC 文件"))
                return False

        except subprocess.TimeoutExpired:
            self.logMessage.emit(i18n.t("colprof 执行超时"))
            return False
        except Exception as e:
            self.logMessage.emit(f"创建 ICC 文件时发生错误: {str(e)}")
            return False

    @pyqtSlot(str)
    def create_lut_file(self, params_json: str):
        """
        创建 LUT 文件

        Args:
            params_json: JSON 格式的参数
                - cal_path: 可选，校准文件路径
                - ti3_path: 可选，TI3 测量数据路径
                - json_path: 可选，JSON 测量数据路径
        """
        from pathlib import Path

        try:
            params = json.loads(params_json)
        except json.JSONDecodeError:
            self.logMessage.emit(i18n.t("参数解析失败"))
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": "参数解析失败"
            }))
            return

        # 检查是否使用外部校准数据
        ti3_path = params.get("ti3_path")
        json_path = params.get("json_path")
        use_external_calibration = bool(ti3_path or json_path)

        if use_external_calibration:
            # 使用外部校准数据
            if ti3_path and Path(ti3_path).exists():
                self.logMessage.emit(f"使用校准数据: {Path(ti3_path).parent.name}/{Path(ti3_path).name}")
            elif json_path and Path(json_path).exists():
                # 从 JSON 加载数据
                try:
                    # 直接从完整路径读取 JSON 文件
                    from .data_storage import MeasurementData
                    with open(json_path, 'r', encoding='utf-8') as f:
                        json_str = f.read()
                    temp_measurement = MeasurementData()
                    temp_measurement.from_json(json_str)
                    if not temp_measurement.is_valid():
                        raise ValueError("测量数据无效")

                    # 使用临时测量数据
                    original_measurement = self._current_measurement
                    self._current_measurement = temp_measurement
                    self.logMessage.emit(f"从 JSON 加载校准数据: {Path(json_path).name}")
                except Exception as e:
                    self.logMessage.emit(f"加载 JSON 数据失败: {str(e)}")
                    self.fileCreated.emit(json.dumps({
                        "success": False,
                        "message": f"加载 JSON 数据失败: {str(e)}"
                    }))
                    return
            else:
                self.logMessage.emit(i18n.t("指定的校准数据文件不存在"))
                self.fileCreated.emit(json.dumps({
                    "success": False,
                    "message": "指定的校准数据文件不存在"
                }))
                return
        elif not self._current_measurement.is_valid():
            self.logMessage.emit(i18n.t("没有有效的测量数据"))
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": "没有有效的测量数据"
            }))
            return

        file_path = params.get("file_path", "")
        file_name = params.get("file_name", "display_lut")
        format_type = params.get("format", "cube")
        lut_size = int(params.get("lut_size", 33))
        export_method = params.get("export_method", "fast")  # 'fast' 或 'advanced'

        if file_path:
            full_path = Path(file_path)
        else:
            # 默认保存到项目的 measurements 目录
            project_measurements_dir = Path(__file__).parent.parent / "measurements"
            project_measurements_dir.mkdir(parents=True, exist_ok=True)
            extension = "." + format_type.lower()
            full_path = project_measurements_dir / (file_name + extension)

        # 根据导出方法选择不同的处理方式
        if export_method == "advanced":
            # 高级模式：使用 ArgyllCMS 的 collink 生成 3D LUT
            success = self._create_lut_file_advanced(str(full_path), params)
        else:
            # 快速模式：直接从测量数据计算
            success = self._create_lut_file_internal(full_path, params)

        # 恢复原始测量数据
        if use_external_calibration and json_path and 'original_measurement' in locals():
            self._current_measurement = original_measurement

        if success:
            self.logMessage.emit(f"LUT 文件已创建: {full_path}")
            self.fileCreated.emit(json.dumps({
                "success": True,
                "filepath": str(full_path),
                "format": format_type.upper()
            }))
        else:
            self.logMessage.emit(i18n.t("LUT 文件创建失败"))
            self.fileCreated.emit(json.dumps({
                "success": False,
                "message": "LUT 文件创建失败"
            }))

    def _create_lut_file_internal(self, filepath, params: dict) -> bool:
        """
        内部方法：创建 LUT 文件
        """
        from pathlib import Path

        format_type = params.get("format", "cube")
        lut_size = int(params.get("lut_size", 33))
        target_gamma = params.get("target_gamma", "2.2")
        black_lift = float(params.get("black_lift", 0)) / 100.0

        try:
            lut_data = self._generate_lut_data(lut_size, target_gamma, black_lift)

            if lut_data is None:
                self.logMessage.emit(i18n.t("生成 LUT 数据失败"))
                return False

            if format_type == "cube":
                return self._write_cube_file(filepath, lut_data, lut_size)
            elif format_type == "3dl":
                return self._write_3dl_file(filepath, lut_data, lut_size)
            elif format_type == "mga":
                return self._write_mga_file(filepath, lut_data, lut_size)
            elif format_type == "clf":
                return self._write_clf_file(filepath, lut_data, lut_size)
            else:
                return self._write_cube_file(filepath, lut_data, lut_size)

        except Exception as e:
            self.logMessage.emit(f"创建 LUT 文件时发生错误: {str(e)}")
            return False

    def _generate_lut_data(self, size: int, target_gamma: str, black_lift: float):
        """
        生成 LUT 数据
        
        校正 LUT 的核心作用是预补偿显示器的物理偏差。
        例如：实测 Gamma 2.2，目标 Gamma 2.6，显示器天然 2.2 会让画面比 2.6 亮，
        因此 LUT 必须把输入信号压暗（指数需大于 1，即 2.6 / 2.2 = 1.18）。
        """
        import numpy as np

        measured_gamma = self._analyzer.calculate_gamma() or 2.2

        lut_data = np.zeros((size ** 3, 3), dtype=np.float64)  # 使用 float64 确保最高精度

        for i in range(size):
            for j in range(size):
                for k in range(size):
                    r_in = i / (size - 1)
                    g_in = j / (size - 1)
                    b_in = k / (size - 1)

                    if target_gamma == "sRGB":
                        # sRGB 曲线：先把非线性信号转换为线性光 (Target EOTF)
                        def srgb_gamma(v):
                            if v <= 0.04045:
                                return v / 12.92
                            else:
                                return ((v + 0.055) / 1.055) ** 2.4
                        
                        # 1. 把非线性信号转换为线性光 (Target EOTF)
                        L_target_r = srgb_gamma(r_in)
                        L_target_g = srgb_gamma(g_in)
                        L_target_b = srgb_gamma(b_in)
                        
                        # 2. 对线性光施加显示器实际物理 Gamma 的逆补偿 (Measured Inverse EOTF)
                        # 这样当显示器施加 2.2 的物理 Gamma 后，最终输出才是正确的线性光
                        r_out = L_target_r ** (1.0 / measured_gamma)
                        g_out = L_target_g ** (1.0 / measured_gamma)
                        b_out = L_target_b ** (1.0 / measured_gamma)
                    else:
                        target_g = float(target_gamma)
                        # 正确的影视级 LUT 预畸变公式：(Target / Measured)
                        # 例如：目标 2.6 / 实测 2.2 = 1.18（压暗信号）
                        gamma_ratio = target_g / measured_gamma
                        
                        r_out = r_in ** gamma_ratio
                        g_out = g_in ** gamma_ratio
                        b_out = b_in ** gamma_ratio

                    # Black lift 处理
                    if black_lift > 0:
                        r_out = r_out * (1 - black_lift) + black_lift
                        g_out = g_out * (1 - black_lift) + black_lift
                        b_out = b_out * (1 - black_lift) + black_lift

                    idx = i * size * size + j * size + k
                    lut_data[idx] = [r_out, g_out, b_out]

        return lut_data

    def _write_cube_file(self, filepath, lut_data, size: int) -> bool:
        """
        写入 CUBE 格式 LUT 文件
        """
        try:
            with open(filepath, 'w') as f:
                f.write(f"TITLE \"Topos Calibrator Display LUT\"\n")
                f.write(f"# Created by Topos Calibrator\n")
                f.write(f"LUT_3D_SIZE {size}\n\n")
                for row in lut_data:
                    f.write(f"{row[0]:.6f} {row[1]:.6f} {row[2]:.6f}\n")
            return True
        except Exception as e:
            self.logMessage.emit(f"写入 CUBE 文件失败: {str(e)}")
            return False

    def _write_3dl_file(self, filepath, lut_data, size: int) -> bool:
        """
        写入 3DL 格式 LUT 文件
        """
        try:
            bit_depth = 10
            max_val = (1 << bit_depth) - 1

            with open(filepath, 'w') as f:
                f.write(f"# 3DL LUT created by Topos Calibrator\n\n")
                for row in lut_data:
                    r = int(row[0] * max_val)
                    g = int(row[1] * max_val)
                    b = int(row[2] * max_val)
                    f.write(f"{r} {g} {b}\n")
            return True
        except Exception as e:
            self.logMessage.emit(f"写入 3DL 文件失败: {str(e)}")
            return False

    def _write_mga_file(self, filepath, lut_data, size: int) -> bool:
        """
        写入 MGA 格式 LUT 文件
        """
        try:
            with open(filepath, 'w') as f:
                f.write(f"MGA_LUT\nVERSION 1.0\nSIZE {size}\n\n")
                for row in lut_data:
                    f.write(f"{row[0]:.6f} {row[1]:.6f} {row[2]:.6f}\n")
            return True
        except Exception as e:
            self.logMessage.emit(f"写入 MGA 文件失败: {str(e)}")
            return False

    def _write_clf_file(self, filepath, lut_data, size: int) -> bool:
        """
        写入 CLF (Common LUT Format) 文件
        """
        try:
            with open(filepath, 'w') as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write('<ProcessList version="1.0">\n')
                f.write(f'  <LUT3D name="Topos Calibrator Display LUT" size="{size}">\n')
                f.write('    <Array dimension="3">\n')
                for row in lut_data:
                    f.write(f'      {row[0]:.6f} {row[1]:.6f} {row[2]:.6f}\n')
                f.write('    </Array>\n')
                f.write('  </LUT3D>\n')
                f.write('</ProcessList>\n')
            return True
        except Exception as e:
            self.logMessage.emit(f"写入 CLF 文件失败: {str(e)}")
            return False

    def _create_lut_file_advanced(self, filepath: str, params: dict) -> bool:
        """
        高级模式：使用 ArgyllCMS 的 collink 生成 3D LUT

        流程：
        1. 导出 TI3 文件（CTI3 格式）
        2. 使用 colprof 生成 ICC Profile
        3. 使用 collink 生成 3D LUT

        Args:
            filepath: 输出 LUT 文件路径
            params: 参数字典
                - source_gamut: 源色域 (Rec709/P3/Rec2020/sRGB)
                - rendering_intent: 渲染意图 (r/p/s/a)
                - use_bpc: 是否使用黑场补偿
        """
        from pathlib import Path
        import subprocess
        import shutil

        argyll_path = self._argyll_controller._argyll_path if self._argyll_controller else ""
        if not argyll_path:
            self.logMessage.emit(i18n.t("高级模式需要 ArgyllCMS，请配置路径"))
            return False

        try:
            # 准备工作目录
            output_dir = Path(filepath).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            base_name = Path(filepath).stem

            # 步骤 1: 导出 TI3 文件
            self.logMessage.emit(i18n.t("步骤 1/3: 导出测量数据为 TI3 格式..."))
            ti3_path = output_dir / f"{base_name}.ti3"

            if not self._cgats_exporter.export_ti3(self._current_measurement, str(ti3_path)):
                self.logMessage.emit(i18n.t("导出 TI3 文件失败"))
                return False
            self.logMessage.emit(f"TI3 文件已创建: {ti3_path}")

            # 步骤 2: 生成 ICC Profile
            self.logMessage.emit(i18n.t("步骤 2/3: 生成 ICC Profile..."))
            icc_path = output_dir / f"{base_name}.icc"

            colprof_name = str(Path(argyll_path) / "colprof")
            output_base = str(output_dir / base_name)

            cmd_colprof = [
                colprof_name, "-v", "-qm",
                "-al",  # Lab LUT
                "-D", base_name,
                output_base
            ]

            self.logMessage.emit(f"执行: {' '.join(cmd_colprof)}")

            result = subprocess.run(cmd_colprof, capture_output=True, text=True,
                                    timeout=120, cwd=str(output_dir))

            if result.returncode != 0:
                stderr = result.stderr.strip()
                if "tcgetattr" not in stderr and "tcsetattr" not in stderr:
                    self.logMessage.emit(f"colprof 失败: {stderr}")
                else:
                    self.logMessage.emit(i18n.t("colprof 执行失败"))
                return False

            if not Path(icc_path).exists():
                self.logMessage.emit(i18n.t("ICC 文件未生成"))
                return False

            self.logMessage.emit(f"ICC Profile 已创建: {icc_path}")

            # 步骤 3: 使用 collink 生成 3D LUT
            self.logMessage.emit(i18n.t("步骤 3/3: 使用 collink 生成 3D LUT..."))

            source_gamut = params.get("source_gamut", "Rec709")
            rendering_intent = params.get("rendering_intent", "r")
            use_bpc = params.get("use_bpc", True)
            lut_size = int(params.get("lut_size", 33))

            # 映射源色域到 ArgyllCMS ref 目录下的 ICC 文件
            source_icc_map = {
                "Rec709": "Rec709.icm",
                "P3": "DisplayP3.icm",
                "Rec2020": "Rec2020.icm",
                "sRGB": "sRGB.icm"
            }
            source_icc_file = source_icc_map.get(source_gamut, "Rec709.icm")
            source_icc_path = str(Path(argyll_path) / "ref" / source_icc_file)

            if not Path(source_icc_path).exists():
                self.logMessage.emit(f"源 ICC 文件不存在: {source_icc_path}")
                return False

            # 输出的 linked profile 路径
            # collink 会生成 linked.icc 和 linked.cube
            linked_base = output_dir / f"{base_name}_linked"

            collink_name = str(Path(argyll_path) / "collink")

            # collink 命令格式：
            # collink [options] srcprofile dstprofile linkedprofile
            # -3 c - 创建额外的 .cube 文件
            # -q m - 质量（Medium）
            # -r size - 覆盖 CLUT 分辨率
            # -i in_intent -o out_intent - 渲染意图（简单模式）
            cmd_collink = [
                collink_name,
                "-v",
                "-q" + params.get("quality", "h"),  # 质量从参数获取，默认 high
                "-r", str(lut_size),  # LUT 尺寸（CLUT 分辨率）
                "-i" + rendering_intent,  # 输入渲染意图
                "-o" + rendering_intent,  # 输出渲染意图
            ]

            # 黑场补偿（仅用于相对色度）
            if use_bpc and rendering_intent == 'r':
                cmd_collink.append("-b")

            # 添加 3D LUT 输出选项和 profile 参数
            cmd_collink.extend([
                "-3", "c",  # 创建 .cube 格式的 3D LUT
                source_icc_path,  # 源 ICC profile
                str(icc_path),  # 目标 ICC Profile（显示器）
                str(linked_base),  # 输出 profile 基础路径
            ])

            self.logMessage.emit(f"执行: {' '.join(cmd_collink)}")

            result = subprocess.run(cmd_collink, capture_output=True, text=True,
                                    timeout=300, cwd=str(output_dir))

            if result.returncode != 0:
                stderr = result.stderr.strip()
                if "tcgetattr" not in stderr and "tcsetattr" not in stderr:
                    self.logMessage.emit(f"collink 失败: {stderr}")
                else:
                    self.logMessage.emit(i18n.t("collink 执行失败"))
                return False

            # collink 生成的 .cube 文件名是 linked_base + ".cube"
            generated_cube = linked_base.with_suffix(".cube")
            if not generated_cube.exists():
                self.logMessage.emit(i18n.t("collink 执行成功但未生成 .cube 文件"))
                return False

            # 将生成的 .cube 移动到用户指定的最终位置
            if str(generated_cube) != filepath:
                shutil.move(str(generated_cube), filepath)

            # 清理中间文件
            try:
                if Path(ti3_path).exists():
                    Path(ti3_path).unlink()
                if Path(icc_path).exists():
                    Path(icc_path).unlink()
                # 清理 linked.icc（如果存在）
                linked_icc = linked_base.with_suffix(".icc")
                if linked_icc.exists():
                    linked_icc.unlink()
            except:
                pass

            self.logMessage.emit(f"高级 3D LUT 已创建: {filepath}")
            return True

        except subprocess.TimeoutExpired:
            self.logMessage.emit(i18n.t("collink 执行超时"))
            return False
        except Exception as e:
            self.logMessage.emit(f"高级 LUT 创建失败: {str(e)}")
            return False

    # ========== CCMX 矩阵制作 ==========

    @pyqtSlot(str)
    def generate_ccmx(self, json_data: str):
        """
        生成 CCMX 校正矩阵文件

        Args:
            json_data: JSON 字符串，包含 ref (基准探头数据) 和 target (目标探头数据)
                      格式: {"ref": {"white": {...}, "red": {...}, ...}, "target": {...}}
        """
        try:
            data = json.loads(json_data)
            ref_data = data.get('ref', {})
            target_data = data.get('target', {})

            if not ref_data or not target_data:
                self.logMessage.emit(i18n.t("CCMX 生成失败: 缺少基准或目标探头数据"))
                return

            self.logMessage.emit(i18n.t("开始生成 CCMX 校正矩阵..."))

            # 使用项目的 measurements 目录存放 ti3 文件（永久保存）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            measurements_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'measurements')
            os.makedirs(measurements_dir, exist_ok=True)
            ref_ti3_path = os.path.join(measurements_dir, f"ref_{timestamp}.ti3")
            target_ti3_path = os.path.join(measurements_dir, f"target_{timestamp}.ti3")

            # 将 ref_data 转换为 MeasurementData 对象并导出 ti3
            ref_measurement = self._convert_gamut_to_measurement(ref_data)
            if not self._cgats_exporter.export_ti3(ref_measurement, ref_ti3_path):
                self.logMessage.emit(i18n.t("CCMX 生成失败: 导出基准 ti3 文件失败"))
                return

            # 将 target_data 转换为 MeasurementData 对象并导出 ti3
            target_measurement = self._convert_gamut_to_measurement(target_data)
            if not self._cgats_exporter.export_ti3(target_measurement, target_ti3_path):
                self.logMessage.emit(i18n.t("CCMX 生成失败: 导出目标 ti3 文件失败"))
                return

            self.logMessage.emit(f"ti3 原始数据已保存至 measurements 目录")

            # 生成带时间戳的输出文件名
            output_ccmx_path = os.path.join(self._corrections_dir, f'custom_matrix_{timestamp}.ccmx')
            display_tech = self._current_display_type.value if hasattr(self._current_display_type, 'value') else 'l'
            success = self._argyll_controller.make_ccmx(
                ref_ti3_path=ref_ti3_path,
                target_ti3_path=target_ti3_path,
                output_ccmx_path=output_ccmx_path,
                display_tech=display_tech
            )

            # 失败时输出排查命令
            if not success:
                self.logMessage.emit(f"ti3 文件位置:")
                self.logMessage.emit(f"  ref: {ref_ti3_path}")
                self.logMessage.emit(f"  target: {target_ti3_path}")
                # 获取 ccxxmake 路径
                ccxxmake_path = self._argyll_controller._argyll_path
                if ccxxmake_path:
                    ccxxmake_cmd = os.path.join(ccxxmake_path, "ccxxmake")
                else:
                    ccxxmake_cmd = "ccxxmake"
                # 路径含空格时需用双引号包裹
                debug_cmd = f'"{ccxxmake_cmd}" -v -t {display_tech} "{ref_ti3_path}" "{target_ti3_path}" "{output_ccmx_path}"'
                self.logMessage.emit(f"排查命令: {debug_cmd}")

            if success:
                self.logMessage.emit(f"✓ CCMX 校正文件已保存至: {output_ccmx_path}")
                self.logMessage.emit(f"校正文件已保存至 corrections 目录")
            else:
                self.logMessage.emit(i18n.t("CCMX 生成失败: ccxxmake 执行失败"))

        except json.JSONDecodeError as e:
            self.logMessage.emit(f"CCMX 生成失败: JSON 解析错误 - {e}")
        except Exception as e:
            self.logMessage.emit(f"CCMX 生成失败: {e}")

    def _convert_gamut_to_measurement(self, gamut_data: dict) -> 'MeasurementData':
        """
        将前端传来的 gamut 数据转换为 MeasurementData 对象

        Args:
            gamut_data: 格式为 {"red": {...}, "green": {...}, "blue": {...}, "white": {...}, "black": {...}, "probe": "..."}

        Returns:
            MeasurementData 对象
        """
        from .data_storage import MeasurementData

        measurement = MeasurementData()

        # 设置 probe metadata（用于 TI3 文件的 TARGET_INSTRUMENT）
        probe_name = gamut_data.get('probe', 'Unknown')
        if probe_name == 'Unknown':
            # 如果数据中没有 probe，使用当前探头类型
            probe_name = self._argyll_controller._probe_type.value if hasattr(self._argyll_controller, '_probe_type') else 'Unknown'
        measurement.set_probe(probe_name)

        # 色块名称映射
        name_mapping = {
            'red': '红',
            'green': '绿',
            'blue': '蓝',
            'white': '白',
            'black': '黑'
        }

        rgb_mapping = {
            'red': (255, 0, 0),
            'green': (0, 255, 0),
            'blue': (0, 0, 255),
            'white': (255, 255, 255),
            'black': (0, 0, 0)
        }

        for key, color_name in name_mapping.items():
            if key in gamut_data and gamut_data[key]:
                patch_data = gamut_data[key]
                rgb = rgb_mapping[key]

                # 提取 xyY 数据
                if 'x' in patch_data and 'y' in patch_data and 'Y' in patch_data:
                    x = patch_data['x']
                    y = patch_data['y']
                    Y = patch_data['Y']

                    measurement.update_gamut_measurement(color_name, rgb, x, y, Y)

        return measurement

    @pyqtSlot(str, str)
    def generate_ccmx_from_measurements(self, ref_id: str, target_id: str):
        """
        从历史测量数据生成 CCMX 校正矩阵文件

        Args:
            ref_id: 分光仪（基准探头）测量数据ID
            target_id: 度计（目标探头）测量数据ID
        """
        try:
            # 加载测量数据
            ref_measurement = self._data_storage.load_measurement(ref_id)
            target_measurement = self._data_storage.load_measurement(target_id)

            if not ref_measurement:
                self.logMessage.emit(f"CCMX 生成失败: 无法加载基准测量数据 {ref_id}")
                return

            if not target_measurement:
                self.logMessage.emit(f"CCMX 生成失败: 无法加载目标测量数据 {target_id}")
                return

            # 检查数据是否有效（必须有白、红、绿、蓝四个色块的测量数据）
            ref_gamut = ref_measurement.measurements.get("gamut", {})
            target_gamut = target_measurement.measurements.get("gamut", {})

            required_colors = ["white", "red", "green", "blue"]
            for color in required_colors:
                if not ref_gamut.get(color) or not ref_gamut[color].get("xyY"):
                    self.logMessage.emit(f"CCMX 生成失败: 基准数据缺少 {color} 色块测量")
                    return
                if not target_gamut.get(color) or not target_gamut[color].get("xyY"):
                    self.logMessage.emit(f"CCMX 生成失败: 目标数据缺少 {color} 色块测量")
                    return

            self.logMessage.emit(i18n.t("开始生成 CCMX 校正矩阵..."))
            self.logMessage.emit(f"基准探头: {ref_measurement.metadata.get('probe', '未知')}")
            self.logMessage.emit(f"目标探头: {target_measurement.metadata.get('probe', '未知')}")

            # 使用项目的 measurements 目录存放 ti3 文件（永久保存）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            measurements_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'measurements')
            os.makedirs(measurements_dir, exist_ok=True)
            ref_ti3_path = os.path.join(measurements_dir, f"ref_{timestamp}.ti3")
            target_ti3_path = os.path.join(measurements_dir, f"target_{timestamp}.ti3")

            # 导出 ti3 文件
            if not self._cgats_exporter.export_ti3(ref_measurement, ref_ti3_path):
                self.logMessage.emit(i18n.t("CCMX 生成失败: 导出基准 ti3 文件失败"))
                return

            if not self._cgats_exporter.export_ti3(target_measurement, target_ti3_path):
                self.logMessage.emit(i18n.t("CCMX 生成失败: 导出目标 ti3 文件失败"))
                return

            self.logMessage.emit(f"ti3 原始数据已保存至 measurements 目录")

            # 生成带时间戳的输出文件名
            target_probe = target_measurement.metadata.get('probe', 'unknown')
            output_filename = f"{target_probe}_matrix_{timestamp}.ccmx"
            output_ccmx_path = os.path.join(self._corrections_dir, output_filename)

            # 调用 argyll_controller 的 make_ccmx 方法
            display_tech = self._current_display_type.value if hasattr(self._current_display_type, 'value') else 'l'
            success = self._argyll_controller.make_ccmx(
                ref_ti3_path=ref_ti3_path,
                target_ti3_path=target_ti3_path,
                output_ccmx_path=output_ccmx_path,
                display_tech=display_tech
            )

            # 失败时输出排查命令
            if not success:
                self.logMessage.emit(f"ti3 文件位置:")
                self.logMessage.emit(f"  ref: {ref_ti3_path}")
                self.logMessage.emit(f"  target: {target_ti3_path}")
                # 获取 ccxxmake 路径
                ccxxmake_path = self._argyll_controller._argyll_path
                if ccxxmake_path:
                    ccxxmake_cmd = os.path.join(ccxxmake_path, "ccxxmake")
                else:
                    ccxxmake_cmd = "ccxxmake"
                # 路径含空格时需用双引号包裹
                debug_cmd = f'"{ccxxmake_cmd}" -v -t {display_tech} "{ref_ti3_path}" "{target_ti3_path}" "{output_ccmx_path}"'
                self.logMessage.emit(f"排查命令: {debug_cmd}")

            if success:
                self.logMessage.emit(f"✓ CCMX 校正文件已保存至: {output_ccmx_path}")
                self.logMessage.emit(f"校正文件已保存至 corrections 目录，可在光谱校正文件中选择使用")
            else:
                self.logMessage.emit(i18n.t("CCMX 生成失败: ccxxmake 执行失败"))

        except Exception as e:
            self.logMessage.emit(f"CCMX 生成失败: {e}")

    # ========== 3D LUT 制作流程（targen -> 测量 -> colprof -> collink） ==========

    @pyqtSlot(int, str)
    def generate_lut_patches(self, patch_count: int, output_name: str = ""):
        """
        生成 3D LUT 测量所需的色块序列（使用 targen）

        流程：
        1. 使用 targen 生成 .ti1 文件（包含离散色块 RGB 值）
        2. 解析 ti1 文件，提取 RGB 色块队列供前端投射

        Args:
            patch_count: 色块数量（常用：512、1024、2048）
            output_name: 输出文件名（不含扩展名），空则自动生成时间戳名称

        此方法是非阻塞的，通过信号反馈结果：
        - ti1PatchesGenerated: 生成完成，返回色块列表
        - lutGenerationError: 生成失败
        """
        if not self._argyll_controller:
            self.lutGenerationError.emit(json.dumps({
                "stage": "targen",
                "error": "Argyll 控制器未初始化"
            }))
            return

        # 确定输出路径
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        measurements_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'measurements')
        os.makedirs(measurements_dir, exist_ok=True)

        if output_name:
            output_path = os.path.join(measurements_dir, output_name)
        else:
            output_path = os.path.join(measurements_dir, f"lut_patches_{patch_count}_{timestamp}")

        self.logMessage.emit(f"开始生成 {patch_count} 色块的测试序列...")

        # 发送进度信号
        self.lutGenerationProgress.emit(json.dumps({
            "stage": "targen",
            "progress": 0,
            "message": f"正在生成 {patch_count} 个色块..."
        }))

        # 在后台线程中执行 targen（避免阻塞主线程）
        thread = threading.Thread(
            target=self._execute_targen_thread,
            args=(patch_count, output_path),
            name="backend-targen-thread",
            daemon=True
        )
        thread.start()

    def _execute_targen_thread(self, patch_count: int, output_path: str):
        """
        在后台线程中执行 targen 命令

        Args:
            patch_count: 色块数量
            output_path: 输出路径（不含扩展名）
        """
        try:
            # 进度回调函数
            def on_progress(current, total, message):
                # Qt 信号是线程安全的，可以直接从后台线程发射
                self.lutGenerationProgress.emit(json.dumps({
                    "stage": "targen",
                    "progress": current,
                    "message": message
                }))

            success = self._argyll_controller.generate_target(
                patch_count=patch_count,
                output_path=output_path,
                on_progress=on_progress
            )

            if success:
                # 解析 ti1 文件，提取 RGB 队列
                ti1_path = output_path + ".ti1"

                # ========== 临时文件跟踪（用于极端中断清理） ==========
                # 将临时文件路径添加到全局集合，确保异常退出时能被清理
                self._track_temp_file(ti1_path)

                patches = self._argyll_controller.parse_ti1_to_rgb_queue(ti1_path)

                if patches:
                    # 通过信号返回色块列表
                    self.ti1PatchesGenerated.emit(json.dumps({
                        "patch_count": len(patches),
                        "ti1_path": ti1_path,
                        "patches": [
                            {"r": p[0], "g": p[1], "b": p[2], "name": p[3]}
                            for p in patches[:100]  # 只返回前100个用于预览
                        ],
                        "total_patches": len(patches)
                    }))
                    self.logMessage.emit(f"色块序列生成完成: {len(patches)} 个色块")
                else:
                    self.lutGenerationError.emit(json.dumps({
                        "stage": "targen",
                        "error": "解析 ti1 文件失败"
                    }))
            else:
                error_msg = self._argyll_controller.get_error_message()
                self.lutGenerationError.emit(json.dumps({
                    "stage": "targen",
                    "error": error_msg
                }))

        except Exception as e:
            self.lutGenerationError.emit(json.dumps({
                "stage": "targen",
                "error": str(e)
            }))

    def _auto_export_ti3_for_lut_workflow(self):
        """
        LUT 工作流自动导出 ti3 文件

        在 LUT 色块测量完成后，自动将测量数据导出为 ti3 格式，
        并发送信号通知前端可以继续 ICC Profile 生成流程。

        流程：
        1. 从测量数据生成 MeasurementData 对象
        2. 导出为 ti3 文件（ArgyllCMS 兼容格式）
        3. 发送 lutGenerationProgress 信号通知测量阶段完成
        4. 发送 ti3 文件路径供后续步骤使用
        """
        if self._lut_workflow_params is None:
            self.logMessage.emit(i18n.t("无 LUT 工作流参数，跳过 ti3 导出"))
            return

        self.logMessage.emit("=== LUT 工作流：导出 ti3 文件 ===")

        # 获取工作流参数
        params = self._lut_workflow_params
        patch_count = params.get("patch_count", 1024)
        profile_name = params.get("profile_name", "Display_Profile")
        source_space = params.get("source_space", "Rec709")

        # 确定输出路径
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        measurements_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'measurements')
        os.makedirs(measurements_dir, exist_ok=True)

        ti3_filename = f"{profile_name}_{patch_count}_{timestamp}.ti3"
        ti3_path = os.path.join(measurements_dir, ti3_filename)

        # ========== 临时文件跟踪（用于极端中断清理） ==========
        self._track_temp_file(ti3_path)

        # ========== 构建测量数据对象 ==========
        # 将当前测量数据转换为 MeasurementData 格式
        # 注意：_cycle_completed_data 包含所有已完成的测量结果
        # 但对于 LUT 工作流，我们使用 _current_measurement 对象

        # 更新测量数据元数据
        if self._argyll_controller:
            probe_type = self._argyll_controller._probe_type.value if hasattr(self._argyll_controller, '_probe_type') else "未知"
            self._current_measurement.set_probe(probe_type)

        display_type_str = self._current_display_type.value if hasattr(self._current_display_type, 'value') else str(self._current_display_type)
        self._current_measurement.set_display_type(display_type_str)

        display_model = self._get_display_model()
        if display_model:
            self._current_measurement.set_display_model(display_model)

        self._current_measurement.set_measure_mode("lut")
        self._current_measurement.set_timestamp()

        # ========== 导出 ti3 文件 ==========
        try:
            # 使用 CGATSExporter 导出 ti3 格式
            success = self._cgats_exporter.export_ti3(self._current_measurement, ti3_path)

            if success:
                file_size = os.path.getsize(ti3_path)
                self.logMessage.emit(f"ti3 文件已导出: {ti3_path} ({file_size} bytes)")

                # 更新工作流参数，记录 ti3 路径
                self._lut_workflow_params["ti3_path"] = ti3_path

                # 发送进度信号：测量阶段完成
                self.lutGenerationProgress.emit(json.dumps({
                    "stage": "measurement",
                    "progress": 100,
                    "message": f"测量完成，ti3 已导出 ({len(self._gamma_measurements)} 个色块)"
                }))

                # 发送 ti3 导出完成信号，通知前端可以继续
                self.lutGenerationProgress.emit(json.dumps({
                    "stage": "ti3_export",
                    "progress": 100,
                    "message": "ti3 导出完成，准备生成 ICC Profile",
                    "ti3_path": ti3_path,
                    "patch_count": patch_count,
                    "profile_name": profile_name,
                    "source_space": source_space,
                    "next_step": "generate_icc"
                }))

            else:
                self.logMessage.emit(i18n.t("导出 ti3 文件失败"))
                self.lutGenerationError.emit(json.dumps({
                    "stage": "ti3_export",
                    "error": "导出 ti3 文件失败"
                }))

        except Exception as e:
            self.logMessage.emit(f"ti3 导出异常: {str(e)}")
            self.lutGenerationError.emit(json.dumps({
                "stage": "ti3_export",
                "error": str(e)
            }))

    @pyqtSlot(str)
    def start_lut_measurement_cycle(self, ti1_path: str):
        """
        开始 3D LUT 色块的循环测量

        流程：
        1. 解析 ti1 文件获取 RGB 色块队列
        2. 保存 ti1 路径到工作流参数（用于后续步骤）
        3. 启动循环测量，依次投射每个色块并测量

        Args:
            ti1_path: .ti1 文件路径
        """
        if not self._argyll_controller or not self._argyll_controller.is_connected():
            self.logMessage.emit(i18n.t("探头未连接，无法开始 LUT 测量"))
            self.lutGenerationError.emit(json.dumps({
                "stage": "measurement",
                "error": "探头未连接"
            }))
            return

        # 解析 ti1 文件
        patches = self._argyll_controller.parse_ti1_to_rgb_queue(ti1_path)

        if not patches:
            self.logMessage.emit(f"解析 ti1 文件失败: {ti1_path}")
            self.lutGenerationError.emit(json.dumps({
                "stage": "measurement",
                "error": "解析 ti1 文件失败"
            }))
            return

        self.logMessage.emit(f"开始 LUT 色块测量: 共 {len(patches)} 个色块")

        # ========== 保存 ti1 路径到工作流参数 ==========
        # 用于后续步骤（ti3 导出、ICC 生成等）
        if self._lut_workflow_params is None:
            self._lut_workflow_params = {}

        self._lut_workflow_params["ti1_path"] = ti1_path
        self._lut_workflow_params["patch_count"] = len(patches)

        # 使用现有的循环测量机制
        self._start_cycle(patches, f"3D LUT 测量 ({len(patches)} 色块)")

        # 发送进度信号
        self.lutGenerationProgress.emit(json.dumps({
            "stage": "measurement",
            "progress": 0,
            "message": f"开始测量 {len(patches)} 个色块..."
        }))

    @pyqtSlot(str, str, str)
    def generate_icc_profile(self, ti3_path: str, profile_name: str, quality: str = "m"):
        """
        使用 colprof 从测量数据生成 ICC Profile

        Args:
            ti3_path: .ti3 测量数据文件路径
            profile_name: ICC Profile 名称
            quality: 精度等级 (l/m/h/u)

        此方法是非阻塞的，通过信号反馈进度：
        - lutGenerationProgress: 进度更新
        - lutGenerationCompleted/Error: 完成/失败
        """
        if not self._argyll_controller:
            self.lutGenerationError.emit(json.dumps({
                "stage": "colprof",
                "error": "Argyll 控制器未初始化"
            }))
            return

        # 确定输出路径
        measurements_dir = os.path.dirname(ti3_path)
        output_path = os.path.join(measurements_dir, profile_name)

        self.logMessage.emit(f"开始生成 ICC Profile: {profile_name}")
        self.logMessage.emit(f"精度等级: {quality}")

        # 发送进度信号
        self.lutGenerationProgress.emit(json.dumps({
            "stage": "colprof",
            "progress": 0,
            "message": "正在计算 ICC Profile..."
        }))

        # 在后台线程中执行 colprof（避免阻塞主线程）
        thread = threading.Thread(
            target=self._execute_colprof_thread,
            args=(ti3_path, output_path, profile_name, quality),
            name="backend-colprof-thread",
            daemon=True
        )
        thread.start()

    def _execute_colprof_thread(self, ti3_path: str, output_path: str,
                                  profile_name: str, quality: str):
        """
        在后台线程中执行 colprof 命令

        Args:
            ti3_path: ti3 文件路径
            output_path: 输出 ICC 路径（不含扩展名）
            profile_name: Profile 名称
            quality: 精度等级
        """
        try:
            # 进度回调函数
            def on_progress(current, total, message):
                # Qt 信号是线程安全的，可以直接从后台线程发射
                self.lutGenerationProgress.emit(json.dumps({
                    "stage": "colprof",
                    "progress": current,
                    "message": message
                }))

            success = self._argyll_controller.make_icc_profile(
                ti3_path=ti3_path,
                output_path=output_path,
                profile_name=profile_name,
                quality=quality,
                on_progress=on_progress
            )

            if success:
                icc_path = output_path + ".icc"
                self.lutGenerationCompleted.emit(json.dumps({
                    "success": True,
                    "stage": "colprof",
                    "icc_path": icc_path,
                    "message": f"ICC Profile 已生成: {icc_path}"
                }))
                self.logMessage.emit(f"ICC Profile 生成完成: {icc_path}")
            else:
                error_msg = self._argyll_controller.get_error_message()
                self.lutGenerationError.emit(json.dumps({
                    "stage": "colprof",
                    "error": error_msg
                }))

        except Exception as e:
            self.lutGenerationError.emit(json.dumps({
                "stage": "colprof",
                "error": str(e)
            }))

    @pyqtSlot(str, str, str, int, str, bool)
    def generate_3dlut(self,
                       source_space: str,
                       target_icc_path: str,
                       output_lut_name: str,
                       lut_size: int = 33,
                       intent: str = "r",
                       use_bpc: bool = True):
        """
        使用 collink 生成 3D LUT (.cube 文件)

        Args:
            source_space: 源色彩空间 (Rec709/P3/Rec2020 或 ICC 路径)
            target_icc_path: 目标 ICC Profile 文件路径
            output_lut_name: 输出 LUT 文件名
            lut_size: LUT 立方体尺寸 (33/65/129)，默认 33（行业最佳平衡点）
            intent: 渲染意图 (r/p/s)，r=相对色度，p=绝对色度，s=感知
            use_bpc: 黑场补偿 (Black Point Compensation)，默认 True

        此方法是非阻塞的，通过信号反馈进度：
        - lutGenerationProgress: 进度更新
        - lutGenerationCompleted/Error: 完成/失败
        """
        if not self._argyll_controller:
            self.lutGenerationError.emit(json.dumps({
                "stage": "collink",
                "error": "Argyll 控制器未初始化"
            }))
            return

        # 确定输出路径
        measurements_dir = os.path.dirname(os.path.dirname(__file__))
        lut_output_dir = os.path.join(measurements_dir, 'measurements')
        os.makedirs(lut_output_dir, exist_ok=True)

        # 确保 .cube 扩展名
        if not output_lut_name.lower().endswith('.cube'):
            output_lut_path = os.path.join(lut_output_dir, output_lut_name + '.cube')
        else:
            output_lut_path = os.path.join(lut_output_dir, output_lut_name)

        self.logMessage.emit(f"开始生成 3D LUT...")
        self.logMessage.emit(f"源色彩空间: {source_space}")
        self.logMessage.emit(f"目标 ICC: {target_icc_path}")
        self.logMessage.emit(f"LUT 尺寸: {lut_size}")
        self.logMessage.emit(f"渲染意图: {intent}")
        self.logMessage.emit(f"黑场补偿 (BPC): {'启用' if use_bpc else '禁用'}")

        # 发送进度信号
        self.lutGenerationProgress.emit(json.dumps({
            "stage": "collink",
            "progress": 0,
            "message": "正在计算 3D LUT..."
        }))

        # 在后台线程中执行 collink（避免阻塞主线程）
        thread = threading.Thread(
            target=self._execute_collink_thread,
            args=(source_space, target_icc_path, output_lut_path, lut_size, intent, use_bpc),
            name="backend-collink-thread",
            daemon=True
        )
        thread.start()

    def _execute_collink_thread(self, source_space: str, target_icc_path: str,
                                  output_lut_path: str, lut_size: int, intent: str,
                                  use_bpc: bool = True):
        """
        在后台线程中执行 collink 命令

        Args:
            source_space: 源色彩空间
            target_icc_path: 目标 ICC 路径
            output_lut_path: 输出 .cube 路径
            lut_size: LUT 尺寸
            intent: 渲染意图
            use_bpc: 黑场补偿
        """
        try:
            # 进度回调函数
            def on_progress(current, total, message):
                # Qt 信号是线程安全的，可以直接从后台线程发射
                self.lutGenerationProgress.emit(json.dumps({
                    "stage": "collink",
                    "progress": current,
                    "message": message
                }))

            success = self._argyll_controller.make_3dlut(
                source_space=source_space,
                target_icc_path=target_icc_path,
                output_lut_path=output_lut_path,
                lut_size=lut_size,
                intent=intent,
                use_bpc=use_bpc,
                on_progress=on_progress
            )

            if success:
                self.lutGenerationCompleted.emit(json.dumps({
                    "success": True,
                    "stage": "collink",
                    "lut_path": output_lut_path,
                    "icc_path": target_icc_path,
                    "source_space": source_space,
                    "lut_size": lut_size,
                    "use_bpc": use_bpc,
                    "message": f"3D LUT 已生成: {output_lut_path}"
                }))
                self.logMessage.emit(f"3D LUT 生成完成: {output_lut_path}")

                # ========== 自动清理中间临时文件 ==========
                # 成功生成 .cube 后，清理中间的 .ti3 和目标 ICC 文件（可选）
                # 注意：这里清理的是 target_icc_path 对应的基础路径
                # 用户可能需要保留 ICC 文件，所以只清理 .ti3
                base_path = os.path.splitext(target_icc_path)[0]
                ti3_path = base_path + '.ti3'
                if os.path.exists(ti3_path):
                    try:
                        os.remove(ti3_path)
                        self.logMessage.emit(f"已清理中间 .ti3 文件: {ti3_path}")
                    except Exception as cleanup_error:
                        self.logMessage.emit(f"清理 .ti3 文件失败: {cleanup_error}")

                # 提示用户可以清理 ICC 文件
                self.logMessage.emit(f"提示: 中间 ICC 文件保留在 {target_icc_path}，如需清理可手动删除")
            else:
                error_msg = self._argyll_controller.get_error_message()
                self.lutGenerationError.emit(json.dumps({
                    "stage": "collink",
                    "error": error_msg
                }))

                # ========== 异常时清理临时文件 ==========
                # 失败时清理可能的残留文件
                base_path = os.path.splitext(target_icc_path)[0]
                self._cleanup_temp_files(base_path, ['.ti3'])

        except Exception as e:
            self.lutGenerationError.emit(json.dumps({
                "stage": "collink",
                "error": str(e)
            }))

            # ========== 异常时清理临时文件 ==========
            try:
                base_path = os.path.splitext(target_icc_path)[0]
                self._cleanup_temp_files(base_path, ['.ti3'])
            except Exception as cleanup_error:
                self.logMessage.emit(f"清理临时文件失败: {cleanup_error}")

    @pyqtSlot(int, str, str, int, str, str, bool)
    def generate_full_3dlut_workflow(self,
                                       patch_count: int,
                                       source_space: str,
                                       profile_name: str,
                                       lut_size: int = 33,
                                       quality: str = "m",
                                       intent: str = "r",
                                       use_bpc: bool = True):
        """
        执行完整的 3D LUT 制作流程（一键流程）

        流程：
        1. generate_target (targen): 生成色块序列
        2. 测量阶段（用户手动完成，通过 start_lut_measurement_cycle）
        3. make_icc_profile (colprof): 生成 ICC Profile
        4. make_3dlut (collink): 生成最终 3D LUT

        Args:
            patch_count: 色块数量 (512/1024/2048)
            source_space: 源色彩空间 (Rec709/P3/Rec2020)
            profile_name: ICC Profile 名称
            lut_size: LUT 尺寸 (33/65/129)，默认 33（行业最佳平衡点）
            quality: ICC 精度等级 (l/m/h/u)
            intent: 渲染意图 (r/p/s)
            use_bpc: 黑场补偿 (BPC)，默认 True

        注意：此方法只启动流程的第1步（生成色块），后续步骤需要用户完成测量后手动调用。
        """
        self.logMessage.emit("=== 开始 3D LUT 制作流程 ===")
        self.logMessage.emit(f"色块数量: {patch_count}")
        self.logMessage.emit(f"源色彩空间: {source_space}")
        self.logMessage.emit(f"LUT 尺寸: {lut_size}")
        self.logMessage.emit(f"黑场补偿 (BPC): {'启用' if use_bpc else '禁用'}")

        # 存储流程参数（用于后续步骤）
        self._lut_workflow_params = {
            "patch_count": patch_count,
            "source_space": source_space,
            "profile_name": profile_name,
            "lut_size": lut_size,
            "quality": quality,
            "intent": intent,
            "use_bpc": use_bpc
        }

        # 启动第一步：生成色块序列
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_name = f"{profile_name}_{patch_count}_{timestamp}"
        self.generate_lut_patches(patch_count, output_name)

    @pyqtSlot(str, str)
    def continue_3dlut_workflow_after_measurement(self, ti3_path: str, profile_name: str):
        """
        在完成 LUT 色块测量后，继续执行 ICC Profile 和 3D LUT 生成

        Args:
            ti3_path: 测量完成的 .ti3 文件路径
            profile_name: ICC Profile 名称
        """
        if not self._lut_workflow_params:
            self.logMessage.emit(i18n.t("无 LUT 工作流参数，请先调用 generate_full_3dlut_workflow"))
            return

        params = self._lut_workflow_params
        quality = params.get("quality", "m")

        self.logMessage.emit("=== 继续 3D LUT 制作流程 ===")
        self.logMessage.emit(f"步骤 2: 生成 ICC Profile (colprof)")

        # 启动 ICC Profile 生成
        self.generate_icc_profile(ti3_path, profile_name, quality)

    @pyqtSlot(str)
    def continue_3dlut_workflow_after_icc(self, icc_path: str):
        """
        在 ICC Profile 生成完成后，继续执行 3D LUT 生成

        Args:
            icc_path: 生成的 .icc 文件路径
        """
        if not self._lut_workflow_params:
            self.logMessage.emit(i18n.t("无 LUT 工作流参数，请先调用 generate_full_3dlut_workflow"))
            return

        params = self._lut_workflow_params
        source_space = params.get("source_space", "Rec709")
        lut_size = params.get("lut_size", 33)
        intent = params.get("intent", "r")
        use_bpc = params.get("use_bpc", True)

        self.logMessage.emit("=== 继续 3D LUT 制作流程 ===")
        self.logMessage.emit(f"步骤 3: 生成 3D LUT (collink)")

        # 生成输出文件名
        profile_name = os.path.splitext(os.path.basename(icc_path))[0]
        lut_name = f"{profile_name}_{source_space}_{lut_size}"

        # 启动 3D LUT 生成
        self.generate_3dlut(source_space, icc_path, lut_name, lut_size, intent, use_bpc)

    @pyqtSlot(result=str)
    def get_lut_workflow_params(self):
        """
        获取当前 LUT 工作流参数

        Returns:
            JSON 字符串，包含工作流参数
        """
        return json.dumps(self._lut_workflow_params or {})

    @pyqtSlot()
    def clear_lut_workflow_params(self):
        """
        清除 LUT 工作流参数
        """
        self._lut_workflow_params = None
        self.logMessage.emit(i18n.t("LUT 工作流参数已清除"))

    # ========== 临时文件清理 ==========
    def _cleanup_temp_files(self, base_path: str, extensions: List[str] = None):
        """
        清理 LUT 生成流程产生的临时文件

        Args:
            base_path: 基础文件路径（不含扩展名）
            extensions: 要清理的扩展名列表，默认 ['.ti1', '.ti3']

        清理的文件类型：
            - .ti1: targen 生成的色块序列文件
            - .ti3: 测量后的数据文件（中间产物）
            - 中间 .icc: colprof 生成的 ICC Profile（如果最终只需要 .cube）
        """
        if extensions is None:
            extensions = ['.ti1', '.ti3']

        cleaned_files = []

        for ext in extensions:
            file_path = base_path + ext
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    cleaned_files.append(file_path)
                    self.logMessage.emit(f"已清理临时文件: {file_path}")
                except Exception as e:
                    self.logMessage.emit(f"清理临时文件失败: {file_path} - {str(e)}")

        # 清理同名的 .icc 中间文件（如果存在）
        icc_path = base_path + '.icc'
        if os.path.exists(icc_path):
            try:
                # 检查是否是最终需要的 ICC（通过检查是否有对应的 .cube）
                cube_path = base_path + '.cube'
                if os.path.exists(cube_path):
                    # .cube 已生成，可以清理中间 .icc
                    os.remove(icc_path)
                    cleaned_files.append(icc_path)
                    self.logMessage.emit(f"已清理中间 ICC 文件: {icc_path}")
            except Exception as e:
                self.logMessage.emit(f"清理 ICC 文件失败: {icc_path} - {str(e)}")

        return cleaned_files

    @pyqtSlot(str)
    def cleanup_lut_workflow_temp_files(self, workflow_base_path: str):
        """
        清理整个 LUT 工作流产生的临时文件（前端调用）

        Args:
            workflow_base_path: 工作流基础路径（不含扩展名）
        """
        self._cleanup_temp_files(workflow_base_path, ['.ti1', '.ti3', '.icc'])
        self.logMessage.emit(i18n.t("LUT 工作流临时文件已清理"))

        # 从全局临时文件集合中移除已清理的文件
        global _global_temp_files
        for ext in ['.ti1', '.ti3', '.icc', '.cube']:
            file_path = workflow_base_path + ext
            if file_path in _global_temp_files:
                _global_temp_files.discard(file_path)

    def _cleanup_all_temp_files(self):
        """
        清理所有已跟踪的临时文件（用于全局异常钩子调用）

        此方法由 atexit 和 sys.excepthook 调用，确保极端中断时临时文件被清理。

        注意：此方法应避免发送信号到 UI，因为此时 UI 可能已不可用。
        同时避免可能导致死锁的阻塞调用（如 QTimer、信号发射等）。
        """
        global _global_temp_files

        # ========== 兜底卸载 Null Profile（跨平台统一） ==========
        # 如果测量被中断（如异常退出、窗口被关闭），确保 Null Profile 被卸载
        # **跨平台统一**：使用 _lut_controller 的 cleanup_null_profile_direct 方法
        # 此方法直接调用 subprocess，避免可能导致的问题（如信号发射、锁等待等）
        if self._lut_controller and hasattr(self._lut_controller, 'cleanup_null_profile_direct'):
            if self._lut_controller.cleanup_null_profile_direct():
                # 同步更新 backend 层的状态标记
                self._null_profile_applied = False
            else:
                # 兜底清理失败，继续清理临时文件
                pass
        elif self._null_profile_applied and self._linear_profile_path:
            # 如果 _lut_controller 不可用，使用直接 subprocess 调用（旧逻辑保留作为兜底）
            try:
                display_index = self._get_patch_display_index() if hasattr(self, '_get_patch_display_index') else 1
                if self._lut_controller and hasattr(self._lut_controller, '_dispwin_path'):
                    dispwin_path = self._lut_controller._dispwin_path
                    if dispwin_path:
                        subprocess.run(
                            [dispwin_path, "-d", str(display_index), "-U", self._linear_profile_path, "-S", "u"],
                            capture_output=True,
                            timeout=5
                        )
                        subprocess.run(
                            [dispwin_path, "-d", str(display_index), "-L"],
                            capture_output=True,
                            timeout=5
                        )
                        self._null_profile_applied = False
            except Exception:
                pass

        # 清理全局临时文件集合中的所有文件
        for temp_file in list(_global_temp_files):
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass  # 清理失败不影响后续清理

        _global_temp_files.clear()

        # 清理当前工作流的临时文件
        for temp_file in list(self._current_workflow_temp_files):
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass

        self._current_workflow_temp_files.clear()

    def _track_temp_file(self, file_path: str):
        """
        将临时文件路径添加到全局跟踪集合

        Args:
            file_path: 临时文件完整路径
        """
        global _global_temp_files
        _global_temp_files.add(file_path)
        self._current_workflow_temp_files.add(file_path)

    def _untrack_temp_file(self, file_path: str):
        """
        从全局跟踪集合中移除临时文件路径

        Args:
            file_path: 临时文件完整路径
        """
        global _global_temp_files
        _global_temp_files.discard(file_path)
        self._current_workflow_temp_files.discard(file_path)

    # ========== 预检相关方法 (P3-C) ==========

    @pyqtSlot()
    def run_preflight_check(self):
        """
        运行预检检查（委托给 PreflightService）

        前端调用此方法触发预检。预检结果通过 preflightCheckCompleted 信号返回。
        进度更新通过 preflightCheckProgress 信号返回。
        """
        # 更新 PreflightService 参数
        argyll_bin_path = None
        if self._argyll_controller:
            argyll_bin_path = self._argyll_controller._argyll_path
        self._preflight_service.set_argyll_bin_path(argyll_bin_path)
        self._preflight_service.set_display_index(
            self._get_patch_display_index() if hasattr(self, '_get_patch_display_index') else 1
        )
        if hasattr(self, '_correction_file_path'):
            self._preflight_service.set_correction_file_path(self._correction_file_path)
        self._preflight_service.set_override(self._preflight_override_enabled)

        self.preflightCheckStarted.emit()

        # 进度回调（在 worker 线程被调用；Qt 信号 emit 会自动走队列连接回主线程）
        def progress_callback(current: int, total: int, item_id: str, label: str):
            progress_data = {
                "current": current,
                "total": total,
                "item": item_id,
                "label": label,
            }
            self.preflightCheckProgress.emit(json.dumps(progress_data, ensure_ascii=False))

        # 完成回调
        def completed_callback(report_dict: Dict):
            self._preflight_completed = True
            report_json = json.dumps(report_dict)
            self.preflightCheckCompleted.emit(report_json)

        # 错误回调
        def error_callback(error_dict: Dict):
            error_json = json.dumps(error_dict)
            self.preflightCheckCompleted.emit(error_json)

        # 委托给 PreflightService
        self._preflight_service.run_checks_async(
            progress_callback=progress_callback,
            completed_callback=completed_callback,
            error_callback=error_callback,
        )

    @pyqtSlot(result=str)
    def get_preflight_report(self):
        """获取最新预检报告（委托给 PreflightService）"""
        return self._preflight_service.get_report_json()

    @pyqtSlot(result=bool)
    def can_proceed_with_measurement(self):
        """检查是否可以进行测量（委托给 PreflightService）"""
        return self._preflight_service.can_proceed()

    @pyqtSlot(bool)
    def set_preflight_override(self, enabled: bool):
        """设置预检覆盖状态"""
        self._preflight_override_enabled = enabled
        self._preflight_service.set_override(enabled)
        self.preflightOverrideChanged.emit(enabled)

        # 如果已有预检报告，重新发送更新后的报告
        report_json = self._preflight_service.get_report_json()
        if report_json and self._preflight_service.is_completed():
            self.preflightCheckCompleted.emit(report_json)

    @pyqtSlot(result=bool)
    def get_preflight_override_status(self):
        """获取预检覆盖状态"""
        return self._preflight_service.is_override_enabled()

    @pyqtSlot(result=bool)
    def has_preflight_blocking_items(self):
        """检查是否有阻断项（委托给 PreflightService）"""
        return self._preflight_service.has_blocking_items()

    @pyqtSlot(result=str)
    def get_preflight_blocking_items(self):
        """获取阻断项列表（委托给 PreflightService）"""
        return self._preflight_service.get_blocking_items_json()

    @pyqtSlot(result=str)
    def get_preflight_warning_items(self):
        """获取警告项列表（委托给 PreflightService）"""
        return self._preflight_service.get_warning_items_json()

    @pyqtSlot(str)
    def export_preflight_report(self, filepath: str):
        """导出预检报告到文件（委托给 PreflightService）"""
        success = self._preflight_service.export_report(filepath)
        result = {
            "success": success,
            "path": filepath,
            "message": "预检报告已导出" if success else "导出失败",
        }
        self.logMessage.emit(result["message"])
        self.fileCreated.emit(json.dumps(result))

    # ========== 报告导出 API (P5-C) ==========

    @pyqtSlot(str, result=str)
    def generate_calibration_report(self, measurement_id: str):
        """
        为指定测量数据生成校准报告
        
        Args:
            measurement_id: 测量 ID（如 "20260519_123456_abc123"）
            
        Returns:
            JSON 字符串: {"success": true, "path": "...", "report_id": "..."}
        
        前端调用此方法为历史测量数据生成报告。
        """
        try:
            # 加载测量数据
            storage = DataStorage()
            measurement_data = storage.load_measurement(measurement_id)
            
            if not measurement_data:
                return json.dumps({
                    "success": False,
                    "error": f"找不到测量数据: {measurement_id}"
                })
            
            # 生成报告
            report_type = ReportType.FULL_REPORT
            mode = measurement_data.metadata.get("measure_mode", "")
            if mode == "icc":
                report_type = ReportType.ICC_VALIDATION
            elif mode == "lut":
                report_type = ReportType.LUT_VALIDATION
            elif mode == "gamut":
                report_type = ReportType.GAMUT_MEASUREMENT
            elif mode == "gamma":
                report_type = ReportType.GAMMA_ANALYSIS
            
            html_content = self._report_generator.generate_from_dict(
                measurement_data.to_dict(), report_type
            )
            
            # 确定保存路径
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            reports_dir = os.path.join(project_root, "measurements", "reports")
            if not os.path.exists(reports_dir):
                os.makedirs(reports_dir)
            
            # 使用 measurement_id 作为报告文件名
            report_filename = f"{measurement_id}_report.html"
            report_path = os.path.join(reports_dir, report_filename)
            
            # 保存报告
            success = self._report_generator.save_report(html_content, report_path)
            
            if success:
                self._last_report_path = report_path
                result = {
                    "success": True,
                    "path": report_path,
                    "report_id": measurement_id,
                    "message": "报告已生成"
                }
                self.logMessage.emit(f"校准报告已生成: {report_path}")
                self.reportGenerated.emit(json.dumps(result))
            else:
                result = {
                    "success": False,
                    "error": "保存报告失败"
                }
            
            return json.dumps(result)
            
        except Exception as e:
            self._logger.error(f"生成报告失败: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    @pyqtSlot(result=str)
    def generate_current_report(self):
        """
        为当前测量数据生成报告
        
        Returns:
            JSON 字符串: {"success": true, "path": "...", "report_id": "..."}
        
        在 ICC/LUT 验证完成后自动调用此方法生成报告。
        """
        try:
            # 使用当前测量数据
            if not self._measurement_data or not self._measurement_data.is_valid():
                return json.dumps({
                    "success": False,
                    "error": "当前测量数据无效"
                })
            
            # 确定报告类型
            report_type = ReportType.FULL_REPORT
            mode = self._measure_mode or ""
            if mode == "icc":
                report_type = ReportType.ICC_VALIDATION
            elif mode == "lut":
                report_type = ReportType.LUT_VALIDATION
            
            # 发送报告导出开始信号
            self.reportExportStarted.emit(json.dumps({"type": report_type.value}))
            
            # 生成报告
            html_content = self._report_generator.generate_from_dict(
                self._measurement_data.to_dict(), report_type
            )
            
            # 确定保存路径
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            # 如果有 session 目录，使用 session 目录
            if hasattr(self, '_session_storage') and self._session_storage:
                reports_dir = os.path.join(self._session_storage.get_session_path(), "reports")
            else:
                reports_dir = os.path.join(project_root, "measurements", "reports")
            
            if not os.path.exists(reports_dir):
                os.makedirs(reports_dir)
            
            # 生成报告 ID
            report_id = self._measurement_data.metadata.get("measurement_id", 
                datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + os.urandom(3).hex())
            report_filename = f"{report_id}_report.html"
            report_path = os.path.join(reports_dir, report_filename)
            
            # 保存报告
            success = self._report_generator.save_report(html_content, report_path)
            
            if success:
                self._last_report_path = report_path
                result = {
                    "success": True,
                    "path": report_path,
                    "report_id": report_id,
                    "report_type": report_type.value,
                    "message": "报告已自动生成"
                }
                self.logMessage.emit(f"校准报告已自动生成: {report_path}")
                self.reportGenerated.emit(json.dumps(result))
                self.reportExportCompleted.emit(json.dumps(result))
            else:
                result = {
                    "success": False,
                    "error": "保存报告失败"
                }
                self.reportExportCompleted.emit(json.dumps(result))
            
            return json.dumps(result)
            
        except Exception as e:
            self._logger.error(f"生成当前报告失败: {e}")
            result = {
                "success": False,
                "error": str(e)
            }
            self.reportExportCompleted.emit(json.dumps(result))
            return json.dumps(result)

    @pyqtSlot(result=str)
    def get_last_report_path(self):
        """
        获取最新生成的报告路径
        
        Returns:
            JSON 字符串: {"path": "...", "exists": true/false}
        """
        if self._last_report_path:
            exists = os.path.exists(self._last_report_path)
            return json.dumps({
                "path": self._last_report_path,
                "exists": exists
            })
        else:
            return json.dumps({
                "path": "",
                "exists": False
            })

    @pyqtSlot(str)
    def set_report_config(self, config_json: str):
        """
        设置报告配置
        
        Args:
            config_json: JSON 字符串格式的配置
            
        支持自定义：
        - title: 报告标题
        - include_charts: 是否包含图表
        - thresholds: 验证阈值配置
        """
        try:
            config_data = json.loads(config_json)
            
            # 更新配置
            if "title" in config_data:
                self._report_config.title = config_data["title"]
            if "include_charts" in config_data:
                self._report_config.include_charts = config_data["include_charts"]
            
            # 更新阈值配置
            if "thresholds" in config_data:
                thresholds = config_data["thresholds"]
                tc = self._report_config.threshold_config
                if "delta_e_avg_pass" in thresholds:
                    tc.delta_e_avg_pass = thresholds["delta_e_avg_pass"]
                if "delta_e_avg_warn" in thresholds:
                    tc.delta_e_avg_warn = thresholds["delta_e_avg_warn"]
                if "gamma_deviation_pass" in thresholds:
                    tc.gamma_deviation_pass = thresholds["gamma_deviation_pass"]
                if "gamut_coverage_pass" in thresholds:
                    tc.gamut_coverage_pass = thresholds["gamut_coverage_pass"]
            
            # 更新生成器配置
            self._report_generator = ReportGenerator(self._report_config)
            
            self.logMessage.emit(i18n.t("报告配置已更新"))
            
        except Exception as e:
            self._logger.error(f"设置报告配置失败: {e}")

    @pyqtSlot(result=str)
    def get_report_config(self):
        """
        获取当前报告配置
        
        Returns:
            JSON 字符串格式的配置
        """
        config_data = {
            "title": self._report_config.title,
            "include_charts": self._report_config.include_charts,
            "output_format": self._report_config.output_format,
            "language": self._report_config.language,
            "thresholds": {
                "delta_e_avg_pass": self._report_config.threshold_config.delta_e_avg_pass,
                "delta_e_avg_warn": self._report_config.threshold_config.delta_e_avg_warn,
                "delta_e_max_pass": self._report_config.threshold_config.delta_e_max_pass,
                "gamma_deviation_pass": self._report_config.threshold_config.gamma_deviation_pass,
                "gamut_coverage_pass": self._report_config.threshold_config.gamut_coverage_pass,
            }
        }
        return json.dumps(config_data)

    @pyqtSlot(str, str, result=str)
    def export_report_to_path(self, measurement_id: str, output_path: str):
        """
        导出报告到指定路径
        
        Args:
            measurement_id: 测量 ID
            output_path: 输出文件路径
            
        Returns:
            JSON 字符串: {"success": true, "path": "..."}
        """
        try:
            # 加载测量数据
            storage = DataStorage()
            measurement_data = storage.load_measurement(measurement_id)
            
            if not measurement_data:
                return json.dumps({
                    "success": False,
                    "error": f"找不到测量数据: {measurement_id}"
                })
            
            # 生成报告
            html_content = self._report_generator.generate_from_dict(
                measurement_data.to_dict(), ReportType.FULL_REPORT
            )
            
            # 保存到指定路径
            success = self._report_generator.save_report(html_content, output_path)
            
            if success:
                result = {
                    "success": True,
                    "path": output_path,
                    "message": "报告已导出"
                }
                self.logMessage.emit(f"报告已导出到: {output_path}")
                self.reportExportCompleted.emit(json.dumps(result))
            else:
                result = {
                    "success": False,
                    "error": "保存报告失败"
                }
            
            return json.dumps(result)
            
        except Exception as e:
            self._logger.error(f"导出报告失败: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    # ========== 向导报告导出功能 ==========

    @pyqtSlot(result=str)
    def export_wizard_report_html(self):
        """
        导出向导测量报告为 HTML 格式

        使用文件对话框让用户选择保存路径，然后生成 HTML 报告。
        结果通过 reportExportCompleted 信号返回。
        """
        try:
            if not self._measurement_data or not self._measurement_data.is_valid():
                self.reportExportCompleted.emit(json.dumps({
                    "success": False,
                    "error": "当前测量数据无效，无法生成报告"
                }))
                return json.dumps({"success": False, "error": "测量数据无效"})

            # 生成默认文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"calibration_report_{timestamp}.html"

            # 请求用户选择保存路径
            self._pending_export_format = "html"
            self.select_save_path(default_filename, "html")

            return json.dumps({"success": True, "action": "select_path"})

        except Exception as e:
            self._logger.error(f"导出 HTML 报告失败: {e}")
            self.reportExportCompleted.emit(json.dumps({
                "success": False,
                "error": str(e)
            }))
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(result=str)
    def export_wizard_report_json(self):
        """
        导出向导测量数据为 JSON 格式

        使用文件对话框让用户选择保存路径，然后导出 JSON 数据。
        结果通过 reportExportCompleted 信号返回。
        """
        try:
            if not self._measurement_data or not self._measurement_data.is_valid():
                self.reportExportCompleted.emit(json.dumps({
                    "success": False,
                    "error": "当前测量数据无效，无法导出"
                }))
                return json.dumps({"success": False, "error": "测量数据无效"})

            # 生成默认文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"calibration_data_{timestamp}.json"

            # 请求用户选择保存路径
            self._pending_export_format = "json"
            self.select_save_path(default_filename, "json")

            return json.dumps({"success": True, "action": "select_path"})

        except Exception as e:
            self._logger.error(f"导出 JSON 数据失败: {e}")
            self.reportExportCompleted.emit(json.dumps({
                "success": False,
                "error": str(e)
            }))
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(result=str)
    def export_wizard_report_pdf(self):
        """
        导出向导测量报告为 PDF 格式

        使用文件对话框让用户选择保存路径，然后经 weasyprint 渲染 PDF
        （P4: 统一走 reports.generator.generate_pdf_report，含 CJK 字体注入）。
        结果通过 reportExportCompleted 信号返回。
        """
        try:
            if not self._measurement_data or not self._measurement_data.is_valid():
                self.reportExportCompleted.emit(json.dumps({
                    "success": False,
                    "error": "当前测量数据无效，无法生成报告"
                }))
                return json.dumps({"success": False, "error": "测量数据无效"})

            # 生成默认文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"calibration_report_{timestamp}.pdf"

            # 请求用户选择保存路径
            self._pending_export_format = "pdf"
            self.select_save_path(default_filename, "pdf")

            return json.dumps({"success": True, "action": "select_path"})

        except Exception as e:
            self._logger.error(f"导出 PDF 报告失败: {e}")
            self.reportExportCompleted.emit(json.dumps({
                "success": False,
                "error": str(e)
            }))
            return json.dumps({"success": False, "error": str(e)})

    def _complete_report_export(self, output_path: str, format_type: str):
        """
        完成报告导出（在用户选择路径后调用）

        Args:
            output_path: 用户选择的输出路径
            format_type: 导出格式 (html, json, pdf)
        """
        try:
            if not self._measurement_data:
                self.reportExportCompleted.emit(json.dumps({
                    "success": False,
                    "error": "测量数据无效"
                }))
                return

            # 确定报告类型
            report_type = ReportType.FULL_REPORT
            mode = self._measure_mode or ""
            if mode == "icc":
                report_type = ReportType.ICC_VALIDATION
            elif mode == "lut":
                report_type = ReportType.LUT_VALIDATION
            elif mode == "gamut":
                report_type = ReportType.GAMUT_MEASUREMENT
            elif mode == "gamma":
                report_type = ReportType.GAMMA_ANALYSIS

            if format_type == "html":
                # 生成 HTML 报告
                html_content = self._report_generator.generate_from_dict(
                    self._measurement_data.to_dict(), report_type
                )
                success = self._report_generator.save_report(html_content, output_path)

                if success:
                    self.reportExportCompleted.emit(json.dumps({
                        "success": True,
                        "path": output_path,
                        "format": "html",
                        "message": "HTML 报告已导出"
                    }))
                else:
                    self.reportExportCompleted.emit(json.dumps({
                        "success": False,
                        "error": "保存 HTML 报告失败"
                    }))

            elif format_type == "json":
                # 导出 JSON 数据 - 直接导出测量数据
                json_content = json.dumps(
                    self._measurement_data.to_dict(),
                    indent=2,
                    ensure_ascii=False
                )

                # 确保目录存在
                output_dir = os.path.dirname(output_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)

                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(json_content)

                self.reportExportCompleted.emit(json.dumps({
                    "success": True,
                    "path": output_path,
                    "format": "json",
                    "message": "JSON 数据已导出"
                }))

            elif format_type == "pdf":
                # 生成 HTML 报告，然后转换为 PDF（P4: 统一走 generate_pdf_report）
                html_content = self._report_generator.generate_from_dict(
                    self._measurement_data.to_dict(), report_type
                )

                from .reports.generator import generate_pdf_report
                if generate_pdf_report(html_content, output_path):
                    self.reportExportCompleted.emit(json.dumps({
                        "success": True,
                        "path": output_path,
                        "format": "pdf",
                        "message": "PDF 报告已导出"
                    }))
                else:
                    self.reportExportCompleted.emit(json.dumps({
                        "success": False,
                        "error": "PDF 导出失败：weasyprint 未安装或渲染错误",
                        "suggestion": "安装 weasyprint (pip install weasyprint)，或使用 HTML 导出后浏览器打印为 PDF"
                    }))

        except Exception as e:
            self._logger.error(f"完成报告导出失败: {e}", exc_info=True)
            self.reportExportCompleted.emit(json.dumps({
                "success": False,
                "error": str(e)
            }))

    # ========== P7-B: 诊断包导出功能 ==========

    @pyqtSlot(result=str)
    def get_export_options(self) -> str:
        """
        获取诊断包导出选项

        Returns:
            JSON 字符串: {"options": {"logs": "Session logs", ...}}
        """
        return json.dumps({"options": get_export_options()})

    @pyqtSlot(str, str, bool, result=str)
    def export_diagnostics_pack(
        self,
        session_id: str,
        output_path: str,
        include_private: bool = False
    ) -> str:
        """
        导出诊断包

        一键导出诊断信息，用于用户反馈问题时提供完整的调试信息。
        包含：manifest、日志、环境信息、Argyll 输出文件、异常栈。

        Args:
            session_id: 会话 ID（可选，空则使用当前会话）
            output_path: 输出 ZIP 文件路径
            include_private: 是否包含隐私敏感文件（ICC、CAL）

        Returns:
            JSON 字符串: {"success": true, "path": "...", "included_files": [...]}
        """
        try:
            # 使用当前会话 ID 或指定 ID
            actual_session_id = session_id or self._session_id

            # 确定会话目录（从自动保存目录查找）
            session_dir = None
            auto_save_dir = Path(self._auto_save_base_dir)
            if auto_save_dir.exists():
                # 查找匹配 session_id 的目录
                for date_dir in auto_save_dir.iterdir():
                    if date_dir.is_dir():
                        for session_folder in date_dir.iterdir():
                            if session_folder.is_dir() and actual_session_id in session_folder.name:
                                session_dir = session_folder
                                break

            # 导出诊断包
            zip_path = export_diagnostics_pack(
                session_id=actual_session_id,
                session_dir=session_dir,
                output_path=Path(output_path),
                include_private=include_private,
                collector=self._diagnostics_collector
            )

            self._logger.info(f"诊断包已导出: {zip_path}")
            self.logMessage.emit(f"诊断包已导出到: {zip_path}")

            result = {
                "success": True,
                "path": str(zip_path),
                "session_id": actual_session_id,
                "message": "诊断包已成功导出"
            }

            return json.dumps(result)

        except Exception as e:
            self._logger.error(f"导出诊断包失败: {e}")
            self._diagnostics_collector.record_exception(e, {
                "session_id": session_id,
                "output_path": output_path
            })
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    @pyqtSlot(result=str)
    def get_session_id(self) -> str:
        """
        获取当前会话 ID

        Returns:
            JSON 字符串: {"session_id": "..."}
        """
        return json.dumps({"session_id": self._session_id})

    @pyqtSlot(str)
    def set_log_level(self, level: str):
        """
        设置日志级别

        Args:
            level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        set_log_level(level)
        self._logger.info(f"日志级别已设置为: {level}")
        self.logMessage.emit(f"日志级别已设置为: {level}")

    # ========== P4-B: ICC Workflow 集成 ==========

    def _init_icc_workflow(self) -> ICCWorkflow:
        """
        初始化 ICC Workflow 实例

        Returns:
            ICCWorkflow 实例
        """
        if self._icc_workflow is None:
            # 获取 ArgyllCMS 路径
            argyll_path = ""
            if self._argyll_controller and hasattr(self._argyll_controller, '_argyll_path'):
                argyll_path = self._argyll_controller._argyll_path or ""

            # 获取 measurements 目录
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            measurements_dir = Path(project_root) / "measurements" / "sessions"

            # 创建 ICC Workflow 实例
            self._icc_workflow = ICCWorkflow(
                argyll_path=argyll_path,
                measurements_dir=measurements_dir,
                argyll_controller=self._argyll_controller,
            )

            # 注册回调：状态变化
            self._icc_workflow.on_state_change(self._handle_icc_workflow_state_change)

            # 注册回调：进度更新
            self._icc_workflow.on_progress(self._handle_icc_workflow_progress)

            # 注册回调：错误处理
            self._icc_workflow.on_error(self._handle_icc_workflow_error)

            # 注册回调：完成
            self._icc_workflow.on_completed(self._handle_icc_workflow_completed)

            # 注册回调：测量结果
            self._icc_workflow.on_measurement(self._handle_icc_workflow_measurement)

            self._logger.info("ICC Workflow 实例已初始化")

        return self._icc_workflow

    def _handle_icc_workflow_state_change(
        self, old_state: ICCWorkflowState, new_state: ICCWorkflowState
    ) -> None:
        """
        处理 ICC Workflow 状态变化

        Args:
            old_state: 旧状态
            new_state: 新状态
        """
        # 发送状态变化信号
        self._emit_json(self.iccWorkflowStateChanged, {
            "state": new_state.value,
            "previous": old_state.value,
        })
        self._logger.info(f"ICC Workflow 状态变化: {old_state.value} -> {new_state.value}")

    def _handle_icc_workflow_progress(self, percent: int, step: str) -> None:
        """
        处理 ICC Workflow 进度更新

        Args:
            percent: 进度百分比
            step: 当前步骤描述
        """
        # 发送进度信号
        self._emit_json(self.iccWorkflowProgress, {
            "percent": percent,
            "step": step,
        })
        self.logMessage.emit(f"ICC Workflow: {step} ({percent}%)")

    def _handle_icc_workflow_error(self, error: ICCWorkflowError) -> None:
        """
        处理 ICC Workflow 错误

        Args:
            error: ICCWorkflowError 实例
        """
        # 发送错误信号
        self._emit_json(self.iccWorkflowFailed, {
            "error": str(error),
            "error_code": error.error_code,
            "recoverable": error.recoverable,
            "suggestion": error.suggestion,
            "state": error.state.value if error.state else None,
        })
        self.logMessage.emit(f"ICC Workflow 错误: {error}")

        # 如果是 recoverable 错误，保存断点以便恢复
        if error.recoverable and self._icc_session_dir:
            self._emit_json(self.measurementSuspended, {
                "reason": error.error_code,
                "canResume": True,
                "session_dir": self._icc_session_dir,
            })

    def _handle_icc_workflow_completed(self, session: ICCWorkflowSession) -> None:
        """
        处理 ICC Workflow 完成

        Args:
            session: ICCWorkflowSession 实例
        """
        # 获取生成的 artifacts
        artifacts = []
        if self._icc_workflow and self._icc_workflow.session_dir:
            session_dir = self._icc_workflow.session_dir

            # 添加 ICC 文件
            if session.icc_file:
                icc_path = session_dir / session.icc_file
                if icc_path.exists():
                    artifacts.append({
                        "type": "icc",
                        "path": str(icc_path),
                        "size": icc_path.stat().st_size,
                    })

            # 添加测量 JSON
            if session.ti3_file:
                ti3_path = session_dir / session.ti3_file
                if ti3_path.exists():
                    artifacts.append({
                        "type": "ti3",
                        "path": str(ti3_path),
                        "size": ti3_path.stat().st_size,
                    })

            # 添加 manifest
            manifest_path = session_dir / "manifest.json"
            if manifest_path.exists():
                artifacts.append({
                    "type": "manifest",
                    "path": str(manifest_path),
                })

            # 添加 checkpoint（用于恢复）
            checkpoint_path = session_dir / "checkpoint.json"
            if checkpoint_path.exists():
                artifacts.append({
                    "type": "checkpoint",
                    "path": str(checkpoint_path),
                })

        # 发送完成信号
        self._emit_json(self.iccWorkflowCompleted, {
            "success": True,
            "session_id": session.session_id,
            "icc_path": str(self._icc_workflow.get_icc_profile_path()) if self._icc_workflow else None,
            "session_dir": str(self._icc_workflow.session_dir) if self._icc_workflow else None,
            "artifacts": artifacts,
            "verification_results": session.verification_results,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        })
        self.logMessage.emit(f"ICC Profile 生成完成: {session.icc_file}")

    def _handle_icc_workflow_measurement(
        self, patch_index: int, total_patches: int, result: Dict
    ) -> None:
        """
        处理 ICC Workflow 测量结果

        Args:
            patch_index: 当前色块索引
            total_patches: 总色块数
            result: 测量结果 dict
        """
        # 发送测量结果信号（用于 UI 显示）
        self._emit_json(self.measurementResult, {
            "patchName": result.get("patch_name", f"Patch_{patch_index + 1}"),
            "rgb": result.get("rgb", {"r": 0, "g": 0, "b": 0}),
            "x": result.get("xyY", [0, 0, 0])[0],
            "y": result.get("xyY", [0, 0, 0])[1],
            "Y": result.get("xyY", [0, 0, 0])[2],
            "index": patch_index,
            "total": total_patches,
        })

        # 发送断点更新信号（用于恢复）
        self._emit_json(self.checkpointUpdated, {
            "index": patch_index,
            "total": total_patches,
            "completed": patch_index + 1,
        })

    @pyqtSlot(str, result=str)
    def start_icc_workflow(self, config_json: str) -> str:
        """
        启动 ICC Profile 工作流

        Args:
            config_json: JSON 配置字符串，包含:
                - preset: 预设类型 (photography/video/general/soft_proof)
                - white_point: 白点目标 (D65/D50/custom)
                - white_point_xy: 自定义白点 xy 坐标 [x, y]
                - gamma: gamma 值 (2.2/2.4/sRGB/BT.1886)
                - brightness: 亮度目标 (cd/m²)
                - patch_set: 色块集 (quick/standard/high_precision)
                - profile_name: Profile 名称
                - use_dispcal: 是否执行 dispcal 校准
                - display_index: 显示器索引
                - instrument_port: 仪器端口
                - correction_file: 校正文件路径

        Returns:
            JSON 字符串: {"success": true, "session_id": "..."} 或
            {"success": false, "error": "..."}
        """
        try:
            # 解析配置
            config = json.loads(config_json)
            self._icc_workflow_config = config

            # 初始化 ICC Workflow
            workflow = self._init_icc_workflow()

            # 构建 ICCWorkflowConfig
            preset_map = {
                "photography": ProfilePreset.PHOTOGRAPHY,
                "video": ProfilePreset.VIDEO,
                "general": ProfilePreset.GENERAL,
                "soft_proof": ProfilePreset.SOFT_PROOF,
            }
            preset = preset_map.get(config.get("preset", "general"), ProfilePreset.GENERAL)

            # 解析 gamma/EOTF
            gamma_map = {
                "sRGB": 2.2,  # sRGB 实际使用 2.2 作为参考
                "BT.1886": 2.4,
                "2.2": 2.2,
                "2.4": 2.4,
            }
            gamma = gamma_map.get(config.get("gamma", "2.2"), 2.2)

            # 解析 patch set
            patch_count_map = {
                "quick": 512,
                "standard": 1024,
                "high_precision": 2048,
            }
            patch_count = patch_count_map.get(config.get("patch_set", "standard"), 1024)

            # 解析白点
            white_point = config.get("white_point", "D65")
            white_point_xy = None
            if white_point == "custom":
                xy = config.get("white_point_xy", [0.3127, 0.329])
                white_point_xy = (xy[0], xy[1])
            elif white_point == "D50":
                white_point_xy = None  # ICCWorkflow 会自动处理

            # 创建 ICCWorkflowConfig
            icc_config = ICCWorkflowConfig(
                preset=preset,
                display_type=DisplayType.LCD,  # 默认 LCD，可从配置覆盖
                display_index=config.get("display_index", 1),
                instrument_port=config.get("instrument_port", 1),
                correction_file=config.get("correction_file"),
                white_point_target=white_point,
                white_point_xy=white_point_xy,
                gamma_target=gamma,
                brightness_target=config.get("brightness"),
                patch_count=patch_count,
                use_dispcal=config.get("use_dispcal", True),
                auto_verify=True,  # 验证测量是必需的
                verify_patch_count=64,
                profile_name=config.get("profile_name", "Topos Display Profile"),
            )

            self.logMessage.emit(f"启动 ICC Profile 工作流: {preset.value} 预设")
            self.logMessage.emit(f"白点: {white_point}, Gamma: {gamma}")
            self.logMessage.emit(f"色块数: {patch_count}")

            # 启动工作流
            session = workflow.start(icc_config)

            # 保存会话目录
            self._icc_session_dir = str(workflow.session_dir) if workflow.session_dir else None

            # 发送会话信息
            self._emit_json(self.iccWorkflowSessionInfo, workflow.get_session_info())

            return json.dumps({
                "success": True,
                "session_id": session.session_id,
                "session_dir": self._icc_session_dir,
            })

        except ICCWorkflowError as e:
            self._logger.error(f"ICC Workflow 启动失败: {e}")
            self._emit_json(self.iccWorkflowFailed, {
                "error": str(e),
                "error_code": e.error_code,
                "recoverable": e.recoverable,
            })
            return json.dumps({
                "success": False,
                "error": str(e),
                "error_code": e.error_code,
            })

        except Exception as e:
            self._logger.error(f"ICC Workflow 启动异常: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
            })

    @pyqtSlot(result=bool)
    def pause_icc_workflow(self) -> bool:
        """
        暂停 ICC Profile 工作流

        保存当前状态的 checkpoint，以便后续恢复。

        Returns:
            bool: 是否成功暂停
        """
        if not self._icc_workflow:
            self.logMessage.emit(i18n.t("ICC Workflow 未运行，无法暂停"))
            return False

        try:
            workflow = self._icc_workflow

            # 检查当前状态是否可以暂停
            if workflow.state in [ICCWorkflowState.IDLE, ICCWorkflowState.COMPLETED,
                                  ICCWorkflowState.FAILED, ICCWorkflowState.SUSPENDED]:
                self.logMessage.emit(f"ICC Workflow 当前状态 {workflow.state.value} 无法暂停")
                return False

            # 停止工作流并保存 checkpoint
            success = workflow.stop(save_checkpoint=True, reason="user_pause")

            if success:
                self._emit_json(self.measurementSuspended, {
                    "reason": "user_pause",
                    "canResume": True,
                    "session_dir": self._icc_session_dir,
                })
                self.logMessage.emit(i18n.t("ICC Workflow 已暂停，可从断点恢复"))

            return success

        except Exception as e:
            self._logger.error(f"暂停 ICC Workflow 失败: {e}")
            return False

    @pyqtSlot(str, result=str)
    def resume_icc_workflow(self, session_dir: str) -> str:
        """
        从 checkpoint 恢复 ICC Profile 工作流

        Args:
            session_dir: 会话目录路径（包含 checkpoint.json）

        Returns:
            JSON 字符串: {"success": true, "session_id": "..."} 或
            {"success": false, "error": "..."}
        """
        try:
            # 初始化 ICC Workflow
            workflow = self._init_icc_workflow()

            # 加载 checkpoint
            checkpoint = ICCWorkflowCheckpoint.load(Path(session_dir))

            if not checkpoint:
                return json.dumps({
                    "success": False,
                    "error": "找不到 checkpoint 文件",
                })

            self.logMessage.emit(f"恢复 ICC Workflow: {checkpoint.session_id}")
            self.logMessage.emit(f"恢复状态: {checkpoint.state.value}")
            self.logMessage.emit(f"恢复原因: {checkpoint.reason}")

            # 恢复工作流
            session = workflow.resume(session_dir=Path(session_dir), checkpoint=checkpoint)

            # 保存会话目录
            self._icc_session_dir = str(workflow.session_dir) if workflow.session_dir else None

            # 发送恢复通知
            self.measurementResumed.emit()
            self._emit_json(self.iccWorkflowSessionInfo, workflow.get_session_info())

            return json.dumps({
                "success": True,
                "session_id": session.session_id,
                "state": session.state.value,
            })

        except ICCWorkflowError as e:
            self._logger.error(f"恢复 ICC Workflow 失败: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "error_code": e.error_code,
            })

        except Exception as e:
            self._logger.error(f"恢复 ICC Workflow 异常: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
            })

    @pyqtSlot(result=bool)
    def cancel_icc_workflow(self) -> bool:
        """
        取消 ICC Profile 工作流

        不保存 checkpoint，清理当前状态。

        Returns:
            bool: 是否成功取消
        """
        if not self._icc_workflow:
            return True

        try:
            workflow = self._icc_workflow

            # 取消工作流（不保存 checkpoint）
            success = workflow.cancel()

            if success:
                self.logMessage.emit(i18n.t("ICC Workflow 已取消"))
                self._emit_json(self.iccWorkflowStateChanged, {
                    "state": "idle",
                    "previous": workflow.state.value if workflow.session else "unknown",
                })

            # 清理状态
            self._icc_workflow_config = None
            self._icc_session_dir = None

            return success

        except Exception as e:
            self._logger.error(f"取消 ICC Workflow 失败: {e}")
            return False

    @pyqtSlot(result=str)
    def get_icc_workflow_presets(self) -> str:
        """
        获取可用的 ICC Profile 预设列表

        Returns:
            JSON 字符串: {"presets": {...}}
        """
        presets = get_available_presets()
        return json.dumps({"presets": presets}, ensure_ascii=False)

    @pyqtSlot(result=str)
    def get_icc_workflow_session_info(self) -> str:
        """
        获取当前 ICC Workflow 会话信息

        Returns:
            JSON 字符串: {"session_id": "...", "state": "...", ...}
        """
        if self._icc_workflow:
            return json.dumps(self._icc_workflow.get_session_info())
        return json.dumps({"state": "idle"})

    @pyqtSlot(result=str)
    def list_icc_recoverable_sessions(self) -> str:
        """
        列出可恢复的 ICC Workflow 会话

        Returns:
            JSON 字符串: {"sessions": [...]}
        """
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        measurements_dir = Path(project_root) / "measurements" / "sessions"

        sessions = list_recoverable_sessions(measurements_dir)
        return json.dumps({"sessions": sessions}, ensure_ascii=False)

    @pyqtSlot(str, result=bool)
    def provide_icc_measurement_data(self, measurements_json: str) -> bool:
        """
        为 ICC Workflow 提供测量数据

        用于 MeasurementService 集成模式下，从外部提供测量数据。

        Args:
            measurements_json: JSON 字符串，包含测量结果列表

        Returns:
            bool: 是否成功接收数据
        """
        if not self._icc_workflow:
            self.logMessage.emit(i18n.t("ICC Workflow 未运行，无法提供测量数据"))
            return False

        try:
            measurements = json.loads(measurements_json)
            workflow = self._icc_workflow

            # 检查当前状态
            if workflow.state != ICCWorkflowState.MEASURING:
                self.logMessage.emit(f"ICC Workflow 当前状态 {workflow.state.value} 无法接收测量数据")
                return False

            # 提供测量数据
            success = workflow.provide_measurement_data(measurements=measurements)

            if success:
                self.logMessage.emit(f"ICC Workflow 接收到 {len(measurements)} 个测量数据")

            return success

        except Exception as e:
            self._logger.error(f"提供 ICC 测量数据失败: {e}")
            return False

    @pyqtSlot(str, result=bool)
    def provide_icc_verification_data(self, verification_json: str) -> bool:
        """
        为 ICC Workflow 提供验证测量数据

        Args:
            verification_json: JSON 字符串，包含验证测量结果列表

        Returns:
            bool: 是否成功接收数据
        """
        if not self._icc_workflow:
            self.logMessage.emit(i18n.t("ICC Workflow 未运行，无法提供验证数据"))
            return False

        try:
            verification = json.loads(verification_json)
            workflow = self._icc_workflow

            # 检查当前状态
            if workflow.state != ICCWorkflowState.VERIFYING:
                self.logMessage.emit(f"ICC Workflow 当前状态 {workflow.state.value} 无法接收验证数据")

            return False

        except Exception as e:
            self._logger.error(f"提供 ICC 验证数据失败: {e}")
            return False

    # ========== AutoCal 自动校准闭环 Slot 方法 (P1 集成) ==========

    def _generate_uniformity_patches(self) -> dict:
        """
        生成均匀性测量的多点网格色块

        每个色块带 zone 定位信息 (x, y, size)：
        - x/y 为色块中心在屏幕上的 0-1 比例坐标（九宫格/25 宫格中心）
        - size 为色块面积占屏幕面积百分比
        色块命名 "U-r{row}c{col}"，供前端热力图解析。

        Returns:
            dict: 均匀性网格色块列表
        """
        grid = int(getattr(self, '_uniformity_grid', 3))
        grid = max(2, min(9, grid))
        level_pct = float(getattr(self, '_uniformity_level', 100))
        level_pct = max(5.0, min(100.0, level_pct))
        size_pct = float(getattr(self, '_uniformity_patch_size', 15.0))
        size_pct = max(3.0, min(50.0, size_pct))

        v = int(round(255 * level_pct / 100.0))
        patches = []
        for row in range(grid):
            for col in range(grid):
                x = (col + 0.5) / grid
                y = (row + 0.5) / grid
                patches.append({
                    "name": f"U-r{row}c{col}",
                    "rgb": [v, v, v],
                    "zone": [round(x, 4), round(y, 4), size_pct],
                })

        level_label = f"{int(level_pct)}% 灰" if level_pct < 100 else "白色"
        return {
            "mode": "uniformity",
            "groups": [{"label": f"均匀性 {grid}×{grid}（{level_label}）", "patches": patches}],
        }

    @pyqtSlot(int, float, float)
    def set_uniformity_config(self, grid: int, level: float, patch_size: float):
        """
        设置均匀性测量配置

        Args:
            grid: 网格边数（3 = 九点，5 = 25 点）
            level: 测量灰阶电平百分比（100 = 白场）
            patch_size: 每个色块面积占屏幕面积百分比
        """
        self._uniformity_grid = max(2, min(9, int(grid)))
        self._uniformity_level = max(5.0, min(100.0, float(level)))
        self._uniformity_patch_size = max(3.0, min(50.0, float(patch_size)))
        self.logMessage.emit(
            f"均匀性配置: {self._uniformity_grid}×{self._uniformity_grid} 网格, "
            f"{self._uniformity_level:.0f}% 电平, 色块面积 {self._uniformity_patch_size:.0f}%"
        )

    @pyqtSlot(str, float)
    def set_hdr_config(self, eotf: str, peak_nits: float):
        """
        设置 HDR 追踪模式配置

        Args:
            eotf: "PQ" 或 "HLG"
            peak_nits: 目标峰值亮度 (cd/m²)
        """
        self._hdr_eotf = "HLG" if str(eotf).upper() == "HLG" else "PQ"
        self._hdr_peak_nits = max(100.0, min(10000.0, float(peak_nits)))
        self.logMessage.emit(f"HDR 追踪配置: {self._hdr_eotf}, 峰值 {self._hdr_peak_nits:.0f} nits")

    @pyqtSlot(str, result=str)
    def analyze_hdr_eotf(self, payload_json: str) -> str:
        """
        分析 HDR EOTF 追踪测量（P3 集成）

        接收前端累积的 HDR 灰阶测量（patchName 形如 "HDR-173"），
        按 PQ/HLG 目标计算每点亮度误差（nits 与 %）与 ΔE ITP（BT.2124），
        输出可渲染的追踪报告。

        Args:
            payload_json: {
                "eotf": "PQ" | "HLG",
                "peak_nits": 1000,
                "measurements": [{"patchName": "HDR-173", "x":.., "y":.., "Y":..}, ...]
            }

        Returns:
            JSON: {"success": bool, "points": [...], "summary": {...}}
        """
        from src.color_science.transfer import apply_eotf
        from src.color_science import delta_e_itp_from_xyY

        try:
            payload = json.loads(payload_json) if payload_json else {}
            eotf = "HLG" if str(payload.get("eotf", "PQ")).upper() == "HLG" else "PQ"
            peak_nits = float(payload.get("peak_nits", 1000.0))
            measurements = payload.get("measurements", [])

            points = []
            for m in measurements:
                name = str(m.get("patchName", ""))
                if not name.startswith("HDR-"):
                    continue
                try:
                    code8 = int(name.split("-", 1)[1])
                except ValueError:
                    continue
                V = code8 / 255.0
                if eotf == "PQ":
                    L_target = apply_eotf(V, "PQ", L_max=10000.0)
                else:
                    L_target = apply_eotf(V, "HLG", Lw=peak_nits, Lb=0.0)

                Y = float(m.get("Y", 0.0))
                x, y = float(m.get("x", 0.3127)), float(m.get("y", 0.3290))
                err = Y - L_target
                err_pct = (err / L_target * 100.0) if L_target > 0 else 0.0
                itp = delta_e_itp_from_xyY((x, y, Y), (0.3127, 0.3290, L_target))

                points.append({
                    "code": code8,
                    "signal": round(V, 4),
                    "target_nits": round(L_target, 2),
                    "measured_nits": round(Y, 2),
                    "error_nits": round(err, 2),
                    "error_pct": round(err_pct, 1),
                    "delta_e_itp": round(itp["itp"], 2),
                    "delta_e_i": round(itp["i"], 2),
                    "delta_e_ct": round(itp["ct"], 2),
                    "x": x, "y": y,
                })

            points.sort(key=lambda p: p["code"])

            if points:
                abs_errs = [abs(p["error_nits"]) for p in points]
                summary = {
                    "point_count": len(points),
                    "mean_abs_error_nits": round(sum(abs_errs) / len(abs_errs), 2),
                    "max_abs_error_nits": round(max(abs_errs), 2),
                    "max_abs_error_point": points[abs_errs.index(max(abs_errs))]["code"],
                    "mean_delta_e_itp": round(sum(p["delta_e_itp"] for p in points) / len(points), 2),
                    "max_delta_e_itp": round(max(p["delta_e_itp"] for p in points), 2),
                    "peak_measured_nits": round(max(p["measured_nits"] for p in points), 1),
                }
            else:
                summary = {"point_count": 0}

            return json.dumps({
                "success": True,
                "eotf": eotf,
                "peak_nits": peak_nits,
                "points": points,
                "summary": summary,
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(result=str)
    def list_displays(self):
        """
        枚举系统显示器（供前端下拉选择）

        index 为 1-based，与 ArgyllCMS (dispwin/dispcal -d) 及 ICC workflow 的
        display_index 语义一致；current 标记色块窗口当前所在屏幕。

        Returns:
            JSON: {"displays": [{"index","name","model","manufacturer",
                                 "primary","width","height","current"}],
                   "current": int}
        """
        try:
            from PyQt6.QtWidgets import QApplication
            screens = QApplication.screens()
        except Exception as e:
            return json.dumps({"displays": [], "current": 1, "error": str(e)})

        current = self._get_patch_display_index()
        displays = []
        for i, s in enumerate(screens):
            try:
                name = s.name() or f"显示器 {i + 1}"
            except Exception:
                name = f"显示器 {i + 1}"
            model = ""
            manufacturer = ""
            try:
                model = s.model() or ""
            except Exception:
                model = ""
            try:
                manufacturer = s.manufacturer() or ""
            except Exception:
                manufacturer = ""
            displays.append({
                "index": i + 1,
                "name": name,
                "model": model,
                "manufacturer": manufacturer,
                "primary": bool(s.isPrimary()) if hasattr(s, "isPrimary") else (i == 0),
                "width": s.geometry().width(),
                "height": s.geometry().height(),
                "current": (i + 1 == current),
            })
        return json.dumps({"displays": displays, "current": current}, ensure_ascii=False)

    @pyqtSlot(int, bool)
    def display_control_connect(self, display_id: int = 1, allow_fake: bool = False):
        """
        连接显示器 DDC/CI 控制通道

        Args:
            display_id: 显示器序号 (1-based)
            allow_fake: DDC 不可用时降级为模拟适配器（演练模式）
        """
        try:
            result = self._autocal_service.connect_display(
                display_id=int(display_id), allow_fake=bool(allow_fake)
            )
        except Exception as e:
            result = {"success": False, "error": str(e), "capabilities": None, "is_fake": False}
        if result.get("is_fake"):
            self.logMessage.emit(i18n.t("警告: DDC/CI 不可用，已使用模拟适配器（仅演练，不会真正控制显示器）"))
        self._emit_json(self.displayControlUpdated, {"type": "connect", **result})

    @pyqtSlot()
    def display_control_disconnect(self):
        """断开显示器 DDC/CI 控制通道"""
        result = self._autocal_service.disconnect_display()
        self._emit_json(self.displayControlUpdated, {"type": "disconnect", **result})

    @pyqtSlot()
    def display_control_get_capabilities(self):
        """查询显示器控制能力集（亮度/对比度/RGB 增益等可写控制项）"""
        caps = self._autocal_service.get_capabilities()
        self._emit_json(self.displayControlUpdated, {
            "type": "capabilities",
            "connected": self._autocal_service.is_display_connected(),
            "capabilities": caps,
        })

    @pyqtSlot(str, int)
    def display_control_write(self, name: str, value: int):
        """写入单个显示器控制项（写前自动保存回滚快照）"""
        try:
            result = self._autocal_service.write_control(str(name), int(value))
        except AutoCalServiceError as e:
            result = {"success": False, "name": name, "error": str(e)}
        self._emit_json(self.displayControlUpdated, {"type": "write", **result})

    @pyqtSlot(str)
    def display_control_read(self, name: str):
        """读取单个显示器控制项当前值"""
        try:
            result = self._autocal_service.read_control(str(name))
        except AutoCalServiceError as e:
            result = {"success": False, "name": name, "error": str(e)}
        self._emit_json(self.displayControlUpdated, {"type": "read", **result})

    @pyqtSlot()
    def display_control_save_snapshot(self):
        """保存显示器控制值快照（用于回滚）"""
        try:
            result = self._autocal_service.save_snapshot(source="manual_ui")
        except AutoCalServiceError as e:
            result = {"success": False, "error": str(e)}
        self._emit_json(self.displayControlUpdated, {"type": "snapshot", **result})

    @pyqtSlot()
    def display_control_rollback(self):
        """回滚显示器控制值到最近快照"""
        try:
            result = self._autocal_service.rollback()
        except AutoCalServiceError as e:
            result = {"success": False, "error": str(e)}
        self._emit_json(self.displayControlUpdated, {"type": "rollback", **result})

    @pyqtSlot(str)
    def autocal_start(self, config_json: str):
        """
        启动自动校准闭环（后台线程执行，进度经 autocalStateChanged/autocalProgress 推送）

        Args:
            config_json: {
                "target": {
                    "white_point": "D65",        // D50/D55/D60/D65/D70/D75/native
                    "target_Y_white": 120,        // 目标白场亮度 cd/m²
                    "target_gamma": 2.2,
                    "delta_e_threshold": 2.0,
                    "target_duv_max": 0.005,
                    "max_iterations": 5
                },
                "config": {
                    "dry_run": false,             // 演练模式（不写入显示器）
                    "mode": "auto",               // auto/manual/hybrid
                    "max_iterations": 5,
                    "settling_time": 2.0,         // 写入后稳定等待（秒）
                    "grayscale_steps": 5,
                    "include_primaries": true,
                    "enable_rollback": true,
                    "enable_manual_guide": true
                },
                "display_name": "..."
            }
        """
        # 前置校验
        if self._autocal_service.is_running:
            self._emit_json(self.autocalFinished, {
                "success": False, "error": "校准已在运行中", "error_code": "ALREADY_RUNNING",
            })
            return

        if not self._argyll_controller or not self._argyll_controller.is_connected():
            self._emit_json(self.autocalFinished, {
                "success": False, "error": "探头未连接，请先连接探头", "error_code": "PROBE_NOT_CONNECTED",
            })
            return

        if not self._autocal_service.is_display_connected():
            self._emit_json(self.autocalFinished, {
                "success": False, "error": "显示器控制通道未连接，请先连接 DDC/CI",
                "error_code": "DISPLAY_NOT_CONNECTED",
            })
            return

        try:
            payload = json.loads(config_json) if config_json else {}
        except json.JSONDecodeError as e:
            self._emit_json(self.autocalFinished, {
                "success": False, "error": f"配置 JSON 解析失败: {e}", "error_code": "BAD_CONFIG",
            })
            return

        target_cfg = payload.get("target") or {}
        autocal_cfg = payload.get("config") or {}
        dry_run = bool(autocal_cfg.get("dry_run", False))

        self.logMessage.emit(
            f"启动自动校准闭环: 白点 {target_cfg.get('white_point', 'D65')}, "
            f"目标亮度 {target_cfg.get('target_Y_white', 100)} cd/m², "
            f"最多 {autocal_cfg.get('max_iterations', 5)} 轮迭代"
            + ("（演练模式，不写入显示器）" if dry_run else "")
        )
        self._emit_json(self.autocalProgress, {"percent": 0, "message": "启动自动校准..."})

        self._autocal_thread = threading.Thread(
            target=self._autocal_worker,
            args=(target_cfg, autocal_cfg),
            name="backend-autocal-thread",
            daemon=True,
        )
        self._autocal_thread.start()

    @pyqtSlot()
    def autocal_stop(self):
        """请求取消当前自动校准（在安全点停止）"""
        result = self._autocal_service.stop()
        self.logMessage.emit(result.get("message", ""))
        self._emit_json(self.autocalProgress, {"percent": -1, "message": result.get("message", "已请求取消")})

    @pyqtSlot()
    def autocal_get_status(self):
        """查询 AutoCal 服务状态"""
        self._emit_json(self.displayControlUpdated, {"type": "autocal_status", **self._autocal_service.get_status()})

    def _autocal_worker(self, target_cfg: Dict, autocal_cfg: Dict):
        """AutoCal 工作线程主体（阻塞执行闭环，完成后发 autocalFinished）"""
        try:
            session = self._autocal_service.start(
                self._autocal_measure_bridge, target_cfg, autocal_cfg
            )
            state = session.get("state", "failed")
            self._emit_json(self.autocalFinished, {
                "success": state == "completed",
                "state": state,
                "session": session,
            })
        except AutoCalServiceError as e:
            self._emit_json(self.autocalFinished, {
                "success": False, "error": str(e), "error_code": e.error_code,
            })
        except Exception as e:
            self._emit_json(self.autocalFinished, {
                "success": False, "error": f"自动校准异常: {e}", "error_code": "UNEXPECTED",
            })
        finally:
            # 收尾：隐藏色块（主线程）+ 清理显式色块名，避免影响后续单次测量
            self._autocalHidePatchSignal.emit()
            self._explicit_patch_name = None

    def _autocal_measure_bridge(self, rgb, name):
        """
        AutoCal 同步测量桥（在 AutoCal 工作线程中调用）

        流程：主线程显示色块 → 等待稳定延迟 → measure_sync 阻等待结果。
        测量结果同时会照常走正常管线（UI 实时显示测量值）。
        """
        if not self._argyll_controller or not self._argyll_controller.is_connected():
            raise RuntimeError("探头连接已断开")

        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])

        # 主线程显示色块（Qt 控件只能在主线程操作）
        self._autocalShowPatchSignal.emit(r, g, b)
        # 供正常测量管线记录（_process_measurement_in_main_thread 读取）
        self._current_patch_color = (r, g, b)
        self._current_patch_name = f"AutoCal-{name}"
        self._explicit_patch_name = self._current_patch_name
        self._argyll_controller.set_current_patch_rgb((r, g, b))

        # 等待显示器稳定（复用按探头/面板/亮度的动态延迟配置）
        try:
            delay_ms = self._auto_configure_delay(patch_rgb=(r, g, b))
        except Exception:
            delay_ms = 500
        time.sleep(max(delay_ms, 300) / 1000.0)

        result = self._argyll_controller.measure_sync(timeout=30.0)
        if result is None:
            raise RuntimeError(
                f"测量失败: {self._argyll_controller.get_error_message() or '超时'}"
            )

        x, y, Y = result
        return AutoCalMeasurementPoint(rgb=(r, g, b), name=name, xyY=(x, y, Y))

    @pyqtSlot(int, int, int)
    def _autocal_show_patch_in_main_thread(self, r: int, g: int, b: int):
        """在主线程显示 AutoCal 测量色块"""
        self._show_color(r, g, b)
        self.patchColorChanged.emit(json.dumps({"r": r, "g": g, "b": b}))

    def _on_autocal_state_change(self, old_state: str, new_state: str):
        """AutoCal 状态变化回调（工作线程 → 信号）"""
        self._emit_json(self.autocalStateChanged, {"state": new_state, "previous": old_state})

    def _on_autocal_progress(self, message: str, percent: float):
        """AutoCal 进度回调（工作线程 → 信号）"""
        self._emit_json(self.autocalProgress, {"percent": percent, "message": message})

    # ========== LUT Workflow Slot 方法 ==========

    def _init_lut_workflow(self, config: Optional['LUTWorkflowConfig'] = None) -> 'LUTWorkflow':
        """
        初始化 LUT Workflow 实例

        Args:
            config: LUT Workflow 配置（可选，从 JSON 解析）

        Returns:
            LUTWorkflow: 工作流实例
        """
        from src.workflows.lut_workflow import (
            LUTWorkflow,
            LUTWorkflowConfig,
            LUTWorkflowState,
            LUTType,
            GridSize,
            InterpolationMethod,
            TargetSpace,
            SourceSpacePreset,
            LUTSpec,
            LUTFormat,
        )
        from src.instruments.argyll_params import RenderingIntent

        # 获取 Argyll bin 路径
        argyll_path = None
        if self._argyll_controller:
            argyll_path = self._argyll_controller._argyll_path

        # 创建回调
        def on_state_change(old_state: LUTWorkflowState, new_state: LUTWorkflowState):
            """状态变化回调"""
            self._emit_json(self.lutWorkflowStateChanged, {
                "state": new_state.value,
                "previous": old_state.value,
            })

        def on_progress(current: int, total: int, message: str):
            """进度回调"""
            percent = int(current * 100 / total) if total > 0 else 0
            self._emit_json(self.lutWorkflowProgress, {
                "percent": percent,
                "current": current,
                "total": total,
                "step": message,
                "message": message,
            })

        def on_status(message: str):
            """状态消息回调"""
            self.logMessage.emit(message)

        def on_validation_request(patches: List[Tuple[int, int, int, str]]):
            """验证请求回调"""
            patch_list = [{"rgb": list(rgb), "name": name} for rgb, name in patches]
            self._emit_json(self.lutWorkflowValidationRequest, {
                "patch_count": len(patches),
                "patches": patch_list,
            })
            # 存储验证色块，等待外部提供测量数据
            self._lut_validation_patches = patches

        def on_completed(report: 'LUTGenerationReport'):
            """完成回调"""
            self._emit_json(self.lutWorkflowCompleted, {
                "success": report.success,
                "lut_path": report.output_path,
                "manifest_path": report.manifest_path,
                "generation_time_ms": report.generation_time_ms,
                "report": report.to_dict(),
            })

        # 如果没有提供 config，使用默认配置
        if not config:
            config = LUTWorkflowConfig(argyll_path=argyll_path or "")

        workflow = LUTWorkflow(
            config=config,
            on_progress=on_progress,
            on_status=on_status,
            on_state_change=on_state_change,
            on_validation_request=on_validation_request,
            on_completed=on_completed,
        )

        self._lut_workflow = workflow
        return workflow

    @pyqtSlot(str, result=str)
    def start_lut_workflow(self, config_json: str) -> str:
        """
        启动 LUT 工作流

        Args:
            config_json: JSON 字符串格式的 LUT Workflow 配置
                {
                    "lut_type": "3d",  // "1d" 或 "3d"
                    "source_space": "Rec709_Gamma24",  // 源色彩空间预设
                    "target_space": "Rec709",  // 目标色彩空间
                    "target_icc_path": "/path/to/icc",  // 目标 ICC 文件路径
                    "output_path": "/path/to/output.cube",  // 输出路径
                    "grid_size": 33,  // LUT Grid 尺寸: 17, 21, 33, 65
                    "interpolation": "trilinear",  // 插值方法: trilinear, tetrahedral
                    "intent": "r",  // 渲染意图: r, a, p, s
                    "use_bpc": true,  // 黑场补偿
                    "measurement_count": 500,  // 测量点数（用于密度校验）
                    "measurement_path": "/path/to/ti3",  // 测量数据路径
                    "auto_validate": true,  // 自动运行验证
                    "validation_patch_count": 50,  // 验证色块数
                }

        Returns:
            JSON 字符串: {"success": true, "session_id": "..."} 或
            {"success": false, "error": "...", "density_warning": {...}}
        """
        from src.workflows.lut_workflow import (
            LUTWorkflowConfig,
            LUTType,
            GridSize,
            InterpolationMethod,
            TargetSpace,
            SourceSpacePreset,
            LUTSpec,
            LUTFormat,
            check_measurement_density,
            LUTWorkflowState,
        )
        from src.instruments.argyll_params import RenderingIntent

        try:
            # 解析配置
            config_data = json.loads(config_json)

            # 构建 LUT Workflow 配置
            lut_type = LUTType(config_data.get("lut_type", "3d"))
            grid_size = GridSize(config_data.get("grid_size", 33))
            interpolation = InterpolationMethod(config_data.get("interpolation", "trilinear"))
            target_space = TargetSpace(config_data.get("target_space", "Rec709"))
            source_space = SourceSpacePreset(config_data.get("source_space", "Rec709_Gamma24"))
            intent = RenderingIntent(config_data.get("intent", "r"))

            lut_spec = LUTSpec(
                lut_type=lut_type,
                size=grid_size,
                interpolation=interpolation,
            )

            # 获取 Argyll bin 路径
            argyll_path = None
            if self._argyll_controller:
                argyll_path = self._argyll_controller._argyll_path

            config = LUTWorkflowConfig(
                lut_type=lut_type,
                source_space=source_space,
                target_space=target_space,
                target_icc_path=config_data.get("target_icc_path", ""),
                output_path=config_data.get("output_path", ""),
                lut_spec=lut_spec,
                intent=intent,
                use_bpc=config_data.get("use_bpc", True),
                argyll_path=argyll_path or "",
                session_dir=config_data.get("session_dir", ""),
                measurement_data_path=config_data.get("measurement_path", ""),
                auto_validate=config_data.get("auto_validate", True),
                validation_patch_count=config_data.get("validation_patch_count", 50),
            )

            measurement_count = config_data.get("measurement_count", 0)
            measurement_path = config_data.get("measurement_path", "")

            self.logMessage.emit("=== 启动 LUT Workflow ===")
            self.logMessage.emit(f"LUT 类型: {lut_type.value}")
            self.logMessage.emit(f"Grid 尺寸: {grid_size.value} ({grid_size.name})")
            self.logMessage.emit(f"源色彩空间: {source_space.value}")
            self.logMessage.emit(f"目标色彩空间: {target_space.value}")
            self.logMessage.emit(f"渲染意图: {intent.value}")
            self.logMessage.emit(f"黑场补偿: {config.use_bpc}")

            # 1. 检查测量点密度（生成前必须校验）
            if measurement_count > 0:
                density_result = check_measurement_density(
                    measurement_count,
                    lut_spec,
                    strict=False  # 非严格模式，发出警告但允许继续
                )

                if not density_result.sufficient:
                    self._emit_json(self.lutWorkflowDensityWarning, density_result.to_dict())
                    self.logMessage.emit(f"警告: 测量点密度不足")
                    self.logMessage.emit(density_result.recommendation)

            # 2. 初始化工作流
            workflow = self._init_lut_workflow(config)

            # 3. 启动工作流（创建 session）
            session = workflow.start(
                measurement_count=measurement_count,
                measurement_path=measurement_path,
            )

            self._lut_session_dir = str(workflow.session_dir) if workflow.session_dir else None

            self._emit_json(self.lutWorkflowSessionInfo, workflow.get_session_info())

            return json.dumps({
                "success": True,
                "session_id": session.session_id,
                "state": session.state.value,
                "session_dir": self._lut_session_dir,
            })

        except Exception as e:
            self._logger.error(f"启动 LUT Workflow 失败: {e}")
            self._emit_json(self.lutWorkflowFailed, {
                "error": str(e),
                "recoverable": False,
                "stage": "init",
            })
            return json.dumps({
                "success": False,
                "error": str(e),
            })

    @pyqtSlot(result=bool)
    def pause_lut_workflow(self) -> bool:
        """
        暂停 LUT Workflow

        保存 checkpoint，允许后续恢复。

        Returns:
            bool: 是否成功暂停
        """
        if not self._lut_workflow:
            return True

        try:
            workflow = self._lut_workflow

            # 暂停工作流（保存 checkpoint）
            success = workflow.pause()

            if success:
                self.logMessage.emit(i18n.t("LUT Workflow 已暂停"))
                self.logMessage.emit(f"Session 目录: {self._lut_session_dir}")
                self._emit_json(self.lutWorkflowStateChanged, {
                    "state": "suspended",
                    "previous": workflow.state.value if workflow.session else "unknown",
                })

            return success

        except Exception as e:
            self._logger.error(f"暂停 LUT Workflow 失败: {e}")
            return False

    @pyqtSlot(str, result=str)
    def resume_lut_workflow(self, session_dir: str) -> str:
        """
        从 checkpoint 恢复 LUT Workflow

        Args:
            session_dir: 会话目录路径（包含 checkpoint.json）

        Returns:
            JSON 字符串: {"success": true, "session_id": "..."} 或
            {"success": false, "error": "..."}
        """
        from src.workflows.lut_workflow import LUTWorkflowState

        try:
            # 初始化 LUT Workflow
            workflow = self._init_lut_workflow()

            # 恢复工作流
            session = workflow.resume(session_dir=Path(session_dir))

            # 保存会话目录
            self._lut_session_dir = str(workflow.session_dir) if workflow.session_dir else None

            # 发送恢复通知
            self.measurementResumed.emit()
            self._emit_json(self.lutWorkflowSessionInfo, workflow.get_session_info())

            self.logMessage.emit(f"恢复 LUT Workflow: {session.session_id}")
            self.logMessage.emit(f"恢复状态: {session.state.value}")

            return json.dumps({
                "success": True,
                "session_id": session.session_id,
                "state": session.state.value,
            })

        except Exception as e:
            self._logger.error(f"恢复 LUT Workflow 失败: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
            })

    @pyqtSlot(result=bool)
    def cancel_lut_workflow(self) -> bool:
        """
        取消 LUT Workflow

        不保存 checkpoint，清理当前状态。

        Returns:
            bool: 是否成功取消
        """
        if not self._lut_workflow:
            return True

        try:
            workflow = self._lut_workflow

            # 取消工作流
            success = workflow.cancel()

            if success:
                self.logMessage.emit(i18n.t("LUT Workflow 已取消"))
                self._emit_json(self.lutWorkflowStateChanged, {
                    "state": "cancelled",
                    "previous": workflow.state.value if workflow.session else "unknown",
                })

            # 清理状态
            self._lut_workflow = None
            self._lut_session_dir = None
            self._lut_workflow_config = None

            return success

        except Exception as e:
            self._logger.error(f"取消 LUT Workflow 失败: {e}")
            return False

    @pyqtSlot(result=str)
    def get_lut_workflow_session_info(self) -> str:
        """
        获取当前 LUT Workflow 会话信息

        Returns:
            JSON 字符串: {"session_id": "...", "state": "...", ...}
        """
        if self._lut_workflow:
            return json.dumps(self._lut_workflow.get_session_info())
        return json.dumps({"state": "idle"})

    @pyqtSlot(result=str)
    def get_lut_workflow_options(self) -> str:
        """
        获取可用的 LUT Workflow 选项列表

        Returns:
            JSON 字符串: {
                "lut_types": [...],
                "grid_sizes": [...],
                "interpolations": [...],
                "target_spaces": [...],
                "source_spaces": [...],
            }
        """
        from src.workflows.lut_workflow import (
            LUTType,
            GridSize,
            InterpolationMethod,
            TargetSpace,
            get_source_space_list,
            GRID_SIZE_CATEGORY,
        )

        return json.dumps({
            "lut_types": [
                {"value": t.value, "name": t.name}
                for t in LUTType
            ],
            "grid_sizes": [
                {
                    "value": s.value,
                    "name": s.name,
                    "category": GRID_SIZE_CATEGORY.get(s, "unknown"),
                    "min_measurements": {
                        "1d": 50,
                        "3d": s.value ** 3 // 10,  # 估算最小测量数
                    },
                }
                for s in [GridSize.SIZE_17, GridSize.SIZE_21, GridSize.SIZE_33, GridSize.SIZE_65]
            ],
            "interpolations": [
                {"value": i.value, "name": i.name}
                for i in InterpolationMethod
            ],
            "target_spaces": [
                {"value": t.value, "name": t.name}
                for t in TargetSpace
            ],
            "source_spaces": get_source_space_list(),
        }, ensure_ascii=False)

    @pyqtSlot(str, result=bool)
    def provide_lut_validation_data(self, validation_json: str) -> bool:
        """
        为 LUT Workflow 提供验证测量数据

        Args:
            validation_json: JSON 字符串，包含验证测量结果列表和 Delta E 值
                {
                    "measurements": [...],
                    "delta_e_values": [...],  // 可选
                }

        Returns:
            bool: 是否成功接收数据
        """
        if not self._lut_workflow:
            self.logMessage.emit(i18n.t("LUT Workflow 未运行，无法提供验证数据"))
            return False

        try:
            data = json.loads(validation_json)
            measurements = data.get("measurements", [])
            delta_e_values = data.get("delta_e_values")

            workflow = self._lut_workflow

            # 提供验证数据
            success = workflow.provide_validation_data(
                measurements=measurements,
                delta_e_values=delta_e_values,
            )

            if success:
                self.logMessage.emit(f"LUT Workflow 接收到 {len(measurements)} 个验证数据")

                # 如果有 Delta E 值，发送验证报告
                if delta_e_values:
                    avg = sum(delta_e_values) / len(delta_e_values)
                    max_val = max(delta_e_values)
                    self.logMessage.emit(f"验证结果: 平均 Delta E = {avg:.2f}, 最大 = {max_val:.2f}")

            return success

        except Exception as e:
            self._logger.error(f"提供 LUT 验证数据失败: {e}")
            return False

    @pyqtSlot(str, result=str)
    def run_lut_generation(self, config_json: str) -> str:
        """
        执行 LUT 生成（fake adapter 可用）

        这是一个简化接口，用于测试和快速生成 LUT。

        Args:
            config_json: JSON 字符串格式的 LUT 配置（同 start_lut_workflow）

        Returns:
            JSON 字符串: {"success": true, "report": {...}} 或
            {"success": false, "error": "..."}
        """
        # 首先启动工作流
        start_result = self.start_lut_workflow(config_json)
        start_data = json.loads(start_result)

        if not start_data.get("success"):
            return start_result

        # 执行生成（使用 start_lut_workflow 中解析的配置）
        if self._lut_workflow:
            try:
                from src.workflows.lut_workflow import LUTWorkflowState

                config_data = json.loads(config_json)
                measurement_count = config_data.get("measurement_count", 0)
                measurement_path = config_data.get("measurement_path", "")
                skip_density_check = config_data.get("skip_density_check", False)

                success, report = self._lut_workflow.generate(
                    measurement_count=measurement_count,
                    measurement_path=measurement_path,
                    skip_density_check=skip_density_check,
                )

                return json.dumps({
                    "success": success,
                    "report": report.to_dict() if report else {},
                    "lut_path": report.output_path if report else "",
                    "generation_time_ms": report.generation_time_ms if report else 0,
                })

            except Exception as e:
                self._logger.error(f"LUT 生成失败: {e}")
                return json.dumps({
                    "success": False,
                    "error": str(e),
                })

        return json.dumps({
            "success": False,
            "error": "LUT Workflow 未初始化",
        })
