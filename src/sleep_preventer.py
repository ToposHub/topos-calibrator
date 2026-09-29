"""
SystemSleepPreventer - 跨平台防休眠工具

在长时间测量过程中阻止系统和显示器进入休眠状态，确保测量稳定性。

支持平台：
- Windows: 使用 SetThreadExecutionState API
- macOS: 使用 caffeinate 命令
- Linux: 使用 systemd-inhibit (基础支持)

使用方式：
    # 方式1: 上下文管理器（推荐）
    with SystemSleepPreventer():
        # 测量代码...
        pass

    # 方式2: 手动控制
    preventer = SystemSleepPreventer()
    preventer.start()
    try:
        # 测量代码...
        pass
    finally:
        preventer.stop()
"""

import platform
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SystemSleepPreventer:
    """
    跨平台系统防休眠工具

    阻止系统休眠和显示器关闭，确保长时间测量任务不被中断。

    使用示例:
        with SystemSleepPreventer():
            # 执行长时间测量
            perform_measurement()
    """

    # Windows API 常量
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    def __init__(self):
        """初始化防休眠控制器"""
        self._active = False
        self._platform = platform.system()
        self._caffeinate_process: Optional[subprocess.Popen] = None
        self._previous_state: Optional[int] = None  # Windows: 保存之前的执行状态

    def start(self) -> bool:
        """
        启动防休眠保护

        Returns:
            bool: 是否成功启动
        """
        if self._active:
            logger.warning("防休眠保护已处于活动状态")
            return True

        try:
            if self._platform == "Windows":
                return self._start_windows()
            elif self._platform == "Darwin":
                return self._start_macos()
            elif self._platform == "Linux":
                return self._start_linux()
            else:
                logger.warning(f"不支持的平台: {self._platform}，防休眠功能将不会生效")
                return False
        except Exception as e:
            logger.error(f"启动防休眠保护失败: {e}")
            return False

    def stop(self) -> bool:
        """
        停止防休眠保护，恢复系统默认电源管理

        Returns:
            bool: 是否成功停止
        """
        if not self._active:
            return True

        try:
            if self._platform == "Windows":
                return self._stop_windows()
            elif self._platform == "Darwin":
                return self._stop_macos()
            elif self._platform == "Linux":
                return self._stop_linux()
            else:
                return True
        except Exception as e:
            logger.error(f"停止防休眠保护失败: {e}")
            return False
        finally:
            self._active = False

    def _start_windows(self) -> bool:
        """
        Windows 平台: 使用 SetThreadExecutionState API

        参考: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate

        ES_CONTINUOUS: 状态持续生效，直到下一次调用并清除该标志
        ES_SYSTEM_REQUIRED: 阻止系统自动进入睡眠
        ES_DISPLAY_REQUIRED: 阻止显示器自动关闭
        """
        import ctypes

        # 组合标志：持续阻止系统休眠和显示器关闭
        flags = self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | self.ES_DISPLAY_REQUIRED

        # 调用 Windows API
        result = ctypes.windll.kernel32.SetThreadExecutionState(flags)

        if result == 0:
            # 返回 0 表示失败
            logger.error("SetThreadExecutionState 调用失败")
            return False

        self._previous_state = result
        self._active = True
        logger.info("Windows: 防休眠保护已启动 (ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)")
        return True

    def _stop_windows(self) -> bool:
        """
        Windows 平台: 恢复系统默认电源状态

        通过设置 ES_CONTINUOUS 但不设置其他标志来清除之前的请求
        """
        import ctypes

        # 清除之前的请求，恢复系统默认电源管理
        result = ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)

        if result == 0:
            logger.error("SetThreadExecutionState (清除) 调用失败")
            return False

        self._previous_state = None
        logger.info("Windows: 防休眠保护已停止，系统电源管理已恢复正常")
        return True

    def _start_macos(self) -> bool:
        """
        macOS 平台: 使用 caffeinate 命令

        -d: 阻止显示器休眠
        -i: 阻止系统空闲休眠
        -s: 仅在接电源时阻止系统休眠（笔记本场景）
        -u: 模拟用户活动

        我们使用 caffeinate -d -i 来阻止显示器和系统休眠
        """
        try:
            # 启动 caffeinate 进程，阻止休眠
            # -d: 阻止显示器休眠
            # -i: 阻止系统空闲休眠
            self._caffeinate_process = subprocess.Popen(
                ['caffeinate', '-d', '-i'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            self._active = True
            logger.info("macOS: 防休眠保护已启动 (caffeinate -d -i)")
            return True
        except FileNotFoundError:
            logger.error("caffeinate 命令不存在")
            return False
        except Exception as e:
            logger.error(f"启动 caffeinate 失败: {e}")
            return False

    def _stop_macos(self) -> bool:
        """macOS 平台: 终止 caffeinate 进程"""
        if self._caffeinate_process is not None:
            try:
                self._caffeinate_process.terminate()
                # 等待进程结束（最多等待 3 秒）
                try:
                    self._caffeinate_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    # 如果进程未响应，强制杀死
                    self._caffeinate_process.kill()
                    self._caffeinate_process.wait()

                logger.info("macOS: 防休眠保护已停止，caffeinate 进程已终止")
            except Exception as e:
                logger.error(f"终止 caffeinate 进程失败: {e}")
            finally:
                self._caffeinate_process = None

        return True

    def _start_linux(self) -> bool:
        """
        Linux 平台: 使用 systemd-inhibit 或 xdg-screensaver

        注意: Linux 平台支持有限，依赖于 systemd 或 X11
        """
        try:
            # 尝试使用 systemd-inhibit
            # 这是一个临时解决方案，实际效果取决于桌面环境
            self._caffeinate_process = subprocess.Popen(
                ['systemd-inhibit', '--what=sleep:idle', '--who=Topos Calibrator',
                 '--why=正在进行显示器测量，需要阻止休眠', 'sleep', 'infinity'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self._active = True
            logger.info("Linux: 防休眠保护已启动 (systemd-inhibit)")
            return True
        except FileNotFoundError:
            logger.warning("Linux: systemd-inhibit 不存在，尝试备用方案")
        except Exception as e:
            logger.error(f"启动 systemd-inhibit 失败: {e}")

        # 备用方案：尝试 xdg-screensaver
        try:
            subprocess.run(['xdg-screensaver', 'reset'], check=False)
            self._active = True
            logger.info("Linux: 防休眠保护已启动 (xdg-screensaver reset)")
            return True
        except Exception as e:
            logger.error(f"Linux 平台防休眠启动失败: {e}")
            return False

    def _stop_linux(self) -> bool:
        """Linux 平台: 停止防休眠保护"""
        if self._caffeinate_process is not None:
            try:
                self._caffeinate_process.terminate()
                self._caffeinate_process.wait(timeout=3)
            except Exception:
                pass
            finally:
                self._caffeinate_process = None

        logger.info("Linux: 防休眠保护已停止")
        return True

    @property
    def is_active(self) -> bool:
        """返回当前防休眠保护是否处于活动状态"""
        return self._active

    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口：确保在退出时停止防休眠保护"""
        self.stop()
        return False  # 不抑制异常