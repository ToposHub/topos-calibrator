#!/usr/bin/env python3
"""
Topos Calibrator macOS 公证脚本

将已签名的 app bundle 提交到 Apple 公证服务。

使用方法:
    python scripts/macos_notarize.py

环境变量:
    NOTARY_APPLE_ID - Apple ID
    NOTARYTOOL_PASSWORD - App-Specific Password
    APPLE_TEAM_ID - 团队 ID
"""

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

def create_zip(app_path, zip_path):
    """创建 zip 文件用于公证"""
    print(f"创建 zip: {zip_path}")
    
    cmd = ["ditto", "-c", "-k", "--keepParent", str(app_path), str(zip_path)]
    result = subprocess.run(cmd)
    
    return result.returncode == 0

def submit_notarization(zip_path, apple_id, password, team_id):
    """提交公证"""
    print("提交公证...")
    
    cmd = [
        "xcrun", "notarytool", "submit",
        str(zip_path),
        "--apple-id", apple_id,
        "--password", password,
        "--team-id", team_id,
        "--wait"  # 等待完成
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print(result.stdout)
    
    if result.returncode == 0 and "success" in result.stdout.lower():
        return True
    else:
        print("公证失败")
        print(result.stderr)
        return False

def staple_ticket(app_path):
    """将公证票据 stapled 到 app"""
    print(f"Staple 公证票据: {app_path}")
    
    cmd = ["xcrun", "stapler", "staple", str(app_path)]
    result = subprocess.run(cmd)
    
    return result.returncode == 0

def verify_notarization(app_path):
    """验证公证状态"""
    print("验证公证状态...")
    
    cmd = ["spctl", "-a", "-t", "vv", "-vv", str(app_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print(result.stdout)
    
    if "Notarized Developer ID" in result.stdout:
        print("公证验证通过")
        return True
    else:
        print("公证验证失败")
        return False

def main():
    # 检查环境变量
    apple_id = os.environ.get("NOTARY_APPLE_ID", "")
    password = os.environ.get("NOTARYTOOL_PASSWORD", "")
    team_id = os.environ.get("APPLE_TEAM_ID", "")
    
    if not apple_id:
        print("错误: 未设置 NOTARY_APPLE_ID 环境变量")
        sys.exit(1)
    
    if not password:
        print("错误: 未设置 NOTARYTOOL_PASSWORD 环境变量")
        print("从 https://appleid.apple.com 创建 App-Specific Password")
        sys.exit(1)
    
    if not team_id:
        print("错误: 未设置 APPLE_TEAM_ID 环境变量")
        sys.exit(1)
    
    # app bundle 路径
    app_path = PROJECT_ROOT / "dist" / "Topos Calibrator.app"
    
    if not app_path.exists():
        print(f"错误: App bundle 不存在: {app_path}")
        sys.exit(1)
    
    # zip 文件路径
    zip_path = PROJECT_ROOT / "dist" / "ToposCalibrator.zip"
    
    print("=" * 60)
    print("Topos Calibrator macOS Notarization")
    print("=" * 60)
    print(f"Apple ID: {apple_id}")
    print(f"Team ID: {team_id}")
    print(f"App Bundle: {app_path}")
    print("=" * 60)
    
    # 创建 zip
    if not create_zip(app_path, zip_path):
        print("创建 zip 失败")
        sys.exit(1)
    
    # 提交公证
    if not submit_notarization(zip_path, apple_id, password, team_id):
        sys.exit(1)
    
    # Staple 公证票据
    if not staple_ticket(app_path):
        print("Staple 失败")
        sys.exit(1)
    
    # 验证公证
    if not verify_notarization(app_path):
        sys.exit(1)
    
    # 清理 zip
    print(f"清理临时文件: {zip_path}")
    zip_path.unlink()
    
    print("公证完成")
    sys.exit(0)

if __name__ == "__main__":
    main()