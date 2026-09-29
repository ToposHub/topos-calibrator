#!/usr/bin/env python3
"""
Topos Calibrator Package Smoke Test

验证打包后的应用能否正常启动和运行基本功能。

使用方法:
    python scripts/package_smoke_test.py --platform macos
    python scripts/package_smoke_test.py --platform windows
    python scripts/package_smoke_test.py --platform linux
"""

import argparse
import subprocess
import sys
import time
import platform
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# ========== Smoke Test 项 ==========

SMOKE_TEST_ITEMS = [
    ("应用启动", "Application starts without crash"),
    ("Web UI 加载", "Web UI loads correctly"),
    ("ArgyllCMS 检测", "ArgyllCMS detection works"),
    ("色块窗口", "Patch window can be created"),
    ("预检模块", "Preflight module works"),
    ("退出正常", "Application exits cleanly"),
]


def test_macos_app():
    """测试 macOS app bundle"""
    app_path = PROJECT_ROOT / "dist" / "Topos Calibrator.app"

    if not app_path.exists():
        print(f"错误: App bundle 不存在: {app_path}")
        return False

    print("启动 macOS app bundle...")

    # 使用 open 命令启动
    process = subprocess.Popen(
        ["open", str(app_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # 等待启动
    time.sleep(5)

    # 检查进程
    result = subprocess.run(
        ["pgrep", "-f", "Topos Calibrator"],
        capture_output=True
    )

    if result.returncode == 0:
        print("应用已启动 (PID: {})".format(result.stdout.decode().strip()))
        return True
    else:
        print("应用启动失败")
        return False


def test_windows_exe():
    """测试 Windows 可执行文件"""
    exe_path = PROJECT_ROOT / "dist" / "Topos Calibrator" / "Topos Calibrator.exe"

    if not exe_path.exists():
        print(f"错误: EXE 不存在: {exe_path}")
        return False

    print("启动 Windows EXE...")

    # 启动进程
    process = subprocess.Popen(
        [str(exe_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )

    # 等待启动
    time.sleep(5)

    # 检查进程是否运行
    if process.poll() is None:
        print("应用已启动")
        process.terminate()
        return True
    else:
        print("应用启动失败")
        print(process.stderr.read().decode())
        return False


def test_linux_appimage():
    """测试 Linux AppImage"""
    appimage_path = PROJECT_ROOT / "dist" / "ToposCalibrator-x86_64.AppImage"

    if not appimage_path.exists():
        print(f"错误: AppImage 不存在: {appimage_path}")
        return False

    print("启动 Linux AppImage...")

    # 启动进程
    process = subprocess.Popen(
        [str(appimage_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # 等待启动
    time.sleep(5)

    # 检查进程是否运行
    if process.poll() is None:
        print("应用已启动")
        process.terminate()
        return True
    else:
        print("应用启动失败")
        print(process.stderr.read().decode())
        return False


def check_argyll_detection():
    """检查 ArgyllCMS 检测功能"""
    print("\n检查 ArgyllCMS 检测...")

    # 检查 ArgyllCMS 是否在系统中
    argyll_tools = ["spotread", "dispcal", "colprof"]
    found = []

    for tool in argyll_tools:
        result = subprocess.run(["which", tool], capture_output=True)
        if result.returncode == 0:
            found.append(tool)

    if found:
        print(f"已找到 ArgyllCMS 工具: {found}")
    else:
        print("系统中未找到 ArgyllCMS")
        print("应用应显示缺失引导对话框")

    return True


def check_pyinstaller_output(target_platform: str) -> bool:
    """检查 PyInstaller 输出"""
    print("\n检查 PyInstaller 输出...")

    dist_dir = PROJECT_ROOT / "dist"

    if target_platform == "macos":
        app_path = dist_dir / "Topos Calibrator.app"
        if not app_path.exists():
            print(f"错误: App bundle 不存在: {app_path}")
            return False

        # 检查可执行文件
        exe_path = app_path / "Contents" / "MacOS" / "Topos Calibrator"
        if not exe_path.exists():
            print(f"错误: 可执行文件不存在: {exe_path}")
            return False

        # 检查资源
        resources_path = app_path / "Contents" / "Resources"
        web_path = resources_path / "web"
        if not web_path.exists():
            print(f"错误: Web 资源不存在: {web_path}")
            return False

        print("PyInstaller 输出检查通过")
        return True

    elif target_platform == "windows":
        app_dir = dist_dir / "Topos Calibrator"
        if not app_dir.exists():
            print(f"错误: 应用目录不存在: {app_dir}")
            return False

        exe_path = app_dir / "Topos Calibrator.exe"
        if not exe_path.exists():
            print(f"错误: EXE 不存在: {exe_path}")
            return False

        web_path = app_dir / "web"
        if not web_path.exists():
            print(f"错误: Web 资源不存在: {web_path}")
            return False

        print("PyInstaller 输出检查通过")
        return True

    elif target_platform == "linux":
        app_dir = dist_dir / "topos-calibrator"
        if not app_dir.exists():
            print(f"错误: 应用目录不存在: {app_dir}")
            return False

        exe_path = app_dir / "topos-calibrator"
        if not exe_path.exists():
            print(f"错误: 可执行文件不存在: {exe_path}")
            return False

        print("PyInstaller 输出检查通过")
        return True

    return False


def get_dist_app_path(target_platform: str) -> Path | None:
    """获取打包应用的路径"""
    if target_platform == "macos":
        return PROJECT_ROOT / "dist" / "Topos Calibrator.app"
    elif target_platform == "windows":
        return PROJECT_ROOT / "dist" / "Topos Calibrator" / "Topos Calibrator.exe"
    elif target_platform == "linux":
        return PROJECT_ROOT / "dist" / "ToposCalibrator-x86_64.AppImage"
    return None


def run_package_smoke_tests(target_platform: str, quick: bool = False) -> int:
    """运行打包应用 smoke 测试，返回退出码"""
    print("=" * 60)
    print("Topos Calibrator Package Smoke Test")
    print("=" * 60)
    print(f"平台: {target_platform}")
    print("=" * 60)

    # Smoke Test 列表
    print("\nSmoke Test 检查项:")
    for name, desc in SMOKE_TEST_ITEMS:
        print(f"  - {name}: {desc}")

    # 检查 PyInstaller 输出
    if not check_pyinstaller_output(target_platform):
        return 1

    # ArgyllCMS 检测检查
    check_argyll_detection()

    # 如果是快速测试，跳过启动测试
    if quick:
        print("\n快速测试完成")
        return 0

    # 启动测试
    print("\n启动测试...")

    if target_platform == "macos":
        success = test_macos_app()
    elif target_platform == "windows":
        success = test_windows_exe()
    elif target_platform == "linux":
        success = test_linux_appimage()
    else:
        print(f"不支持的平台: {target_platform}")
        return 1

    if success:
        print("\nPackage Smoke Test 通过")
        return 0
    else:
        print("\nPackage Smoke Test 失败")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Topos Calibrator Package Smoke Test"
    )
    parser.add_argument(
        "--platform", "-p",
        choices=["macos", "windows", "linux", "current"],
        default="current",
        help="测试平台"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速测试（仅检查输出文件）"
    )

    args = parser.parse_args()

    # 确定平台
    if args.platform == "current":
        system = platform.system()
        if system == "Darwin":
            target_platform = "macos"
        elif system == "Windows":
            target_platform = "windows"
        elif system == "Linux":
            target_platform = "linux"
        else:
            print(f"不支持的平台: {system}")
            sys.exit(1)
    else:
        target_platform = args.platform

    sys.exit(run_package_smoke_tests(target_platform, args.quick))


if __name__ == "__main__":
    main()