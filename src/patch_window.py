"""
PatchWindow - 测量窗口
用于显示测量色块，支持放大缩小、全屏、关闭等操作
确保窗口不受系统色彩配置文件影响，显示真实的显示器颜色

跨平台色彩管理策略（重构版）：
=====================

采用"系统级挂载 Null Profile"方案替代不稳定代码级 ColorSpace 强制转换：

1. 测色准备阶段：
   - 通过 DisplayLUTController.apply_linear_profile() 挂载线性 ICC Profile
   - 使显示器输出呈线性状态，绕过系统色彩管理
   - 同时清空 VCGT 显卡曲线

2. 校准完成/验证阶段：
   - 使用 dispwin -I 挂载新生成的校准 ICC Profile
   - 用户可查看真实的校准效果

3. 降级方案（用户未勾选"自动清除系统ICC"）：
   - 仅使用 dispwin -c 清除显卡 1D LUT
   - Windows/Linux 平台通常足够

窗口绘制策略（不变）：
- 使用 QPalette 直接设置颜色，绕过 Qt 的样式表色彩管理
- 在 paintEvent 中直接绘制颜色，绕过 Qt 的色彩管理

废弃方案：
- 已移除 pyobjc 的 NSColorSpace 强制设置代码（不稳定）
- macOS 不再需要代码级 ColorSpace 操作
"""

import sys
import json
import logging
import socket
import platform
import urllib.request
import urllib.error
import threading
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSizeGrip, QFrame
)
from PyQt6.QtCore import Qt, QSize, QPoint, QRect, QTimer
from PyQt6.QtGui import QColor, QPalette, QFont, QCursor, QPainter, QShortcut, QKeySequence

from . import i18n

logger = logging.getLogger(__name__)


class PatchWindow(QWidget):
    """
    测量窗口，用于显示测量色块
    支持拖拽移动、放大缩小、全屏显示
    确保显示真实的显示器颜色（尽量不受色彩配置文件影响）
    
    色彩管理策略：
    1. 使用 QPalette 直接设置背景色，避免样式表的色彩转换
    2. 设置窗口表面格式为默认色彩空间
    3. 在 paintEvent 中直接绘制颜色，绕过 Qt 的色彩管理
    4. 提供警告提示，建议用户在测量时禁用系统色彩配置
    """

    def __init__(self, screen=None):
        super().__init__()

        self.current_color = (0, 0, 0)
        self._drag_position = None

        # ========== 窗口置顶守护 ==========
        # 用于在长时间测量过程中定期强制将窗口置于最前
        # 防止其他软件弹窗抢占前台
        self._guardian_timer = QTimer(self)
        self._guardian_timer.timeout.connect(self._enforce_top)
        self._guardian_interval = 2000  # 默认 2 秒检查一次
        self._guardian_active = False

        # 设置窗口属性 - 尝试禁用色彩管理
        self._setup_color_management()

        # 设置窗口标志
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        # 如果指定了屏幕，移动到该屏幕
        if screen:
            self.move_to_screen(screen)

        # 初始化 UI
        self._init_ui()

        # 设置初始颜色为黑色
        self.set_color(0, 0, 0)

    def _setup_color_management(self):
        """
        设置窗口以尽量禁用色彩管理
        确保显示真实的显示器颜色

        策略（重构版）：
        - 所有平台：通过 QPalette 和直接绘制绕过 Qt 色彩管理
        - 系统级色彩管理绕过由 DisplayLUTController 通过 dispwin 实现
        - macOS 不再需要代码级 NSColorSpace 操作（已废弃）
        """
        # QWidget 不支持 setFormat，跳过表面格式设置
        # 色彩管理主要通过 QPalette 和直接绘制来控制

        # 禁用 Qt 的自动色彩管理属性
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # 设置窗口不接受色彩配置文件
        # 注意：这个属性在某些平台上可能不完全有效
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)

        # 初始化 palette 为纯黑色
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0))
        self.setPalette(palette)

    def _init_ui(self):
        """初始化界面"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ========== 控制栏（顶部） ==========
        self.control_bar = QFrame()
        self.control_bar.setObjectName("controlBar")
        self.control_bar.setFixedHeight(36)
        self.control_bar.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        control_layout = QHBoxLayout(self.control_bar)
        control_layout.setContentsMargins(12, 4, 12, 4)
        control_layout.setSpacing(8)

        # 弹簧（左侧）
        control_layout.addStretch()

        # 放大按钮
        self.btn_zoom_in = QPushButton("＋")
        self.btn_zoom_in.setObjectName("btnZoomIn")
        self.btn_zoom_in.setFixedSize(28, 28)
        self.btn_zoom_in.setToolTip("放大窗口")
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        control_layout.addWidget(self.btn_zoom_in)

        # 缩小按钮
        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setObjectName("btnZoomOut")
        self.btn_zoom_out.setFixedSize(28, 28)
        self.btn_zoom_out.setToolTip("缩小窗口")
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        control_layout.addWidget(self.btn_zoom_out)

        # 全屏按钮：进入全屏测量模式（整个屏幕显示为纯色色块）
        self.btn_fullscreen = QPushButton("⤢")
        self.btn_fullscreen.setObjectName("btnFullscreen")
        self.btn_fullscreen.setFixedSize(28, 28)
        self.btn_fullscreen.setToolTip("全屏测量：整个屏幕显示为纯色色块（ESC 退出）")
        self.btn_fullscreen.clicked.connect(self.show_fullscreen_patch)
        control_layout.addWidget(self.btn_fullscreen)
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("btnClose")
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setToolTip("关闭窗口")
        self.btn_close.clicked.connect(self.hide_patch)
        control_layout.addWidget(self.btn_close)

        main_layout.addWidget(self.control_bar)

        # ========== 色块显示区域 ==========
        # 使用自定义绘制的 widget，直接绘制颜色
        self.patch_area = ColorPatchWidget()
        self.patch_area.setObjectName("patchArea")
        main_layout.addWidget(self.patch_area, 1)

        # ========== RGB 数值标签（底部居中） ==========
        self.color_label = QLabel("RGB(0, 0, 0)")
        self.color_label.setObjectName("colorLabel")
        self.color_label.setFont(QFont("SF Mono", 11))
        self.color_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.color_label)

        # ========== 大小调整手柄（右下角） ==========
        self.size_grip = QSizeGrip(self)
        self.size_grip.setObjectName("sizeGrip")
        self.size_grip.setFixedSize(20, 20)

        # ========== 全屏模式退出按钮（悬浮，不在布局中） ==========
        # 全屏测量时控制栏整体隐藏，若不保留独立出口，
        # 用户将没有任何办法退回窗口模式（ESC 还可能因焦点不在窗口而失效）
        self.btn_exit_fullscreen = QPushButton(i18n.t("✕ 退出全屏 (ESC)"), self)
        self.btn_exit_fullscreen.setObjectName("btnExitFullscreen")
        self.btn_exit_fullscreen.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_exit_fullscreen.setToolTip(i18n.t("退出全屏测量模式"))
        self.btn_exit_fullscreen.setVisible(False)
        self.btn_exit_fullscreen.clicked.connect(self.exit_fullscreen_patch)
        self.btn_exit_fullscreen.setStyleSheet("""
            QPushButton#btnExitFullscreen {
                background-color: rgba(30, 30, 45, 160);
                color: rgba(255, 255, 255, 190);
                border: 1px solid rgba(255, 255, 255, 60);
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
            }
            QPushButton#btnExitFullscreen:hover {
                background-color: rgba(60, 60, 80, 220);
                color: white;
                border-color: rgba(255, 255, 255, 120);
            }
        """)

        # ESC 快捷键：窗口处于激活状态时无论焦点在哪个子控件都能退出全屏
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.activated.connect(self._handle_escape)

        # ========== 全屏模式底部悬浮控制条（半透明，不挡中心测量区） ==========
        # 左侧：实时测量进度（由 backend 测量信号驱动）
        # 右侧：停止测量按钮（点击后停止并退回窗口模式）
        # 全屏测量（含未来均匀度测量）时主窗口被覆盖，没有它用户既看不到
        # 进度也无法停止测量
        self._stop_callback = None
        self._measuring_active = False
        self._overlay_text = ""

        self.progress_overlay = QFrame(self)
        self.progress_overlay.setObjectName("progressOverlay")
        self.progress_overlay.setVisible(False)
        overlay_layout = QHBoxLayout(self.progress_overlay)
        overlay_layout.setContentsMargins(16, 8, 16, 8)

        self.progress_label = QLabel(i18n.t("准备测量"))
        self.progress_label.setObjectName("progressLabel")
        overlay_layout.addWidget(self.progress_label)
        overlay_layout.addStretch()

        # 引导式测量确认按钮（均匀性等需人工移动探头的场景，默认隐藏）
        self._confirm_callback = None
        self.btn_confirm_measure = QPushButton(i18n.t("✓ 测量此点 (空格)"))
        self.btn_confirm_measure.setObjectName("btnConfirmMeasure")
        self.btn_confirm_measure.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_confirm_measure.setToolTip("确认探头已对准当前区域，开始测量")
        self.btn_confirm_measure.setVisible(False)
        self.btn_confirm_measure.clicked.connect(self._request_confirm)
        overlay_layout.addWidget(self.btn_confirm_measure)

        self.btn_stop_measure = QPushButton(i18n.t("⏹ 停止测量"))
        self.btn_stop_measure.setObjectName("btnStopMeasure")
        self.btn_stop_measure.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_stop_measure.setToolTip("停止测量并退出全屏")
        self.btn_stop_measure.clicked.connect(self._request_stop)
        overlay_layout.addWidget(self.btn_stop_measure)

        # 空格/回车快捷键：引导式测量确认（仅确认按钮可见时生效）
        self._confirm_shortcut_space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._confirm_shortcut_space.activated.connect(self._shortcut_confirm)
        self._confirm_shortcut_return = QShortcut(QKeySequence(Qt.Key.Key_Return), self)
        self._confirm_shortcut_return.activated.connect(self._shortcut_confirm)

        self.progress_overlay.setStyleSheet("""
            QFrame#progressOverlay {
                background-color: rgba(15, 15, 25, 195);
                border-top: 1px solid rgba(255, 255, 255, 45);
            }
            QLabel#progressLabel {
                color: rgba(255, 255, 255, 225);
                font-size: 13px;
                font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
                background: transparent;
            }
            QPushButton#btnStopMeasure {
                background-color: rgba(220, 60, 60, 0.85);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#btnStopMeasure:hover {
                background-color: rgba(238, 82, 82, 0.95);
            }
            QPushButton#btnConfirmMeasure {
                background-color: rgba(16, 185, 129, 0.9);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#btnConfirmMeasure:hover {
                background-color: rgba(22, 200, 120, 1.0);
            }
        """)

        # 应用样式
        self._apply_style()

        # 启用鼠标跟踪
        self.setMouseTracking(True)

    def _apply_style(self):
        """应用窗口样式 - 只应用于控制栏，不应用于色块区域"""
        self.setStyleSheet("""
            /* 控制栏样式 */
            QFrame#controlBar {
                background-color: rgba(30, 30, 45, 200);
                border-bottom: 1px solid rgba(60, 60, 80, 150);
            }

            /* 颜色信息标签（底部） */
            QLabel#colorLabel {
                color: rgba(255, 255, 255, 200);
                font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
                font-size: 11px;
                padding: 8px 12px;
                background-color: rgba(30, 30, 45, 200);
                border-top: 1px solid rgba(60, 60, 80, 150);
            }

            /* 控制按钮通用样式 */
            QPushButton#btnZoomIn,
            QPushButton#btnZoomOut,
            QPushButton#btnFullscreen,
            QPushButton#btnClose {
                background-color: rgba(50, 50, 70, 180);
                border: 1px solid rgba(80, 80, 100, 150);
                border-radius: 6px;
                color: rgba(255, 255, 255, 200);
                font-size: 14px;
                font-weight: bold;
            }

            QPushButton#btnZoomIn:hover,
            QPushButton#btnZoomOut:hover,
            QPushButton#btnFullscreen:hover {
                background-color: rgba(70, 70, 90, 200);
                border-color: rgba(100, 100, 120, 180);
                color: white;
            }

            QPushButton#btnClose:hover {
                background-color: rgba(220, 60, 60, 200);
                border-color: rgba(255, 80, 80, 180);
                color: white;
            }

            QPushButton#btnZoomIn:pressed,
            QPushButton#btnZoomOut:pressed,
            QPushButton#btnFullscreen:pressed,
            QPushButton#btnClose:pressed {
                background-color: rgba(40, 40, 60, 180);
            }

            /* 大小调整手柄 */
            QSizeGrip#sizeGrip {
                background: transparent;
            }
        """)

    def set_color(self, r: int, g: int, b: int):
        """
        设置窗口背景色
        使用直接绘制方式，尽量绕过色彩管理

        Args:
            r: 红色分量 (0-255)
            g: 绿色分量 (0-255)
            b: 蓝色分量 (0-255)
        """
        self.current_color = (r, g, b)

        # 直接设置色块区域的颜色（使用自定义绘制）
        self.patch_area.set_color(r, g, b)

        # 更新颜色信息标签
        self.color_label.setText(f"RGB({r}, {g}, {b})")

        # 根据背景亮度调整控制栏和标签颜色
        brightness = (r + g + b) / 3

        if brightness < 128:
            # 深色背景 - 使用浅色文字和半透明深色控制栏
            self.control_bar.setStyleSheet("""
                QFrame#controlBar {
                    background-color: rgba(30, 30, 45, 200);
                    border-bottom: 1px solid rgba(60, 60, 80, 150);
                }
            """)
            self.color_label.setStyleSheet("""
                QLabel#colorLabel {
                    color: rgba(255, 255, 255, 200);
                    background-color: rgba(30, 30, 45, 200);
                    border-top: 1px solid rgba(60, 60, 80, 150);
                }
            """)
            # 重置按钮样式为深色主题
            self._set_dark_button_style()
        else:
            # 浅色背景 - 使用深色文字和半透明浅色控制栏
            self.control_bar.setStyleSheet("""
                QFrame#controlBar {
                    background-color: rgba(240, 240, 245, 200);
                    border-bottom: 1px solid rgba(200, 200, 210, 150);
                }
            """)
            self.color_label.setStyleSheet("""
                QLabel#colorLabel {
                    color: rgba(0, 0, 0, 200);
                    background-color: rgba(240, 240, 245, 200);
                    border-top: 1px solid rgba(200, 200, 210, 150);
                }
            """)
            # 设置按钮为浅色主题
            self._set_light_button_style()

        self.update()

    def _set_dark_button_style(self):
        """设置深色主题按钮样式"""
        self.setStyleSheet("""
            QFrame#controlBar {
                background-color: rgba(30, 30, 45, 200);
                border-bottom: 1px solid rgba(60, 60, 80, 150);
            }
            QLabel#colorLabel {
                color: rgba(255, 255, 255, 200);
                background-color: rgba(30, 30, 45, 200);
                border-top: 1px solid rgba(60, 60, 80, 150);
            }
            QPushButton#btnZoomIn,
            QPushButton#btnZoomOut,
            QPushButton#btnFullscreen,
            QPushButton#btnClose {
                background-color: rgba(50, 50, 70, 180);
                border: 1px solid rgba(80, 80, 100, 150);
                border-radius: 6px;
                color: rgba(255, 255, 255, 200);
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#btnZoomIn:hover,
            QPushButton#btnZoomOut:hover,
            QPushButton#btnFullscreen:hover {
                background-color: rgba(70, 70, 90, 200);
                border-color: rgba(100, 100, 120, 180);
                color: white;
            }
            QPushButton#btnClose:hover {
                background-color: rgba(220, 60, 60, 200);
                border-color: rgba(255, 80, 80, 180);
                color: white;
            }
            QPushButton#btnZoomIn:pressed,
            QPushButton#btnZoomOut:pressed,
            QPushButton#btnFullscreen:pressed,
            QPushButton#btnClose:pressed {
                background-color: rgba(40, 40, 60, 180);
            }
            QSizeGrip#sizeGrip {
                background: transparent;
            }
        """)

    def _set_light_button_style(self):
        """设置浅色主题按钮样式"""
        self.setStyleSheet("""
            QFrame#controlBar {
                background-color: rgba(240, 240, 245, 200);
                border-bottom: 1px solid rgba(200, 200, 210, 150);
            }
            QLabel#colorLabel {
                color: rgba(0, 0, 0, 200);
                background-color: rgba(240, 240, 245, 200);
                border-top: 1px solid rgba(200, 200, 210, 150);
            }
            QPushButton#btnZoomIn,
            QPushButton#btnZoomOut,
            QPushButton#btnFullscreen,
            QPushButton#btnClose {
                background-color: rgba(180, 180, 190, 180);
                border: 1px solid rgba(150, 150, 160, 150);
                border-radius: 6px;
                color: rgba(0, 0, 0, 200);
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#btnZoomIn:hover,
            QPushButton#btnZoomOut:hover,
            QPushButton#btnFullscreen:hover {
                background-color: rgba(160, 160, 170, 200);
                border-color: rgba(130, 130, 140, 180);
                color: rgba(0, 0, 0, 220);
            }
            QPushButton#btnClose:hover {
                background-color: rgba(220, 60, 60, 200);
                border-color: rgba(255, 80, 80, 180);
                color: white;
            }
            QPushButton#btnZoomIn:pressed,
            QPushButton#btnZoomOut:pressed,
            QPushButton#btnFullscreen:pressed,
            QPushButton#btnClose:pressed {
                background-color: rgba(140, 140, 150, 180);
            }
            QSizeGrip#sizeGrip {
                background: transparent;
            }
        """)

    def _zoom_in(self):
        """放大窗口"""
        current_size = self.size()
        new_width = min(current_size.width() + 100, 16384)
        new_height = min(current_size.height() + 100, 16384)
        self.resize(new_width, new_height)

    def _zoom_out(self):
        """缩小窗口"""
        current_size = self.size()
        new_width = max(current_size.width() - 100, 200)
        new_height = max(current_size.height() - 100, 200)
        self.resize(new_width, new_height)

    def _center_on_screen(self):
        """将窗口居中到当前屏幕"""
        screen = self.screen()
        if screen:
            geometry = screen.geometry()
            x = geometry.x() + (geometry.width() - self.width()) // 2
            y = geometry.y() + (geometry.height() - self.height()) // 2
            self.move(x, y)

    def show_resizable(self, width: int = 400, height: int = 400):
        """
        显示可调整大小的测量窗口

        Args:
            width: 初始宽度
            height: 初始高度
        """
        self.setMinimumSize(200, 200)
        # 上限不能太小：全屏测量前会 resize 到屏幕逻辑尺寸（4K 屏为 3840×2160），
        # 若上限低于屏幕尺寸，全屏内容会被钳制成小方块铺不满屏幕
        self.setMaximumSize(16384, 16384)
        self.resize(width, height)

        # 居中显示
        self._center_on_screen()

        # 显示控制栏和大小调整手柄
        self.control_bar.show()
        self.size_grip.show()

        self.show()
        self.raise_()

    def show_fixed_size(self, width: int = 400, height: int = 400):
        """
        显示固定大小的测量窗口

        Args:
            width: 窗口宽度
            height: 窗口高度
        """
        self.setFixedSize(width, height)

        # 居中显示
        self._center_on_screen()

        # 显示控制栏，隐藏大小调整手柄
        self.control_bar.show()
        self.size_grip.hide()

        self.show()
        self.raise_()

    def show_fullscreen(self):
        """显示窗口"""
        self.show()
        self.raise_()

    def show_fullscreen_patch(self):
        """
        进入全屏测量模式

        隐藏控制栏和 RGB 标签，整个屏幕作为一个纯色色块显示，
        确保测量探头完全落在纯色区域内（不受边框、控制栏干扰）。
        按 ESC / 双击 / 右上角"退出全屏"按钮退出。
        """
        # 记录进入全屏前的几何，退出时显式还原。
        # 窗口从未显示过时 geometry() 是无意义的默认值（0,0,640,480），
        # 先按浮动尺寸初始化，保证退出后还原到合理位置
        if not self.isVisible():
            self.show_resizable(400, 400)
        self._pre_fullscreen_geometry = self.geometry()

        screen = self.screen()
        if screen is None:
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()

        # ===== 几何模拟全屏，禁用 showFullScreen =====
        # macOS 对置顶工具窗口（Tool + StaysOnTop）调用 showFullScreen 会
        # 切入系统全屏"空间"：退出后应用被困在纯黑背景的空间里，主窗口
        # 看起来"消失"（Qt 仍报告 visible=True，实际留在另一个空间）。
        # 本窗口本就无边框 + 置顶，直接把几何铺满屏幕即可达到纯色全屏效果，
        # 完全不涉及系统空间切换，退出即普通还原。
        if screen:
            self.setGeometry(screen.geometry())

        self.control_bar.hide()
        self.color_label.hide()
        self.size_grip.hide()
        self.show()
        self.raise_()
        self._fullscreen_emulated = True

        # macOS：系统级隐藏菜单栏与 Dock（标准 kiosk 机制），
        # 配合无边框窗口铺满屏幕即为真正的全屏效果。
        # 注意不要用 NSWindow setLevel 提层级——Qt 托管的窗口降回普通层级后
        # 会被 Window Server 拒绝合成（Qt 显示 visible 但永不渲染）。
        if platform.system() == 'Darwin':
            self._set_fullscreen_presentation(True)

        # 全屏模式下的独立出口：右上角悬浮"退出全屏"按钮
        # （控制栏已隐藏，没有它 + ESC 失焦时用户将无法退回窗口模式）
        self._position_exit_button()
        self.btn_exit_fullscreen.show()
        self.btn_exit_fullscreen.raise_()

        # 全屏期间测量中：显示底部悬浮控制条（进度 + 停止）
        if self._measuring_active:
            self._position_progress_overlay()
            self.progress_overlay.show()
            self.progress_overlay.raise_()

        # 抢占键盘焦点，确保 ESC 能送达本窗口
        self.activateWindow()
        self.setFocus()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _position_progress_overlay(self):
        """把测量控制条定位到窗口底部，横向铺满"""
        bar_height = 44
        self.progress_overlay.setGeometry(
            0, self.height() - bar_height, self.width(), bar_height
        )

    # ========== 全屏测量控制条（信号驱动） ==========

    def set_stop_callback(self, callback):
        """注入停止测量的回调（由 backend 提供）"""
        self._stop_callback = callback

    def set_confirm_callback(self, callback):
        """注入引导式测量确认回调（由 backend 提供）"""
        self._confirm_callback = callback

    def _request_stop(self):
        """停止测量按钮：回调 backend 停止测量并退回窗口模式"""
        if self._stop_callback:
            self._stop_callback()

    def _shortcut_confirm(self):
        """空格/回车：等价于点击确认按钮（仅按钮可见时）"""
        if self.btn_confirm_measure.isVisible():
            self._request_confirm()

    def _request_confirm(self):
        """引导式测量确认：回调 backend 测量当前点"""
        self.btn_confirm_measure.hide()
        if self._confirm_callback:
            self._confirm_callback()

    def on_measurement_started(self, patch_name: str):
        """backend.measurementStarted 信号：显示控制条"""
        self._measuring_active = True
        self._overlay_text = f"正在测量: {patch_name}"
        self.progress_label.setText(self._overlay_text)
        self.btn_confirm_measure.hide()  # 已开始测量，隐藏确认按钮
        if self.is_fullscreen_patch():
            self._position_progress_overlay()
            self.progress_overlay.show()
            self.progress_overlay.raise_()

    def on_cycle_progress(self, progress_json: str):
        """backend.cycleMeasurementProgress 信号：更新进度文本"""
        try:
            progress = json.loads(progress_json)
            name = progress.get('patchName', '')
            current = progress.get('current', 0)
            total = progress.get('total', 0)
            self._measuring_active = True

            # 引导式测量：等待确认时给出明确提示并显示确认按钮
            if progress.get('guided') and progress.get('waitingConfirm'):
                self._overlay_text = f"请将探头对准 {name} 区域 · {current}/{total} · 确认后测量"
            else:
                self._overlay_text = f"{name} · {current}/{total}"
            self.progress_label.setText(self._overlay_text)

            waiting = bool(progress.get('guided') and progress.get('waitingConfirm'))
            self.btn_confirm_measure.setVisible(waiting)

            if self.is_fullscreen_patch():
                # 循环路径不发 measurementStarted，首次进度信号时需定位
                self._position_progress_overlay()
                self.progress_overlay.show()
                self.progress_overlay.raise_()
        except Exception:
            pass

    def on_measurement_completed(self):
        """backend.measurementCompleted 信号：隐藏控制条"""
        self._measuring_active = False
        self._overlay_text = ""
        self.btn_confirm_measure.hide()
        self.progress_overlay.hide()

    def _set_fullscreen_presentation(self, enable: bool):
        """macOS：全屏测量期间隐藏系统菜单栏与 Dock，退出时恢复"""
        if platform.system() != 'Darwin':
            return
        try:
            import AppKit
            app = AppKit.NSApplication.sharedApplication()
            if enable:
                self._saved_presentation = int(app.presentationOptions())
                hide_dock = AppKit.NSApplicationPresentationHideDock
                hide_menu_bar = AppKit.NSApplicationPresentationHideMenuBar
                app.setPresentationOptions_(self._saved_presentation | hide_dock | hide_menu_bar)
            else:
                app.setPresentationOptions_(getattr(self, '_saved_presentation', 0))
        except Exception as e:
            logger.warning(f"设置系统呈现选项失败: {e}")

    def is_fullscreen_patch(self):
        """是否处于（几何模拟的）全屏测量模式"""
        return getattr(self, '_fullscreen_emulated', False)

    def _position_exit_button(self):
        """把退出按钮定位到窗口右上角"""
        self.btn_exit_fullscreen.adjustSize()
        margin = 16
        self.btn_exit_fullscreen.move(
            self.width() - self.btn_exit_fullscreen.width() - margin,
            margin
        )

    def _handle_escape(self):
        """ESC / 快捷键：退出全屏测量模式，非全屏时隐藏窗口"""
        if self.is_fullscreen_patch():
            self.exit_fullscreen_patch()
        else:
            self.hide_patch()

    def exit_fullscreen_patch(self):
        """退出全屏测量模式，恢复控制栏和标签（同时清除均匀性 zone 定位）"""
        self.patch_area.clear_zone()
        self.btn_confirm_measure.hide()
        if self.is_fullscreen_patch():
            self._fullscreen_emulated = False
            pre = getattr(self, '_pre_fullscreen_geometry', None)
            if pre is not None:
                self.setGeometry(pre)
            if platform.system() == 'Darwin':
                self._set_fullscreen_presentation(False)
                self.raise_()
        self.btn_exit_fullscreen.hide()
        # 控制条仅属于全屏模式（测量信号重新驱动显示）
        self.progress_overlay.hide()
        self.control_bar.show()
        self.color_label.show()
        self.size_grip.show()

    def move_to_screen(self, screen):
        """将窗口移动到指定屏幕"""
        if screen:
            geometry = screen.geometry()
            self.move(geometry.x(), geometry.y())

    def hide_patch(self):
        """隐藏色块窗口"""
        # 若处于全屏测量模式，先恢复正常窗口状态，避免残留全屏 UI 状态
        self.exit_fullscreen_patch()
        # 隐藏窗口时停止置顶守护
        self.stop_guardian()
        self.hide()

    # ========== 窗口置顶守护 ==========

    def start_guardian(self, interval_ms: int = 2000):
        """
        启动窗口置顶守护

        在长时间测量过程中，定期将窗口强制置顶，
        防止其他软件弹窗抢占前台，确保色块窗口始终可见。

        Args:
            interval_ms: 检查间隔（毫秒），默认 2000ms（2秒）
        """
        if self._guardian_active:
            logger.warning("窗口置顶守护已处于活动状态")
            return

        self._guardian_interval = interval_ms
        self._guardian_timer.start(interval_ms)
        self._guardian_active = True

        logger.info(f"窗口置顶守护已启动 (间隔: {interval_ms}ms)")

        # 立即执行一次置顶
        self._enforce_top()

    def stop_guardian(self):
        """
        停止窗口置顶守护

        测量结束后应调用此方法停止守护，
        避免持续消耗系统资源。
        """
        if not self._guardian_active:
            return

        self._guardian_timer.stop()
        self._guardian_active = False

        logger.info("窗口置顶守护已停止")

    def _enforce_top(self):
        """
        强制将窗口置于最前

        通过 raise_() 和 activateWindow() 组合，
        确保窗口在所有其他窗口之上。
        """
        if not self.isVisible():
            return

        # 强制提升窗口层级
        self.raise_()

        # 尝试激活窗口（获取焦点）
        # 注意：在某些平台上 activateWindow() 可能不会实际获取焦点
        # 但它可以帮助提升窗口的视觉层级
        self.activateWindow()

        logger.debug("窗口置顶守护：执行置顶操作")

    def get_current_color(self) -> tuple:
        """获取当前显示的颜色"""
        return self.current_color

    # ========== OLED Window Patch ==========

    def set_zone(self, x: float, y: float, size_percent: float = 15.0):
        """
        均匀性测量：把色块定位到屏幕比例坐标 (x, y)

        Args:
            x: 色块中心 x（0-1，占屏幕宽度比例）
            y: 色块中心 y（0-1，占屏幕高度比例）
            size_percent: 色块面积百分比（1-100）
        """
        self.patch_area.set_zone(x, y, size_percent)

    def clear_zone(self):
        """退出均匀性 zone 模式"""
        self.patch_area.clear_zone()

    def set_oled_window_size_percent(self, percent: int):
        """
        设置 OLED 色块窗口大小百分比

        OLED 显示器进行 HDR 测量时需要使用较小的色块窗口
        （10% 或 18%）来避免 ABL (Automatic Brightness Limiter) 影响。

        业内标准是使用 10% 面积的窗口色块，其余屏幕保持纯黑。
        这样可以避免 OLED 的 ABL 机制降低高亮色块的亮度，
        确保 HDR 测量的准确性。

        Args:
            percent: 色块窗口面积百分比（1-100），默认 100%
                    - 10: 10% 窗口（HDR 标准测量）
                    - 18: 18% 窗口（某些显示器）
                    - 100: 全屏（默认，非 HDR）
        """
        if percent < 1:
            percent = 1
        elif percent > 100:
            percent = 100

        logger.info(f"PatchWindow: OLED 窗口大小设置为 {percent}%")

        # 将整数转换为浮点数传递给 ColorPatchWidget
        self.patch_area.set_oled_window_size(float(percent))

    def get_oled_window_size_percent(self) -> int:
        """获取当前 OLED 窗口大小百分比"""
        return int(self.patch_area.get_oled_window_size())

    def is_oled_window_mode(self) -> bool:
        """检查是否处于 OLED 窗口模式"""
        return self.patch_area.is_oled_window_mode()

    def show_black_frame(self, duration_ms: int = 100):
        """
        显示黑帧（用于 OLED BFI）

        OLED 显示器在高亮度色块之间插入黑帧可以：
        - 重置 ABL 状态
        - 减少像素老化
        - 提高测量稳定性

        Args:
            duration_ms: 黑帧持续时间（毫秒），默认 100ms
        """
        # 临时保存当前颜色
        saved_color = self.current_color

        # 显示纯黑
        self.patch_area.set_color(0, 0, 0)
        self.patch_area.update()

        logger.debug(f"显示黑帧 {duration_ms}ms")

        # 注意：实际的黑帧持续时间由调用方通过 QTimer 控制
        # 这里只是设置颜色，不阻塞等待

        # 黑帧结束后恢复颜色（由调用方在 QTimer.singleShot 后调用）
        return saved_color

    def restore_color_after_black_frame(self, r: int, g: int, b: int):
        """黑帧结束后恢复色块颜色"""
        self.set_color(r, g, b)

    def resizeEvent(self, event):
        """调整大小时更新手柄位置"""
        grip_size = self.size_grip.size()
        self.size_grip.move(
            self.width() - grip_size.width(),
            self.height() - grip_size.height()
        )
        super().resizeEvent(event)

    # ========== 鼠标事件 ==========

    def mousePressEvent(self, event):
        """鼠标按下：开始拖拽"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 只在控制栏区域允许拖拽
            pos = event.position()
            if pos.y() <= self.control_bar.height():
                self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        """鼠标移动：拖拽窗口"""
        if self._drag_position is not None:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        """鼠标释放：结束拖拽"""
        self._drag_position = None
        event.accept()

    def mouseDoubleClickEvent(self, event):
        """双击：全屏模式下退出全屏；窗口模式无操作"""
        if self.is_fullscreen_patch():
            self.exit_fullscreen_patch()
            event.accept()
            return
        event.accept()

    def keyPressEvent(self, event):
        """键盘事件：ESC 退出全屏测量模式或关闭窗口"""
        if event.key() == Qt.Key.Key_Escape:
            self._handle_escape()
            event.accept()


class ColorPatchWidget(QWidget):
    """
    自定义色块绘制 Widget
    直接使用 QPainter 绘制颜色，尽量绕过 Qt 的色彩管理

    OLED Window Patch 支持：
    - 可设置色块窗口大小百分比（10%/18%等）
    - 色块居中显示，周围区域为纯黑
    - 用于 HDR 测量避免 OLED ABL 影响
    """

    def __init__(self):
        super().__init__()
        self._color = QColor(0, 0, 0)

        # OLED window patch 参数
        self._oled_window_percent: float = 100.0  # 默认 100% 全屏
        self._oled_background_color = QColor(0, 0, 0)  # OLED 窗口模式下周围为纯黑
        self._oled_mode_enabled: bool = False  # OLED 窗口模式开关

        # 均匀性测量 zone 参数：色块定位到屏幕指定比例坐标，周围纯黑
        self._zone_active: bool = False
        self._zone_x: float = 0.5  # 色块中心 x（0-1 比例坐标）
        self._zone_y: float = 0.5  # 色块中心 y（0-1 比例坐标）
        self._zone_size_percent: float = 15.0  # 色块面积占比

        # 禁用自动填充背景
        self.setAutoFillBackground(False)

        # 设置 palette 为纯色
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, self._color)
        self.setPalette(palette)

    def set_color(self, r: int, g: int, b: int):
        """
        设置颜色

        OLED 窗口模式 / 均匀性 zone 模式下，色块只占据指定百分比区域，周围为纯黑。
        """
        self._color = QColor(r, g, b)

        # 窗口类模式（OLED 窗口或均匀性 zone）下背景为纯黑
        window_mode = (self._oled_mode_enabled and self._oled_window_percent < 100.0) or self._zone_active
        if window_mode:
            self._oled_background_color = QColor(0, 0, 0)

        # 更新 palette
        palette = QPalette()
        if window_mode:
            palette.setColor(QPalette.ColorRole.Window, self._oled_background_color)
            palette.setColor(QPalette.ColorRole.Base, self._oled_background_color)
        else:
            palette.setColor(QPalette.ColorRole.Window, self._color)
            palette.setColor(QPalette.ColorRole.Base, self._color)
        self.setPalette(palette)

        self.update()

    def set_zone(self, x: float, y: float, size_percent: float = 15.0):
        """
        均匀性测量：把色块中心定位到屏幕比例坐标 (x, y)，周围纯黑

        Args:
            x: 色块中心 x（0-1，占屏幕宽度比例）
            y: 色块中心 y（0-1，占屏幕高度比例）
            size_percent: 色块面积占屏幕面积的百分比（1-100）
        """
        self._zone_active = True
        self._zone_x = max(0.0, min(1.0, float(x)))
        self._zone_y = max(0.0, min(1.0, float(y)))
        self._zone_size_percent = max(1.0, min(100.0, float(size_percent)))
        self.update()

    def clear_zone(self):
        """退出均匀性 zone 模式（恢复全屏/居中显示）"""
        self._zone_active = False
        self.update()

    def set_oled_window_size(self, percent: float):
        """
        设置 OLED 窗口大小百分比

        OLED 显示器进行 HDR 测量时需要使用较小的色块窗口
        （10% 或 18%）来避免 ABL (Automatic Brightness Limiter) 影响。
        色块会居中显示，周围区域保持纯黑。

        Args:
            percent: 窗口大小百分比（1.0 - 100.0）
                    - 10.0: 10% 窗口（HDR 标准测量）
                    - 18.0: 18% 窗口（某些显示器）
                    - 100.0: 全屏（默认，非 HDR）
        """
        # 限制范围
        if percent < 1.0:
            percent = 1.0
        elif percent > 100.0:
            percent = 100.0

        self._oled_window_percent = percent
        self._oled_mode_enabled = percent < 100.0

        logger.info(f"OLED 窗口大小设置为 {percent}%，模式 {'启用' if self._oled_mode_enabled else '禁用'}")

        # 触发重绘
        self.update()

    def get_oled_window_size(self) -> float:
        """获取当前 OLED 窗口大小百分比"""
        return self._oled_window_percent

    def is_oled_window_mode(self) -> bool:
        """检查是否处于 OLED 窗口模式"""
        return self._oled_mode_enabled

    def _calculate_patch_rect(self) -> QRect:
        """
        计算色块绘制区域

        OLED 窗口模式：色块居中，占指定面积百分比。
        均匀性 zone 模式：色块中心定位到 (zone_x, zone_y) 比例坐标。

        Returns:
            QRect: 色块绘制区域
        """
        widget_rect = self.rect()

        window_mode = (self._oled_mode_enabled and self._oled_window_percent < 100.0) or self._zone_active
        if not window_mode:
            # 全屏模式：返回整个 widget 区域
            return widget_rect

        # 窗口类模式：计算正方形色块区域
        # 百分比指的是面积百分比：area = percent * total_area
        percent = (self._zone_size_percent if self._zone_active else self._oled_window_percent) / 100.0

        total_width = widget_rect.width()
        total_height = widget_rect.height()

        # 计算正方形色块的边长：patch_size = sqrt(area)
        import math
        patch_size = math.sqrt(percent * total_width * total_height)

        # 确保色块不超过 widget 尺寸
        patch_size = min(patch_size, total_width, total_height)

        patch_width = int(patch_size)
        patch_height = int(patch_size)

        if self._zone_active:
            # 均匀性 zone：色块中心定位到指定比例坐标（并夹紧在窗口内）
            patch_x = int(self._zone_x * total_width - patch_width / 2)
            patch_y = int(self._zone_y * total_height - patch_height / 2)
            patch_x = max(0, min(patch_x, total_width - patch_width))
            patch_y = max(0, min(patch_y, total_height - patch_height))
        else:
            # OLED 窗口模式：居中
            patch_x = (total_width - patch_width) // 2
            patch_y = (total_height - patch_height) // 2

        return QRect(patch_x, patch_y, patch_width, patch_height)

    def paintEvent(self, event):
        """
        直接绘制颜色，绕过样式表

        OLED 窗口模式 / 均匀性 zone 模式下：
        - 先绘制纯黑背景
        - 然后在指定位置绘制指定百分比的色块
        """
        painter = QPainter(self)

        window_mode = (self._oled_mode_enabled and self._oled_window_percent < 100.0) or self._zone_active
        if not window_mode:
            # 全屏模式：直接填充整个区域
            painter.fillRect(self.rect(), self._color)
        else:
            # 窗口类模式：
            # 1. 先绘制纯黑背景（整个 widget）
            painter.fillRect(self.rect(), self._oled_background_color)

            # 2. 在指定位置绘制色块
            patch_rect = self._calculate_patch_rect()
            painter.fillRect(patch_rect, self._color)


class DispcalWebClient:
    """
    ArgyllCMS dispcal Web Server 客户端

    连接到 dispcal -dweb:PORT 启动的 HTTP 服务器，
    轮询获取色块指令并通过 PatchWindow 显示。

    ArgyllCMS dispcal Web Server API:
    - GET /ajax/messages?<当前颜色>: 获取下一个色块指令
      响应格式: 十六进制颜色值，如 "#000000", "#808080" 等
      客户端需要在请求中发送当前显示的颜色
    """

    def __init__(self, patch_window: PatchWindow):
        """
        Args:
            patch_window: 测量窗口实例，用于显示色块
        """
        self._patch_window = patch_window
        self._base_url = ""
        self._poll_timer: QTimer = None
        self._total_patches = 0
        self._current_index = 0
        self._poll_interval_ms = 200  # 轮询间隔（毫秒）
        self._active = False
        self._on_progress = None  # 进度回调
        self._on_complete = None  # 完成回调
        self._on_error = None     # 错误回调
        self._on_color_changed = None  # 颜色变化回调 fn(r, g, b)
        self._port = 0            # 服务器端口
        self._attempted_urls = [] # 尝试过的 URL 列表
        self._connection_established = False  # 连接是否已建立
        self._current_color = "#808080"  # 当前显示的颜色（初始为灰色）
        self._request_timeout = 30  # 请求超时时间（秒）- 测量可能需要较长时间

    def connect_to_server(self, port: int, on_progress=None, on_complete=None, on_error=None, on_color_changed=None):
        """
        连接到 dispcal Web Server 并开始轮询

        Args:
            port: Web Server 端口号
            on_progress: 进度回调 fn(current, total, message)
            on_complete: 完成回调 fn()
            on_error: 错误回调 fn(message)
            on_color_changed: 颜色变化回调 fn(r, g, b) - 用于同步前端色块预览
        """
        print(f"DispcalWebClient: connect_to_server 被调用，端口={port}", flush=True)
        logger.info(f"DispcalWebClient: connect_to_server 被调用，端口={port}")
        print(f"DispcalWebClient: _patch_window={self._patch_window is not None}", flush=True)
        logger.info(f"DispcalWebClient: _patch_window={self._patch_window is not None}")

        self._port = port
        # 如果 _base_url 还没被设置，使用默认值
        if not self._base_url:
            self._base_url = f"http://127.0.0.1:{port}"
        self._on_progress = on_progress
        self._on_complete = on_complete
        self._on_error = on_error
        self._on_color_changed = on_color_changed
        self._total_patches = 0
        self._current_index = 0
        self._active = True
        self._connection_established = False

        # 如果 _base_url 已通过 set_server_url 设置，使用它
        # 否则尝试多个可能的地址
        if self._base_url != f"http://127.0.0.1:{port}":
            # 已经通过 set_server_url 设置了地址
            self._attempted_urls = [self._base_url]
            logger.info(f"DispcalWebClient: 使用已设置的地址: {self._base_url}")
        else:
            # 尝试多个可能的地址
            import socket
            possible_urls = [f"http://127.0.0.1:{port}"]
            try:
                # 获取本机所有 IP 地址
                hostname = socket.gethostname()
                addr_info = socket.getaddrinfo(hostname, None)
                seen_ips = set()
                for info in addr_info:
                    ip = info[4][0]
                    # 跳过本地链路地址和已见过的 IP
                    if not ip.startswith('fe80:') and ip not in seen_ips:
                        seen_ips.add(ip)
                        possible_urls.append(f"http://{ip}:{port}")
            except Exception:
                pass

            self._attempted_urls = possible_urls
            logger.info(f"DispcalWebClient: 将尝试以下地址: {possible_urls}")

        # 注意：不再自动显示测量窗口，假设用户已手动打开并定位窗口
        if self._patch_window and self._patch_window.isVisible():
            logger.info(f"DispcalWebClient: 测量窗口已打开可见，位置=({self._patch_window.x()}, {self._patch_window.y()}), 大小={self._patch_window.width()}x{self._patch_window.height()}")
            self._patch_window.start_guardian(interval_ms=2000)
        elif self._patch_window and not self._patch_window.isVisible():
            logger.info(f"DispcalWebClient: 测量窗口已创建但未显示，等待用户手动打开")
        else:
            logger.error("DispcalWebClient: _patch_window 为 None！")

        # 创建轮询定时器（重连时先停掉旧 timer，避免多路并发轮询与泄漏）
        if getattr(self, '_poll_timer', None) is not None:
            self._poll_timer.stop()
            self._poll_timer.deleteLater()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_next_patch)
        self._poll_timer.start(self._poll_interval_ms)

        # 立即执行第一次轮询
        QTimer.singleShot(500, self._poll_next_patch)

    def set_server_url(self, url: str):
        """
        设置实际的 Web Server URL

        当 dispcal 监听在非 localhost 地址时调用。

        Args:
            url: 实际的 Web Server URL (例如 "http://192.168.1.20:9292")
        """
        old_url = self._base_url
        self._base_url = url
        # 将此 URL 添加到尝试列表的开头
        if url not in self._attempted_urls:
            self._attempted_urls.insert(0, url)
        # 重置连接状态，以便立即尝试新 URL
        if hasattr(self, '_attempt_index'):
            self._attempt_index = 0
        logger.info(f"DispcalWebClient: 更新服务器地址 {old_url} -> {url}")

    def disconnect(self):
        """断开连接，停止轮询"""
        self._active = False

        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None

        if self._patch_window:
            self._patch_window.stop_guardian()

        logger.info("DispcalWebClient: 已断开连接")

    def _poll_next_patch(self):
        """轮询获取下一个色块指令"""
        if not self._active:
            logger.debug("DispcalWebClient: 轮询停止（_active=False）")
            return

        # 添加调试输出（只在连接未建立时输出，避免刷屏）
        if not self._connection_established:
            print(f"DispcalWebClient: _poll_next_patch 被调用，_active={self._active}", flush=True)

        # 如果连接已建立，使用当前 URL
        if self._connection_established:
            url_to_try = self._base_url
        else:
            # 尝试列表中的下一个 URL
            if not hasattr(self, '_attempt_index'):
                self._attempt_index = 0

            if self._attempt_index < len(self._attempted_urls):
                url_to_try = self._attempted_urls[self._attempt_index]
                # 更新 base_url 以便后续使用
                self._base_url = url_to_try
                self._attempt_index += 1
            else:
                # 所有地址都尝试过了，使用最后一个
                url_to_try = self._base_url

        # 每次轮询时记录（便于调试）
        if not self._connection_established:
            logger.info(f"DispcalWebClient: 尝试连接 {url_to_try}/ajax/messages")
        else:
            logger.debug(f"DispcalWebClient: 轮询 {url_to_try}/ajax/messages?{self._current_color}")

        try:
            # 使用 ArgyllCMS Web Server 的正确协议
            # GET /ajax/messages?<当前颜色>
            url = f"{url_to_try}/ajax/messages?{self._current_color}"
            logger.debug(f"DispcalWebClient: 发送请求 {url}")
            req = urllib.request.Request(
                url,
                headers={"Connection": "close"}
            )
            with urllib.request.urlopen(req, timeout=self._request_timeout) as response:
                data = response.read().decode('utf-8').strip()
                logger.debug(f"DispcalWebClient: 收到响应 '{data}'")
                if data and data != self._current_color:
                    print(f"DispcalWebClient: 收到颜色变化 {self._current_color} -> {data}", flush=True)

                # 首次成功连接时记录
                if not self._connection_established:
                    self._connection_established = True
                    self._base_url = url_to_try  # 固定使用成功的地址
                    logger.info(f"DispcalWebClient: 成功连接到 {self._base_url}")

                if not data:
                    # 空响应可能表示校准完成
                    logger.info("DispcalWebClient: 收到空响应，校准可能已完成")
                    self._handle_completion()
                    return

                # 解析十六进制颜色值 (如 #000000, #808080)
                if not data.startswith('#'):
                    logger.warning(f"DispcalWebClient: 收到非颜色响应: {data[:100]}")
                    # 如果收到 HTML 或其他错误，可能连接有问题
                    if '<html' in data.lower() or '<!DOCTYPE' in data.lower():
                        logger.error("DispcalWebClient: 收到 HTML 响应，可能 URL 错误或 dispcal 异常")
                    return

                # 更新当前颜色
                new_color = data
                if new_color == self._current_color:
                    # 颜色没有变化，dispcal 可能还在等待测量
                    logger.debug(f"DispcalWebClient: 颜色未变化 {self._current_color}，等待中...")
                    return
                else:
                    logger.info(f"DispcalWebClient: 颜色变化 {self._current_color} -> {new_color}")

                self._current_color = new_color
                self._current_index += 1

                # 解析十六进制颜色为 RGB
                try:
                    hex_color = new_color.lstrip('#')
                    if len(hex_color) == 6:
                        r = int(hex_color[0:2], 16)
                        g = int(hex_color[2:4], 16)
                        b = int(hex_color[4:6], 16)
                    else:
                        logger.warning(f"DispcalWebClient: 无效的颜色格式: {new_color}")
                        return
                except ValueError:
                    logger.warning(f"DispcalWebClient: 无法解析颜色: {new_color}")
                    return

                logger.info(
                    f"DispcalWebClient: 色块 {self._current_index}"
                    f" RGB({r}, {g}, {b})"
                )

                # 在 PatchWindow 上显示色块
                if self._patch_window:
                    self._patch_window.set_color(r, g, b)

                # 发送颜色变化回调（用于同步前端色块预览）
                if self._on_color_changed:
                    try:
                        self._on_color_changed(r, g, b)
                    except Exception as e:
                        logger.error(f"颜色变化回调错误: {e}")

                # 发送进度回调
                if self._on_progress:
                    try:
                        msg = f"校准色块 {self._current_index}"
                        self._on_progress(self._current_index, self._total_patches, msg)
                    except Exception as e:
                        logger.error(f"进度回调错误: {e}")

        except urllib.error.URLError as e:
            # 连接被拒绝可能意味着 dispcal 尚未启动或地址不对
            if not self._active:
                logger.debug("DispcalWebClient: 连接失败但已停止活动")
                return
            # 如果连接失败且还有其他地址可尝试，不记录错误
            if not self._connection_established and self._attempt_index < len(self._attempted_urls):
                logger.info(f"DispcalWebClient: {url_to_try} 连接失败，尝试下一个地址...")
                return  # 下次轮询会尝试下一个地址
            # 所有地址都失败了，记录错误但继续重试
            # 超时错误是正常的（dispcal 在测量时可能需要较长时间响应）
            if 'timed out' in str(e).lower() or 'timeout' in str(e).lower():
                logger.debug(f"DispcalWebClient: 请求超时（dispcal 正在测量），继续重试...")
            else:
                logger.info(f"DispcalWebClient: 连接错误 ({type(e).__name__}: {e})")

        except ConnectionResetError as e:
            # 连接被重置通常意味着 dispcal 完成并关闭了 Web Server
            if self._connection_established and self._active:
                logger.info("DispcalWebClient: 连接被重置，dispcal 可能已完成校准")
                print("DispcalWebClient: 连接被重置，触发完成回调", flush=True)
                self._handle_completion()
            elif not self._active:
                logger.debug("DispcalWebClient: 连接重置但已停止活动")
            else:
                logger.debug(f"DispcalWebClient: 连接重置（尚未建立连接）: {e}")

        except Exception as e:
            if not self._active:
                logger.debug("DispcalWebClient: 发生异常但已停止活动")
                return
            # 超时是正常的，不打印错误
            if 'timed out' in str(e).lower() or 'timeout' in str(e).lower():
                logger.debug(f"DispcalWebClient: 请求超时（dispcal 正在测量）")
            else:
                logger.error(f"DispcalWebClient: 轮询错误 ({type(e).__name__}): {e}")
                import traceback
                logger.debug(f"DispcalWebClient: 堆栈跟踪:\n{traceback.format_exc()}")

    def _handle_completion(self):
        """处理校准完成"""
        self._active = False

        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None

        if self._patch_window:
            self._patch_window.stop_guardian()

        if self._on_complete:
            try:
                self._on_complete()
            except Exception as e:
                logger.error(f"完成回调错误: {e}")

        logger.info("DispcalWebClient: 校准完成")
