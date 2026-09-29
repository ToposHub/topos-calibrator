# 跨平台色彩管理架构文档

## 概述

本项目的核心目标：**绕过系统色彩管理以获取物理原生颜色**。

在开始显示测量色块之前，必须清空系统显卡的硬件 LUT（VCGT），让输出呈线性状态。测量结束后，恢复原始 LUT 或加载新的 ICC Profile。

## 跨平台策略

### 对应 C++ Qt 的宏定义

| C++ Qt 宏 | Python 等价实现 |
|-----------|----------------|
| `#ifdef Q_OS_MAC` | `platform.system() == 'Darwin'` |
| `#ifdef Q_OS_WIN` | `platform.system() == 'Windows'` |
| `#ifdef Q_OS_LINUX` | `platform.system() == 'Linux'` |

### 1. 所有平台通用（VCGT LUT 清除与恢复）

**核心模块**: `src/display_lut_controller.py`

```
CalibrationEngine::clearVideoCardLUT()   →   DisplayLUTController.clear_lut()
CalibrationEngine::restoreVideoCardLUT() →   DisplayLUTController.restore_lut()
```

**实现方式**: 通过 `QProcess` 的 Python 等价物 `subprocess.run()` 静默调用 ArgyllCMS 的 `dispwin` 命令：

| 操作 | 命令 | 说明 |
|------|------|------|
| 清除 LUT | `dispwin -d <index> -c` | 清空指定显示器的显卡 LUT |
| 恢复 LUT | `dispwin -d <index> -r` | 恢复指定显示器的显卡 LUT |
| 加载 ICC | `dispwin -d <index> -I <profile.icc>` | 挂载新的 ICC Profile |

### 2. macOS 平台特殊处理

**对应代码**: `#ifdef Q_OS_MAC` → `platform.system() == 'Darwin'`

macOS 的 Window Server 会强制进行色彩映射，因此必须：

1. **获取测量窗口的 NSWindow* 句柄**
2. **强制设置为 `NSColorSpace.deviceRGBColorSpace`**

**实现方式**: 通过 `pyobjc` 框架（`Foundation` + `AppKit`）

```python
# display_lut_controller.py
from AppKit import NSColorSpace, NSApp

# 设置设备 RGB 色彩空间
device_rgb = NSColorSpace.deviceRGBColorSpace()
window.setColorSpace_(device_rgb)

# 恢复原始色彩空间
window.setColorSpace_(original_colorspace)
```

**依赖**: `requirements.txt` 中添加了条件依赖：
```
pyobjc-core>=9.0; sys_platform == 'darwin'
pyobjc-framework-Cocoa>=9.0; sys_platform == 'darwin'
pyobjc-framework-Quartz>=9.0; sys_platform == 'darwin'
```

### 3. Windows 和 Linux 平台处理

**对应代码**: `#if defined(Q_OS_WIN) || defined(Q_OS_LINUX)`

在这两个平台上：
- 桌面窗口管理器（DWM / X11 / Wayland）通常不会强制色彩映射
- 核心在于确保 Qt 框架自身不进行颜色转换

**实现方式**:
1. **`main.py`**: 不设置 `Qt::AA_UseColorManagement` 属性
2. **`display_lut_controller.py`**: `setup_windows_linux_color_management()` 仅记录日志
3. 依赖 `dispwin -c` 清空显卡 LUT 即可实现"裸奔"输出

## 模块关系图

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 禁用 Qt 色彩管理                                      │    │
│  │ - 不设置 AA_UseColorManagement                       │    │
│  │ - Windows/Linux: 仅依赖 dispwin                      │    │
│  │ - macOS: 后续通过 pyobjc 设置 NSColorSpace           │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     src/backend.py                           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ _init_lut_controller()                               │    │
│  │   1. 创建 DisplayLUTController                       │    │
│  │   2. check_environment() - 环境检测                  │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ _start_cycle() - 开始测量                             │    │
│  │   1. _get_patch_display_index() - 获取屏幕索引       │    │
│  │   2. lut_controller.clear_lut(display_index)         │    │
│  │   3. [macOS] setup_macos_color_space()               │    │
│  │   4. 开始循环测量色块...                               │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ _cycle_next_measurement() - 测量完成                  │    │
│  │   1. _get_patch_display_index()                      │    │
│  │   2. [macOS] restore_macos_color_space()             │    │
│  │   3. lut_controller.restore_lut(display_index)       │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ stop_cycle() - 测量取消                               │    │
│  │   1. _get_patch_display_index()                      │    │
│  │   2. [macOS] restore_macos_color_space()             │    │
│  │   3. lut_controller.restore_lut(display_index)       │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              src/display_lut_controller.py                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 生产级加固 #4：构造函数抛出 DispwinNotFoundError    │    │
│  │ 如果 dispwin 未找到，立即抛出明确异常                │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ clear_lut(display_index)                              │    │
│  │   → subprocess dispwin -d <index> -c                 │    │
│  │ restore_lut(display_index)                            │    │
│  │   → subprocess dispwin -d <index> -r                 │    │
│  │ load_icc_profile(icc, display_index)                  │    │
│  │   → subprocess dispwin -d <index> -I xxx.icc         │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ check_environment() - 生产级加固 #3                  │    │
│  │   - Windows: 检测 HDR 注册表状态                     │    │
│  │   - macOS: 检测 pyobjc 是否可用                      │    │
│  │   - Linux: 检测 X11/Wayland 显示服务器               │    │
│  │   - 所有平台: 验证 dispwin 可执行性                  │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ setup_macos_measurement_color_space()                 │    │
│  │   生产级加固 #1：正确的 NSView → NSWindow 转换       │    │
│  │   → objc.objc_object(metaclass=NSView, pointer=...) │    │
│  │   → view.window()                                   │    │
│  │   → window.setColorSpace_(deviceRGB)                 │    │
│  │   → _verify_macos_colorspace() 验证设置是否生效      │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## 生产级加固详情

### 加固 #1：修正 macOS 句柄转换逻辑

**问题**: PyQt 的 `winId()` 在 macOS 上返回的是 `NSView*` 指针，而非 `NSWindow*`。

**解决方案**:
```python
# 步骤 1：将整数指针转换为 NSView 对象
nsview = objc.objc_object(metaclass=NSView, pointer=handle)

# 步骤 2：通过 NSView.window() 获取 NSWindow 实例
window = nsview.window()

# 步骤 3：调用 setColorSpace_
window.setColorSpace_(NSColorSpace.deviceRGBColorSpace())
```

**兜底策略**: 如果 `window()` 返回 None，遍历 `NSApp.sharedApplication().windows()` 查找可见窗口。

### 加固 #2：增加多显示器支持

**问题**: 多显示器环境下，`dispwin` 默认操作主显示器，可能导致测量色块所在的屏幕未被正确处理。

**解决方案**:
- `clear_lut(display_index)` → `dispwin -d <index> -c`
- `restore_lut(display_index)` → `dispwin -d <index> -r`
- `load_icc_profile(icc, display_index)` → `dispwin -d <index> -I <icc>`
- `Backend._get_patch_display_index()` 自动获取测量窗口所在屏幕的索引

**屏幕索引获取逻辑**:
```python
screen = self._patch_window.screen()
screens = QApplication.screens()
for i, s in enumerate(screens):
    if s == screen:
        return i
return 0  # 默认主显示器
```

### 加固 #3：细化环境检测

**问题**: 用户可能在不利环境下进行测量（如 Windows HDR 开启），导致测量结果不准确。

**解决方案**: 新增 `check_environment()` 方法，返回 `EnvironmentStatus` 对象：

| 平台 | 检测项 | 不满足时的影响 |
|------|--------|---------------|
| Windows | HDR 注册表状态 | HDR 开启时 LUT 操作可能无效 |
| macOS | pyobjc 是否可用 | 无法设置 ColorSpace |
| Linux | X11/Wayland 显示服务器 | Wayland 下 LUT 操作可能受限 |
| 所有平台 | dispwin 可执行性 | 无法清除/恢复 LUT |

**调用时机**:
- `Backend._init_lut_controller()` 初始化时自动检测
- 结果通过 `logMessage` 信号输出到 UI
- 严重问题时通过 `probeStatusChanged` 信号通知 UI

### 加固 #4：完善依赖处理

**问题**: 
1. `pyobjc-core` 是 pyobjc 的基础，必须先安装
2. `dispwin` 未找到时没有明确提示

**解决方案**:
1. **requirements.txt** 添加 `pyobjc-core` 并放在首位：
   ```
   pyobjc-core>=9.0; sys_platform == 'darwin'
   pyobjc-framework-Cocoa>=9.0; sys_platform == 'darwin'
   ```

2. **构造函数异常**: 如果 `dispwin` 未找到，抛出 `DispwinNotFoundError`：
   ```python
   if not self._dispwin_path:
       raise DispwinNotFoundError(
           f"无法找到 ArgyllCMS 的 dispwin 工具。\n"
           f"请确保 ArgyllCMS 已安装，并将 dispwin 所在路径添加到 PATH 环境变量，\n"
           f"或将 ArgyllCMS 文件放入项目目录的 ArgyllCMS/ 文件夹中。"
       )
   ```

3. **Backend 容错处理**: 捕获初始化异常，不阻断程序启动，但输出警告：
   ```python
   try:
       self._lut_controller = DisplayLUTController(...)
   except Exception as e:
       self._lut_controller = None
       self.logMessage.emit(f"警告: DisplayLUTController 初始化失败: {e}")
   ```

## 测量流程中的 LUT 控制

```
测量开始
    │
    ▼
_get_patch_display_index() ─→ 获取测量窗口所在屏幕索引
    │
    ▼
clear_lut(display_index) ──→ dispwin -d <index> -c (所有平台)
    │
    ├─ [macOS] setup_macos_measurement_color_space()
    │       → NSView* → NSWindow 转换（加固 #1）
    │       → NSColorSpace.deviceRGBColorSpace
    │       → _verify_macos_colorspace() 验证
    │
    ├─ [Windows] setup_windows_linux_color_management() → 无操作
    │
    └─ [Linux] setup_windows_linux_color_management() → 无操作
    │
    ▼
显示色块 → 测量 → 存储结果
    │
    ▼ (循环下一个色块)
    │
    ▼ (测量完成或取消)
_get_patch_display_index() ─→ 获取相同屏幕索引
    │
    ▼
restore_macos_measurement_color_space() (仅 macOS)
    │
    ▼
restore_lut(display_index) ──→ dispwin -d <index> -r (所有平台)
```

## 文件清单

| 文件 | 说明 |
|------|------|
| `src/display_lut_controller.py` | 跨平台 LUT 控制核心模块（含 4 项生产级加固） |
| `src/backend.py` | 集成 LUT 控制到测量流程 |
| `main.py` | 禁用 Qt 色彩管理 |
| `src/patch_window.py` | 测量色块窗口（更新注释） |
| `requirements.txt` | 添加 macOS pyobjc 依赖（含 pyobjc-core） |
| `src/__init__.py` | 导出 DisplayLUTController 及异常类 |

## C++ Qt 与 Python 的对应关系

| C++ Qt | Python PyQt6 |
|--------|-------------|
| `#ifdef Q_OS_MAC` | `platform.system() == 'Darwin'` |
| `#ifdef Q_OS_WIN` | `platform.system() == 'Windows'` |
| `#ifdef Q_OS_LINUX` | `platform.system() == 'Linux'` |
| `QProcess` | `subprocess.run()` |
| `QApplication::setAttribute(Qt::AA_UseColorManagement, false)` | 不设置该属性（PyQt6 默认不启用） |
| `NSColorSpace.deviceRGBColorSpace()` (Obj-C++) | `NSColorSpace.deviceRGBColorSpace()` (pyobjc) |
| `-framework AppKit` (CMakeLists.txt) | `pyobjc-core`, `pyobjc-framework-Cocoa` (requirements.txt) |
| `CalibrationEngine::checkEnvironment()` | `DisplayLUTController.check_environment()` → `EnvironmentStatus` |
| `dispwin -c` | `DisplayLUTController.clear_lut(display_index)` |
| `dispwin -r` | `DisplayLUTController.restore_lut(display_index)` |

## 异常类

| 异常类 | 触发条件 | 处理方式 |
|--------|---------|---------|
| `DispwinNotFoundError` | `dispwin` 可执行文件未找到 | Backend 捕获并输出警告，程序继续运行 |
| `DispwinExecutionError` | `dispwin` 执行失败（预留） | 可由上层代码捕获处理 |
