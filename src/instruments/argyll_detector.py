"""
ArgyllCMS Detector - ArgyllCMS 工具检测和缺失引导

此模块负责：
1. 检测 ArgyllCMS 工具是否存在
2. 确定最佳 ArgyllCMS 路径
3. 生成缺失引导信息

打包后的应用启动时应调用此模块进行检测。
"""

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum


class ArgyllToolStatus(Enum):
    """ArgyllCMS 工具状态"""
    FOUND = "found"           # 工具已找到
    NOT_FOUND = "not_found"   # 工具未找到
    ERROR = "error"           # 检测出错


@dataclass
class ArgyllToolInfo:
    """ArgyllCMS 工具信息"""
    name: str                 # 工具名称
    path: Optional[Path]      # 工具路径
    status: ArgyllToolStatus  # 状态
    version: Optional[str]    # 版本信息
    error: Optional[str]      # 错误信息


@dataclass
class ArgyllDetectionResult:
    """ArgyllCMS 检测结果"""
    available: bool                          # ArgyllCMS 是否可用
    path: Optional[Path]                     # ArgyllCMS bin 目录路径
    source: str                              # 路径来源（内置/系统/用户/未找到）
    tools: List[ArgyllToolInfo]              # 各工具状态
    missing_tools: List[str]                 # 缺失的必要工具
    platform_instructions: str               # 平台特定安装说明


# ========== 必要工具列表 ==========
# spotread 是最基础的测量工具，必须存在
REQUIRED_TOOLS = [
    "spotread",    # 色块测量（必须）
    "dispcal",     # 显示器校准（必须）
    "dispwin",     # LUT/ICC 操作（必须）
]

# 可选工具（用于高级功能）
OPTIONAL_TOOLS = [
    "targen",      # 色块生成
    "colprof",     # ICC Profile 创建
    "collink",     # 3D LUT 创建
    "ccxxmake",    # 修正文件创建
    "dispread",    # 批量测量
    "applycal",    # 应用校准
]


class ArgyllDetector:
    """ArgyllCMS 检测器"""

    def __init__(self):
        self.system = platform.system()
        self.project_root = Path(__file__).parent.parent.parent
        
        # 可能的 ArgyllCMS 路径（按优先级排序）
        self._candidate_paths: List[Path] = []
        self._build_candidate_paths()

    def _build_candidate_paths(self):
        """构建候选路径列表"""
        # 1. 内置路径（打包应用中的 ArgyllCMS 目录）
        internal_path = self.project_root / "ArgyllCMS" / "bin"
        self._candidate_paths.append(("internal", internal_path))
        
        # 2. 系统路径
        if self.system == "Darwin":
            # macOS Homebrew 路径
            brew_paths = [
                Path("/opt/homebrew/bin"),
                Path("/usr/local/bin"),
            ]
            for p in brew_paths:
                self._candidate_paths.append(("system_brew", p))
            
        elif self.system == "Windows":
            # Windows 常见安装路径
            program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
            program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
            
            win_paths = [
                Path(program_files) / "ArgyllCMS" / "bin",
                Path(program_files_x86) / "ArgyllCMS" / "bin",
                Path("C:\\ArgyllCMS") / "bin",
            ]
            for p in win_paths:
                self._candidate_paths.append(("system_windows", p))
            
        elif self.system == "Linux":
            # Linux 系统路径
            linux_paths = [
                Path("/usr/bin"),
                Path("/usr/local/bin"),
                Path("/opt/argyllcms/bin"),
            ]
            for p in linux_paths:
                self._candidate_paths.append(("system_linux", p))
        
        # 3. 用户路径
        home = Path.home()
        user_paths = [
            home / ".local" / "bin",
            home / "bin",
            home / "ArgyllCMS" / "bin",
        ]
        for p in user_paths:
            self._candidate_paths.append(("user", p))
        
        # 4. 用户指定的路径（从环境变量）
        env_path = os.environ.get("ARGYLLCMS_PATH", "")
        if env_path:
            self._candidate_paths.append(("env", Path(env_path)))

    def _check_tool_exists(self, tool_name: str, path: Path) -> Tuple[bool, Optional[str]]:
        """检查单个工具是否存在"""
        # 添加平台特定后缀
        if self.system == "Windows":
            tool_file = path / f"{tool_name}.exe"
        else:
            tool_file = path / tool_name
        
        if not tool_file.exists():
            return False, f"文件不存在: {tool_file}"
        
        # 尝试获取版本信息
        try:
            result = subprocess.run(
                [str(tool_file), "-V"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # 解析版本信息
            version = self._parse_version(result.stdout or result.stderr)
            return True, version
        except subprocess.TimeoutExpired:
            return True, "timeout"
        except Exception as e:
            return True, None

    def _parse_version(self, output: str) -> Optional[str]:
        """解析版本信息"""
        # ArgyllCMS 版本格式: "Argyll CMS Version X.Y.Z"
        import re
        match = re.search(r"Argyll\s+CMS\s+Version\s+(\d+\.\d+\.\d+)", output)
        if match:
            return match.group(1)
        return None

    def detect(self) -> ArgyllDetectionResult:
        """执行检测"""
        tools_info: List[ArgyllToolInfo] = []
        found_path: Optional[Path] = None
        path_source: str = "not_found"
        
        # 按优先级检查每个候选路径
        for source, path in self._candidate_paths:
            if not path.exists():
                continue
            
            # 检查必要工具
            found_required = 0
            for tool in REQUIRED_TOOLS:
                exists, version = self._check_tool_exists(tool, path)
                status = ArgyllToolStatus.FOUND if exists else ArgyllToolStatus.NOT_FOUND
                tools_info.append(ArgyllToolInfo(
                    name=tool,
                    path=path if exists else None,
                    status=status,
                    version=version if version != "timeout" else None,
                    error=None if exists else f"未在 {path} 找到"
                ))
                if exists:
                    found_required += 1
            
            # 检查可选工具
            for tool in OPTIONAL_TOOLS:
                exists, version = self._check_tool_exists(tool, path)
                status = ArgyllToolStatus.FOUND if exists else ArgyllToolStatus.NOT_FOUND
                tools_info.append(ArgyllToolInfo(
                    name=tool,
                    path=path if exists else None,
                    status=status,
                    version=version if version != "timeout" else None,
                    error=None if exists else f"未在 {path} 找到"
                ))
            
            # 如果找到所有必要工具，使用此路径
            if found_required == len(REQUIRED_TOOLS):
                found_path = path
                path_source = source
                break
        
        # 确定缺失的必要工具
        missing_required = [
            t.name for t in tools_info 
            if t.name in REQUIRED_TOOLS and t.status != ArgyllToolStatus.FOUND
        ]
        
        # 生成平台特定说明
        instructions = self._generate_install_instructions()
        
        return ArgyllDetectionResult(
            available=found_path is not None and len(missing_required) == 0,
            path=found_path,
            source=path_source,
            tools=tools_info,
            missing_tools=missing_required,
            platform_instructions=instructions
        )

    def _generate_install_instructions(self) -> str:
        """生成平台特定安装说明"""
        if self.system == "Darwin":
            return """
安装方式：

macOS (Homebrew):
    brew install argyll-cms

或从官网下载:
    https://www.argyllcms.com/
    
下载后，将 bin 目录放入应用程序的 ArgyllCMS 目录。
"""
        elif self.system == "Windows":
            return """
安装方式：

从官网下载 ArgyllCMS:
    https://www.argyllcms.com/

下载后:
    1. 解压 ZIP 文件
    2. 将 bin 目录复制到应用程序的 ArgyllCMS 目录
    或
    3. 将 bin 目录复制到 C:\\ArgyllCMS\\bin

USB 驱动安装:
    使用 Zadig 安装 WinUSB 驱动
    https://zadig.akeo.ie/
"""
        elif self.system == "Linux":
            return """
安装方式：

Debian/Ubuntu:
    sudo apt install argyll

Fedora:
    sudo dnf install argyllcms

Arch Linux:
    sudo pacman -S argyllcms

或从官网下载:
    https://www.argyllcms.com/

USB 权限设置:
    需要 udev 规则，详见文档。
"""
        else:
            return f"""
请从 ArgyllCMS 官网下载:
    https://www.argyllcms.com/

当前平台: {self.system}
"""

    def get_argyll_path(self) -> Optional[Path]:
        """获取最佳 ArgyllCMS 路径"""
        result = self.detect()
        return result.path


def detect_argyllcms() -> ArgyllDetectionResult:
    """快捷检测函数"""
    detector = ArgyllDetector()
    return detector.detect()


def get_argyll_path() -> Optional[Path]:
    """快捷获取路径函数"""
    detector = ArgyllDetector()
    return detector.get_argyll_path()


def generate_missing_dialog(result: ArgyllDetectionResult) -> str:
    """生成缺失引导对话框内容"""
    if result.available:
        return ""
    
    dialog = """
┌─────────────────────────────────────────────────────────────┐
│  ⚠ ArgyllCMS 未找到                                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Topos Calibrator 需要 ArgyllCMS 进行色彩测量。             │
│                                                             │
│  缺失的必要工具: {missing}                                   │
│                                                             │
│  {instructions}                                             │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  [下载 ArgyllCMS]  [手动指定路径]  [退出程序]               │
└─────────────────────────────────────────────────────────────┘
""".format(
        missing=", ".join(result.missing_tools) if result.missing_tools else "spotread",
        instructions=result.platform_instructions.strip()
    )
    
    return dialog


# ========== 打包应用启动时调用 ==========

def check_argyllcms_on_startup() -> Tuple[bool, Optional[Path]]:
    """
    打包应用启动时检查 ArgyllCMS
    
    返回:
        (是否可用, 路径)
    
    如果不可用，应用应显示引导对话框。
    """
    result = detect_argyllcms()
    
    if not result.available:
        # 打印缺失引导
        print(generate_missing_dialog(result))
        return False, None
    
    return True, result.path


if __name__ == "__main__":
    # 测试检测
    print("ArgyllCMS 检测测试")
    print("=" * 60)
    
    result = detect_argyllcms()
    
    print(f"可用: {result.available}")
    print(f"路径: {result.path}")
    print(f"来源: {result.source}")
    print(f"缺失工具: {result.missing_tools}")
    
    print("\n工具状态:")
    for tool in result.tools:
        status_icon = "✓" if tool.status == ArgyllToolStatus.FOUND else "✗"
        version_str = f" (v{tool.version})" if tool.version else ""
        print(f"  {status_icon} {tool.name}{version_str}")
    
    if not result.available:
        print("\n安装说明:")
        print(result.platform_instructions)