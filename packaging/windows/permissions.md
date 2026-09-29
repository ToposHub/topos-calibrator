# Topos Calibrator Windows 权限设置指南

## 概述

Topos Calibrator 在 Windows 上需要特定的权限才能正常工作：

1. **USB 设备访问** - 连接校色仪
2. **显卡 LUT 操作** - 加载/清除显卡校准曲线
3. **DDC/CI 显示器控制** - 控制显示器亮度、对比度等

## 权限详情

### 1. USB 设备访问

校色仪（如 i1 Display Pro、SpyderX）通过 USB 连接。Windows 需要 USB HID 驱动。

**自动安装驱动**：
- 大多数校色仪自带 Windows 驱动
- 连接设备时 Windows 会自动安装

**WinUSB 驱动**：
- 部分 ArgyllCMS 工具需要 WinUSB 驱动
- 使用 Zadig 工具安装 WinUSB 驱动

**安装步骤**：
```
1. 下载 Zadig: https://zadig.akeo.ie/
2. 连接校色仪
3. 在 Zadig 中找到校色仪设备
4. 选择 WinUSB 驱动
5. 点击 "Replace Driver"
```

**ArgyllCMS 官方指南**：
https://www.argyllcms.com/doc/USBInstall.html

### 2. 显卡 LUT 操作

`dispwin` 工具需要访问显卡 LUT（查找表）来加载或清除 ICC Profile 的 VCGT。

**可能的问题**：
- 部分 HDR/ACM 设置会锁定 LUT
- 需要禁用 Windows HDR 或特殊配置

**解决方案**：
```
1. 检查 Windows HDR 设置
   设置 > 系统 > 显示 > HDR
   
2. 检查 ACM (Automatic Color Management)
   Windows 11 22H2+ 自动启用 ACM
   
3. 使用 dispwin -c 清除 LUT
   如果被锁定，可能需要重启系统
```

**HDR/ACM 预检**：
- Topos Calibrator 启动时会检测 HDR 状态
- 如果 HDR 启用，会提示用户可能的问题

### 3. DDC/CI 显示器控制

DDC/CI 允许软件控制显示器硬件参数（亮度、对比度等）。

**启用 DDC/CI**：
```
1. 进入显示器 OSD 菜单
2. 找到 "DDC/CI" 或 "USB Control" 设置
3. 启用该选项
```

**常见问题**：
- 部分显示器默认禁用 DDC/CI
- HDMI/DP 连接可能不支持 DDC/CI
- 需要显示器驱动（部分品牌）

**验证 DDC/CI**：
```bash
# 使用 ArgyllCMS dispcal 检查
dispcal -v

# 或使用第三方工具
# Monitor Control: https://github.com/mgth/MonitorControl
```

## Windows 11 特殊设置

### Automatic Color Management (ACM)

Windows 11 22H2+ 引入了 ACM，会自动管理显示器色彩：

**影响**：
- ACM 可能锁定显卡 LUT
- 可能改变 ICC Profile 应用方式
- 与 dispwin 交互可能受限

**解决方案**：
```
1. 暂时禁用 ACM (如果需要)
   设置 > 系统 > 显示 > 颜色管理
   
2. 或使用 dispwin 的特殊选项
   dispwin -c  # 清除 LUT，可能需要禁用 ACM
   
3. 使用 "SDR 内容增强" 可能与校准冲突
```

### HDR 设置

HDR 模式下显示器色彩行为不同：

**注意事项**：
- HDR 模式下 SDR 内容会被色调映射
- 校色仪测量结果可能不准确
- 建议在 SDR 模式下校准

**切换 HDR**：
```
Windows 设置 > 系统 > 显示 > 使用 HDR
- 校准时建议关闭
- 校准后可根据需要开启
```

## 系统要求

| 项目 | 要求 | 说明 |
|------|------|------|
| Windows 版本 | Windows 10 1903+ | 推荐 Windows 11 |
| 显卡驱动 | 最新版 | 旧驱动可能不支持 LUT |
| 校色仪驱动 | WinUSB 或厂商驱动 | ArgyllCMS 需要 WinUSB |

## 预检检查项

Topos Calibrator 启动时会自动检查：

| 检查项 | 状态 | 解决方案 |
|--------|------|----------|
| ArgyllCMS 工具 | PASS/FAIL | 安装 ArgyllCMS |
| 校色仪驱动 | PASS/WARN | 使用 Zadig 安装 WinUSB |
| 显示器 DDC/CI | PASS/WARN | 启用显示器 OSD 中的 DDC/CI |
| HDR 状态 | PASS/WARN | 关闭 HDR 进行校准 |
| ACM 状态 | PASS/WARN | 检查 ACM 是否启用 |

## 常见问题解答

### Q: 校色仪无法识别

A: 检查以下项：
1. 校色仪是否正确连接
2. 是否安装了驱动（厂商驱动或 WinUSB）
3. 其他软件是否占用设备

### Q: dispwin 无法操作 LUT

A: 可能的原因：
1. HDR 或 ACM 锁定了 LUT
2. 显卡驱动不支持
3. 需要管理员权限

### Q: 测量结果与预期不符

A: 检查：
1. HDR 是否启用（影响色彩）
2. Night Light 是否启用
3. 其他色彩管理软件是否运行

## 相关文档

- `packaging/windows/app.manifest` - Windows 应用配置
- `packaging/windows/installer.nsi` - NSIS 安装器脚本
- `src/workflows/preflight.py` - 预检检查实现