"""
DisplayLUTController - 跨平台显卡 LUT（VCGT）和 ICC Profile 控制模块

核心策略（跨平台统一重构版）：
    采用"系统级挂载 Null Profile"方案替代不稳定代码级 ColorSpace 强制转换。
    **关键原则：消灭平台差异，dispwin 自动处理 macOS ColorSync 和 Windows WCS。**

    1. 测色准备阶段：使用 dispwin -I 挂载线性 ICC Profile (Topos_Linear_Native.icc)
       - 清空系统色彩管理，使输出呈线性状态
       - 同时清除 VCGT 显卡曲线

    2. 校准完成/验证阶段：使用 dispwin -I 挂载新生成的校准 ICC Profile
       - 用户可查看真实的校准效果

    3. 保留原有的 dispwin -c (仅清除显卡 1D LUT) 作为降级方案

跨平台分发处理（无硬编码分支）：
    - **所有平台统一**：通过 ArgyllCMS dispwin 工具操作
    - **路径处理**：强制使用 pathlib.Path.resolve() 确保绝对路径
    - **异常捕获**：统一使用 subprocess.CalledProcessError 处理
    - **状态管理**：统一 _null_profile_applied 状态标记

    macOS: dispwin 自动调用 ColorSync API
    Windows: dispwin 自动调用 WCS (Windows Color System) API
    Linux: dispwin 自动调用 X11/Wayland 相关 API

废弃方案：
    - 已移除 pyobjc 的 NSColorSpace 强制设置代码（不稳定）
    - 已移除 AppKit/objc 相关导入（高风险依赖）
    - **严禁使用 if platform.system() == 'Windows': 做分支挂载**
"""

import os
import sys
import platform
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ========== macOS 专用：原生 CoreGraphics 刷新 API ==========
# 使用 Python 内置 ctypes 调用，彻底摆脱 pyobjc 依赖
_MAC_CG_LIB = None
_MAC_CG_API_READY = False
if platform.system() == 'Darwin':
    try:
        import ctypes
        import ctypes.util
        cg_path = ctypes.util.find_library("CoreGraphics")
        if cg_path:
            _MAC_CG_LIB = ctypes.cdll.LoadLibrary(cg_path)
            # CGDisplayRestoreColorSyncSettings - 重置 ColorSync 设置
            _MAC_CG_LIB.CGDisplayRestoreColorSyncSettings.restype = None
            _MAC_CG_LIB.CGDisplayRestoreColorSyncSettings.argtypes = []
            # CGMainDisplayID - 获取主显示器 ID
            _MAC_CG_LIB.CGMainDisplayID.restype = ctypes.c_uint32
            _MAC_CG_LIB.CGMainDisplayID.argtypes = []
            # CGBeginDisplayConfiguration - 开启配置事务
            _MAC_CG_LIB.CGBeginDisplayConfiguration.restype = ctypes.c_int
            _MAC_CG_LIB.CGBeginDisplayConfiguration.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
            # CGCompleteDisplayConfiguration - 完成配置事务
            _MAC_CG_LIB.CGCompleteDisplayConfiguration.restype = ctypes.c_int
            _MAC_CG_LIB.CGCompleteDisplayConfiguration.argtypes = [ctypes.c_void_p, ctypes.c_int]
            # CGGetDisplayTransferByTable - 读取 Gamma 表
            _MAC_CG_LIB.CGGetDisplayTransferByTable.restype = ctypes.c_int32
            _MAC_CG_LIB.CGGetDisplayTransferByTable.argtypes = [
                ctypes.c_uint32, ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float),
                ctypes.POINTER(ctypes.c_uint32)
            ]
            # CGSetDisplayTransferByTable - 设置 Gamma 表
            _MAC_CG_LIB.CGSetDisplayTransferByTable.restype = ctypes.c_int32
            _MAC_CG_LIB.CGSetDisplayTransferByTable.argtypes = [
                ctypes.c_uint32, ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float)
            ]
            _MAC_CG_API_READY = True
            logger.debug("[macOS] 成功通过 ctypes 加载 CoreGraphics 库（含配置事务 + Gamma LUT API）")
        else:
            logger.warning("[macOS] 未找到 CoreGraphics 动态库")
    except Exception as e:
        logger.warning(f"[macOS] 加载 CoreGraphics 失败: {e}")


def _force_macos_display_refresh(swift_script_path: str = None):
    """
    macOS 专用：强制物理刷新屏幕显示

    **核心原理**：
    通过切换显示器分辨率/刷新率，强制 macOS WindowServer 重建色彩缓存。
    这是最可靠的方案，因为用户发现手动改变分辨率后颜色立刻正常。

    **方案优先级**：
    1. Swift 可执行文件（物理切换分辨率，100% 有效，会有短暂黑屏）
    2. ctypes 空配置事务（软刷新，无黑屏但可能无效）

    Args:
        swift_script_path: Swift 刷新脚本的路径，如果提供则优先使用

    **注意**：此函数仅在 macOS 上有效，其他平台直接返回。
    """
    if platform.system() != 'Darwin':
        return

    import subprocess

    # 方案 1：使用 Swift 脚本进行物理刷新（最强方案）
    if swift_script_path:
        try:
            result = subprocess.run(
                [swift_script_path],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info("[macOS·Swift刷新] 物理刷新成功（分辨率切换）")
                # 刷新成功后再调用 ColorSync 恢复
                if _MAC_CG_LIB and hasattr(_MAC_CG_LIB, 'CGDisplayRestoreColorSyncSettings'):
                    _MAC_CG_LIB.CGDisplayRestoreColorSyncSettings()
                return
            else:
                logger.warning(f"[macOS·Swift刷新] 脚本执行失败: {result.returncode}")
        except FileNotFoundError:
            logger.warning(f"[macOS·Swift刷新] 脚本不存在: {swift_script_path}")
        except subprocess.TimeoutExpired:
            logger.warning("[macOS·Swift刷新] 脚本执行超时")
        except Exception as e:
            logger.warning(f"[macOS·Swift刷新] 异常: {e}")

    # 方案 2：ctypes 空配置事务（后备方案）
    if not _MAC_CG_LIB:
        logger.warning("[macOS·刷新] CoreGraphics 库未加载")
        return

    try:
        import ctypes

        # 开启一个配置事务
        config_ref = ctypes.c_void_p()
        result = _MAC_CG_LIB.CGBeginDisplayConfiguration(ctypes.byref(config_ref))

        if result == 0:
            # 直接提交事务（不包含任何修改）
            _MAC_CG_LIB.CGCompleteDisplayConfiguration(config_ref, 0)
            logger.info("[macOS·空事务刷新] 成功发送空配置事务")
        else:
            logger.warning(f"[macOS·空事务刷新] CGBeginDisplayConfiguration 失败: {result}")

        # 顺带调用 ColorSync 恢复作为双重保险
        _MAC_CG_LIB.CGDisplayRestoreColorSyncSettings()
        logger.info("[macOS·双重保险] CGDisplayRestoreColorSyncSettings 已调用")

    except Exception as e:
        logger.error(f"[macOS·刷新] 强制刷新屏幕失败: {e}")


def _get_refresh_script_path() -> str:
    """获取 Swift 刷新脚本的绝对路径"""
    import os
    # 相对于本模块的位置
    module_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(module_dir)
    return os.path.join(project_root, "resources", "refresh_display")


# ========== 环境检查结果 ==========

@dataclass
class EnvironmentStatus:
    """平台环境检查结果"""
    is_valid: bool = True
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    details: dict = field(default_factory=dict)


# ========== 自定义异常 ==========

class DispwinNotFoundError(Exception):
    """dispwin 可执行文件未找到异常"""
    pass


class DispwinExecutionError(Exception):
    """dispwin 执行失败异常"""
    def __init__(self, returncode: int, stderr: str, command: list):
        self.returncode = returncode
        self.stderr = stderr
        self.command = command
        super().__init__(
            f"dispwin 执行失败: 命令={' '.join(command)}, "
            f"退出码={returncode}, 错误={stderr}"
        )


class ProfileNotFoundError(Exception):
    """ICC Profile 文件未找到异常"""
    def __init__(self, profile_path: str):
        self.profile_path = profile_path
        super().__init__(f"ICC Profile 文件未找到: {profile_path}")


class DisplayLUTController:
    """
    跨平台显卡 LUT 和 ICC Profile 控制器

    封装 dispwin 命令调用，提供：
    - apply_profile(): 挂载 ICC Profile 到系统（替代系统默认配置）
    - uninstall_profile(): 卸载指定的 ICC Profile
    - clear_lut(): 仅清除显卡 VCGT（降级方案）
    - restore_lut(): 恢复之前的 LUT 状态

    对应 Qt/C++ 中的 CalibrationEngine 的 LUT 操作方法。
    """

    def __init__(self, argyll_bin_path: Optional[str] = None):
        """
        初始化 LUT 控制器

        Args:
            argyll_bin_path: ArgyllCMS bin 目录路径，如果为 None 则自动检测

        Raises:
            DispwinNotFoundError: 当 dispwin 可执行文件未找到时抛出
        """
        self._argyll_bin_path = argyll_bin_path or self._auto_detect_argyll_path()
        self._dispwin_path = self._find_dispwin()

        # 生产级加固 #4：如果找不到 dispwin，抛出明确异常
        if not self._dispwin_path:
            raise DispwinNotFoundError(
                f"无法找到 ArgyllCMS 的 dispwin 工具。\n"
                f"请确保 ArgyllCMS 已安装，并将 dispwin 所在路径添加到 PATH 环境变量，\n"
                f"或将 ArgyllCMS 文件放入项目目录的 ArgyllCMS/ 文件夹中。\n"
                f"当前检测路径: {self._argyll_bin_path or '未指定'}"
            )

        # 保存 dispwin -c 之前加载的 LUT 信息（用于恢复）
        self._saved_lut_info: Optional[str] = None

        # 平台标识
        self._platform = platform.system()  # 'Darwin', 'Windows', 'Linux'

        # ========== 生产级加固 #2：多显示器支持 ==========
        # 默认显示器索引（0 = 主显示器）
        self._default_display_index: int = 0
        # 记录每个显示器是否已清除 LUT
        self._display_lut_cleared: Dict[int, bool] = {}
        # 记录每个显示器当前挂载的 Profile（用于卸载）
        self._display_current_profile: Dict[int, str] = {}

        # ========== Null Profile 路径与状态管理 ==========
        # 内置线性 ICC Profile 路径（用于测量前的色彩管理绕过）
        self._linear_profile_path: Optional[str] = None
        # **跨平台状态标记**：当前是否已挂载 Null Profile
        # 用于生命周期结束时的恢复（stop_cycle / atexit）
        self._null_profile_applied: bool = False
        # 记录挂载 Null Profile 的显示器索引
        self._null_profile_display_index: Optional[int] = None

        # ========== macOS 专用：Gamma 表保存/恢复 ==========
        # 保存挂载 Null Profile 前的 Gamma 表（用于卸载时恢复）
        self._saved_gamma_table: Optional[Dict] = None

        # ========== 错误信息存储 ==========
        # 存储最后一次操作的详细错误信息，供调用方获取
        self._last_error: Optional[str] = None
        # 存储最后一次错误的类型（用于前端判断）
        self._last_error_type: Optional[str] = None  # 'permission', 'not_found', 'timeout', 'other'

        self._auto_detect_linear_profile()

    # ========== macOS 专用：Gamma 表保存/恢复 ==========

    def _save_gamma_table_macos(self) -> bool:
        """
        macOS 专用：保存当前显示器 Gamma 表

        在挂载 Null Profile 之前调用，保存当前 Gamma 表以便卸载时恢复。

        Returns:
            bool: 是否成功保存
        """
        if self._platform != 'Darwin':
            return True

        if not _MAC_CG_API_READY:
            logger.warning("[macOS] Gamma LUT API 未就绪，无法保存")
            return False

        try:
            import ctypes
            display_id = _MAC_CG_LIB.CGMainDisplayID()
            table_size = 256
            red = (ctypes.c_float * table_size)()
            green = (ctypes.c_float * table_size)()
            blue = (ctypes.c_float * table_size)()
            count = ctypes.c_uint32()

            result = _MAC_CG_LIB.CGGetDisplayTransferByTable(
                display_id, table_size, red, green, blue, ctypes.byref(count)
            )

            if result != 0:
                logger.warning(f"[macOS·Gamma保存] 读取失败: {result}")
                return False

            # 保存到实例变量
            self._saved_gamma_table = {
                'red': [red[i] for i in range(count.value)],
                'green': [green[i] for i in range(count.value)],
                'blue': [blue[i] for i in range(count.value)],
                'count': count.value
            }
            logger.info(f"[macOS·Gamma保存] 已保存 Gamma 表 ({count.value} entries)")
            return True

        except Exception as e:
            logger.error(f"[macOS·Gamma保存] 异常: {e}")
            return False

    def _restore_gamma_table_macos(self) -> bool:
        """
        macOS 专用：恢复之前保存的 Gamma 表

        在卸载 Null Profile 时调用，恢复挂载前的 Gamma 表。

        Returns:
            bool: 是否成功恢复
        """
        if self._platform != 'Darwin':
            return True

        if not _MAC_CG_API_READY:
            logger.warning("[macOS] Gamma LUT API 未就绪，无法恢复")
            return False

        if not self._saved_gamma_table:
            logger.warning("[macOS·Gamma恢复] 无保存的 Gamma 表，设置 Gamma 2.2")
            return self._set_gamma_2_2_macos()

        try:
            import ctypes
            display_id = _MAC_CG_LIB.CGMainDisplayID()
            count = self._saved_gamma_table['count']

            red = (ctypes.c_float * count)(*self._saved_gamma_table['red'])
            green = (ctypes.c_float * count)(*self._saved_gamma_table['green'])
            blue = (ctypes.c_float * count)(*self._saved_gamma_table['blue'])

            result = _MAC_CG_LIB.CGSetDisplayTransferByTable(
                display_id, count, red, green, blue
            )

            if result == 0:
                logger.info(f"[macOS·Gamma恢复] 已恢复 Gamma 表 ({count} entries)")
                self._saved_gamma_table = None  # 清除保存的表
                return True
            else:
                logger.warning(f"[macOS·Gamma恢复] 设置失败: {result}")
                return self._set_gamma_2_2_macos()

        except Exception as e:
            logger.error(f"[macOS·Gamma恢复] 异常: {e}")
            return self._set_gamma_2_2_macos()

    def _set_gamma_2_2_macos(self) -> bool:
        """
        macOS 专用：设置标准 Gamma 2.2 曲线

        当无法恢复原 Gamma 表时，设置标准 Gamma 2.2 作为后备方案。

        Returns:
            bool: 是否成功
        """
        if self._platform != 'Darwin':
            return True

        if not _MAC_CG_API_READY:
            return False

        try:
            import ctypes
            display_id = _MAC_CG_LIB.CGMainDisplayID()
            table_size = 256

            # 创建 Gamma 2.2 曲线 (解码 gamma = 1/2.2)
            gamma = 2.2
            red = (ctypes.c_float * table_size)()
            green = (ctypes.c_float * table_size)()
            blue = (ctypes.c_float * table_size)()

            for i in range(table_size):
                x = i / (table_size - 1)
                y = x ** (1.0 / gamma)
                red[i] = y
                green[i] = y
                blue[i] = y

            result = _MAC_CG_LIB.CGSetDisplayTransferByTable(
                display_id, table_size, red, green, blue
            )

            if result == 0:
                logger.info("[macOS·Gamma2.2] 已设置标准 Gamma 2.2 曲线")
                return True
            else:
                logger.warning(f"[macOS·Gamma2.2] 设置失败: {result}")
                return False

        except Exception as e:
            logger.error(f"[macOS·Gamma2.2] 异常: {e}")
            return False

    # ========== macOS 专用：ColorSync 刷新方法 ==========

    def _refresh_colorsync_macos(self) -> bool:
        """
        macOS 专用：强制刷新 ColorSync 设置（解决 WindowServer 缓存问题）

        **背景问题**：
        在 macOS 上，dispwin -I 成功修改了 ColorSync 数据库，
        但 WindowServer 渲染层不会立即响应变化。
        用户在"系统设置"中看到 Profile 已切换，但实际显示未刷新。
        用户发现：手动改变分辨率或刷新率，颜色就会立刻正常。

        **解决方案**：
        使用 Swift 脚本物理切换显示器分辨率/刷新率，
        强制 macOS WindowServer 重建色彩缓存（100% 有效，会有短暂黑屏）。
        如果 Swift 脚本不可用，回退到 ctypes 空配置事务。

        **注意**：此方法仅在 macOS 上有效，Windows 不需要此步骤。

        Returns:
            bool: 是否成功刷新（非 macOS 平台返回 True）
        """
        if self._platform != 'Darwin':
            return True

        # 调用全局刷新函数（优先使用 Swift 脚本进行物理刷新）
        swift_script = _get_refresh_script_path()
        _force_macos_display_refresh(swift_script_path=swift_script)

        # 补充：重新设置当前 Gamma 表（确保 LUT 也刷新）
        if _MAC_CG_API_READY:
            try:
                import ctypes
                display_id = _MAC_CG_LIB.CGMainDisplayID()
                table_size = 256
                red = (ctypes.c_float * table_size)()
                green = (ctypes.c_float * table_size)()
                blue = (ctypes.c_float * table_size)()
                count = ctypes.c_uint32()

                result = _MAC_CG_LIB.CGGetDisplayTransferByTable(
                    display_id, table_size, red, green, blue, ctypes.byref(count)
                )

                if result == 0 and count.value > 0:
                    # 立即重新设置 Gamma 表（强制刷新 LUT）
                    _MAC_CG_LIB.CGSetDisplayTransferByTable(
                        display_id, count.value, red, green, blue
                    )
                    logger.info(f"[macOS·Gamma补充] Gamma 表已重新设置 ({count.value} entries)")
            except Exception as e:
                logger.warning(f"[macOS·Gamma补充] 异常: {e}")

        return True

    def _fallback_refresh_macos(self) -> bool:
        """
        macOS 备用刷新方案：当 CoreGraphics API 不可用时使用

        通过执行 dispwin -L 强制重新加载 VCGT，可能触发刷新。

        Returns:
            bool: 是否成功
        """
        if not self._dispwin_path:
            return False

        try:
            # 尝试对所有已知显示器执行 -L 刷新
            for disp_idx in self._display_current_profile.keys():
                cmd = [self._dispwin_path, "-d", str(disp_idx), "-L"]
                subprocess.run(cmd, capture_output=True, timeout=5)
            logger.info("[macOS·备用刷新] dispwin -L 刷新完成")
            return True
        except Exception as e:
            logger.warning(f"[macOS·备用刷新] 执行失败: {e}")
            return False

    # ========== 公共 API：ICC Profile 挂载 ==========

    def apply_profile(self, display_index: int, profile_path: str) -> bool:
        """
        挂载 ICC Profile 到指定显示器（跨平台统一实现）

        **核心原则**：消灭平台差异，dispwin 自动处理 macOS ColorSync 和 Windows WCS。
        **路径处理**：强制使用 pathlib.Path.resolve() 确保绝对路径。
        **异常捕获**：统一使用 subprocess.CalledProcessError 处理。

        使用 dispwin -I 命令将 ICC Profile 安装并应用为系统默认配置。
        此命令会：
        1. 将 Profile 安装到系统
        2. 应用 VCGT 曲线到显卡 LUT
        3. 设置 Profile 为显示器默认配置

        Args:
            display_index: 显示器索引（dispwin 使用 1-based 索引，1 = 主显示器）
            profile_path: ICC Profile 文件路径（会自动转换为绝对路径）

        Returns:
            bool: 是否成功挂载
        """
        if not self._dispwin_path:
            logger.error("dispwin 可执行文件未找到，无法挂载 ICC Profile")
            return False

        # ========== 跨平台路径处理：强制使用 Path.resolve() ==========
        # 确保路径在 Windows 和 macOS 上都是合法的绝对路径
        safe_path = str(Path(profile_path).resolve())

        if not Path(safe_path).exists():
            logger.error(f"ICC Profile 文件不存在: {safe_path}")
            return False

        # ========== macOS 专用：在挂载 Null Profile 前保存 Gamma 表 ==========
        # 检查是否是 Null Profile 且尚未保存 Gamma 表
        is_null_profile = (
            self._linear_profile_path and
            Path(safe_path).resolve() == Path(self._linear_profile_path).resolve()
        )
        if is_null_profile and self._platform == 'Darwin' and not self._saved_gamma_table:
            logger.info("[macOS] 挂载 Null Profile 前，保存当前 Gamma 表...")
            self._save_gamma_table_macos()

        logger.info(f"[跨平台] 正在挂载 ICC Profile 到显示器 {display_index}: {safe_path}")

        try:
            # ========== 第一步：安装 ICC Profile ==========
            # dispwin -d{display_index} -I {profile_path}
            # -d: 指定显示器索引
            # -I: 安装并应用 ICC Profile
            # **跨平台统一**：dispwin 自动处理 macOS ColorSync 和 Windows WCS
            cmd_install = [self._dispwin_path, "-d", str(display_index), "-I", safe_path]

            # 使用 check=True 捕获非零返回码
            result = subprocess.run(
                cmd_install,
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )

            logger.info(f"[跨平台] ICC Profile 已安装到显示器 {display_index}")

            # ========== 第二步：强制刷新 VCGT（解决 macOS WindowServer 缓存问题）==========
            # macOS 的 WindowServer 可能不会立即响应 Profile 变化
            # 执行 dispwin -L 强制重新加载已安装 Profile 的 VCGT 到显卡 LUT
            # 这会触发 WindowServer 重新渲染，解决"设置变了但屏幕没变"的问题
            # 注意：此步骤在 Windows 上无害，可以跨平台统一执行
            cmd_refresh = [self._dispwin_path, "-d", str(display_index), "-L"]

            try:
                refresh_result = subprocess.run(
                    cmd_refresh,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False  # 不抛出异常，因为可能返回非零但实际已刷新
                )
                if refresh_result.returncode == 0:
                    logger.info(f"[跨平台] VCGT 刷新成功，WindowServer 已更新")
                else:
                    # 返回码非零但可能已成功刷新（macOS 权限警告常见此情况）
                    stderr = refresh_result.stderr.strip() if refresh_result.stderr else ""
                    logger.warning(
                        f"[跨平台] VCGT 刷新返回非零码 {refresh_result.returncode}，"
                        f"但可能已成功刷新。stderr: {stderr[:100] if stderr else '(空)'}"
                    )
            except subprocess.TimeoutExpired:
                logger.warning("[跨平台] VCGT 刷新超时，但主安装已完成")
            except Exception as e:
                logger.warning(f"[跨平台] VCGT 刷新异常: {e}，但主安装已完成")

            # ========== 第三步：macOS 专用 ColorSync 软刷新 ==========
            # 注意：挂载 Null Profile 时不需要 Swift 物理刷新（Null Profile 够"重"能自动刷新）
            # 只调用 ctypes 空配置事务作为补充，不会导致黑屏
            if self._platform == 'Darwin' and _MAC_CG_LIB:
                try:
                    import ctypes
                    config_ref = ctypes.c_void_p()
                    if _MAC_CG_LIB.CGBeginDisplayConfiguration(ctypes.byref(config_ref)) == 0:
                        _MAC_CG_LIB.CGCompleteDisplayConfiguration(config_ref, 0)
                    _MAC_CG_LIB.CGDisplayRestoreColorSyncSettings()
                    logger.info("[macOS·软刷新] 空配置事务 + ColorSync 恢复完成")
                except Exception as e:
                    logger.warning(f"[macOS·软刷新] 异常: {e}")

            # 成功执行
            logger.info(f"[跨平台] ICC Profile 已成功挂载并刷新到显示器 {display_index}")
            self._display_current_profile[display_index] = safe_path
            self._display_lut_cleared[display_index] = True

            # 如果是线性 Profile，更新 Null Profile 状态
            if self._linear_profile_path and Path(safe_path).resolve() == Path(self._linear_profile_path).resolve():
                self._null_profile_applied = True
                self._null_profile_display_index = display_index
                logger.info("[跨平台] Null Profile 状态已更新: applied=True")

            return True

        except subprocess.CalledProcessError as e:
            # ========== 统一异常捕获：捕获 check=True 抛出的异常 ==========
            stderr = e.stderr.strip() if e.stderr else ""
            stdout = e.stdout.strip() if e.stdout else ""

            # 检测权限相关错误
            permission_keywords = [
                "permission", "access denied", "denied", "forbidden",
                "权限", "无法访问", "拒绝访问", "没有权限",
                "eacces", "eperm", "error 5"
            ]
            is_permission_error = any(
                kw in stderr.lower() or kw in stdout.lower()
                for kw in permission_keywords
            )

            # 检测文件不存在错误
            not_found_keywords = [
                "not found", "cannot find", "no such file", "找不到文件", "不存在",
                "error 2", "enoent"
            ]
            is_not_found_error = any(
                kw in stderr.lower() or kw in stdout.lower()
                for kw in not_found_keywords
            )

            # 记录详细错误信息
            error_details = (
                f"[跨平台] dispwin -I 执行失败: "
                f"退出码={e.returncode}, "
                f"命令={' '.join(e.cmd)}"
            )
            if stderr:
                error_details += f", stderr={stderr}"
            if stdout:
                error_details += f", stdout={stdout}"

            logger.error(error_details)

            # 设置错误类型和消息
            if is_permission_error:
                self._last_error_type = "permission"
                self._last_error = self._get_permission_error_message(safe_path)
            elif is_not_found_error:
                self._last_error_type = "not_found"
                self._last_error = f"ICC 文件不存在: {safe_path}"
            else:
                self._last_error_type = "other"
                self._last_error = f"ICC 安装失败: {stderr or stdout or '未知错误'}"

            return False

        except subprocess.TimeoutExpired:
            logger.error(f"[跨平台] dispwin -I 执行超时")
            self._last_error_type = "timeout"
            self._last_error = "ICC 安装超时，请重试"
            return False

        except Exception as e:
            logger.error(f"[跨平台] 挂载 ICC Profile 时发生异常: {e}")
            self._last_error_type = "other"
            self._last_error = f"ICC 安装异常: {str(e)}"
            return False

    def uninstall_profile(self, display_index: int, profile_path: str) -> bool:
        """
        卸载指定显示器上的 ICC Profile（跨平台统一实现）

        **核心原则**：消灭平台差异，dispwin 自动处理 macOS ColorSync 和 Windows WCS。
        **路径处理**：强制使用 pathlib.Path.resolve() 确保绝对路径。
        **异常捕获**：统一使用 subprocess.CalledProcessError 处理。

        使用 dispwin -U 命令卸载指定的 ICC Profile。
        注意：卸载后会恢复系统默认的配置（如果有）。

        Args:
            display_index: 显示器索引（1-based）
            profile_path: 要卸载的 ICC Profile 文件路径（会自动转换为绝对路径）

        Returns:
            bool: 是否成功卸载
        """
        if not self._dispwin_path:
            logger.error("dispwin 可执行文件未找到，无法卸载 ICC Profile")
            return False

        # ========== 跨平台路径处理：强制使用 Path.resolve() ==========
        safe_path = str(Path(profile_path).resolve())

        logger.info(f"[跨平台] 正在卸载显示器 {display_index} 的 ICC Profile: {safe_path}")

        try:
            # dispwin -d{display_index} -U {profile_path} -S u
            # -U: 卸载指定的 Profile
            # -S u: 设置卸载模式（用户级别）
            # **跨平台统一**：dispwin 自动处理 macOS ColorSync 和 Windows WCS
            cmd = [self._dispwin_path, "-d", str(display_index), "-U", safe_path, "-S", "u"]

            # ========== 使用 check=True 捕获非零返回码 ==========
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=True  # **关键**：自动捕获非零返回码
            )

            # 成功执行
            logger.info(f"[跨平台] ICC Profile 已成功卸载")
            # 清除记录
            if display_index in self._display_current_profile:
                del self._display_current_profile[display_index]

            # 如果是 Null Profile，更新状态
            if self._linear_profile_path and Path(safe_path).resolve() == Path(self._linear_profile_path).resolve():
                self._null_profile_applied = False
                self._null_profile_display_index = None
                logger.info("[跨平台] Null Profile 状态已更新: applied=False")

            return True

        except subprocess.CalledProcessError as e:
            # ========== 统一异常捕获：捕获 check=True 抛出的异常 ==========
            stderr = e.stderr.strip() if e.stderr else ""
            logger.warning(
                f"[跨平台] dispwin -U 执行失败: "
                f"退出码={e.returncode}, "
                f"命令={' '.join(e.cmd)}, "
                f"stderr={stderr}"
            )
            # Windows WCS 或 macOS ColorSync 可能返回特定错误码
            # 记录详细信息帮助排查
            if "not found" in stderr.lower():
                logger.warning(f"[跨平台] Profile 可能已被手动移除")
            elif "permission" in stderr.lower() or "access" in stderr.lower():
                logger.warning(f"[跨平台] 可能需要管理员权限")
            return False

        except subprocess.TimeoutExpired:
            logger.error(f"[跨平台] dispwin -U 执行超时")
            return False

        except Exception as e:
            logger.error(f"[跨平台] 卸载 ICC Profile 时发生异常: {e}")
            return False

    def apply_linear_profile(self, display_index: int) -> bool:
        """
        挂载线性 ICC Profile（Null Profile）以绕过系统色彩管理

        测色准备阶段调用此方法，使显示器输出呈线性状态。

        Args:
            display_index: 显示器索引（1-based）

        Returns:
            bool: 是否成功挂载
        """
        if not self._linear_profile_path:
            logger.error("线性 ICC Profile 未找到，无法挂载 Null Profile")
            return False

        return self.apply_profile(display_index, self._linear_profile_path)

    def get_linear_profile_path(self) -> Optional[str]:
        """
        获取线性 ICC Profile 文件路径

        Returns:
            Optional[str]: Profile 路径，如果未找到返回 None
        """
        return self._linear_profile_path

    # ========== 公共 API：LUT 操作（降级方案） ==========

    def clear_lut(self, display_index: Optional[int] = None) -> bool:
        """
        清除显卡 LUT（VCGT）使输出呈线性状态（跨平台降级方案）

        **降级方案**：仅清除显卡 1D LUT，不替换系统 ICC Profile。
        当用户未勾选"自动清除系统ICC"选项时使用此方法。

        **适用场景**：
        - 用户未勾选"自动清除系统ICC"选项
        - Null Profile 挂载失败后的降级处理
        - 快速测试场景

        **注意**：此方法不更新 _null_profile_applied 状态，
        因为它不是 Null Profile 方案的一部分。

        Args:
            display_index: 显示器索引（0 = 主显示器）。如果为 None，使用默认索引。

        Returns:
            bool: 是否成功清除
        """
        if not self._dispwin_path:
            logger.error("dispwin 可执行文件未找到，无法清除 LUT")
            return False

        disp_idx = display_index if display_index is not None else self._default_display_index

        logger.info(f"[跨平台·降级] 正在清除显示器 {disp_idx} 的显卡 LUT...")

        try:
            # dispwin -d{display_index} -c
            # **跨平台统一**：清除显卡 1D LUT
            cmd = [self._dispwin_path, "-d", str(disp_idx), "-c"]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.info(f"[跨平台·降级] 显示器 {disp_idx} 的显卡 LUT 已成功清除")
                self._display_lut_cleared[disp_idx] = True
                return True
            else:
                stderr = result.stderr.strip()
                logger.warning(
                    f"[跨平台·降级] dispwin -c 返回非零退出码: "
                    f"{result.returncode}, stderr: {stderr}"
                )
                # dispwin -c 通常即使有警告也会成功
                # 标记为已清除以保持一致性
                self._display_lut_cleared[disp_idx] = True
                return True

        except subprocess.CalledProcessError as e:
            stderr = e.stderr.strip() if e.stderr else ""
            logger.warning(
                f"[跨平台·降级] dispwin -c 执行异常: "
                f"退出码={e.returncode}, stderr={stderr}"
            )
            return False

        except subprocess.TimeoutExpired:
            logger.error(f"[跨平台·降级] dispwin -c 执行超时")
            return False

        except Exception as e:
            logger.error(f"[跨平台·降级] 清除 LUT 时发生异常: {e}")
            return False

    def restore_lut(self, display_index: Optional[int] = None) -> bool:
        """
        恢复显卡 LUT（跨平台统一实现）

        使用 dispwin -r 恢复之前保存的 LUT 状态。

        Args:
            display_index: 显示器索引。如果为 None，使用默认索引。

        Returns:
            bool: 是否成功恢复
        """
        if not self._dispwin_path:
            logger.error("dispwin 可执行文件未找到，无法恢复 LUT")
            return False

        disp_idx = display_index if display_index is not None else self._default_display_index

        logger.info(f"[跨平台] 正在恢复显示器 {disp_idx} 的显卡 LUT...")

        try:
            # dispwin -d{display_index} -r
            # **跨平台统一**：恢复之前保存的 LUT
            cmd = [self._dispwin_path, "-d", str(disp_idx), "-r"]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.info(f"[跨平台] 显示器 {disp_idx} 的显卡 LUT 已成功恢复")
                self._display_lut_cleared[disp_idx] = False
                return True
            else:
                stderr = result.stderr.strip()
                logger.warning(
                    f"[跨平台] dispwin -r 返回非零退出码: "
                    f"{result.returncode}, stderr: {stderr}"
                )
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"[跨平台] dispwin -r 执行超时")
            return False

        except Exception as e:
            logger.error(f"[跨平台] 恢复 LUT 时发生异常: {e}")
            return False

    def load_system_profile_lut(self, display_index: Optional[int] = None) -> bool:
        """
        加载系统当前 ICC Profile 的 VCGT 到 Video LUT（跨平台统一实现）

        使用 dispwin -L 命令：
        - 获取当前系统已安装的默认 Profile
        - 将该 Profile 的 vcgt 标签加载到显卡 LUT

        **用途**：卸载 Null Profile 后刷新显示效果，确保显示真正更新。
        这是在生命周期结束时（stop_cycle / atexit）恢复原始显示状态的关键步骤。

        Args:
            display_index: 显示器索引。如果为 None，使用默认索引。

        Returns:
            bool: 是否成功加载
        """
        if not self._dispwin_path:
            logger.error("dispwin 可执行文件未找到，无法加载系统 Profile LUT")
            return False

        disp_idx = display_index if display_index is not None else self._default_display_index

        logger.info(f"[跨平台] 正在加载显示器 {disp_idx} 的系统 Profile VCGT...")

        try:
            # dispwin -d{display_index} -L
            # -L: 获取当前已安装的系统 Profile，并将其 vcgt 加载到 Video LUT
            # **跨平台统一**：dispwin 自动处理 macOS ColorSync 和 Windows WCS
            cmd = [self._dispwin_path, "-d", str(disp_idx), "-L"]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                logger.info(f"[跨平台] 显示器 {disp_idx} 的系统 Profile VCGT 已成功加载")
                self._display_lut_cleared[disp_idx] = False
                return True
            else:
                stderr = result.stderr.strip()
                logger.warning(
                    f"[跨平台] dispwin -L 返回非零退出码: "
                    f"{result.returncode}, stderr: {stderr}"
                )
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"[跨平台] dispwin -L 执行超时")
            return False

        except Exception as e:
            logger.error(f"[跨平台] 加载系统 Profile LUT 时发生异常: {e}")
            return False

    def load_icc_profile(self, icc_path: str,
                         display_index: Optional[int] = None) -> bool:
        """
        加载 ICC Profile 并应用到显卡 LUT（别名方法）

        与 apply_profile 功能相同，保留向后兼容。

        Args:
            icc_path: ICC Profile 文件路径
            display_index: 显示器索引。

        Returns:
            bool: 是否成功加载
        """
        disp_idx = display_index if display_index is not None else self._default_display_index
        return self.apply_profile(disp_idx, icc_path)

    # ========== 生产级加固 #3：环境检测 ==========

    def check_environment(self) -> EnvironmentStatus:
        """
        检查当前平台环境是否满足色彩测量的要求

        检测结果：
            - Windows: 检测 HDR 是否开启（HDR 会干扰 LUT 操作）
            - macOS: 检测系统权限（无 pyobjc 依赖）
            - 所有平台: 检测 dispwin 是否可执行

        Returns:
            EnvironmentStatus: 包含检查结果的对象
        """
        status = EnvironmentStatus()
        status.details["platform"] = self._platform
        status.details["dispwin_path"] = self._dispwin_path or "未找到"
        status.details["linear_profile_path"] = self._linear_profile_path or "未找到"

        # 1. 检查 dispwin 是否存在且可执行
        if self._dispwin_path:
            if os.access(self._dispwin_path, os.X_OK):
                status.details["dispwin_executable"] = True
                # 获取 dispwin 版本信息
                try:
                    result = subprocess.run(
                        [self._dispwin_path, "-V"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        version_info = result.stdout.strip() or result.stderr.strip()
                        status.details["dispwin_version"] = version_info
                        logger.info(f"dispwin 版本: {version_info}")
                except Exception as e:
                    logger.warning(f"无法获取 dispwin 版本: {e}")
            else:
                status.is_valid = False
                status.details["dispwin_executable"] = False
                status.errors.append(
                    f"dispwin 文件存在但不可执行: {self._dispwin_path}"
                )
        else:
            status.is_valid = False
            status.errors.append("dispwin 可执行文件未找到")

        # 2. 检查线性 ICC Profile
        if self._linear_profile_path:
            status.details["linear_profile_available"] = True
        else:
            status.warnings.append(
                "线性 ICC Profile 未找到。测色时将仅清除显卡 LUT，"
                "可能无法完全绕过系统色彩管理。"
            )
            status.details["linear_profile_available"] = False

        # 3. 平台特定检测
        if self._platform == 'Windows':
            self._check_windows_environment(status)
        elif self._platform == 'Darwin':
            self._check_macos_environment(status)
        elif self._platform == 'Linux':
            self._check_linux_environment(status)

        return status

    # ========== 内部方法 ==========

    def _check_windows_environment(self, status: EnvironmentStatus):
        """
        Windows 平台环境检测

        主要检测 HDR 状态和 Auto Color Management (ACM)。
        """
        hdr_detected = False
        acm_detected = False

        try:
            import winreg

            # ========== 方法 1：通过注册表检测 HDR 状态 ==========
            hdr_registry_keys = [
                (winreg.HKEY_CURRENT_USER,
                 r"Software\Microsoft\Windows\CurrentVersion\VideoSettings",
                 "VideoDynamicRange"),
                (winreg.HKEY_LOCAL_MACHINE,
                 r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
                 "HdrEnabled"),
            ]

            for root, subkey, value_name in hdr_registry_keys:
                try:
                    with winreg.OpenKey(root, subkey) as key:
                        value, _ = winreg.QueryValueEx(key, value_name)
                        status.details["hdr_registry_value"] = value
                        if value and value > 0:
                            hdr_detected = True
                            status.details["hdr_detected"] = True
                except FileNotFoundError:
                    pass
                except Exception as e:
                    logger.debug(f"读取注册表 HDR 状态失败: {e}")

            # ========== 方法 2：检测 Auto Color Management (ACM) ==========
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\ColorSystem"
                ) as key:
                    value, _ = winreg.QueryValueEx(key, "AutoColorManagement")
                    if value and value > 0:
                        acm_detected = True
                        status.details["acm_detected"] = True
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.debug(f"读取 ACM 状态失败: {e}")

            # ========== 生成警告 ==========
            if hdr_detected:
                status.errors.append(
                    "⚠️ 检测到 HDR 已开启！\n"
                    "HDR 模式下，Windows DWM 会强制将 SDR 窗口从 sRGB 转换到 scRGB 色彩空间，\n"
                    "即使清空显卡 LUT 也无法获得原生颜色响应。\n"
                    "请在 Windows 设置 > 系统 > 显示 > HDR 中关闭 HDR，然后再进行测量。"
                )
                status.is_valid = False

            if acm_detected:
                status.warnings.append(
                    "⚠️ 检测到 Auto Color Management (ACM) 已开启。\n"
                    "ACM 可能会干扰色彩测量结果。建议在设置 > 系统 > 显示 > 颜色 中关闭。"
                )

            if not hdr_detected and not acm_detected:
                status.details["windows_color_environment"] = "normal_sdr"

        except ImportError:
            status.warnings.append("无法导入 winreg 模块，跳过 Windows 环境检测")

        status.details["os_version"] = platform.version()

    def _check_macos_environment(self, status: EnvironmentStatus):
        """
        macOS 平台环境检测

        检测系统权限和显示器配置。不再检测 pyobjc（已移除）。
        """
        status.details["macos_version"] = platform.mac_ver()[0]

        # 检测是否是 Apple Silicon
        status.details["apple_silicon"] = "arm64" in platform.processor().lower() if platform.processor() else False

        # macOS 不需要 pyobjc，使用纯 dispwin 方案
        status.details["color_management_method"] = "dispwin_null_profile"
        logger.info("[macOS] 使用 dispwin Null Profile 方案绕过色彩管理")

    def _check_linux_environment(self, status: EnvironmentStatus):
        """
        Linux 平台环境检测

        检测显示服务器类型（X11/Wayland）。
        """
        display_server = os.environ.get("XDG_SESSION_TYPE", "unknown")
        status.details["display_server"] = display_server

        wayland_display = os.environ.get("WAYLAND_DISPLAY")
        if wayland_display:
            display_server = "wayland"
        elif os.environ.get("DISPLAY"):
            display_server = "x11"

        status.details["display_server_detected"] = display_server

        if display_server == "wayland":
            status.warnings.append(
                "检测到 Wayland 显示服务器。在某些 Wayland 合成器下，"
                "dispwin 的 LUT 操作可能受限。如遇问题，请尝试切换到 X11 会话。"
            )

        status.details["os_info"] = f"{platform.system()} {platform.release()}"

    def _auto_detect_argyll_path(self) -> str:
        """
        自动检测 ArgyllCMS bin 目录路径

        Returns:
            str: ArgyllCMS bin 目录路径，如果未找到则返回空字符串
        """
        project_root = Path(__file__).parent.parent

        possible_paths = [
            project_root / "ArgyllCMS" / "bin",
            project_root / "ArgyllCMS",
        ]

        system = platform.system()
        dispwin_name = "dispwin.exe" if system == "Windows" else "dispwin"

        for path in possible_paths:
            if path.exists() and path.is_dir():
                dispwin_path = path / dispwin_name
                if dispwin_path.exists():
                    logger.info(f"自动检测到 ArgyllCMS: {path}")
                    return str(path)

        # 检查系统 PATH
        try:
            check_cmd = ["where", "dispwin"] if system == "Windows" else ["which", "dispwin"]
            result = subprocess.run(
                check_cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info("使用系统 PATH 中的 dispwin")
                return ""
        except Exception:
            pass

        logger.warning("未检测到 ArgyllCMS dispwin，请将 ArgyllCMS 文件放入项目目录")
        return ""

    def _find_dispwin(self) -> Optional[str]:
        """
        查找 dispwin 可执行文件的完整路径

        Returns:
            Optional[str]: dispwin 的完整路径，如果未找到则返回 None
        """
        system = platform.system()
        dispwin_name = "dispwin.exe" if system == "Windows" else "dispwin"

        candidate_paths = []

        if self._argyll_bin_path:
            candidate_paths.append(Path(self._argyll_bin_path) / dispwin_name)

        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            if path_dir:
                full_path = Path(path_dir) / dispwin_name
                candidate_paths.append(full_path)

        for candidate in candidate_paths:
            if candidate.exists():
                if os.access(candidate, os.X_OK):
                    logger.info(f"找到 dispwin: {candidate}")
                    return str(candidate)
                else:
                    logger.warning(f"dispwin 文件存在但不可执行: {candidate}")

        return None

    def _auto_detect_linear_profile(self):
        """
        自动检测线性 ICC Profile 文件路径

        搜索顺序：
        1. 项目根目录下的 resources/Topos_Linear_Native.icc
        2. 项目根目录下的 Topos_Linear_Native.icc
        3. ArgyllCMS 目录下的线性 Profile（如果存在）
        """
        project_root = Path(__file__).parent.parent

        possible_paths = [
            project_root / "resources" / "Topos_Linear_Native.icc",
            project_root / "Topos_Linear_Native.icc",
            project_root / "ArgyllCMS" / "ref" / "Linear.icc",  # ArgyllCMS 可能自带
        ]

        for path in possible_paths:
            if path.exists():
                # 使用 resolve() 确保路径是绝对路径
                self._linear_profile_path = str(path.resolve())
                logger.info(f"[跨平台] 检测到线性 ICC Profile: {self._linear_profile_path}")
                return

        logger.warning("[跨平台] 未检测到线性 ICC Profile，将仅使用 dispwin -c 清除 LUT")
        self._linear_profile_path = None

    def set_default_display(self, display_index: int):
        """
        设置默认显示器索引

        Args:
            display_index: 显示器索引（0 = 主显示器）
        """
        self._default_display_index = display_index
        logger.info(f"默认显示器索引已设置为: {display_index}")

    def get_display_status(self) -> Dict[int, bool]:
        """
        获取各显示器的 LUT 状态

        Returns:
            Dict[int, bool]: 显示器索引 -> 是否已清除 LUT
        """
        return dict(self._display_lut_cleared)

    def get_current_profile(self, display_index: int) -> Optional[str]:
        """
        获取指定显示器当前挂载的 Profile 路径

        Args:
            display_index: 显示器索引

        Returns:
            Optional[str]: Profile 路径，如果未记录返回 None
        """
        return self._display_current_profile.get(display_index)

    # ========== 跨平台状态管理与生命周期清理 ==========

    def is_null_profile_applied(self) -> bool:
        """
        检查当前是否已挂载 Null Profile

        用于生命周期结束时的恢复判断（stop_cycle / atexit）。

        Returns:
            bool: True 表示 Null Profile 已挂载，需要卸载恢复
        """
        return self._null_profile_applied

    def get_null_profile_display_index(self) -> Optional[int]:
        """
        获取挂载 Null Profile 的显示器索引

        Returns:
            Optional[int]: 显示器索引，如果未挂载返回 None
        """
        return self._null_profile_display_index

    def _get_permission_error_message(self, icc_path: str) -> str:
        """
        生成权限错误的友好提示消息

        Args:
            icc_path: ICC 文件路径

        Returns:
            str: 友好的错误提示消息
        """
        if self._platform == 'Darwin':
            return (
                "ICC 安装失败：需要管理员权限\n\n"
                "解决方法：\n"
                f"• 在终端运行: sudo dispwin -I \"{icc_path}\"\n"
                "• 或者右键本应用 - 使用终端打开，然后运行 sudo python3 应用路径\n\n"
                "手动安装方法：\n"
                "• 双击 ICC 文件，点击「安装配置文件」\n"
                "• 或在 系统设置 - 显示器 中选择该配置文件"
            )
        elif self._platform == 'Windows':
            return (
                "ICC 安装失败：需要管理员权限\n\n"
                "解决方法：\n"
                "• 右键本应用 - 以管理员身份运行，然后重试\n\n"
                "手动安装方法：\n"
                "• 右键 ICC 文件 - 安装配置文件\n"
                "• 或在 设置 - 系统 - 显示 - 高级显示设置 中选择该配置文件"
            )
        else:
            return (
                "ICC 安装失败：需要管理员权限\n\n"
                "请尝试以管理员/root权限运行此应用，或手动安装ICC文件。"
            )

    def get_last_error(self) -> Optional[str]:
        """
        获取最后一次操作的详细错误信息

        Returns:
            Optional[str]: 错误信息，如果没有错误返回 None
        """
        return self._last_error

    def get_last_error_type(self) -> Optional[str]:
        """
        获取最后一次操作的错误类型

        Returns:
            Optional[str]: 错误类型 ('permission', 'not_found', 'timeout', 'other')
        """
        return self._last_error_type

    def clear_last_error(self) -> None:
        """清除最后的错误信息"""
        self._last_error = None
        self._last_error_type = None

    def cleanup_null_profile(self) -> bool:
        """
        清理 Null Profile（生命周期结束时调用）

        **跨平台统一**：此方法在 stop_cycle() 或 atexit 触发时调用，
        无差别地在所有平台上执行卸载和恢复操作。

        流程：
        1. 卸载 Null Profile (dispwin -U)
        2. 加载系统 Profile VCGT (dispwin -L)

        Returns:
            bool: 是否成功清理
        """
        if not self._null_profile_applied:
            logger.info("[跨平台] Null Profile 未挂载，无需清理")
            return True

        if not self._linear_profile_path:
            logger.warning("[跨平台] 线性 Profile 路径未记录，无法卸载")
            return False

        if not self._null_profile_display_index:
            logger.warning("[跨平台] 显示器索引未记录，无法卸载")
            return False

        display_index = self._null_profile_display_index

        logger.info(f"[跨平台·生命周期清理] 正在卸载显示器 {display_index} 的 Null Profile...")

        # 步骤 1: 卸载 Null Profile
        uninstall_success = self.uninstall_profile(display_index, self._linear_profile_path)

        if uninstall_success:
            logger.info(f"[跨平台·生命周期清理] Null Profile 已卸载")
        else:
            logger.warning(f"[跨平台·生命周期清理] Null Profile 卸载失败，继续尝试恢复 VCGT")

        # 步骤 2: macOS 专用：恢复之前保存的 Gamma 表
        # 这是解决 macOS "屏幕不刷新"问题的关键！
        # dispwin -L 在 macOS 上经常失败，需要直接用 CGSetDisplayTransferByTable 恢复
        if self._platform == 'Darwin' and self._saved_gamma_table:
            logger.info("[macOS·生命周期清理] 恢复保存的 Gamma 表...")
            self._restore_gamma_table_macos()

        # 步骤 3: 加载系统 Profile VCGT（即使卸载失败也尝试恢复）
        logger.info(f"[跨平台·生命周期清理] 正在加载系统 Profile VCGT...")
        lut_success = self.load_system_profile_lut(display_index)

        # 步骤 4: macOS 专用 ColorSync 强制刷新（作为兜底）
        # 确保 WindowServer 立即响应变化，屏幕真正恢复
        self._refresh_colorsync_macos()

        if lut_success:
            logger.info(f"[跨平台·生命周期清理] 系统 Profile VCGT 已加载，显示已恢复")
            self._null_profile_applied = False
            self._null_profile_display_index = None
            return True
        else:
            logger.warning(f"[跨平台·生命周期清理] 加载系统 VCGT 失败")
            return False

    def cleanup_null_profile_direct(self) -> bool:
        """
        直接清理 Null Profile（用于 atexit 等极端场景）

        **特殊场景**：此方法用于 atexit 或异常钩子等极端场景，
        避免通过常规方法可能导致的问题（如信号发射、锁等待等）。

        直接使用 subprocess 调用，不依赖其他方法。

        Returns:
            bool: 是否成功清理
        """
        if not self._null_profile_applied:
            return True

        if not self._dispwin_path or not self._linear_profile_path or not self._null_profile_display_index:
            return False

        display_index = self._null_profile_display_index

        try:
            # 直接调用 dispwin 卸载 Profile
            subprocess.run(
                [self._dispwin_path, "-d", str(display_index), "-U", self._linear_profile_path, "-S", "u"],
                capture_output=True,
                timeout=5
            )

            # 直接调用 dispwin 加载系统 VCGT
            subprocess.run(
                [self._dispwin_path, "-d", str(display_index), "-L"],
                capture_output=True,
                timeout=5
            )

            # macOS 专用：强制物理刷新（Swift 脚本 + ColorSync 恢复）
            # 这是解决 macOS "屏幕不刷新"问题的关键！
            swift_script = _get_refresh_script_path()
            _force_macos_display_refresh(swift_script_path=swift_script)

            # macOS 专用：恢复保存的 Gamma 表
            # 在 atexit 极端场景下，直接调用 CGSetDisplayTransferByTable
            if _MAC_CG_API_READY and self._saved_gamma_table:
                try:
                    import ctypes
                    display_id = _MAC_CG_LIB.CGMainDisplayID()
                    count = self._saved_gamma_table['count']
                    red = (ctypes.c_float * count)(*self._saved_gamma_table['red'])
                    green = (ctypes.c_float * count)(*self._saved_gamma_table['green'])
                    blue = (ctypes.c_float * count)(*self._saved_gamma_table['blue'])
                    _MAC_CG_LIB.CGSetDisplayTransferByTable(display_id, count, red, green, blue)
                except Exception:
                    pass  # 极端场景，忽略异常
            elif _MAC_CG_API_READY:
                # 无保存的 Gamma 表，设置 Gamma 2.2
                try:
                    import ctypes
                    display_id = _MAC_CG_LIB.CGMainDisplayID()
                    table_size = 256
                    red = (ctypes.c_float * table_size)()
                    green = (ctypes.c_float * table_size)()
                    blue = (ctypes.c_float * table_size)()
                    for i in range(table_size):
                        y = (i / (table_size - 1)) ** (1.0 / 2.2)
                        red[i] = y
                        green[i] = y
                        blue[i] = y
                    _MAC_CG_LIB.CGSetDisplayTransferByTable(display_id, table_size, red, green, blue)
                except Exception:
                    pass

            # 标记已清理
            self._null_profile_applied = False
            self._null_profile_display_index = None

            return True

        except Exception:
            # 极端场景下，清理失败不抛出异常
            return False