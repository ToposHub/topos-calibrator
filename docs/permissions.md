# Topos Calibrator 权限模型文档

**版本**: 1.0
**更新日期**: 2026-05-19
**相关任务**: P7-D (安全与权限模型)

---

## 1. 概述

Topos Calibrator 作为专业显示器校色软件，需要访问多种系统资源才能正常工作。本文档整理了 ArgyllCMS 所需的系统权限，以及各平台下的权限检测方法、获取方式和验证命令。

权限检查集成在预检模块 (`src/workflows/preflight.py`) 中，每项检查产出 `PASS/WARN/BLOCK` 状态结果。

---

## 2. 权限清单总览

| 权限类型 | macOS | Windows | Linux | 影响 |
|----------|-------|---------|-------|------|
| USB 设备访问 | com.apple.security.device.usb | USB HID 驱动 | /dev/usb/hid* 读权限 | BLOCK - 无法访问测量仪器 |
| 屏幕录制/显示捕获 | 屏幕录制权限 | 不需要特殊权限 | X11/Wayland 访问 | WARN - LUT 写入可能受限 |
| 辅助功能/DDC/CI | 辅助功能权限 | 不需要特殊权限 | i2c-dev 设备权限 | WARN - 无法控制显示器亮度 |
| 显卡 LUT 写入 | 核心显示 API | 不需要特殊权限 | /sys/class/backlight 写权限 | WARN - LUT 操作可能受限 |

---

## 3. macOS 权限详情

### 3.1 USB 设备访问权限 (com.apple.security.device.usb)

**用途**: 访问 USB HID 测量仪器（如 i1Display Pro、SpyderX 等）

**影响**: BLOCK - 无法连接测量仪器

#### 三要素

| 项目 | 说明 |
|------|------|
| **检测方法** | 使用 IOKit API 检查 IOUSBDevice 匹配能力，或实际尝试设备访问 |
| **获取方式** | 系统设置 > 隐私与安全性 > USB 设备访问，授权 Topos Calibrator |
| **验证命令** | `spotread -e` 或运行预检模块 |

#### 检测代码

```python
# 使用 IOKit 检查 USB 设备访问能力
import ctypes.util
iokit_path = ctypes.util.find_library("IOKit")
if iokit_path:
    iokit = ctypes.cdll.LoadLibrary(iokit_path)
    matching = iokit.IOServiceMatching("IOUSBDevice")
    if matching:
        # 可以创建 USB 匹配字典，权限可能正常
```

#### 用户引导

当检测到 USB 权限问题时，预检结果显示：

```
[BLOCK] permission_usb: 缺少 USB 设备访问权限
建议: 在"系统设置 > 隐私与安全性 > USB 设备"中授权 Topos Calibrator
修复命令: 打开系统设置: open "x-apple.systempreferences:com.apple.preference.security?Privacy_USB"
```

#### 打包声明 (Entitlements)

```xml
<!-- Entitlements.plist -->
<key>com.apple.security.device.usb</key>
<true/>
```

---

### 3.2 屏幕录制权限

**用途**: 获取显示器像素数据，用于显卡 LUT 写入验证和屏幕捕获

**影响**: WARN - LUT 写入验证可能受限，但不影响测量功能

#### 三要素

| 项目 | 说明 |
|------|------|
| **检测方法** | 使用 ScreenCaptureKit 或 CoreGraphics 检查屏幕捕获能力 |
| **获取方式** | 系统设置 > 隐私与安全性 > 屏幕录制，授权 Topos Calibrator |
| **验证命令** | 运行预检模块或尝试使用 dispwin 进行 LUT 操作 |

#### 检测代码

```python
# 使用 CoreGraphics 检查屏幕捕获权限
import ctypes.util
cg_path = ctypes.util.find_library("CoreGraphics")
if cg_path:
    cg_lib = ctypes.cdll.LoadLibrary(cg_path)
    
    # CGWindowListCopyWindowInfo 检查窗口列表获取能力
    cg_lib.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    
    window_list = cg_lib.CGWindowListCopyWindowInfo(
        ctypes.c_uint32(1),  # kCGWindowListOptionOnScreenOnly
        ctypes.c_uint32(0)   # kCGNullWindowID
    )
    
    if window_list:
        # 权限正常
```

#### 用户引导

```
[WARN] permission_screen_capture: 缺少屏幕录制权限
建议: 在"系统设置 > 隐私与安全性 > 屏幕录制"中授权 Topos Calibrator
修复命令: open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
```

#### 打包声明

```xml
<!-- Entitlements.plist -->
<key>com.apple.security.screen-capture</key>
<true/>
```

---

### 3.3 辅助功能权限

**用途**: DDC/CI 显示器控制（调整亮度、对比度等）

**影响**: WARN - 无法自动控制显示器，需要手动操作

#### 三要素

| 项目 | 说明 |
|------|------|
| **检测方法** | 使用 AXIsProcessTrusted API 检查辅助功能权限 |
| **获取方式** | 系统设置 > 隐私与安全性 > 辅助功能，授权 Topos Calibrator |
| **验证命令** | 运行预检模块 |

#### 检测代码

```python
# 使用 ApplicationServices 检查辅助功能权限
import ctypes.util
app_services_path = ctypes.util.find_library("ApplicationServices")
if app_services_path:
    app_services = ctypes.cdll.LoadLibrary(app_services_path)
    
    # AXIsProcessTrusted
    app_services.AXIsProcessTrusted.restype = ctypes.c_bool
    is_trusted = app_services.AXIsProcessTrusted()
    
    if is_trusted:
        # 权限已授予
```

#### 用户引导

```
[WARN] permission_accessibility: 缺少辅助功能权限
建议: 在"系统设置 > 隐私与安全性 > 辅助功能"中授权 Topos Calibrator
修复命令: open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
```

---

## 4. Windows 权限详情

### 4.1 USB HID 驾动权限

**用途**: 访问 USB HID 测量仪器

**影响**: BLOCK - 无法连接测量仪器

#### 三要素

| 项目 | 说明 |
|------|------|
| **检测方法** | 检查设备管理器中 HID 设备状态，或实际尝试设备访问 |
| **获取方式** | Windows 通常不需要额外权限，但可能需要安装 HID 驱动 |
| **验证命令** | `spotread.exe -e` 或运行预检模块 |

#### 检测方法

```python
# Windows: 使用 pywin32 检查 HID 设备
try:
    import win32api
    import win32con
    
    # 检查 HID 设备列表
    # 使用 SetupAPI 或 WMI 检查设备状态
    import subprocess
    result = subprocess.run(
        ["powershell", "-Command", 
         "Get-PnpDevice | Where-Object {$_.FriendlyName -like '*HID*'}"],
        capture_output=True, text=True, timeout=10
    )
    
    # 解析设备状态
```

#### 用户引导

```
[BLOCK] permission_usb_windows: USB HID 设备访问受限
建议: 
1. 检查设备管理器中 HID 设备状态
2. 确保测量仪器驱动已正确安装
3. 尝试重新插拔仪器
修复命令: 打开设备管理器: devmgmt.msc
```

#### 注意事项

- ArgyllCMS 使用 libusb 或 HID API，通常不需要特殊权限
- 部分仪器可能需要特定驱动（如 X-Rite i1Pro 系列）
- 如果仪器被其他软件占用，需要先关闭其他软件

---

### 4.2 DDC/CI 显示器通信

**用途**: 控制显示器亮度、对比度等参数

**影响**: WARN - 无法自动控制显示器参数

#### 三要素

| 项目 | 说明 |
|------|------|
| **检测方法** | 尝试通过 DDC/CI 协议查询显示器参数 |
| **获取方式** | Windows 不需要特殊权限，但显示器必须支持 DDC/CI |
| **验证命令** | 使用 Argyll dispwin 或第三方 DDC/CI 工具测试 |

#### 检测方法

```python
# Windows: 检查 DDC/CI 支持
# 使用 Win32 API 或 WMI
import subprocess

# 检查显示器是否支持 DDC/CI
result = subprocess.run(
    ["powershell", "-Command",
     "Get-WmiObject -Namespace root\\wmi -Class WmiMonitorBrightness"],
    capture_output=True, text=True, timeout=10
)

# 如果返回亮度信息，说明 DDC/CI 可用
```

#### 用户引导

```
[WARN] permission_ddc_ci_windows: DDC/CI 通信不可用
建议:
1. 确认显示器支持 DDC/CI（MCCS 协议）
2. 在显示器 OSD 中启用 DDC/CI 功能
3. 某些显示器需要特定驱动才能支持 DDC/CI
```

---

### 4.3 显卡 LUT 写入

**用途**: 写入显卡 Gamma 表 (VCGT) 以调整显示输出

**影响**: WARN - 无法加载 LUT，校准效果可能受限

#### 三要素

| 项目 | 说明 |
|------|------|
| **检测方法** | 尝试使用 Win32 API 写入 Gamma 表 |
| **获取方式** | 通常不需要特殊权限；某些情况需要管理员权限或签名驱动 |
| **验证命令** | 使用 dispwin 测试 LUT 写入 |

#### 检测方法

```python
# Windows: 检查 Gamma 表写入能力
import ctypes

# 使用 Win32 API SetDeviceGammaRamp
user32 = ctypes.windll.user32

# 获取显示器设备
hdc = user32.GetDC(0)

# 尝试设置 Gamma Ramp
# 如果返回成功，说明 LUT 写入可用
```

#### 注意事项

- Windows 10/11 通常不需要管理员权限即可写入 LUT
- 某些安全软件可能阻止 Gamma 表修改
- HDR 模式下 LUT 写入可能受限

---

## 5. Linux 权限详情

### 5.1 USB HID 设备权限

**用途**: 访问 USB HID 测量仪器

**影响**: BLOCK - 无法连接测量仪器

#### 三要素

| 项目 | 说明 |
|------|------|
| **检测方法** | 检查 /dev/usb/hid* 或 /dev/hidraw* 设备的读写权限 |
| **获取方式** | 配置 udev 规则，或使用 uucp/uucp 组权限 |
| **验证命令** | `ls -la /dev/hidraw*` 或 `spotread -e` |

#### 检测方法

```python
# Linux: 检查 HID 设备权限
import os
import glob

hid_devices = glob.glob("/dev/hidraw*") + glob.glob("/dev/usb/hid*")

for device in hid_devices:
    if os.access(device, os.R_OK | os.W_OK):
        # 权限正常
        pass
    else:
        # 权限不足
        pass
```

#### 用户引导

```
[BLOCK] permission_usb_linux: USB HID 设备权限不足
建议: 添加 udev 规则或将用户加入 uucp 组
修复命令: 
sudo usermod -a -G uucp $USER
# 或创建 udev 规则:
sudo tee /etc/udev/rules.d/99-argyll.rules << 'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="0765", MODE="0666"
SUBSYSTEM=="hidraw", MODE="0666"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger
```

#### udev 规则示例

```bash
# /etc/udev/rules.d/99-argyll.rules
# ArgyllCMS 测量仪器 udev 规则

# X-Rite i1Display Pro (Vendor ID: 0765)
SUBSYSTEM=="usb", ATTR{idVendor}=="0765", MODE="0666"

# Datacolor SpyderX (Vendor ID: 0852)
SUBSYSTEM=="usb", ATTR{idVendor}=="0852", MODE="0666"

# 所有 HID 设备
SUBSYSTEM=="hidraw", MODE="0666"

# 重新加载规则后生效:
sudo udevadm control --reload-rules
sudo udevadm trigger
```

---

### 5.2 i2c-dev 设备权限 (DDC/CI)

**用途**: 通过 I2C 协议与显示器通信，控制亮度等参数

**影响**: WARN - 无法自动控制显示器参数

#### 三要素

| 项目 | 说明 |
|------|------|
| **检测方法** | 检查 /dev/i2c-* 设备权限和 i2c-dev 模块加载状态 |
| **获取方式** | 加载 i2c-dev 模块，配置设备权限 |
| **验证命令** | `lsmod | grep i2c_dev` 和 `ls -la /dev/i2c-*` |

#### 检测方法

```python
# Linux: 检查 i2c-dev 模块和设备权限
import os
import glob
import subprocess

# 检查 i2c-dev 模块是否加载
result = subprocess.run(["lsmod"], capture_output=True, text=True)
i2c_loaded = "i2c_dev" in result.stdout

# 检查 i2c 设备权限
i2c_devices = glob.glob("/dev/i2c-*")
for device in i2c_devices:
    if os.access(device, os.R_OK | os.W_OK):
        # 权限正常
        pass
```

#### 用户引导

```
[WARN] permission_ddc_ci_linux: i2c-dev 设备权限不足
建议:
1. 加载 i2c-dev 模块: sudo modprobe i2c-dev
2. 配置 udev 规则或加入 i2c 组
修复命令:
sudo modprobe i2c-dev
sudo usermod -a -G i2c $USER
# 持久化 i2c-dev 模块:
echo "i2c-dev" | sudo tee /etc/modules-load.d/i2c.conf
```

---

### 5.3 /sys/class/backlight 写权限

**用途**: 控制显示器背光亮度（适用于笔记本等设备）

**影响**: WARN - 无法调整亮度，需手动控制

#### 三要素

| 项目 | 说明 |
|------|------|
| **检测方法** | 检查 /sys/class/backlight/*/brightness 文件写权限 |
| **获取方式** | 加入 video 组，或使用 udev 规则 |
| **验证命令** | `ls -la /sys/class/backlight/*/brightness` |

#### 检测方法

```python
# Linux: 检查 backlight 权限
import os
import glob

backlight_devices = glob.glob("/sys/class/backlight/*")
for device in backlight_devices:
    brightness_file = os.path.join(device, "brightness")
    if os.path.exists(brightness_file):
        if os.access(brightness_file, os.W_OK):
            # 权限正常
            pass
```

#### 用户引导

```
[WARN] permission_backlight_linux: 背光控制权限不足
建议: 将用户加入 video 组
修复命令: sudo usermod -a -G video $USER
```

---

## 6. 权限状态检查集成

### 6.1 预检模块集成

权限检查已集成到预检模块 (`src/workflows/preflight.py`)，检查项包括：

| 检查项 ID | 平台 | 权限类型 | 状态影响 |
|-----------|------|----------|----------|
| `permission_usb` | macOS | USB 设备访问 | BLOCK |
| `permission_usb_windows` | Windows | USB HID 权限 | BLOCK |
| `permission_usb_linux` | Linux | HID 设备权限 | BLOCK |
| `permission_screen_capture` | macOS | 屏幕录制 | WARN |
| `permission_accessibility` | macOS | 辅助功能 | WARN |
| `permission_ddc_ci_windows` | Windows | DDC/CI | WARN |
| `permission_ddc_ci_linux` | Linux | i2c-dev | WARN |
| `permission_backlight_linux` | Linux | 背光控制 | WARN |

### 6.2 预检报告导出

预检报告包含完整的权限状态信息：

```json
{
  "results": [
    {
      "item_id": "permission_usb",
      "status": "BLOCK",
      "message": "缺少 USB 设备访问权限",
      "fix_command": "open 'x-apple.systempreferences:com.apple.preference.security?Privacy_USB'",
      "fix_url": "https://www.argyllcms.com/doc/Setup.html"
    }
  ],
  "summary": {
    "pass_count": 15,
    "warn_count": 3,
    "block_count": 1
  },
  "can_proceed": false,
  "platform": "Darwin"
}
```

### 6.3 诊断包导出

诊断包自动包含权限状态检查结果，用于用户反馈问题时快速定位权限问题。

---

## 7. 打包权限声明

### 7.1 macOS Entitlements

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- USB 设备访问 -->
    <key>com.apple.security.device.usb</key>
    <true/>
    
    <!-- 屏幕录制（用于 LUT 验证） -->
    <key>com.apple.security.screen-capture</key>
    <true/>
    
    <!-- 辅助功能（用于 DDC/CI） -->
    <!-- 注意：辅助功能无法通过 entitlements 自动授予，需要用户手动授权 -->
    
    <!-- 网络访问（用于 ArgyllCMS） -->
    <key>com.apple.security.network.client</key>
    <true/>
    
    <!-- 文件访问 -->
    <key>com.apple.security.files.user-selected.read-write</key>
    <true/>
</dict>
</plist>
```

### 7.2 Windows Manifest

Windows 不需要特殊的 manifest 权限声明，但建议在安装程序中包含：

- 设备驱动安装提示
- DDC/CI 使用说明
- HDR 模式警告

### 7.3 Linux udev 规则

Linux 需要用户配置 udev 规则，或使用 AppImage 自带的权限请求机制。

---

## 8. 验收标准确认

| 验收标准 | 状态 | 说明 |
|----------|------|------|
| 预检报告能明确指出"缺少 USB 权限"并提供修复命令 | 已实现 | 预检结果包含 fix_command 和 fix_url |
| 三平台文档各记录一条完整的权限设置流程 | 已实现 | macOS、Windows、Linux 各有详细流程 |
| 用户反馈问题时，诊断包包含权限状态检查结果 | 已实现 | 预检报告导出功能支持 |

---

## 9. 参考资料

- [ArgyllCMS Setup Documentation](https://www.argyllcms.com/doc/Setup.html)
- [macOS Privacy Permissions](https://developer.apple.com/documentation/bundleresources/entitlements)
- [Linux udev Rules](https://www.argyllcms.com/doc/Setup_linux.html)
- [Windows HID API](https://docs.microsoft.com/en-us/windows-hardware/drivers/hid/)