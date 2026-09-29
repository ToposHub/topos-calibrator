"""
MainWindow - 主控制窗口
包含 QWebEngineView 用于渲染 Web UI
"""

import os
from pathlib import Path

from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel

from .backend import Backend
from .patch_window import PatchWindow
from .comparison_window import ComparisonWindow
from . import i18n


class MainWindow(QMainWindow):
    """
    主窗口，包含 Web UI 和控制逻辑
    """

    def __init__(self, patch_screen=None):
        super().__init__()

        self.patch_screen = patch_screen
        self.backend = None
        self.channel = None
        self.patch_window = None  # 独立浮动窗口
        self.comparison_window = None  # 数据对比窗口

        # 从持久化配置恢复语言（Web 端切换语言时也会经 backend.setLanguage 同步）
        i18n.init_from_settings()

        self._init_ui()
        self._setup_web_channel()
        self._create_patch_window()

    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle(i18n.t("Topos Calibrator - 显示器校正与测量"))
        self.setMinimumSize(1400, 900)

        # 设置深色主题
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0d0d14;
            }
        """)

        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局 - 只包含 Web UI
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Web UI
        self.web_view = QWebEngineView()
        main_layout.addWidget(self.web_view)

        # 禁用 HTTP 缓存（确保 JS/CSS 文件每次都重新加载）
        from PyQt6.QtWebEngineCore import QWebEngineProfile
        QWebEngineProfile.defaultProfile().setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)

        # 加载 HTML
        self._load_html()

    def _load_html(self):
        """加载本地 HTML 文件"""
        html_path = Path(__file__).parent.parent / "web" / "index.html"

        if html_path.exists():
            self.web_view.setUrl(QUrl.fromLocalFile(str(html_path)))
        else:
            self.web_view.setHtml(f"""
                <html>
                <body style="background: #0d0d14; color: white; font-family: sans-serif; padding: 20px;">
                    <h1>{i18n.t("错误: HTML 文件未找到")}</h1>
                    <p>{i18n.t("请确保文件存在")}: {html_path}</p>
                </body>
                </html>
            """)

    def _setup_web_channel(self):
        """设置 QWebChannel 通信"""
        self.backend = Backend()
        self.channel = QWebChannel()
        self.channel.registerObject("backend", self.backend)
        self.web_view.page().setWebChannel(self.channel)

        # 连接打开对比窗口的信号
        self.backend.openComparisonWindowRequested.connect(self._open_comparison_window)

    def _create_patch_window(self):
        """创建独立浮动窗口"""
        self.patch_window = PatchWindow(screen=self.patch_screen)

        # 将浮动窗口的引用传递给 backend
        self.backend.set_patch_window(self.patch_window)

    def _open_comparison_window(self):
        """打开数据对比窗口"""
        if self.comparison_window is None:
            self.comparison_window = ComparisonWindow()
            # 连接重命名信号，同步刷新主窗口的历史列表
            self.comparison_window.backend.measurementRenamed.connect(
                self._on_comparison_measurement_renamed
            )

        self.comparison_window.show()
        self.comparison_window.raise_()
        self.comparison_window.activateWindow()

    def _on_comparison_measurement_renamed(self):
        """处理对比窗口的重命名事件，刷新主窗口的历史列表"""
        if self.backend:
            self.backend.refresh_measurement_list()
            self.backend.logMessage.emit(i18n.t("主窗口历史列表已同步更新"))

    def get_backend(self) -> Backend:
        return self.backend

    def get_patch_window(self) -> PatchWindow:
        return self.patch_window

    def closeEvent(self, event):
        """
        窗口关闭事件 - 显式清理所有资源

        这是关键的生命周期管理点，确保：
        1. 停止所有正在进行的测量
        2. 显式断开探头连接（避免僵尸进程）
        3. 恢复显卡 LUT
        4. 关闭浮动窗口
        5. 清理 backend 资源
        """
        # ========== 1. 停止循环测量（如果正在进行） ==========
        if self.backend and self.backend._cycle_running:
            self.backend.logMessage.emit(i18n.t("窗口关闭：正在停止测量..."))
            self.backend.stop_cycle()

        # ========== 2. 显式断开探头连接 ==========
        # 这确保 spotread 进程被正确终止，不会变成僵尸进程
        if self.backend and self.backend._argyll_controller:
            if self.backend._argyll_controller.is_connected():
                self.backend.logMessage.emit(i18n.t("窗口关闭：正在断开探头连接..."))
                self.backend._argyll_controller.disconnect()

        # ========== 3. 恢复显卡 LUT 和卸载 Null Profile（如果测量被中断） ==========
        if self.backend and self.backend._lut_controller:
            display_index = self.backend._get_patch_display_index()
            # 卸载 Null Profile（如果已挂载）
            if self.backend._null_profile_applied and self.backend._linear_profile_path:
                self.backend.logMessage.emit(i18n.t("窗口关闭：正在卸载 Null Profile..."))
                self.backend._lut_controller.uninstall_profile(display_index, self.backend._linear_profile_path)
                self.backend._null_profile_applied = False
                # 加载系统当前 Profile 的 VCGT 以刷新显示
                self.backend.logMessage.emit(i18n.t("窗口关闭：正在加载系统 Profile VCGT..."))
                self.backend._lut_controller.load_system_profile_lut(display_index)
            elif self.backend._lut_controller._display_lut_cleared:
                # 如果没有使用 Null Profile，则恢复 LUT
                self.backend.logMessage.emit(i18n.t("窗口关闭：正在恢复显卡 LUT..."))
                self.backend._lut_controller.restore_lut(display_index)

        # ========== 4. 关闭浮动窗口 ==========
        if self.patch_window:
            self.patch_window.hide()
            self.patch_window.close()

        # ========== 4.1. 关闭对比窗口 ==========
        if self.comparison_window:
            self.comparison_window.close()

        # ========== 5. 清理 backend 资源 ==========
        if self.backend:
            # 显式清理 backend
            self.backend._cycle_timer.stop()
            self.backend._cycle_running = False

        super().closeEvent(event)