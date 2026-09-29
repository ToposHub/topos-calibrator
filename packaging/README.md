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
├── argyll/                     # ArgyllCMS 合规说明模板（不含第三方二进制）
│   └── THIRD_PARTY_NOTICES.md  # 随应用分发的第三方声明
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

生成后的 `packaging/macos/ToposCalibrator.icns`、
`packaging/windows/ToposCalibrator.ico` 和 `packaging/linux/ToposCalibrator.png`
已经直接放入仓库，用户可以直接运行打包命令，不需要额外安装图标转换工具。
只有在替换源 PNG 后，才需要重新运行上面的生成脚本。

## ArgyllCMS 策略

ArgyllCMS 不是本仓库的源代码，也不会被提交到 Git。打包时它作为独立的
命令行程序目录随应用分发；应用通过子进程调用这些工具。ArgyllCMS 的主要
代码和可执行文件采用 AGPL-3.0，发行包还包含 GPL、LGPL、MIT/BSD、ISC 等
其他组件许可证。因此不能只放一个简短的“使用了 ArgyllCMS”说明。

### 准备可分发的 ArgyllCMS 目录

1. 从 [ArgyllCMS 官网](https://www.argyllcms.com/) 下载目标平台的官方二进制包。
2. 下载与二进制版本完全匹配的官方源代码压缩包。
3. 将二进制包解压并重命名为项目根目录的 `ArgyllCMS`，确保存在
   `ArgyllCMS/bin/spotread`（macOS）或 `ArgyllCMS/bin/spotread.exe`（Windows）。
4. 在构建命令中通过 `--argyll-source` 传入源代码压缩包路径。

例如：

```bash
python scripts/build_all.py --platform macos --clean \
  --argyll-source /path/to/Argyll_V3.5.0_source.zip

python scripts/build_all.py --platform windows --clean \
  --argyll-source C:\path\to\Argyll_V3.5.0_source.zip
```

`build_all.py` 会自动调用 `scripts/prepare_argyll_bundle.py`，完成以下操作：

- 验证 `bin/` 和 `spotread` 是否存在；
- 从官方发行目录收集 `License.txt`、`License2.txt`、`License3.txt`、
  `License4.txt`、GPL/LGPL/第三方版权文件；
- 将这些文件复制到 `ArgyllCMS/licenses/official/`，并生成
  `ARGYLLCMS_LICENSE_MANIFEST.txt`；
- 把对应源代码压缩包复制到 `ArgyllCMS/source/`，记录 SHA-256；
- 写入 `BUILD_METADATA.txt`、`ARGYLLCMS_SOURCE_CODE.txt` 和
  `THIRD_PARTY_NOTICES.md`。

如果 `ArgyllCMS/` 存在但没有传入匹配的源代码压缩包，构建脚本会停止，避免
生成缺少 AGPL-3.0 对应源代码的可分发安装包。若项目根目录没有 `ArgyllCMS/`，
则可以构建不含第三方工具的应用，用户运行时再按 README 安装 ArgyllCMS。

打包产物中的合规文件位置：

- macOS：`Topos Calibrator.app/Contents/Resources/ArgyllCMS/licenses/`
- Windows：安装目录下的 `ArgyllCMS\licenses\`，以及应用的 `licenses\` 目录

这些文件不能删除或替换成仅有链接的空白文件。若修改了 ArgyllCMS，必须发布
对应修改后的源代码，并按照官方文档对修改版进行清晰标记。

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

# 打包（若存在 ./ArgyllCMS，则必须同时提供匹配的源代码压缩包）
python scripts/build_all.py --platform macos --clean \
  --argyll-source /path/to/Argyll_V3.5.0_source.zip

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

# 使用统一脚本打包 PyInstaller 目录并创建 NSIS 安装器
python scripts/build_all.py --platform windows --clean \
  --argyll-source C:\path\to\Argyll_V3.5.0_source.zip
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
