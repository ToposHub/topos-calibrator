/*
 * Topos Calibrator - 预检结果翻译（英文 → 界面语言）
 *
 * 背景：预检消息由 Python 后端（src/workflows/preflight.py）以英文生成，
 * 前端 i18n 体系（i18n.js）是「中文原文 → 英文」方向，无法覆盖它们。
 * 本模块为预检结果提供独立的 英文 → 中文 映射：
 *   1. itemNames:  item_id → 中文检查项名称
 *   2. messages:   静态消息精确匹配
 *   3. patterns:   含动态值（{e}、路径、数字等）的消息用正则匹配
 *
 * 用法（main.js 渲染预检结果时调用）：
 *   translatePreflightMessage('Night Shift status unknown')
 *   translatePreflightItemName('argyll_spotread')   // => 'spotread 程序'
 * 英文模式下原样返回，不做任何转换。
 */
(function (global) {
    'use strict';

    /* ==================== 检查项名称 ==================== */

    var ITEM_NAMES = {
        'argyll_spotread': 'spotread 程序',
        'argyll_dispcal': 'dispcal 程序',
        'argyll_targen': 'targen 程序',
        'argyll_colprof': 'colprof 程序',
        'argyll_collink': 'collink 程序',
        'argyll_dispwin': 'dispwin 程序',
        'argyll_ccxxmake': 'ccxxmake 程序',
        'argyll_version': 'ArgyllCMS 版本',
        'instrument_connected': '探头连接',
        'instrument_calibrated': '探头校正',
        'instrument_correction': '光谱校正文件',
        'display_index': '显示器选择',
        'display_hdr_acm': 'HDR / 自动亮度',
        'display_night_shift': '夜览 (Night Shift)',
        'icc_current_profile': '系统 ICC Profile',
        'lut_vcgt_status': '显卡 LUT (VCGT)',
        'system_sleep': '系统睡眠',
        'system_display_sleep': '显示器睡眠',
        'permission_usb': 'USB 设备权限',
        'permission_screen_capture': '屏幕录制权限',
        'permission_accessibility': '辅助功能权限',
        'permission_usb_windows': 'USB 设备权限 (Windows)',
        'permission_ddc_ci_windows': 'DDC/CI 权限 (Windows)',
        'permission_usb_linux': 'USB 设备权限 (Linux)',
        'permission_i2c_linux': 'I2C 权限 (Linux)',
        'permission_backlight_linux': '背光控制权限 (Linux)'
    };

    /* ==================== 静态消息（精确匹配） ==================== */

    var MESSAGES = {
        // ArgyllCMS 工具
        '{tool_name} not found - Install ArgyllCMS or add it to PATH':
            '未找到 {tool_name} —— 请安装 ArgyllCMS 或将其加入 PATH',

        // 探头
        'Instrument adapter not provided, check skipped': '未提供探头适配器，检查已跳过',
        'Instrument adapter not provided': '未提供探头适配器',
        'Instrument connected': '探头已连接',
        'Instrument not connected': '探头未连接',
        'Instrument calibrated recently': '探头近期已校正',
        'No calibration recorded': '没有校正记录',
        'Failed to check instrument status': '检查探头状态失败',
        'Failed to check calibration': '检查校正状态失败',
        'No correction file selected (recommended for colorimeters) - Select a CCSS/CCMX file appropriate for your display technology':
            '未选择光谱校正文件（色度计建议使用）—— 请选择与显示器技术匹配的 CCSS/CCMX 文件',
        'Correction file selected': '已选择光谱校正文件',
        'Correction file path invalid': '校正文件路径无效',

        // 显示器
        'Could not enumerate displays': '无法枚举显示器列表',
        'Could not enumerate displays for ICC check': '无法枚举显示器（ICC 检查）',
        'Could not query display list': '无法查询显示器列表',
        'Could not read display color space': '无法读取显示器色彩空间',
        'Display enumeration failed': '显示器枚举失败',
        'dispwin not available, display index check skipped': 'dispwin 不可用，已跳过显示器索引检查',
        'HDR/ACM status not fully detectable on macOS': 'macOS 上无法完全探测 HDR / 自动亮度状态',
        'HDR/ACM status requires manual verification on Windows': 'Windows 上需手动确认 HDR / 自动亮度状态',
        'HDR check not available on Linux': 'Linux 上不支持 HDR 检查',

        // 夜览 / 干扰软件
        'Night Shift status unknown': '夜览状态未知',
        'Night Shift appears to be disabled': '夜览似乎已关闭',
        'Night Shift may be active': '夜览可能处于开启状态',
        'No color-adjusting software detected': '未检测到改色软件（f.lux 等）',

        // 睡眠
        'System sleep disabled': '系统睡眠已禁用',
        'Display sleep disabled': '显示器睡眠已禁用',
        'Display sleep check not available': '显示器睡眠检查不可用',
        'Display sleep requires manual verification': '显示器睡眠需手动确认',
        'Sleep settings require manual verification on Windows': 'Windows 上需手动确认睡眠设置',
        'Sleep settings require manual verification on Linux': 'Linux 上需手动确认睡眠设置',
        'Sleep check not available on this platform': '当前平台不支持睡眠检查',
        'Could not read sleep settings': '无法读取睡眠设置',

        // 权限
        'USB device access appears available': 'USB 设备访问可用',
        'Could not verify USB permission': '无法验证 USB 权限',
        'Could not verify HID device status': '无法验证 HID 设备状态',
        'HID devices accessible': 'HID 设备可访问',
        'No HID devices accessible': '没有可访问的 HID 设备',
        'No HID devices found - instrument may not be connected': '未发现 HID 设备 —— 探头可能未连接',
        'Some HID devices have issues': '部分 HID 设备状态异常',
        'Screen recording permission appears available': '屏幕录制权限可用',
        'Screen recording permission may not be granted': '屏幕录制权限可能未授予',
        'Accessibility permission granted': '辅助功能权限已授予',
        'Accessibility permission not granted': '辅助功能权限未授予',
        'Accessibility check only applicable on macOS': '辅助功能检查仅适用于 macOS',
        'ApplicationServices not available': 'ApplicationServices 框架不可用',
        'IOKit not available': 'IOKit 框架不可用',
        'CoreGraphics not available': 'CoreGraphics 框架不可用',
        'USB Windows check only applicable on Windows': 'USB 检查仅适用于 Windows',
        'USB Linux check only applicable on Linux': 'USB 检查仅适用于 Linux',
        'DDC/CI Windows check only applicable on Windows': 'DDC/CI 检查仅适用于 Windows',
        'DDC/CI brightness control available': 'DDC/CI 亮度控制可用',
        'i2c Linux check only applicable on Linux': 'I2C 检查仅适用于 Linux',
        'i2c-dev module not loaded': 'i2c-dev 模块未加载',
        'i2c-dev module loaded but no device access': 'i2c-dev 模块已加载但无法访问设备',
        'No i2c devices found': '未找到 I2C 设备',
        'Backlight Linux check only applicable on Linux': '背光检查仅适用于 Linux',
        'Backlight control not accessible': '背光控制不可访问',
        'No backlight devices found (external monitor or not applicable)': '未找到背光设备（外接显示器或不适用）',

        // ICC / VCGT
        'Automatic ICC profile query not supported on this platform': '当前平台不支持自动查询 ICC Profile',
        'Could not read VCGT': '无法读取 VCGT',
        'VCGT LUT is linear': 'VCGT LUT 为线性（未修改）',
        'VCGT LUT is modified (non-linear)': 'VCGT LUT 已被修改（非线性）',
        'VCGT check failed': 'VCGT 检查失败',
        'VCGT check not available on this platform': '当前平台不支持 VCGT 检查',
        'VCGT check requires manual verification on Windows': 'Windows 上需手动确认 VCGT',
        'VCGT check skipped (dispwin not available)': '已跳过 VCGT 检查（dispwin 不可用）',

        // 通用
        'Check method not implemented': '检查方法未实现',
        'Check skipped (not applicable on': '已跳过（不适用于当前平台）'
    };

    /* ==================== 动态消息（正则匹配） ====================
     * 每项: [正则, 替换模板]；替换模板中 $1/$2 引用捕获组。
     * 顺序即优先级，先命中先用。
     */

    var PATTERNS = [
        [/^Instrument connected: (.+)$/, '探头已连接：$1'],
        [/^Instrument connected$/, '探头已连接'],
        [/^Correction file selected: (.+)$/, '已选择光谱校正文件：$1'],
        [/^Correction file path invalid: (.+)$/, '校正文件路径无效：$1'],
        [/^Display index (\d+) invalid \(only (\d+) displays?\)$/, '显示器索引 $1 无效（仅有 $2 台显示器）'],
        [/^Display index (\d+) valid \((\d+) displays? available\)$/, '显示器索引 $1 有效（共 $2 台显示器）'],
        [/^Display enumeration failed: (.+)$/, '显示器枚举失败：$1'],
        [/^Display sleep: (\d+) minutes \(adequate\)$/, '显示器睡眠：$1 分钟（充足）'],
        [/^Display sleep: (\d+) minutes$/, '显示器睡眠：$1 分钟'],
        [/^System sleep timeout: (\d+) minutes \(adequate\)$/, '系统睡眠超时：$1 分钟（充足）'],
        [/^System sleep timeout: (\d+) minutes$/, '系统睡眠超时：$1 分钟'],
        [/^Night Shift check failed: (.+)$/, '夜览检查失败：$1'],
        [/^HID devices accessible \((\d+) devices?\)$/, 'HID 设备可访问（$1 台）'],
        [/^HID devices available \((\d+) devices? found\)$/, '发现 HID 设备（$1 台）'],
        [/^HID device check failed: (.+)$/, 'HID 设备检查失败：$1'],
        [/^DDC\/CI check failed: (.+)$/, 'DDC/CI 检查失败：$1'],
        [/^Backlight control accessible \((\d+) devices?\)$/, '背光控制可访问（$1 台设备）'],
        [/^i2c-dev accessible \((\d+) devices?\)$/, 'i2c-dev 可访问（$1 台设备）'],
        [/^i2c permission check failed: (.+)$/, 'I2C 权限检查失败：$1'],
        [/^USB permission check failed: (.+)$/, 'USB 权限检查失败：$1'],
        [/^Could not verify USB permission: (.+)$/, '无法验证 USB 权限：$1'],
        [/^Could not verify accessibility permission: (.+)$/, '无法验证辅助功能权限：$1'],
        [/^Could not verify screen recording permission: (.+)$/, '无法验证屏幕录制权限：$1'],
        [/^Accessibility check failed: (.+)$/, '辅助功能检查失败：$1'],
        [/^ICC profile check failed: (.+)$/, 'ICC Profile 检查失败：$1'],
        [/^ICC check failed: (.+)$/, 'ICC 检查失败：$1'],
        [/^Custom ICC profile loaded: (.+)$/, '已加载自定义 ICC Profile：$1'],
        [/^Null\/system color space in use: (.+)$/, '正在使用系统内置色彩空间：$1'],
        [/^VCGT check failed: (.+)$/, 'VCGT 检查失败：$1'],
        [/^Last calibration: (\d+) minutes ago$/, '上次校正：$1 分钟前'],
        [/^Sleep check failed: (.+)$/, '睡眠检查失败：$1'],
        [/^Display sleep check failed: (.+)$/, '显示器睡眠检查失败：$1'],
        [/^HDR check skipped: (.+)$/, '已跳过 HDR 检查：$1'],
        [/^Windows HDR check skipped: (.+)$/, '已跳过 Windows HDR 检查：$1'],
        [/^f\.lux check failed: (.+)$/, 'f.lux 检查失败：$1'],
        [/^Color-adjusting software detected: (.+)$/, '检测到改色软件：$1'],
        [/^Could not determine Night Shift status$/, '无法确定夜览状态'],
        [/^(\S+) found: (.+)$/, '$1 已找到：$2'],
        [/^(\S+) not found - Install ArgyllCMS or add it to PATH$/, '$1 未找到 —— 请安装 ArgyllCMS 或将其加入 PATH'],
        [/^Check execution failed: (.+)$/, '检查执行失败：$1'],
        [/^Check failed: (.+)$/, '检查失败：$1']
    ];

    /* ==================== 对外接口 ==================== */

    /**
     * 是否需要翻译（英文界面不需要）
     */
    function isZhLang() {
        return !(global.I18N && global.I18N.getLanguage &&
                 global.I18N.getLanguage() === 'en');
    }

    /**
     * 翻译预检消息（英文 → 中文）；英文模式原样返回
     */
    function translatePreflightMessage(text) {
        if (!text) return text;
        if (!isZhLang()) return text;

        if (Object.prototype.hasOwnProperty.call(MESSAGES, text)) {
            return MESSAGES[text];
        }
        for (var i = 0; i < PATTERNS.length; i++) {
            if (PATTERNS[i][0].test(text)) {
                return text.replace(PATTERNS[i][0], PATTERNS[i][1]);
            }
        }
        return text; // 无匹配则原样显示
    }

    /**
     * 翻译检查项名称（item_id → 中文）；英文模式显示原始 item_id
     */
    function translatePreflightItemName(itemId) {
        if (!itemId) return itemId;
        if (!isZhLang()) return itemId;
        return ITEM_NAMES[itemId] || itemId;
    }

    global.PREFLIGHT_I18N = {
        translateMessage: translatePreflightMessage,
        translateItemName: translatePreflightItemName
    };

})(typeof window !== 'undefined' ? window : globalThis);
