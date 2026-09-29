# Topos Calibrator Scripts 目录说明

此目录包含各种辅助脚本，用于开发、测试、打包和维护。

## 目录结构

```
scripts/
├── build_all.py           # 跨平台打包构建脚本
├── macos_sign.py          # macOS 代码签名脚本
├── macos_notarize.py      # macOS 公证脚本
├── linux_appimage.py      # Linux AppImage 创建脚本
├── smoke_test.py          # Smoke Test 脚本
└ README.md               # 本文档
```

## 使用方法

### build_all.py - 跨平台打包

```bash
# 当前平台打包
python scripts/build_all.py

# 指定平台
python scripts/build_all.py --platform macos

# 清理后重新打包
python scripts/build_all.py --clean

# macOS 签名和公证
python scripts/build_all.py --platform macos --sign --notarize
```

环境变量（macOS 签名/公证）：
- `CODESIGN_IDENTITY`: Developer ID Application 证书
- `APPLE_TEAM_ID`: 团队 ID
- `NOTARY_APPLE_ID`: Apple ID
- `NOTARYTOOL_PASSWORD`: App-Specific Password

### macos_sign.py - macOS 签名

```bash
# 签名（需要环境变量）
export CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAM_ID)"
python scripts/macos_sign.py
```

### macos_notarize.py - macOS 公证

```bash
# 公证（需要环境变量）
export NOTARY_APPLE_ID="your@email.com"
export NOTARYTOOL_PASSWORD="xxxx-xxxx-xxxx-xxxx"
export APPLE_TEAM_ID="TEAM_ID"
python scripts/macos_notarize.py
```

### linux_appimage.py - Linux AppImage

```bash
# 创建 AppImage（需要 linuxdeploy）
python scripts/linux_appimage.py
```

依赖：
- [linuxdeploy](https://github.com/linuxdeploy/linuxdeploy)
- [linuxdeploy-plugin-qt](https://github.com/linuxdeploy/linuxdeploy-plugin-qt)

### smoke_test.py - Smoke Test

```bash
# 快速测试（仅检查输出文件）
python scripts/smoke_test.py --quick

# 完整测试（启动应用）
python scripts/smoke_test.py --platform macos
```

## CI/CD 集成

这些脚本已集成到 GitHub Actions：

```yaml
# .github/workflows/build.yml
- name: Build
  run: python scripts/build_all.py --clean

- name: Smoke Test
  run: python scripts/smoke_test.py --quick

- name: Sign (macOS)
  if: matrix.os == 'macos-latest'
  run: python scripts/macos_sign.py
  env:
    CODESIGN_IDENTITY: ${{ secrets.CODESIGN_IDENTITY }}

- name: Notarize (macOS)
  if: matrix.os == 'macos-latest'
  run: python scripts/macos_notarize.py
  env:
    NOTARY_APPLE_ID: ${{ secrets.NOTARY_APPLE_ID }}
    NOTARYTOOL_PASSWORD: ${{ secrets.NOTARYTOOL_PASSWORD }}
    APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
```

## 注意事项

1. **签名/公证需要 Apple Developer 账户**
   - 费用: $99/年
   - 需要 Developer ID Application 证书
   - 需要 App-Specific Password

2. **Linux AppImage 需要 linuxdeploy**
   - 从 GitHub releases 下载
   - 或使用包管理器安装

3. **Windows 需要 NSIS**
   - 从官网下载: https://nsis.sourceforge.io/
   - 或使用包管理器: `choco install nsis`

4. **Smoke Test 需要 GUI 环境**
   - macOS: 无特殊要求
   - Windows: 无特殊要求
   - Linux: 需要 X11 或 Wayland 显示环境