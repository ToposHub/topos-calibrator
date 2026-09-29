# Topos Calibrator 跨平台打包指南

本目录包含跨平台打包配置文件和说明文档。

## 打包工具选择

我们选择 **PyInstaller** 作为主要打包工具：

| 平台 | 打包格式 | 优势 |
|------|----------|------|
| macOS | app bundle | PyInstaller 直接生成 .app，支持签名/公证 |
| Windows | NSIS 安装器 | PyInstaller 生成目录 + NSIS 创建安装器 |
| Linux | AppImage | PyInstaller 生成目录 + AppImage 打包 |

## 目录结构

```
packaging/
├── README.md                   # 本文档
├── pyinstaller.spec            # PyInstaller 配置文件
├── macos/                      # macOS 打包配置
│   ├── Info.plist              # app bundle 元数据
│   ├── entitlements.plist      # 权限声明（USB、辅助功能）
│   ├── codesign.conf           # 签名配置（预留）
│   ├── notarize.conf           # 公证配置（预留）
│   └── ToposCalibrator.icns    # 应用图标
├── windows/                    # Windows 打包配置
│   ├── installer.nsi           # NSIS 安装器脚本
│   ├── app.manifest            # 应用 manifest
│   └── ToposCalibrator.ico     # 应用图标
├── linux/                      # Linux 打包配置
│   ├── AppImage.conf           # AppImage 配置
│   ├── AppRun                  # AppImage 启动脚本
│   ├── topos-calibrator.desktop # 桌面文件
│   └── ToposCalibrator.png     # 应用图标
└── requirements.txt            # 打包工具依赖
```

## 应用图标与高 DPI 支持

图标源文件是 `resources/app-icons/topos-calibrator.png`（1024×1024 RGBA）。
平台资源由以下脚本从源文件生成，避免各平台图标发生偏差：

```bash
python scripts/generate_app_icons.py
```

脚本会生成 macOS 标准 1x/2x `.icns` 图层、包含 16–256px 多尺寸层级的
Windows `.ico`，以及供 AppImage 使用的 Linux PNG。PyInstaller、NSIS 和
运行时 Qt 均已指向这些资源；Windows manifest 与 macOS `Info.plist` 保留
高 DPI 配置。

## ArgyllCMS 策略

### 检测策略

程序启动时检测 ArgyllCMS 可用性：

1. **内置检测**: 检查 `ArgyllCMS/bin` 目录是否存在工具
2. **系统检测**: 检查系统 PATH 中是否有 ArgyllCMS 工具
3. **用户指定**: 用户可在设置中指定 ArgyllCMS 路径

### 缺失引导

如果 ArgyllCMS 缺失，程序会显示引导对话框：

```
┌─────────────────────────────────────────────────────────────┐
│  ArgyllCMS 未找到                                           │
│                                                             │
│  Topos Calibrator 需要 ArgyllCMS 进行色彩测量。             │
│                                                             │
│  安装方式：                                                  │
│                                                             │
│  macOS:                                                     │
│    brew install argyll-cms                                  │
│                                                             │
│  Windows:                                                   │
│    从 https://www.argyllcms.com/ 下载                       │
│    将 bin 目录放入应用程序的 ArgyllCMS 目录                  │
│                                                             │
│  Linux:                                                     │
│    sudo apt install argyll  (Debian/Ubuntu)                 │
│    sudo dnf install argyllcms  (Fedora)                     │
│                                                             │
│  [下载 ArgyllCMS]  [手动指定路径]  [退出程序]               │
└─────────────────────────────────────────────────────────────┘
```

## 权限说明

### macOS 权限

| 权限类型 | 用途 | 配置位置 |
|----------|------|----------|
| USB 设备访问 | 连接校色仪 | entitlements.plist |
| 辅助功能权限 | DDC/CI 显示器控制 | 需用户手动授权 |
| 屏幕录制权限 | dispwin 色块显示 | macOS 10.15+ 自动请求 |

### Windows 权限

| 权限类型 | 用途 | 说明 |
|----------|------|------|
| USB HID | 校色仪通信 | WinUSB 驱动 |
| 显卡 LUT 写入 | dispwin 操作 | 需管理员权限或签名驱动 |
| DDC/CI | 显示器控制 | 一般应用可访问 |

### Linux 权限

| 权限类型 | 用途 | 配置方式 |
|----------|------|----------|
| i2c-dev | DDC/CI 显示器控制 | sudo chmod 666 /dev/i2c-* |
| USB HID | 校色仪通信 | udev 规则 |
| X11/Wayland | 色块窗口显示 | 桌面环境权限 |

## 打包命令

### macOS

```bash
# 安装打包工具
pip install pyinstaller

# 打包
pyinstaller packaging/pyinstaller.spec

# 签名（可选，需要开发者证书）
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Your Name" \
  --options runtime \
  --entitlements packaging/macos/entitlements.plist \
  dist/Topos\ Calibrator.app

# 公证（可选）
xcrun notarytool submit dist/Topos\ Calibrator.zip \
  --apple-id "your@email.com" \
  --password "@keychain:AC_PASSWORD" \
  --team-id "TEAM_ID" \
  --wait
```

### Windows

```bash
# 安装打包工具
pip install pyinstaller

# 使用 PyInstaller 打包
pyinstaller packaging/pyinstaller.spec

# 使用 NSIS 创建安装器
makensis packaging/windows/installer.nsi
```

### Linux

```bash
# 安装打包工具
pip install pyinstaller

# 使用 PyInstaller 打包
pyinstaller packaging/pyinstaller.spec

# 创建 AppImage
# 需要安装 linuxdeploy
linuxdeploy --appdir dist/topos-calibrator \
  --desktop-file packaging/linux/topos-calibrator.desktop \
  --icon-file packaging/linux/ToposCalibrator.png \
  --output appimage
```

## CI/CD 集成

打包过程已集成到 GitHub Actions：

```yaml
# .github/workflows/build.yml
jobs:
  build-macos:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - pip install pyinstaller
      - pyinstaller packaging/pyinstaller.spec
      - # 可选：签名和公证
      
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - pip install pyinstaller
      - pyinstaller packaging/pyinstaller.spec
      - # NSIS 打包
      
  build-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - pip install pyinstaller
      - pyinstaller packaging/pyinstaller.spec
      - # AppImage 打包
```

## 验证清单

打包完成后，请验证以下项目：

### macOS Smoke Test

- [ ] 应用能正常启动
- [ ] Web UI 正常加载
- [ ] 色块窗口能显示
- [ ] ArgyllCMS 检测正常（显示缺失引导）
- [ ] USB 权限提示正常弹出
- [ ] 应用图标正确显示

### Windows Smoke Test

- [ ] 应用能正常启动
- [ ] Web UI 正常加载
- [ ] 色块窗口能显示
- [ ] ArgyllCMS 检测正常
- [ ] 安装器正常工作
- [ ] 卸载器正常工作

### Linux Smoke Test

- [ ] AppImage 能运行
- [ ] Web UI 正常加载
- [ ] 色块窗口能显示（X11）
- [ ] 色块窗口能显示（Wayland，如有支持）
- [ ] ArgyllCMS 检测正常
