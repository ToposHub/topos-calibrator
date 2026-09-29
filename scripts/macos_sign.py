#!/usr/bin/env python3
"""
Topos Calibrator macOS 代码签名脚本

执行 Apple Developer ID Application 签名，为公证做准备。

使用方法:
    python scripts/macos_sign.py

环境变量:
    CODESIGN_IDENTITY - 签名身份
    APPLE_TEAM_ID - 团队 ID
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

def codesign_app(app_path, identity, entitlements_path):
    """对 app bundle 进行签名"""
    print(f"正在签名: {app_path}")
    
    # 签名命令
    cmd = [
        "codesign",
        "--deep",  # 深度签名所有内容
        "--force",  # 强制覆盖已有签名
        "--verify",  # 验证签名
        "--verbose",
        "--sign", identity,
        "--options", "runtime",  # 强化运行时（公证要求）
        "--entitlements", str(entitlements_path),
        "--timestamp",  # 包含时间戳
        str(app_path)
    ]
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("签名成功")
        return True
    else:
        print("签名失败")
        return False

def verify_signature(app_path):
    """验证签名"""
    print(f"验证签名: {app_path}")
    
    # codesign 验证
    cmd = ["codesign", "--verify", "--verbose", str(app_path)]
    result = subprocess.run(cmd)
    
    if result.returncode != 0:
        print("codesign 验证失败")
        return False
    
    # spctl 检查
    cmd = ["spctl", "-a", "-t", "vv", "-vv", str(app_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print(result.stdout)
    
    if "accepted" in result.stdout.lower():
        print("Gatekeeper 验证通过")
        return True
    else:
        print("Gatekeeper 验证失败")
        return False

def main():
    # 检查环境变量
    identity = os.environ.get("CODESIGN_IDENTITY", "")
    team_id = os.environ.get("APPLE_TEAM_ID", "")
    
    if not identity:
        print("错误: 未设置 CODESIGN_IDENTITY 环境变量")
        print("示例: CODESIGN_IDENTITY='Developer ID Application: Your Name (TEAM_ID)'")
        sys.exit(1)
    
    # app bundle 路径
    app_path = PROJECT_ROOT / "dist" / "Topos Calibrator.app"
    
    if not app_path.exists():
        print(f"错误: App bundle 不存在: {app_path}")
        print("请先执行 PyInstaller 打包")
        sys.exit(1)
    
    # entitlements 路径
    entitlements_path = PROJECT_ROOT / "packaging" / "macos" / "entitlements.plist"
    
    if not entitlements_path.exists():
        print(f"错误: entitlements.plist 不存在: {entitlements_path}")
        sys.exit(1)
    
    print("=" * 60)
    print("Topos Calibrator macOS Code Signing")
    print("=" * 60)
    print(f"签名身份: {identity}")
    print(f"App Bundle: {app_path}")
    print(f"Entitlements: {entitlements_path}")
    print("=" * 60)
    
    # 执行签名
    if not codesign_app(app_path, identity, entitlements_path):
        sys.exit(1)
    
    # 验证签名
    if not verify_signature(app_path):
        sys.exit(1)
    
    print("签名完成，可以进行公证")
    sys.exit(0)

if __name__ == "__main__":
    main()