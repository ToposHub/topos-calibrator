# Topos Calibrator Linux udev 规则文件

此文件用于配置 Linux 系统的 USB 和 i2c 设备权限。
复制内容到 `/etc/udev/rules.d/` 目录。

## 安装方法

```bash
# 下载规则文件
sudo curl -o /etc/udev/rules.d/99-topos-calibrator.rules \
  https://toposcalibrator.com/udev/99-topos-calibrator.rules

# 或手动创建
sudo tee /etc/udev/rules.d/99-topos-calibrator.rules > /dev/null << 'EOF'
# 见下方规则内容
EOF

# 重新加载规则
sudo udevadm control --reload-rules
sudo udevadm trigger

# 重新插拔设备
```

## 规则内容

```bash
# Topos Calibrator udev 规则
# ========================
#
# 此规则允许普通用户访问：
# - 校色仪 USB 设备
# - i2c 设备（DDC/CI 显示器控制）

# ========== i2c 设备权限 (DDC/CI) ==========
# 允许所有用户访问 i2c 设备，用于 DDC/CI 显示器控制
KERNEL=="i2c-[0-9]*", MODE="0666"

# ========== 校色仪 USB 设备权限 ==========

# X-Rite i1 Display Pro / i1 Display Studio
# Vendor ID: 0765, Product ID: 5010/5012
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="5010", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="5012", MODE="0666"

# X-Rite i1 Pro / i1 Pro 2 / i1 Pro 3
# Vendor ID: 0765, Product ID: d001/d009/d010
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="d001", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="d009", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="d010", MODE="0666"

# Datacolor SpyderX
# Vendor ID: 0853, Product ID: 0300/0301
SUBSYSTEM=="usb", ATTRS{idVendor}=="0853", ATTRS{idProduct}=="0300", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0853", ATTRS{idProduct}=="0301", MODE="0666"

# Datacolor Spyder5 / Spyder4
# Vendor ID: 0853, Product ID: 0050/0051/0040
SUBSYSTEM=="usb", ATTRS{idVendor}=="0853", ATTRS{idProduct}=="0050", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0853", ATTRS{idProduct}=="0051", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0853", ATTRS{idProduct}=="0040", MODE="0666"

# X-Rite ColorMunki
# Vendor ID: 0765, Product ID: 6001
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="6001", MODE="0666"

# ========== HID 设备权限 ==========
# 允许所有用户访问 HID raw 设备
KERNEL=="hidraw*", MODE="0666"

# ========== USB generic 设备 ==========
# 允许所有用户访问 USB 设备
SUBSYSTEM=="usb", MODE="0666"
```

## 添加新设备

如果您的校色仪不在上述列表中：

```bash
# 1. 连接校色仪
# 2. 查看设备信息
lsusb

# 输出类似：
# Bus 003 Device 012: ID 0765:5010 X-Rite, Inc. i1 Display Pro

# 3. 记录 Vendor ID 和 Product ID
# 例如: 0765:5010

# 4. 添加规则
sudo tee -a /etc/udev/rules.d/99-topos-calibrator.rules > /dev/null << 'EOF'
# 您的设备名称
SUBSYSTEM=="usb", ATTRS{idVendor}=="0765", ATTRS{idProduct}=="5010", MODE="0666"
EOF

# 5. 重新加载
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## 验证规则

```bash
# 查看 udev 规则是否生效
sudo udevadm info -a -n /dev/bus/usb/003/012 | grep -A 5 "ATTRS{idVendor}"

# 查看 i2c 设备权限
ls -la /dev/i2c-*

# 查看 HID 设备权限
ls -la /dev/hidraw*
```

## 安全说明

这些规则允许所有用户访问特定设备。在多用户系统中，可能需要更细粒度的权限控制：

```bash
# 仅允许特定用户组访问
KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"
KERNEL=="hidraw*", GROUP="plugdev", MODE="0660"

# 将用户加入组
sudo usermod -aG i2c $USER
sudo usermod -aG plugdev $USER
```

## 相关文档

- ArgyllCMS USB 安装指南: https://www.argyllcms.com/doc/USBInstall.html
- Linux udev 文档: https://www.kernel.org/doc/html/latest/admin-guide/devices.html
- DDC/CI 协议: https://en.wikipedia.org/wiki/Display_Data_Channel