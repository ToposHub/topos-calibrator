# Topos Calibrator macOS USB 权限指南

## 概述

Topos Calibrator 需要访问 USB 设备来连接校色仪。macOS 对 USB 设备访问有严格的权限控制。

## 权限类型

### 1. USB 设备权限 (com.apple.security.device.usb)

此权限允许应用访问 USB 设备，如 i1 Display Pro、SpyderX 等校色仪。

**获取方式**：
- 在 `entitlements.plist` 中声明
- 签名时包含此权限
- 首次使用时用户会收到系统提示

**配置**：
```xml
<key>com.apple.security.device.usb</key>
<true/>
```

### 2. 辅助功能权限

部分显示器控制功能（DDC/CI）需要辅助功能权限。

**获取方式**：
- 无法通过 entitlements 预授权
- 必须由用户手动授权
- 应用需检查并提示用户

**检查代码**：
```python
# macOS 辅助功能权限检查
import subprocess

def check_accessibility_permission():
    """检查辅助功能权限"""
    try:
        result = subprocess.run(
            ['osascript', '-e', 'tell application "System Events" to get name of processes'],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except:
        return False

def request_accessibility_permission():
    """请求辅助功能权限（打开系统偏好设置）"""
    subprocess.run([
        'open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'
    ])
```

### 3. 屏幕录制权限

dispwin 显示色块窗口需要屏幕录制权限（macOS 10.15+）。

**获取方式**：
- 首次调用 CGDisplayCreateImage 或类似 API 时自动请求
- 用户在系统偏好设置中授权

## 权限检查流程

应用启动时应执行以下检查：

```python
def check_macos_permissions():
    """检查 macOS 所需权限"""
    issues = []
    
    # 1. 检查 USB 权限
    # 如果有校色仪连接但无法访问，提示用户
    if not can_access_usb_devices():
        issues.append({
            'type': 'usb',
            'severity': 'block',
            'message': '无法访问 USB 设备',
            'solution': '请在系统偏好设置中允许 Topos Calibrator 访问 USB 设备'
        })
    
    # 2. 检查屏幕录制权限
    if not has_screen_capture_permission():
        issues.append({
            'type': 'screen_capture',
            'severity': 'warn',
            'message': '无屏幕录制权限，色块窗口可能无法正常显示',
            'solution': '请在系统偏好设置 > 安全性与隐私 > 屏幕录制中授权'
        })
    
    # 3. 检查辅助功能权限（可选，用于 DDC/CI）
    if not check_accessibility_permission():
        issues.append({
            'type': 'accessibility',
            'severity': 'warn',
            'message': '无辅助功能权限，无法使用 DDC/CI 控制显示器',
            'solution': '请在系统偏好设置 > 安全性与隐私 > 辅助功能中授权'
        })
    
    return issues
```

## 用户引导界面

当检测到权限问题时，应显示清晰的引导对话框：

```
┌─────────────────────────────────────────────────────────────┐
│  权限设置                                                    │
│                                                             │
│  Topos Calibrator 需要以下权限才能正常工作：                  │
│                                                             │
│  ✓ USB 设备访问                                             │
│    用于连接校色仪                                            │
│    [已授权]                                                  │
│                                                             │
│  ⚠ 屏幕录制权限                                              │
│    用于显示测量色块                                          │
│    [打开系统偏好设置]                                        │
│                                                             │
│  ℹ 辅助功能权限                                              │
│    用于 DDC/CI 显示器控制（可选）                            │
│    [打开系统偏好设置]                                        │
│                                                             │
│  [稍后设置]  [重新检查]                                      │
└─────────────────────────────────────────────────────────────┘
```

## 常见问题

### Q: 首次启动没有弹出权限请求

A: macOS 只在实际尝试访问设备时才会弹出权限请求。确保：
1. 应用已正确签名
2. entitlements 已配置
3. 首次访问 USB 设备时才会触发

### Q: 权限被拒绝后如何重新请求

A: 用户需要手动在系统偏好设置中授权：
1. 打开系统偏好设置 > 安全性与隐私 > 隐私
2. 选择对应权限类型
3. 点击锁图标解锁
4. 添加 Topos Calibrator 到允许列表

### Q: 如何测试权限配置

A: 可以使用以下命令检查应用的权限配置：
```bash
# 检查签名和权限
codesign -d --entitlements :- /Applications/Topos\ Calibrator.app

# 检查公证状态
spctl -a -t vv -vv /Applications/Topos\ Calibrator.app
```

## 相关文件

- `packaging/macos/entitlements.plist` - 权限声明
- `packaging/macos/Info.plist` - 应用元数据
- `src/workflows/preflight.py` - 预检权限检查