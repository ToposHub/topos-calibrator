#!/usr/bin/env python3
"""
Topos Calibrator Linux AppImage 创建脚本

使用 linuxdeploy 工具创建 AppImage。

使用方法:
    python scripts/linux_appimage.py

依赖:
    linuxdeploy: https://github.com/linuxdeploy/linuxdeploy
    linuxdeploy-qt: https://github.com/linuxdeploy/linuxdeploy-plugin-qt
"""

import os
import subprocess
import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

def prepare_appdir(appdir_path):
    """准备 AppDir 结构"""
    print(f"准备 AppDir: {appdir_path}")
    
    # 复制 PyInstaller 输出到 AppDir
    pyinstaller_output = PROJECT_ROOT / "dist" / "topos-calibrator"
    
    if not pyinstaller_output.exists():
        print(f"错误: PyInstaller 输出不存在: {pyinstaller_output}")
        return False
    
    # 创建 AppDir 结构
    appdir_path.mkdir(parents=True, exist_ok=True)
    
    usr_dir = appdir_path / "usr"
    usr_dir.mkdir(parents=True, exist_ok=True)
    
    bin_dir = usr_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    
    # 复制可执行文件和库
    for item in pyinstaller_output.iterdir():
        dest = usr_dir / "bin" / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)
    
    # 复制桌面文件
    desktop_src = PROJECT_ROOT / "packaging" / "linux" / "topos-calibrator.desktop"
    desktop_dest = usr_dir / "share" / "applications" / "topos-calibrator.desktop"
    desktop_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(desktop_src, desktop_dest)
    
    # 复制图标
    icon_src = PROJECT_ROOT / "packaging" / "linux" / "ToposCalibrator.png"
    if icon_src.exists():
        icon_dir = usr_dir / "share" / "icons" / "hicolor" / "256x256" / "apps"
        icon_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_src, icon_dir / "ToposCalibrator.png")
    
    # 复制 AppRun
    apprun_src = PROJECT_ROOT / "packaging" / "linux" / "AppRun"
    apprun_dest = appdir_path / "AppRun"
    shutil.copy2(apprun_src, apprun_dest)
    os.chmod(apprun_dest, 0o755)
    
    return True

def create_appimage(appdir_path, output_path):
    """使用 linuxdeploy 创建 AppImage"""
    print("创建 AppImage...")
    
    # 检查 linuxdeploy
    linuxdeploy = shutil.which("linuxdeploy")
    if not linuxdeploy:
        print("错误: linuxdeploy 未安装")
        print("下载: https://github.com/linuxdeploy/linuxdeploy/releases")
        return False
    
    # linuxdeploy 命令
    cmd = [
        linuxdeploy,
        "--appdir", str(appdir_path),
        "--desktop-file", str(appdir_path / "usr" / "share" / "applications" / "topos-calibrator.desktop"),
        "--icon-file", str(appdir_path / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "ToposCalibrator.png"),
        "--output", "appimage"
    ]
    
    # 设置输出目录
    env = os.environ.copy()
    env["OUTPUT"] = str(output_path)
    
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)
    
    return result.returncode == 0

def main():
    print("=" * 60)
    print("Topos Calibrator Linux AppImage Creation")
    print("=" * 60)
    
    # AppDir 路径
    appdir_path = PROJECT_ROOT / "AppDir"
    
    # 输出 AppImage 路径
    output_path = PROJECT_ROOT / "dist" / "ToposCalibrator-x86_64.AppImage"
    
    # 准备 AppDir
    if not prepare_appdir(appdir_path):
        sys.exit(1)
    
    # 创建 AppImage
    if not create_appimage(appdir_path, output_path):
        sys.exit(1)
    
    print(f"AppImage 创建成功: {output_path}")
    
    # 清理 AppDir
    print("清理 AppDir...")
    shutil.rmtree(appdir_path, ignore_errors=True)
    
    sys.exit(0)

if __name__ == "__main__":
    main()