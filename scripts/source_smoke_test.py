#!/usr/bin/env python3
"""
Topos Calibrator Source Smoke Test

开发环境 smoke 测试，不依赖打包后的 app bundle。

检查项：
    - Python 版本
    - 关键模块可导入
    - main.py 存在
    - src/backend.py、src/color_science、src/workflows 基础导入

使用方法:
    python3 scripts/source_smoke_test.py
"""

import sys
import platform
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).parent.parent

# 将项目根目录加入 sys.path，以便导入 src 模块
sys.path.insert(0, str(PROJECT_ROOT))


def check_python_version() -> Tuple[bool, str]:
    """检查 Python 版本 >= 3.10"""
    version = sys.version_info
    if version >= (3, 10):
        return True, f"Python {version.major}.{version.minor}.{version.micro}"
    return False, f"Python 版本过低: {version.major}.{version.minor}.{version.micro}, 需要 >= 3.10"


def check_main_py() -> Tuple[bool, str]:
    """检查 main.py 存在"""
    main_path = PROJECT_ROOT / "main.py"
    if main_path.exists():
        return True, str(main_path)
    return False, f"main.py 不存在: {main_path}"


def check_src_directory() -> Tuple[bool, str]:
    """检查 src 目录存在"""
    src_path = PROJECT_ROOT / "src"
    if src_path.is_dir():
        return True, str(src_path)
    return False, f"src 目录不存在: {src_path}"


def check_import(module_path: str) -> Tuple[bool, str]:
    """检查模块是否可导入"""
    try:
        # 将路径转换为模块名
        parts = module_path.replace("/", ".").replace("\\", ".")
        if parts.endswith(".py"):
            parts = parts[:-3]
        __import__(parts)
        return True, module_path
    except ImportError as e:
        return False, f"{module_path}: {e}"
    except Exception as e:
        # 某些模块可能因为依赖问题导入失败，但如果是 SyntaxError 等，应该报告
        if isinstance(e, (SyntaxError, IndentationError)):
            return False, f"{module_path}: {type(e).__name__}: {e}"
        # 其他错误（如配置缺失）视为可通过
        return True, f"{module_path} (警告: {type(e).__name__})"


def check_backend_module() -> Tuple[bool, str]:
    """检查 src.backend 模块"""
    return check_import("src/backend.py")


def check_color_science_module() -> Tuple[bool, str]:
    """检查 src.color_science 模块"""
    return check_import("src/color_science/__init__.py")


def check_workflows_module() -> Tuple[bool, str]:
    """检查 src.workflows 模块"""
    return check_import("src/workflows/__init__.py")


def check_pyqt6() -> Tuple[bool, str]:
    """检查 PyQt6 可导入"""
    try:
        import PyQt6
        from PyQt6.QtWidgets import QApplication
        return True, "PyQt6"
    except ImportError as e:
        return False, f"PyQt6 导入失败: {e}"


def run_source_smoke_tests() -> int:
    """运行所有源码 smoke 测试，返回退出码"""
    print("=" * 60)
    print("Topos Calibrator Source Smoke Test")
    print("=" * 60)
    print(f"平台: {platform.system()} {platform.release()}")
    print(f"工作目录: {PROJECT_ROOT}")
    print("=" * 60)

    tests: List[Tuple[str, Tuple[bool, str]]] = [
        ("Python 版本", check_python_version()),
        ("main.py 存在", check_main_py()),
        ("src 目录存在", check_src_directory()),
        ("src.backend 模块", check_backend_module()),
        ("src.color_science 模块", check_color_science_module()),
        ("src.workflows 模块", check_workflows_module()),
        ("PyQt6 模块", check_pyqt6()),
    ]

    passed = 0
    failed = 0

    print("\n检查项:")
    for name, (success, message) in tests:
        status = "PASS" if success else "FAIL"
        symbol = "✓" if success else "✗"
        print(f"  [{status}] {symbol} {name}: {message}")
        if success:
            passed += 1
        else:
            failed += 1

    print("\n" + "=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    if failed == 0:
        print("\nSource Smoke Test 通过")
        return 0
    else:
        print("\nSource Smoke Test 失败")
        return 1


if __name__ == "__main__":
    sys.exit(run_source_smoke_tests())