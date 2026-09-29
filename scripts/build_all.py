#!/usr/bin/env python3
"""
Topos Calibrator 打包构建脚本

跨平台打包入口脚本，根据当前平台选择对应的构建流程。

使用方法:
    python scripts/build_all.py              # 当前平台打包
    python scripts/build_all.py --platform macos  # 指定平台
    python scripts/build_all.py --clean      # 清理后重新打包
    python scripts/build_all.py --sign       # macOS 签名和公证
"""

import argparse
import platform
import subprocess
import shutil
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# ========== 平台检测 ==========

def get_current_platform():
    """获取当前平台"""
    system = platform.system()
    if system == "Darwin":
        return "macos"
    elif system == "Windows":
        return "windows"
    elif system == "Linux":
        return "linux"
    else:
        raise RuntimeError(f"不支持的平台: {system}")


def prepare_argyll_for_distribution(target_platform, source_archive=None):
    """Validate and document a user-supplied ArgyllCMS bundle before packaging."""
    argyll_dir = PROJECT_ROOT / "ArgyllCMS"
    if not argyll_dir.is_dir():
        print("未找到 ./ArgyllCMS；将构建不含 ArgyllCMS 的应用，运行时可使用系统安装。")
        return True

    print("准备 ArgyllCMS 第三方许可证和对应源代码记录...")
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "prepare_argyll_bundle.py"),
        "--argyll-dir",
        str(argyll_dir),
        "--platform",
        target_platform,
        "--require-source",
    ]
    if source_archive:
        command.extend(["--source-archive", str(source_archive)])
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print("ArgyllCMS 合规准备失败；未继续创建可分发安装包。")
        return False
    return True

# ========== 构建函数 ==========

def build_macos(clean=False, sign=False, notarize=False, argyll_source=None):
    """macOS 平台构建"""
    print("=" * 60)
    print("Topos Calibrator macOS Build")
    print("=" * 60)
    
    # 清理
    if clean:
        print("清理构建目录...")
        shutil.rmtree(PROJECT_ROOT / "build", ignore_errors=True)
        shutil.rmtree(PROJECT_ROOT / "dist", ignore_errors=True)

    if not prepare_argyll_for_distribution("macos", argyll_source):
        return False
    
    # PyInstaller 打包
    print("执行 PyInstaller 打包...")
    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--clean",
            "--noconfirm",
            str(PROJECT_ROOT / "packaging" / "pyinstaller.spec")
        ],
        cwd=PROJECT_ROOT
    )
    
    if result.returncode != 0:
        print("PyInstaller 打包失败")
        return False
    
    # 签名
    if sign:
        print("执行代码签名...")
        sign_script = PROJECT_ROOT / "scripts" / "macos_sign.py"
        if sign_script.exists():
            subprocess.run([sys.executable, str(sign_script)], cwd=PROJECT_ROOT)
        else:
            print("签名脚本不存在，跳过签名")
    
    # 公证
    if notarize:
        print("执行公证...")
        notarize_script = PROJECT_ROOT / "scripts" / "macos_notarize.py"
        if notarize_script.exists():
            subprocess.run([sys.executable, str(notarize_script)], cwd=PROJECT_ROOT)
        else:
            print("公证脚本不存在，跳过公证")
    
    print("macOS 构建完成")
    return True

def build_windows(clean=False, argyll_source=None):
    """Windows 平台构建"""
    print("=" * 60)
    print("Topos Calibrator Windows Build")
    print("=" * 60)
    
    # 清理
    if clean:
        print("清理构建目录...")
        shutil.rmtree(PROJECT_ROOT / "build", ignore_errors=True)
        shutil.rmtree(PROJECT_ROOT / "dist", ignore_errors=True)

    if not prepare_argyll_for_distribution("windows", argyll_source):
        return False
    
    # PyInstaller 打包
    print("执行 PyInstaller 打包...")
    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--clean",
            "--noconfirm",
            str(PROJECT_ROOT / "packaging" / "pyinstaller.spec")
        ],
        cwd=PROJECT_ROOT
    )
    
    if result.returncode != 0:
        print("PyInstaller 打包失败")
        return False
    
    # NSIS 安装器
    print("创建 NSIS 安装器...")
    nsis_script = PROJECT_ROOT / "packaging" / "windows" / "installer.nsi"
    
    # 检查 NSIS 是否可用
    makensis = shutil.which("makensis")
    if makensis:
        result = subprocess.run([makensis, str(nsis_script)], cwd=PROJECT_ROOT)
        if result.returncode != 0:
            print("NSIS 安装器创建失败")
            return False
    else:
        print("NSIS 未安装，跳过安装器创建")
        print("下载 NSIS: https://nsis.sourceforge.io/")
    
    print("Windows 构建完成")
    return True

def build_linux(clean=False, argyll_source=None):
    """Linux 平台构建"""
    print("=" * 60)
    print("Topos Calibrator Linux Build")
    print("=" * 60)
    
    # 清理
    if clean:
        print("清理构建目录...")
        shutil.rmtree(PROJECT_ROOT / "build", ignore_errors=True)
        shutil.rmtree(PROJECT_ROOT / "dist", ignore_errors=True)

    if not prepare_argyll_for_distribution("linux", argyll_source):
        return False
    
    # PyInstaller 打包
    print("执行 PyInstaller 打包...")
    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--clean",
            "--noconfirm",
            str(PROJECT_ROOT / "packaging" / "pyinstaller.spec")
        ],
        cwd=PROJECT_ROOT
    )
    
    if result.returncode != 0:
        print("PyInstaller 打包失败")
        return False
    
    # AppImage
    print("创建 AppImage...")
    appimage_script = PROJECT_ROOT / "scripts" / "linux_appimage.py"
    
    if appimage_script.exists():
        result = subprocess.run(
            [sys.executable, str(appimage_script)],
            cwd=PROJECT_ROOT
        )
        if result.returncode != 0:
            print("AppImage 创建失败")
            return False
    else:
        print("AppImage 脚本不存在，跳过")
        print("需要 linuxdeploy: https://github.com/linuxdeploy/linuxdeploy")
    
    print("Linux 构建完成")
    return True

# ========== 主函数 ==========

def main():
    parser = argparse.ArgumentParser(
        description="Topos Calibrator 跨平台打包构建脚本"
    )
    parser.add_argument(
        "--platform", "-p",
        choices=["macos", "windows", "linux", "current"],
        default="current",
        help="目标平台 (默认: current)"
    )
    parser.add_argument(
        "--clean", "-c",
        action="store_true",
        help="清理构建目录"
    )
    parser.add_argument(
        "--sign", "-s",
        action="store_true",
        help="macOS: 执行代码签名"
    )
    parser.add_argument(
        "--notarize", "-n",
        action="store_true",
        help="macOS: 执行公证"
    )
    parser.add_argument(
        "--argyll-source",
        type=Path,
        help="与 ./ArgyllCMS 中二进制完全匹配的官方 ArgyllCMS 源代码压缩包",
    )
    
    args = parser.parse_args()
    
    # 确定平台
    if args.platform == "current":
        target_platform = get_current_platform()
    else:
        target_platform = args.platform
    
    print(f"目标平台: {target_platform}")
    
    # 执行构建
    if target_platform == "macos":
        success = build_macos(
            clean=args.clean,
            sign=args.sign,
            notarize=args.notarize,
            argyll_source=args.argyll_source,
        )
    elif target_platform == "windows":
        success = build_windows(clean=args.clean, argyll_source=args.argyll_source)
    elif target_platform == "linux":
        success = build_linux(clean=args.clean, argyll_source=args.argyll_source)
    else:
        print(f"不支持的平台: {target_platform}")
        sys.exit(1)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
