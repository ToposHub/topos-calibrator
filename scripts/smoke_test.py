#!/usr/bin/env python3
"""
Topos Calibrator Smoke Test 总入口

运行所有 smoke 测试：
    - Source Smoke Test: 开发环境测试，不依赖打包后的 app bundle
    - Package Smoke Test: 打包后应用测试（如果 dist app 存在）

使用方法:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --quick
    python scripts/smoke_test.py --source-only
    python scripts/smoke_test.py --package-only
"""

import argparse
import platform
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# 导入子测试模块
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from source_smoke_test import run_source_smoke_tests
from package_smoke_test import run_package_smoke_tests, get_dist_app_path


def main():
    parser = argparse.ArgumentParser(
        description="Topos Calibrator Smoke Test 总入口"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速测试（仅检查文件，不启动应用）"
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="仅运行源码测试"
    )
    parser.add_argument(
        "--package-only",
        action="store_true",
        help="仅运行打包测试"
    )

    args = parser.parse_args()

    # 确定当前平台
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

    exit_code = 0

    # 1. Source Smoke Test (默认运行)
    if not args.package_only:
        print("\n" + "=" * 60)
        print(">>> 运行 Source Smoke Test")
        print("=" * 60 + "\n")
        result = run_source_smoke_tests()
        if result != 0:
            exit_code = result

    # 2. Package Smoke Test (如果 dist app 存在，或 --package-only)
    if not args.source_only:
        dist_app_path = get_dist_app_path(target_platform)

        if dist_app_path and dist_app_path.exists():
            print("\n" + "=" * 60)
            print(">>> 运行 Package Smoke Test")
            print("=" * 60 + "\n")
            result = run_package_smoke_tests(target_platform, args.quick)
            if result != 0:
                exit_code = result
        else:
            print("\n" + "=" * 60)
            print(">>> Package Smoke Test: SKIP")
            print("=" * 60)
            print(f"dist app 不存在: {dist_app_path}")
            print("跳过打包测试（开发环境可忽略）\n")

    print("\n" + "=" * 60)
    if exit_code == 0:
        print("所有 Smoke Test 通过")
    else:
        print("Smoke Test 失败")
    print("=" * 60)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()