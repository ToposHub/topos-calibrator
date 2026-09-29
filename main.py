#!/usr/bin/env python3
"""
Topos Calibrator - 显示器校正与测量软件
主入口文件

跨平台色彩管理策略：
    - Windows / Linux: 禁用 Qt 色彩管理，依赖 dispwin -c 清除显卡 LUT
    - macOS: 除 dispwin 外，还需通过 pyobjc 强制设置窗口 NSColorSpace
"""

import sys
import os
import platform
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.main_window import MainWindow


def resource_path(*parts: str) -> Path:
    """Resolve a bundled resource in both source and PyInstaller builds."""
    bundle_root = Path(getattr(sys, "_MEIPASS", project_root))
    return bundle_root.joinpath(*parts)


def main():
    """应用程序入口"""
    # 启用远程调试端口（在创建 QApplication 之前）
    os.environ['QTWEBENGINE_REMOTE_DEBUGGING'] = '9222'
    
    # 启用高 DPI 缩放
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # 创建应用
    app = QApplication(sys.argv)

    # 使用同一份 1024px 源图作为 Qt 图标，保证窗口标题栏、任务栏和
    # 浮动窗口在高 DPI/Retina 屏幕上都有足够的像素可供 Qt 缩放。
    app_icon_path = resource_path("resources", "app-icons", "topos-calibrator.png")
    if app_icon_path.is_file():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    # ========== 禁用 Qt 色彩管理 ==========
    # Windows 和 Linux 平台：桌面窗口管理器（DWM / X11 / Wayland）
    # 通常不会强制对普通窗口的 RGB 值进行二次色彩映射。
    # 因此必须确保 Qt 框架自身不要"自作聪明"地进行颜色转换。
    #
    # 对应 C++ 代码：
    #   QApplication::setAttribute(Qt::AA_UseColorManagement, false);
    #
    # PyQt6 中默认不会启用色彩管理，这里显式确认行为。
    # 不设置 Qt::AA_UseColorManagement 属性即可禁用色彩管理。
    system = platform.system()
    if system in ('Windows', 'Linux'):
        # Windows / Linux: 确保不启用色彩管理
        # PyQt6 中不需要显式设置 AA_UseColorManagement
        pass
    elif system == 'Darwin':
        # macOS: Window Server 会强制进行色彩映射
        # 需要后续通过 pyobjc 设置 NSColorSpace.deviceRGBColorSpace
        pass

    # 设置应用信息
    app.setApplicationName("Topos Calibrator")
    app.setApplicationVersion("0.1.0-preview")
    app.setOrganizationName("Topos Calibrator")

    # 获取可用屏幕
    screens = app.screens()
    print(f"检测到 {len(screens)} 个屏幕:")
    for i, screen in enumerate(screens):
        geometry = screen.geometry()
        print(f"  屏幕 {i}: {geometry.width()}x{geometry.height()} @ ({geometry.x()}, {geometry.y()})")

    # 如果有多个屏幕，可以选择在哪个屏幕显示色块
    patch_screen = None
    if len(screens) > 1:
        # 默认使用第二个屏幕显示色块（如果存在）
        patch_screen = screens[1]
        print(f"色块窗口将显示在屏幕 1")
    else:
        patch_screen = screens[0]
        print(f"色块窗口将显示在主屏幕")

    # 创建主窗口
    window = MainWindow(patch_screen=patch_screen)
    window.show()
    
    # 启用 WebEngine 调试端口
    try:
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        # 获取主窗口的 webview 并启用调试
        if hasattr(window, 'webview'):
            settings = window.webview.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
    except:
        pass

    print("Topos Calibrator 已启动")
    print("请在 Web UI 中操作...")
    print("调试地址: http://localhost:9222 (如果已启用)")

    # 运行应用
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
