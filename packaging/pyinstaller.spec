# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件 - Topos Calibrator

跨平台打包说明：
- macOS: 生成 app bundle，需要 entitlements 配置
- Windows: 生成目录结构，由 NSIS 打包成安装器
- Linux: 生成目录结构，由 AppImage 打包

使用方法：
    pyinstaller packaging/pyinstaller.spec
"""

import sys
import os
from pathlib import Path

# 项目根目录
project_root = Path(SPECPATH).parent
windows_icon = project_root / 'packaging' / 'windows' / 'ToposCalibrator.ico'

# ========== 分析配置 ==========
block_cipher = None

# ArgyllCMS is an optional, user-supplied third-party runtime.  The build
# remains usable without it (the application can guide users to install it),
# but when ./ArgyllCMS exists it is copied as a separate data directory.
argyll_dir = project_root / 'ArgyllCMS'

datas = [
    # Web 前端文件
    (str(project_root / 'web'), 'web'),
    # 项目资源
    (str(project_root / 'resources'), 'resources'),
    # 应用许可证和第三方说明
    (str(project_root / 'LICENSE'), 'licenses'),
    (str(project_root / 'packaging' / 'argyll' / 'THIRD_PARTY_NOTICES.md'), 'licenses'),
    # 文档文件
    (str(project_root / 'README.md'), '.'),
    # 修正文件（如果存在）
    (str(project_root / 'corrections'), 'corrections'),
]
if argyll_dir.is_dir():
    datas.append((str(argyll_dir), 'ArgyllCMS'))

a = Analysis(
    # 主入口文件
    ['main.py'],
    
    # 搜索路径
    pathex=[str(project_root)],
    
    # 二进制数据
    binaries=[],
    
    # 数据文件 - Web 前端、资源、许可证和可选 ArgyllCMS 目录
    datas=datas,
    
    # Hidden imports - PyQt6 和项目模块
    hiddenimports=[
        # PyQt6 核心
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.sip',
        
        # 项目源代码模块
        'src',
        'src.backend',
        'src.main_window',
        'src.argyll_controller',
        'src.patch_window',
        'src.data_storage',
        'src.measurement_analyzer',
        'src.lab_sampler',
        'src.display_lut_controller',
        'src.comparison_window',
        'src.sleep_preventer',
        
        # 子包模块
        'src.core',
        'src.core.events',
        'src.core.state',
        'src.color_science',
        'src.color_science.spaces',
        'src.color_science.transfer',
        'src.color_science.colorimetry',
        'src.color_science.gamut_sampling',
        'src.instruments',
        'src.instruments.base',
        'src.workflows',
        'src.workflows.preflight',
        'src.workflows.measurement_service',
        'src.storage',
        'src.storage.schema',
        'src.storage.manifest',
        'src.diagnostics',
        'src.reports',
        
        # macOS 平台依赖
        'objc',
        'Foundation',
        'AppKit',
        'Cocoa',
        'Quartz',
    ],
    
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的模块以减小体积
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'sphinx',
    ],
    
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ========== macOS 平台配置 ==========
if sys.platform == 'darwin':
    # macOS: 创建 app bundle
    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
    
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='Topos Calibrator',
        debug=False,
        bootloader_arg_signals=False,
        strip=False,
        upx=True,
        console=False,  # GUI 应用，不显示终端
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=str(project_root / 'packaging' / 'macos' / 'entitlements.plist'),
    )
    
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='Topos Calibrator',
    )
    
    # 创建 app bundle
    app = BUNDLE(
        coll,
        name='Topos Calibrator.app',
        icon=str(project_root / 'packaging' / 'macos' / 'ToposCalibrator.icns'),
        bundle_identifier='com.toposcalibrator.app',
        # macOS bundle versions must be numeric; the app UI carries the preview label.
        version='0.1.0',
        info_plist=str(project_root / 'packaging' / 'macos' / 'Info.plist'),
        codesign_identity=None,  # 预留签名，实际签名在打包脚本中
        entitlements_file=str(project_root / 'packaging' / 'macos' / 'entitlements.plist'),
    )

# ========== Windows 平台配置 ==========
elif sys.platform == 'win32':
    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
    
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='Topos Calibrator',
        debug=False,
        bootloader_arg_signals=False,
        strip=False,
        upx=True,
        console=False,  # GUI 应用
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        icon=str(windows_icon),
        codesign_identity=None,
        entitlements_file=None,
    )
    
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='Topos Calibrator',
    )

# ========== Linux 平台配置 ==========
else:
    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
    
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='topos-calibrator',
        debug=False,
        bootloader_arg_signals=False,
        strip=False,
        upx=True,
        console=True,  # Linux GUI 应用通常需要 console 以查看日志
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='topos-calibrator',
    )
