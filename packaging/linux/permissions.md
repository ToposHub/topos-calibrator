# Topos Calibrator Linux 权限设置指南

## 概述

Linux 系统对硬件设备访问有严格的权限控制。Topos Calibrator 需要以下权限：

| 权限类型 | 用途 | 默认状态 |
|----------|------|----------|
| i2c-dev | DDC/CI 显示器控制 | 通常需要手动配置 |
| USB HID | 校色仪通信 | 通常需要 udev 规则 |
| X11/Wayland | 色块窗口显示 | 由桌面环境管理 |

## i2c-dev 权限配置

DDC/CI 协议通过 i2c 设备与显示器通信。

### 方法 1: 临时权限（每次重启需要重新设置）

```bash
# 查看可用的 i2c 设备
ls /dev/i2c-*

# 设置权限（临时）
sudo chmod 666 /dev/i2c-*
```

### 方法 2: 永久权限（udev 规则）

创建 udev 规则文件：

```bash
# 创建规则文件
sudo tee /etc/udev/rules.d/10-i2c.rules > /dev/null << 'EOF'
# Allow all users access to i2c devices (for DDC/CI)
KERNEL=="i2c-[0-9]*", MODE="0666"
EOF

# 重新加载规则
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### 方法 3: 用户组权限

```bash
# 将用户加入 i2c 组
sudo usermod -aG i2c $USER

# 重新登录生效
# 注销并重新登录
```

## USB HID 设备权限

校色仪通常作为 USB HID 设备连接。

### 方法 1: udev 规则（推荐）

创建 udev 规则，允许普通用户访问校色仪：

```bash
# 创建规则文件
sudo tee /etc/udev/rules.d/99-colorimeter.rules > /dev/null << 'EOF'
# X-Rite i1 Display Pro / i1 Display Studio
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="5010", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="5012", MODE="0666"

# X-Rite i1 Pro / i1 Pro 2 / i1 Pro 3
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="d001", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="d009", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="d010", MODE="0666"

# Datacolor SpyderX
SUBSYSTEM=="usb", ATTRS{idVendor}=="0853", ATTRS{idProduct}=="0300", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0853", ATTRS{idProduct}=="0301", MODE="0666"

# Datacolor Spyder5
SUBSYSTEM=="usb", ATTRS{idVendor}=="0853", ATTRS{idProduct}=="0050", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0853", ATTRS{idProduct}=="0051", MODE="0666"

# ColorMunki
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="6001", MODE="0666"

# Generic HID devices
KERNEL=="hidraw*", MODE="0666"
EOF

# 重新加载规则
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### 方法 2: 查找设备 ID

如果您的校色仪不在上述列表中：

```bash
# 连接校色仪
# 查看设备信息
lsusb

# 找到校色仪的 Vendor ID 和 Product ID
# 例如: ID 0765:5010 X-Rite, Inc.

# 添加到 udev 规则
sudo tee -a /etc/udev/rules.d/99-colorimeter.rules > /dev/null << 'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="5010", MODE="0666"
EOF

# 重新加载规则
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## X11 vs Wayland

### X11（推荐）

X11 是传统的显示服务器，对色块窗口没有特殊限制。

**优势**：
- 全屏色块窗口支持
- 多显示器支持
- dispwin 正常工作

**使用方法**：
```bash
# 强制使用 X11
export QT_QPA_PLATFORM=xcb

# 启动应用
./ToposCalibrator-x86_64.AppImage
```

### Wayland

Wayland 是现代显示协议，但有安全限制。

**限制**：
- 部分 compositor 不允许应用绘制全屏窗口
- security context 可能阻止色块窗口
- dispwin 可能无法正常工作

**解决方案**：
```bash
# 使用 XWayland
export QT_QPA_PLATFORM=xcb

# 或使用 Wayland（可能受限）
export QT_QPA_PLATFORM=wayland

# GNOME 特定设置
gsettings set org.gnome.mutter experimental-features "['x11-scaling']"
```

## 系统依赖安装

### Debian/Ubuntu

```bash
# ArgyllCMS
sudo apt install argyll

# Qt 依赖
sudo apt install qt6-base qt6-webengine-dev

# X11 依赖
sudo apt install libxcb-xinerama0 libxcb-cursor0

# i2c 工具
sudo apt install i2c-tools
```

### Fedora

```bash
# ArgyllCMS
sudo dnf install argyllcms

# Qt 依赖
sudo dnf install qt6-qtbase qt6-qtwebengine

# i2c 工具
sudo dnf install i2c-tools
```

### Arch Linux

```bash
# ArgyllCMS
sudo pacman -S argyllcms

# Qt 依赖
sudo pacman -S qt6-base qt6-webengine

# i2c 工具
sudo pacman -S i2c-tools
```

## 验证权限

### 验证 i2c 权限

```bash
# 查看 i2c 设备
ls -la /dev/i2c-*

# 应显示 crw-rw-rw- (666 权限)
```

### 验证 USB 权限

```bash
# 查看 USB HID 设备
ls -la /dev/hidraw*

# 应显示 crw-rw-rw- (666 权限)
```

### 验证 ArgyllCMS

```bash
# 检查 ArgyllCMS 是否可用
which spotread

# 或测试设备
spotread -?
```

## 常见问题

### Q: DDC/CI 无法工作

A: 检查：
1. i2c 设备权限 (`/dev/i2c-*`)
2. 显示器是否启用 DDC/CI
3. HDMI/DP 连接是否支持 DDC/CI

### Q: 校色仪无法识别

A: 检查：
1. USB 设备权限 (`/dev/hidraw*`)
2. udev 规则是否生效
3. 重新插拔设备

### Q: Wayland 下色块窗口无法全屏

A: 使用 XWayland：
```bash
export QT_QPA_PLATFORM=xcb
```

### Q: dispwin 无法操作 LUT

A: 检查：
1. X11/Wayland 环境
2. 显卡驱动支持
3. 运行权限

## 预检检查项

Topos Calibrator 启动时会自动检查：

| 检查项 | 状态 | 解决方案 |
|--------|------|----------|
| ArgyllCMS 工具 | PASS/FAIL | 安装 argyll |
| i2c 设备权限 | PASS/WARN | 设置 udev 规则 |
| USB HID 权限 | PASS/WARN | 设置 udev 规则 |
| X11/Wayland | PASS/WARN | 使用 X11 环境 |

## 相关文件

- `packaging/linux/AppRun` - AppImage 启动脚本
- `packaging/linux/topos-calibrator.desktop` - 桌面文件
- `packaging/linux/AppImage.conf` - AppImage 配置
- `src/workflows/preflight.py` - 预检实现