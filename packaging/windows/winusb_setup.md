# Topos Calibrator Windows USB 驱动安装指南

## 为什么需要 WinUSB 驱动

ArgyllCMS 工具（如 spotread）使用 libusb 访问校色仪。在 Windows 上需要 WinUSB 驱动。

## 使用 Zadig 安装驱动

Zadig 是一个通用的 USB 驱动安装工具，可以将设备驱动替换为 WinUSB。

### 步骤 1: 下载 Zadig

从官方网站下载：https://zadig.akeo.ie/

### 步骤 2: 连接校色仪

将校色仪连接到电脑的 USB 端口。

### 步骤 3: 运行 Zadig

1. 打开 Zadig
2. 在 Options 菜单中勾选 "List All Devices"
3. 在设备列表中找到校色仪

### 步骤 4: 安装驱动

设备名称示例：
- i1 Display Pro: "i1d3" 或 "X-Rite i1 Display"
- SpyderX: "SpyderX" 或 "Datacolor SpyderX"
- ColorMunki: "ColorMunki" 或类似名称

操作：
1. 选择校色仪设备
2. 在右侧选择 "WinUSB" 驱动
3. 点击 "Replace Driver" 或 "Install Driver"

### 步骤 5: 验证安装

使用 ArgyllCMS spotread 验证：
```batch
cd ArgyllCMS\bin
spotread -?
```

如果能看到设备信息，说明驱动安装成功。

## 多设备配置

如果同时使用多个校色仪：

1. 逐个安装每个设备的 WinUSB 驱动
2. 使用 ArgyllCMS 的 `-D` 参数选择设备：
   ```batch
   spotread -D 0  # 第一个设备
   spotread -D 1  # 第二个设备
   ```

## 常见问题

### Q: Zadig 中看不到校色仪

A: 
1. 确保 Options > List All Devices 已勾选
2. 检查设备是否正确连接
3. 尝试更换 USB 端口
4. 可能需要先卸载厂商驱动

### Q: 驱动安装失败

A:
1. 以管理员身份运行 Zadig
2. 尝试先卸载旧驱动（Device Manager）
3. 重启电脑后再次尝试

### Q: 安装后其他软件无法使用校色仪

A: WinUSB 驱动会替换厂商驱动。如果其他软件（如厂商校色软件）需要使用：
1. 在 Zadig 中恢复原驱动
2. 或使用厂商软件时卸载 WinUSB 驱动

### Q: 需要恢复厂商驱动

A: 
1. 打开 Device Manager（设备管理器）
2. 找到校色仪设备
3. 右键 > Uninstall device
4. 勾选 "Delete the driver software for this device"
5. 拔出并重新插入校色仪
6. Windows 会自动安装厂商驱动

## ArgyllCMS 官方文档

更详细的驱动安装指南请参考 ArgyllCMS 官方文档：
https://www.argyllcms.com/doc/USBInstall.html

## 注意事项

- WinUSB 驱动仅影响 USB HID 设备，不会影响其他 USB 设备
- 安装 WinUSB 驱动后，校色仪可能无法与厂商软件同时使用
- 如需使用厂商软件，请恢复厂商驱动
- Topos Calibrator 预检会检测驱动状态并给出提示