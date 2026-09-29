/**
 * Topos Calibrator - 数据对比窗口前端逻辑
 * 用于对比多条历史测量数据
 */

// 后端对象
let backend = null;

// 图表实例
let comparisonCieChart = null;
let comparisonGammaChart = null;

// 当前选中的测量数据 ID
let selectedMeasurementIds = [];

// 当前对比数据
let currentComparisonData = null;

// 所有测量数据列表（用于搜索）
let allMeasurementList = [];

// 当前激活的标签页
let currentTab = 'overview';

// 当前选中的参考色域和曲线预设
let selectedGamuts = ['sRGB'];
let selectedGammas = ['2.2'];

// 用户自定义颜色映射 { measurementId: colorHex }
let customColors = {};

// 预设对比颜色（用于默认分配）
const COMPARISON_COLORS = [
    '#3b82f6',  // 蓝色
    '#ef4444',  // 红色
    '#10b981',  // 绿色
    '#f59e0b',  // 橙色
    '#8b5cf6',  // 紫色
    '#ec4899',  // 粉色
    '#06b6d4',  // 青色
    '#84cc16',  // 黄绿色
    '#f97316',  // 深橙色
    '#6366f1',  // 靛蓝
];

// 标准色域数据 - 与主窗口charts.js一致
const COMPARISON_STANDARD_GAMUTS = {
    sRGB: {
        red: [0.64, 0.33],
        green: [0.30, 0.60],
        blue: [0.15, 0.06],
        white: [0.3127, 0.3290],
        color: '#00ff00',
        name: 'sRGB'
    },
    Rec709: {
        red: [0.64, 0.33],
        green: [0.30, 0.60],
        blue: [0.15, 0.06],
        white: [0.3127, 0.3290],
        color: '#00ff88',
        name: 'Rec.709'
    },
    DCI_P3: {
        red: [0.68, 0.32],
        green: [0.265, 0.69],
        blue: [0.15, 0.06],
        white: [0.314, 0.351],
        color: '#ff6b6b',
        name: 'DCI-P3'
    },
    DisplayP3: {
        red: [0.68, 0.32],
        green: [0.265, 0.69],
        blue: [0.15, 0.06],
        white: [0.3127, 0.3290],
        color: '#ff8888',
        name: 'Display P3'
    },
    AdobeRGB: {
        red: [0.64, 0.33],
        green: [0.21, 0.71],
        blue: [0.15, 0.06],
        white: [0.3127, 0.3290],
        color: '#4ecdc4',
        name: 'Adobe RGB'
    },
    Rec2020: {
        red: [0.708, 0.292],
        green: [0.170, 0.797],
        blue: [0.131, 0.046],
        white: [0.3127, 0.3290],
        color: '#ffe66d',
        name: 'Rec.2020'
    },
    ProPhotoRGB: {
        red: [0.7347, 0.2653],
        green: [0.1596, 0.8404],
        blue: [0.0366, 0.0001],
        white: [0.3457, 0.3585],
        color: '#9b59b6',
        name: 'ProPhoto RGB'
    },
    ACES_AP0: {
        red: [0.7347, 0.2653],
        green: [0.0000, 1.0000],
        blue: [0.0001, -0.0770],
        white: [0.32168, 0.33767],
        color: '#f39c12',
        name: 'ACES AP0'
    },
    ACES_AP1: {
        red: [0.713, 0.293],
        green: [0.165, 0.830],
        blue: [0.128, 0.044],
        white: [0.32168, 0.33767],
        color: '#f1c40f',
        name: 'ACES AP1'
    },
    S_Gamut3: {
        red: [0.730, 0.280],
        green: [0.140, 0.850],
        blue: [0.100, 0.050],
        white: [0.3127, 0.3290],
        color: '#3498db',
        name: 'S-Gamut3'
    },
    V_Gamut: {
        red: [0.730, 0.280],
        green: [0.165, 0.840],
        blue: [0.100, 0.010],
        white: [0.3127, 0.3290],
        color: '#1abc9c',
        name: 'V-Gamut'
    },
    C_Gamut: {
        red: [0.740, 0.270],
        green: [0.170, 0.830],
        blue: [0.100, 0.020],
        white: [0.3127, 0.3290],
        color: '#16a085',
        name: 'C-Gamut'
    },
    REDWideGamutRGB: {
        red: [0.780, 0.304],
        green: [0.121, 0.873],
        blue: [0.095, -0.084],
        white: [0.3127, 0.3290],
        color: '#c0392b',
        name: 'RED WideGamut'
    }
};

// Gamma/EOTF 预设颜色
const COMPARISON_GAMMA_COLORS = {
    '1.8': '#0abde3',
    '2.0': '#00cec9',
    '2.2': '#8888a0',
    '2.4': '#ff9f43',
    '2.6': '#ee5a24',
    'sRGB': '#10b981',
    'Rec709': '#6c5ce7',
    'BT1886': '#fdcb6e',
    'PQ': '#e17055',
    'HLG': '#00b894',
    'LogC': '#74b9ff',
    'SLog3': '#0984e3',
    'VLog': '#81ecec',
    'CLog': '#55a3ff',
    'ACEScct': '#a29bfe',
    'Linear': '#ffeaa7'
};

// CIE 1931 2° 标准观察者光谱轨迹数据（1nm 步进，402 点）
// 与主窗口 charts.js 保持一致，确保马蹄图圆滑
const CIE1931_LOCUS_DATA = [
    [0.1741, 0.0050], [0.1741, 0.0050], [0.1741, 0.0050], [0.1741, 0.0050], [0.1740, 0.0050],
    [0.1740, 0.0050], [0.1740, 0.0050], [0.1739, 0.0049], [0.1739, 0.0049], [0.1738, 0.0049],
    [0.1738, 0.0049], [0.1738, 0.0049], [0.1737, 0.0049], [0.1737, 0.0049], [0.1736, 0.0049],
    [0.1736, 0.0049], [0.1735, 0.0049], [0.1735, 0.0049], [0.1734, 0.0048], [0.1734, 0.0048],
    [0.1733, 0.0048], [0.1733, 0.0048], [0.1732, 0.0048], [0.1732, 0.0048], [0.1731, 0.0048],
    [0.1730, 0.0048], [0.1729, 0.0048], [0.1728, 0.0048], [0.1727, 0.0048], [0.1727, 0.0048],
    [0.1726, 0.0048], [0.1725, 0.0048], [0.1724, 0.0048], [0.1723, 0.0048], [0.1722, 0.0048],
    [0.1721, 0.0048], [0.1720, 0.0049], [0.1719, 0.0049], [0.1717, 0.0049], [0.1716, 0.0050],
    [0.1714, 0.0051], [0.1712, 0.0052], [0.1710, 0.0053], [0.1708, 0.0055], [0.1705, 0.0056],
    [0.1703, 0.0058], [0.1701, 0.0060], [0.1698, 0.0062], [0.1695, 0.0064], [0.1692, 0.0066],
    [0.1689, 0.0069], [0.1685, 0.0072], [0.1681, 0.0075], [0.1678, 0.0078], [0.1673, 0.0082],
    [0.1669, 0.0086], [0.1664, 0.0090], [0.1660, 0.0094], [0.1655, 0.0099], [0.1650, 0.0103],
    [0.1644, 0.0109], [0.1638, 0.0114], [0.1632, 0.0119], [0.1626, 0.0125], [0.1618, 0.0131],
    [0.1611, 0.0138], [0.1603, 0.0145], [0.1595, 0.0152], [0.1586, 0.0160], [0.1576, 0.0168],
    [0.1566, 0.0177], [0.1556, 0.0186], [0.1545, 0.0196], [0.1534, 0.0205], [0.1522, 0.0216],
    [0.1510, 0.0227], [0.1497, 0.0239], [0.1483, 0.0253], [0.1469, 0.0266], [0.1455, 0.0281],
    [0.1440, 0.0297], [0.1424, 0.0314], [0.1408, 0.0332], [0.1391, 0.0352], [0.1374, 0.0374],
    [0.1355, 0.0399], [0.1335, 0.0427], [0.1314, 0.0459], [0.1291, 0.0495], [0.1267, 0.0534],
    [0.1241, 0.0578], [0.1215, 0.0626], [0.1187, 0.0678], [0.1158, 0.0736], [0.1128, 0.0799],
    [0.1096, 0.0868], [0.1063, 0.0945], [0.1028, 0.1029], [0.0991, 0.1120], [0.0953, 0.1219],
    [0.0913, 0.1327], [0.0871, 0.1443], [0.0827, 0.1569], [0.0781, 0.1704], [0.0734, 0.1850],
    [0.0687, 0.2007], [0.0640, 0.2175], [0.0593, 0.2352], [0.0547, 0.2541], [0.0500, 0.2740],
    [0.0454, 0.2950], [0.0408, 0.3170], [0.0362, 0.3399], [0.0318, 0.3636], [0.0275, 0.3879],
    [0.0235, 0.4127], [0.0197, 0.4378], [0.0163, 0.4629], [0.0132, 0.4882], [0.0105, 0.5134],
    [0.0082, 0.5384], [0.0063, 0.5631], [0.0049, 0.5871], [0.0040, 0.6105], [0.0036, 0.6330],
    [0.0039, 0.6548], [0.0046, 0.6759], [0.0060, 0.6961], [0.0080, 0.7153], [0.0106, 0.7334],
    [0.0139, 0.7502], [0.0178, 0.7656], [0.0222, 0.7796], [0.0273, 0.7921], [0.0328, 0.8029],
    [0.0389, 0.8120], [0.0453, 0.8194], [0.0522, 0.8252], [0.0593, 0.8294], [0.0667, 0.8323],
    [0.0743, 0.8338], [0.0820, 0.8341], [0.0899, 0.8333], [0.0979, 0.8316], [0.1060, 0.8292],
    [0.1142, 0.8262], [0.1224, 0.8228], [0.1305, 0.8189], [0.1387, 0.8148], [0.1468, 0.8104],
    [0.1547, 0.8059], [0.1625, 0.8012], [0.1702, 0.7965], [0.1779, 0.7917], [0.1854, 0.7867],
    [0.1929, 0.7816], [0.2003, 0.7764], [0.2077, 0.7711], [0.2150, 0.7656], [0.2223, 0.7600],
    [0.2296, 0.7543], [0.2369, 0.7485], [0.2441, 0.7426], [0.2514, 0.7366], [0.2586, 0.7305],
    [0.2658, 0.7243], [0.2730, 0.7181], [0.2801, 0.7117], [0.2873, 0.7053], [0.2944, 0.6988],
    [0.3016, 0.6923], [0.3088, 0.6857], [0.3159, 0.6791], [0.3231, 0.6724], [0.3302, 0.6656],
    [0.3374, 0.6589], [0.3445, 0.6520], [0.3517, 0.6452], [0.3588, 0.6383], [0.3660, 0.6314],
    [0.3731, 0.6245], [0.3802, 0.6175], [0.3874, 0.6105], [0.3945, 0.6036], [0.4016, 0.5966],
    [0.4087, 0.5896], [0.4158, 0.5826], [0.4229, 0.5756], [0.4300, 0.5686], [0.4370, 0.5617],
    [0.4441, 0.5547], [0.4511, 0.5478], [0.4580, 0.5408], [0.4650, 0.5339], [0.4719, 0.5271],
    [0.4788, 0.5202], [0.4856, 0.5134], [0.4924, 0.5066], [0.4991, 0.4999], [0.5059, 0.4932],
    [0.5125, 0.4866], [0.5191, 0.4800], [0.5256, 0.4735], [0.5321, 0.4671], [0.5385, 0.4607],
    [0.5448, 0.4544], [0.5510, 0.4482], [0.5572, 0.4421], [0.5633, 0.4361], [0.5693, 0.4301],
    [0.5752, 0.4242], [0.5809, 0.4185], [0.5867, 0.4128], [0.5922, 0.4072], [0.5977, 0.4018],
    [0.6029, 0.3965], [0.6080, 0.3914], [0.6130, 0.3865], [0.6178, 0.3817], [0.6225, 0.3770],
    [0.6270, 0.3725], [0.6315, 0.3680], [0.6359, 0.3637], [0.6402, 0.3594], [0.6443, 0.3553],
    [0.6482, 0.3514], [0.6520, 0.3476], [0.6557, 0.3440], [0.6592, 0.3406], [0.6625, 0.3372],
    [0.6658, 0.3340], [0.6689, 0.3309], [0.6719, 0.3280], [0.6747, 0.3251], [0.6775, 0.3224],
    [0.6801, 0.3197], [0.6826, 0.3172], [0.6850, 0.3149], [0.6873, 0.3126], [0.6894, 0.3104],
    [0.6915, 0.3083], [0.6935, 0.3064], [0.6954, 0.3045], [0.6972, 0.3027], [0.6989, 0.3009],
    [0.7006, 0.2993], [0.7022, 0.2977], [0.7037, 0.2962], [0.7052, 0.2948], [0.7066, 0.2934],
    [0.7079, 0.2920], [0.7092, 0.2907], [0.7105, 0.2894], [0.7117, 0.2882], [0.7129, 0.2871],
    [0.7140, 0.2859], [0.7151, 0.2848], [0.7162, 0.2838], [0.7172, 0.2828], [0.7181, 0.2818],
    [0.7190, 0.2809], [0.7199, 0.2801], [0.7208, 0.2792], [0.7216, 0.2784], [0.7223, 0.2777],
    [0.7230, 0.2769], [0.7237, 0.2763], [0.7243, 0.2757], [0.7249, 0.2751], [0.7255, 0.2745],
    [0.7260, 0.2740], [0.7265, 0.2735], [0.7270, 0.2730], [0.7274, 0.2726], [0.7279, 0.2721],
    [0.7283, 0.2717], [0.7287, 0.2713], [0.7290, 0.2710], [0.7294, 0.2706], [0.7297, 0.2703],
    [0.7300, 0.2700], [0.7302, 0.2698], [0.7305, 0.2695], [0.7307, 0.2693], [0.7309, 0.2691],
    [0.7311, 0.2689], [0.7313, 0.2687], [0.7315, 0.2685], [0.7317, 0.2683], [0.7318, 0.2682],
    [0.7320, 0.2680], [0.7321, 0.2678], [0.7323, 0.2677], [0.7324, 0.2676], [0.7326, 0.2674],
    [0.7327, 0.2673], [0.7329, 0.2671], [0.7330, 0.2670], [0.7331, 0.2669], [0.7333, 0.2667],
    [0.7334, 0.2666], [0.7336, 0.2665], [0.7337, 0.2663], [0.7338, 0.2662], [0.7339, 0.2661],
    [0.7340, 0.2660], [0.7341, 0.2659], [0.7342, 0.2658], [0.7343, 0.2657], [0.7343, 0.2657],
    [0.7344, 0.2656], [0.7344, 0.2656], [0.7345, 0.2655], [0.7345, 0.2655], [0.7346, 0.2654],
    [0.7346, 0.2654], [0.7346, 0.2654], [0.7347, 0.2653], [0.7347, 0.2653], [0.7347, 0.2653],
    [0.1741, 0.0050]
];

/**
 * 生成 Gamma 曲线数据
 */
function generateComparisonGammaCurveData(gammaType) {
    const data = [];

    // 标准Gamma曲线
    if (['1.8', '2.0', '2.2', '2.4', '2.6'].includes(gammaType)) {
        const gamma = parseFloat(gammaType);
        for (let i = 0; i <= 100; i += 2) {
            const input = i / 100;
            const output = Math.pow(input, gamma) * 100;
            data.push([i, output]);
        }
        return data;
    }

    // 线性
    if (gammaType === 'Linear') {
        for (let i = 0; i <= 100; i += 2) {
            data.push([i, i]);
        }
        return data;
    }

    // sRGB曲线
    if (gammaType === 'sRGB') {
        for (let i = 0; i <= 100; i += 2) {
            const input = i / 100;
            let output;
            if (input <= 0.04045) {
                output = input / 12.92;
            } else {
                output = Math.pow((input + 0.055) / 1.055, 2.4);
            }
            data.push([i, output * 100]);
        }
        return data;
    }

    // Rec.709曲线
    if (gammaType === 'Rec709') {
        for (let i = 0; i <= 100; i += 2) {
            const input = i / 100;
            let output;
            if (input <= 0.018) {
                output = input * 4.5;
            } else {
                output = 1.099 * Math.pow(input, 0.45) - 0.099;
            }
            data.push([i, output * 100]);
        }
        return data;
    }

    // 其他曲线使用简化处理
    for (let i = 0; i <= 100; i += 2) {
        const gamma = 2.2;
        const input = i / 100;
        const output = Math.pow(input, gamma) * 100;
        data.push([i, output]);
    }
    return data;
}

/**
 * 初始化 QWebChannel 通信
 */
function initWebChannel() {
    new QWebChannel(qt.webChannelTransport, function(channel) {
        backend = channel.objects.backend;

        // 连接信号
        backend.logMessage.connect(handleLogMessage);
        backend.measurementListUpdated.connect(handleMeasurementListUpdated);
        backend.comparisonDataUpdated.connect(handleComparisonDataUpdated);
        backend.errorOccurred.connect(handleError);

        // P6-C: 连接新信号
        backend.groupedMeasurementListUpdated.connect(handleGroupedMeasurementListUpdated);
        backend.goldenBaselineUpdated.connect(handleGoldenBaselineUpdated);
        backend.beforeAfterComparisonUpdated.connect(function(dataJson) {
            const data = parseJson(dataJson);
            if (data) {
                showBeforeAfterComparison(data);
            }
        });
        backend.compatibilityCheckResult.connect(handleCompatibilityCheckResult);

        // 加载测量数据列表
        backend.load_measurement_list();

        console.log('[Comparison] QWebChannel 初始化完成 (P6-C)');
    });
}

/**
 * 处理日志消息
 */
function handleLogMessage(message) {
    console.log('[Backend]', message);
}

/**
 * 处理错误消息
 */
function handleError(error) {
    console.error('[Error]', error);
}

/**
 * 处理测量数据列表更新
 */
function handleMeasurementListUpdated(listJson) {
    const data = parseJson(listJson);
    if (!data) return;

    // 后端发送的是 {"measurements": [...]}，需要提取数组
    const measurements = data.measurements || data;
    
    allMeasurementList = measurements;

    // 渲染列表
    renderMeasurementList(measurements);

    // 隐藏加载占位符
    const placeholder = document.getElementById('loading-placeholder');
    if (placeholder) {
        placeholder.style.display = 'none';
    }

    // 默认选择最上面的两组数据
    if (measurements.length >= 2 && selectedMeasurementIds.length === 0) {
        selectedMeasurementIds = [measurements[0].id, measurements[1].id];
        updateSelectionUI();
        performComparison();
    }

    console.log(`[Comparison] 已加载 ${measurements.length} 条测量数据`);
}

/**
 * 解析 JSON（兼容字符串和对象）
 */
function parseJson(data) {
    if (typeof data === 'string') {
        try {
            return JSON.parse(data);
        } catch (e) {
            console.error('JSON 解析失败:', e);
            return null;
        }
    }
    return data;
}

/**
 * 渲染测量数据列表
 */
function renderMeasurementList(measurements) {
    const listContainer = document.getElementById('measurement-list');
    if (!listContainer) return;

    // 清空现有内容
    listContainer.innerHTML = '';

    if (measurements.length === 0) {
        const emptyItem = document.createElement('div');
        emptyItem.className = 'empty-list-hint';
        emptyItem.innerHTML = '<span style="color: var(--text-muted); padding: 20px;">暂无数据</span>';
        listContainer.appendChild(emptyItem);
        return;
    }

    measurements.forEach(item => {
        const itemElement = createMeasurementItem(item);
        listContainer.appendChild(itemElement);
    });
}

/**
 * 创建测量数据项元素
 */
function createMeasurementItem(item) {
    const div = document.createElement('div');
    div.className = 'measurement-item';
    div.dataset.id = item.id;
    div.dataset.displayName = item.display_name || '';

    // 确定显示名称：优先使用用户自定义名称，否则使用默认格式
    const displayName = item.display_name || formatDefaultName(item);
    const timestamp = formatTimestamp(item.timestamp);
    const probe = item.probe || '未知';

    // 获取或分配颜色
    const color = getMeasurementColor(item.id, selectedMeasurementIds.indexOf(item.id));

    // 构建标签
    let tagsHtml = '';
    if (item.has_gamut) {
        tagsHtml += '<span class="measurement-tag gamut">色域</span>';
    }
    if (item.has_gamma) {
        tagsHtml += '<span class="measurement-tag gamma">Gamma</span>';
    }

    div.innerHTML = `
        <div class="measurement-checkbox"></div>
        <div class="measurement-info">
            <div class="measurement-name">${displayName}</div>
            <div class="measurement-meta">
                <span>${item.display_type || '--'}</span>
                ${tagsHtml}
            </div>
        </div>
        <div class="measurement-color-picker" style="background-color: ${color}" title="点击选择颜色">
            <input type="color" class="measurement-color-input" value="${color}" data-id="${item.id}">
        </div>
    `;

    // 点击事件（选择/取消选择）
    div.addEventListener('click', function(e) {
        // 如果点击的是颜色选择器，不触发选择事件
        if (e.target.classList.contains('measurement-color-input') ||
            e.target.classList.contains('measurement-color-picker')) {
            return;
        }
        toggleMeasurementSelection(item.id);
    });

    // 右键菜单事件
    div.addEventListener('contextmenu', function(e) {
        e.preventDefault();
        e.stopPropagation();
        showContextMenu(e, item);
    });

    // 颜色选择事件
    const colorInput = div.querySelector('.measurement-color-input');
    colorInput.addEventListener('input', function(e) {
        e.stopPropagation();
        const newColor = e.target.value;
        customColors[item.id] = newColor;

        // 更新颜色显示
        const picker = div.querySelector('.measurement-color-picker');
        picker.style.backgroundColor = newColor;
        picker.classList.add('active');

        // 如果有对比数据，重新渲染图表和表格
        if (currentComparisonData) {
            updateChartsWithCustomColors();
        }
    });

    colorInput.addEventListener('change', function(e) {
        e.stopPropagation();
        const picker = div.querySelector('.measurement-color-picker');
        picker.classList.remove('active');
    });

    return div;
}

/**
 * 格式化默认名称（当用户未设置自定义名称时使用）
 */
function formatDefaultName(item) {
    const timestamp = formatTimestamp(item.timestamp);
    const probe = item.probe || '未知';
    return `${timestamp} (${probe})`;
}

// ========== 右键菜单功能 ==========

// 当前右键菜单目标项
let contextMenuTargetItem = null;

/**
 * 显示右键菜单
 */
function showContextMenu(event, item) {
    contextMenuTargetItem = item;

    const menu = document.getElementById('context-menu');
    if (!menu) return;

    // 设置菜单位置
    const menuWidth = 120;
    const menuHeight = 80;

    let x = event.clientX;
    let y = event.clientY;

    // 确保菜单不超出窗口
    if (x + menuWidth > window.innerWidth) {
        x = window.innerWidth - menuWidth - 10;
    }
    if (y + menuHeight > window.innerHeight) {
        y = window.innerHeight - menuHeight - 10;
    }

    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    menu.classList.add('show');

    // 点击其他地方关闭菜单
    document.addEventListener('click', hideContextMenu, { once: true });
}

/**
 * 隐藏右键菜单
 */
function hideContextMenu() {
    const menu = document.getElementById('context-menu');
    if (menu) {
        menu.classList.remove('show');
    }
    contextMenuTargetItem = null;
}

/**
 * 显示重命名对话框
 */
function showRenameDialog(item) {
    hideContextMenu();

    if (!item) return;

    // 创建重命名对话框
    const dialog = document.getElementById('rename-dialog');
    const input = document.getElementById('rename-input');
    const overlay = document.getElementById('rename-overlay');

    if (!dialog || !input || !overlay) return;

    // 设置当前名称（优先显示自定义名称，否则显示默认名称）
    const currentName = item.display_name || formatDefaultName(item);
    input.value = currentName;
    input.placeholder = formatDefaultName(item);

    // 显示对话框
    overlay.classList.add('show');
    dialog.classList.add('show');

    // 聚焦输入框并选中文本
    setTimeout(() => {
        input.focus();
        input.select();
    }, 50);

    // 保存当前处理的项ID
    dialog.dataset.targetId = item.id;
}

/**
 * 隐藏重命名对话框
 */
function hideRenameDialog() {
    const dialog = document.getElementById('rename-dialog');
    const overlay = document.getElementById('rename-overlay');

    if (dialog) {
        dialog.classList.remove('show');
        dialog.dataset.targetId = '';
    }
    if (overlay) {
        overlay.classList.remove('show');
    }
}

/**
 * 执行重命名操作
 */
function executeRename() {
    const dialog = document.getElementById('rename-dialog');
    const input = document.getElementById('rename-input');

    if (!dialog || !input) return;

    const targetId = dialog.dataset.targetId;
    const newName = input.value.trim();

    if (!targetId) {
        hideRenameDialog();
        return;
    }

    // 如果新名称为空，使用默认名称
    // 找到对应的数据项
    const item = allMeasurementList.find(m => m.id === targetId);
    const finalName = newName || (item ? formatDefaultName(item) : '');

    // 调用后端接口
    if (backend) {
        backend.rename_measurement(targetId, finalName, function(resultJson) {
            const result = parseJson(resultJson);
            if (result && result.success) {
                console.log('[Comparison] 重命名成功:', finalName);
                // 列表会自动刷新（后端会调用 load_measurement_list）
            } else {
                console.error('[Comparison] 重命名失败:', result?.message);
                // 显示错误提示
                showErrorToast(result?.message || t('重命名失败'));
            }
        });
    }

    hideRenameDialog();
}

/**
 * 显示错误提示
 */
function showErrorToast(message) {
    // 创建或获取提示元素
    let toast = document.getElementById('error-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'error-toast';
        toast.className = 'error-toast';
        document.body.appendChild(toast);
    }

    toast.textContent = message;
    toast.classList.add('show');

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

/**
 * 获取测量数据的颜色
 * @param {string} id - 测量数据ID
 * @param {number} index - 在选中列表中的索引（用于默认颜色分配）
 */
function getMeasurementColor(id, index) {
    // 如果用户已自定义颜色，返回自定义颜色
    if (customColors[id]) {
        return customColors[id];
    }
    // 如果数据已选中，使用选中顺序分配颜色
    if (index >= 0) {
        return COMPARISON_COLORS[index % COMPARISON_COLORS.length];
    }
    // 未选中的数据使用默认灰色显示
    return '#555566';
}

/**
 * 更新图表和表格使用自定义颜色
 */
function updateChartsWithCustomColors() {
    if (!currentComparisonData) return;

    // 应用自定义颜色到数据
    applyCustomColors(currentComparisonData);

    // 重新渲染图表和表格
    if (comparisonCieChart) {
        updateCieComparisonChart(currentComparisonData);
    }
    if (comparisonGammaChart) {
        updateGammaComparisonChart(currentComparisonData);
    }
    updateComparisonTable(currentComparisonData);
    updateDetailTable(currentComparisonData);
    updateChartLegends(currentComparisonData);

    // 更新测量列表项的颜色显示
    updateMeasurementListColors();
}

/**
 * 更新测量数据列表项的颜色显示
 */
function updateMeasurementListColors() {
    const items = document.querySelectorAll('.measurement-item');
    items.forEach(item => {
        const id = item.dataset.id;
        if (customColors[id]) {
            const picker = item.querySelector('.measurement-color-picker');
            const input = item.querySelector('.measurement-color-input');
            if (picker) {
                picker.style.backgroundColor = customColors[id];
            }
            if (input) {
                input.value = customColors[id];
            }
        }
    });
}

/**
 * 格式化时间戳显示
 */
function formatTimestamp(timestamp) {
    if (!timestamp) return '未知';

    try {
        const date = new Date(timestamp);
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hour = String(date.getHours()).padStart(2, '0');
        const minute = String(date.getMinutes()).padStart(2, '0');

        return `${month}-${day} ${hour}:${minute}`;
    } catch {
        return timestamp.split('T')[0] || timestamp;
    }
}

/**
 * 切换测量数据选择状态
 */
function toggleMeasurementSelection(id) {
    const index = selectedMeasurementIds.indexOf(id);

    if (index >= 0) {
        selectedMeasurementIds.splice(index, 1);
    } else {
        selectedMeasurementIds.push(id);
    }

    updateSelectionUI();

    // 选择变化时自动执行对比
    if (selectedMeasurementIds.length > 0) {
        performComparison();
    } else {
        // 清空选择时隐藏对比数据
        hideComparisonData();
    }
}

/**
 * 更新选择状态 UI
 */
function updateSelectionUI() {
    const items = document.querySelectorAll('.measurement-item');

    items.forEach(item => {
        const id = item.dataset.id;
        const selectedIndex = selectedMeasurementIds.indexOf(id);

        if (selectedIndex >= 0) {
            item.classList.add('selected');
        } else {
            item.classList.remove('selected');
        }

        // 更新颜色显示（根据选中顺序分配颜色）
        const picker = item.querySelector('.measurement-color-picker');
        if (picker && !customColors[id]) {
            const color = getMeasurementColor(id, selectedIndex);
            picker.style.backgroundColor = color;
            // 同步更新颜色输入框的值
            const input = item.querySelector('.measurement-color-input');
            if (input) {
                input.value = color;
            }
        }
    });

    const countElement = document.getElementById('selected-count');
    if (countElement) {
        countElement.textContent = selectedMeasurementIds.length;
    }
}

/**
 * 隐藏对比数据（清空选择时调用）
 */
function hideComparisonData() {
    // 清空图表数据
    if (comparisonCieChart) {
        comparisonCieChart.clear();
        comparisonCieChart.setOption(getBaseCieOption());
    }
    if (comparisonGammaChart) {
        comparisonGammaChart.clear();
        comparisonGammaChart.setOption(getBaseGammaOption());
    }

    // 隐藏图表容器和表格容器
    const chartsContainer = document.getElementById('charts-container');
    const tableContainer = document.getElementById('table-container');
    const emptyState = document.getElementById('empty-state');

    if (chartsContainer) chartsContainer.style.display = 'none';
    if (tableContainer) tableContainer.style.display = 'none';
    if (emptyState) emptyState.style.display = 'flex';

    currentComparisonData = null;
}

/**
 * 全选
 */
function selectAllMeasurements() {
    const visibleItems = document.querySelectorAll('.measurement-item:not([style*="display: none"])');
    visibleItems.forEach(item => {
        const id = item.dataset.id;
        if (!selectedMeasurementIds.includes(id)) {
            selectedMeasurementIds.push(id);
        }
    });

    updateSelectionUI();

    // 选择变化时自动执行对比
    if (selectedMeasurementIds.length > 0) {
        performComparison();
    }
}

/**
 * 清空选择
 */
function clearAllSelections() {
    selectedMeasurementIds = [];
    updateSelectionUI();
    hideComparisonData();
}

/**
 * 搜索过滤
 */
function filterMeasurements(keyword) {
    const items = document.querySelectorAll('.measurement-item');
    const lowerKeyword = keyword.toLowerCase();

    items.forEach(item => {
        const name = item.querySelector('.measurement-name')?.textContent || '';
        const meta = item.querySelector('.measurement-meta')?.textContent || '';

        const matches = name.toLowerCase().includes(lowerKeyword) ||
                       meta.toLowerCase().includes(lowerKeyword);

        item.style.display = matches ? '' : 'none';
    });
}

/**
 * 处理对比数据更新
 */
function handleComparisonDataUpdated(dataJson) {
    const data = parseJson(dataJson);
    if (!data) return;

    // 应用用户自定义颜色
    applyCustomColors(data);

    currentComparisonData = data;

    // 确保空状态隐藏
    const emptyState = document.getElementById('empty-state');
    if (emptyState) {
        emptyState.style.display = 'none';
    }

    // 显示图表区域和表格区域（有对比数据时）
    const chartsContainer = document.getElementById('charts-container');
    if (chartsContainer) {
        chartsContainer.style.display = '';
    }

    const tableContainer = document.getElementById('table-container');
    if (tableContainer) {
        tableContainer.style.display = '';
    }

    // 显示当前标签页的内容
    showTabContent(currentTab);

    // 更新图表和表格
    updateCieComparisonChart(data);
    updateGammaComparisonChart(data);
    updateComparisonTable(data);
    updateDetailTable(data);

    // 更新图例
    updateChartLegends(data);

    // P6-C: 添加目标标准标注（防误对比功能）
    addTargetStandardLabels(data);

    console.log('[Comparison] 对比数据已更新');
}

/**
 * 应用用户自定义颜色到对比数据
 */
function applyCustomColors(data) {
    // 更新色域数据颜色
    if (data.gamut_data) {
        data.gamut_data.forEach(gamut => {
            const id = gamut.id;
            if (id && customColors[id]) {
                gamut.color = customColors[id];
            }
        });
    }

    // 更新 Gamma 数据颜色
    if (data.gamma_data) {
        data.gamma_data.forEach(gamma => {
            const id = gamma.id;
            if (id && customColors[id]) {
                gamma.color = customColors[id];
            }
        });
    }

    // 更新汇总表格颜色
    if (data.summary_table) {
        data.summary_table.forEach(row => {
            const id = row.id;
            if (id && customColors[id]) {
                row.color = customColors[id];
            }
        });
    }

    // 更新详细数据颜色
    if (data.detail_data) {
        data.detail_data.forEach(ds => {
            const id = ds.id;
            if (id && customColors[id]) {
                ds.color = customColors[id];
            }
        });
    }

    // 更新颜色列表
    if (data.colors && selectedMeasurementIds) {
        data.colors = selectedMeasurementIds.map(id => 
            customColors[id] || COMPARISON_COLORS[selectedMeasurementIds.indexOf(id) % COMPARISON_COLORS.length]
        );
    }
}

/**
 * 切换标签页
 */
function switchTab(tabName) {
    currentTab = tabName;

    // 更新标签按钮状态
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    // 趋势页独立于对比数据，无需 currentComparisonData
    if (tabName === 'trend') {
        showTabContent('trend');
        initTrendTab();
        return;
    }

    // 如果有数据，显示对应内容
    if (currentComparisonData) {
        showTabContent(tabName);
    }
}

/**
 * 显示标签页内容
 */
function showTabContent(tabName) {
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });

    const tabContent = document.getElementById(`tab-${tabName}`);
    if (tabContent) {
        tabContent.classList.add('active');
    }

    // 切换到概览时重新调整图表大小
    if (tabName === 'overview') {
        setTimeout(() => {
            if (comparisonCieChart) comparisonCieChart.resize();
            if (comparisonGammaChart) comparisonGammaChart.resize();
        }, 50);
    }
}

/**
 * 初始化 CIE 对比图表
 */
function initCieComparisonChart() {
    const chartDom = document.getElementById('cie-chart');
    if (!chartDom) return;

    comparisonCieChart = echarts.init(chartDom, null, {
        renderer: 'canvas',
        devicePixelRatio: window.devicePixelRatio || 2
    });

    const baseOption = getBaseCieOption();
    comparisonCieChart.setOption(baseOption);

    window.addEventListener('resize', function() {
        if (comparisonCieChart) {
            comparisonCieChart.resize();
        }
    });
}

/**
 * 获取基础 CIE 图表配置
 */
function getBaseCieOption() {
    // 使用完整的 CIE 1931 光谱轨迹数据（402 点，1nm 步进）
    const locusData = CIE1931_LOCUS_DATA;

    // 构建参考色域系列（根据选中的预设）
    const referenceGamutSeries = [];
    selectedGamuts.forEach(name => {
        const gamut = COMPARISON_STANDARD_GAMUTS[name];
        if (gamut) {
            referenceGamutSeries.push({
                name: gamut.name || name,
                type: 'line',
                data: [
                    gamut.red,
                    gamut.green,
                    gamut.blue,
                    gamut.red
                ],
                lineStyle: {
                    color: gamut.color,
                    width: 1,
                    type: 'dashed',
                    opacity: 0.6
                },
                symbol: 'none',
                z: 3
            });
        }
    });

    return {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'item',
            formatter: function(params) {
                if (params.value) {
                    return `${params.name}<br/>x: ${params.value[0].toFixed(4)}<br/>y: ${params.value[1].toFixed(4)}`;
                }
                return params.name;
            },
            backgroundColor: '#1e1e30',
            borderColor: '#3a3a50',
            textStyle: { color: '#ffffff', fontSize: 11 }
        },
        grid: {
            left: 35,
            right: 15,
            top: 10,
            bottom: 25,
            containLabel: false
        },
        xAxis: {
            type: 'value',
            min: 0,
            max: 0.8,
            interval: 0.1,
            name: 'x',
            nameLocation: 'end',
            nameGap: 20,
            nameTextStyle: { color: '#8888a0', fontSize: 10 },
            axisLine: { lineStyle: { color: '#5a5a7a' } },
            axisLabel: { color: '#8888a0', formatter: v => v.toFixed(1), fontSize: 9 },
            splitLine: { lineStyle: { color: '#2a2a3d', type: 'dashed' } }
        },
        yAxis: {
            type: 'value',
            min: 0,
            max: 0.9,
            interval: 0.1,
            name: 'y',
            nameLocation: 'end',
            nameGap: 25,
            nameTextStyle: { color: '#8888a0', fontSize: 10 },
            axisLine: { lineStyle: { color: '#5a5a7a' } },
            axisLabel: { color: '#8888a0', formatter: v => v.toFixed(1), fontSize: 9 },
            splitLine: { lineStyle: { color: '#2a2a3d', type: 'dashed' } }
        },
        series: [
            {
                name: '光谱轨迹',
                type: 'line',
                data: locusData,
                lineStyle: { color: '#ffffff', width: 1.5 },
                symbol: 'none',
                z: 1
            },
            {
                name: 'D65',
                type: 'scatter',
                data: [[0.3127, 0.3290]],
                symbol: 'circle',
                symbolSize: 5,
                itemStyle: { color: '#ffffff', opacity: 0.4 },
                z: 2
            },
            // 动态添加参考色域
            ...referenceGamutSeries
        ]
    };
}

/**
 * 更新 CIE 对比图表
 */
function updateCieComparisonChart(data) {
    if (!comparisonCieChart) {
        initCieComparisonChart();
    }

    // 清空旧数据
    comparisonCieChart.clear();

    if (!data.gamut_data || data.gamut_data.length === 0) {
        // 没有数据时只显示基础配置
        comparisonCieChart.setOption(getBaseCieOption());
        comparisonCieChart.resize();
        return;
    }

    // 色域三角形连线
    const gamutSeries = data.gamut_data.map(gamut => {
        const triangle = gamut.triangle;
        const triangleData = [
            triangle.red,
            triangle.green,
            triangle.blue,
            triangle.red
        ];

        return {
            name: gamut.name,  // 使用完整名称
            type: 'line',
            data: triangleData,
            lineStyle: { color: gamut.color, width: 2, opacity: 0.85 },
            symbol: 'circle',
            symbolSize: 8,
            itemStyle: { color: gamut.color, borderColor: '#ffffff', borderWidth: 1.5 },
            z: 10
        };
    });

    // 白点
    const whitePointSeries = data.gamut_data.map(gamut => {
        const wp = gamut.white_point;
        return {
            name: `${gamut.name} 白点`,  // 使用完整名称
            type: 'scatter',
            data: wp ? [{ value: wp, name: `${gamut.name} 白点` }] : [],
            symbol: 'diamond',
            symbolSize: 12,
            itemStyle: { color: gamut.color, borderColor: '#ffffff', borderWidth: 1.5 },
            z: 11
        };
    });

    const baseOption = getBaseCieOption();
    const allSeries = [...baseOption.series, ...gamutSeries, ...whitePointSeries];

    comparisonCieChart.setOption({
        ...baseOption,
        series: allSeries
    });
    comparisonCieChart.resize();
}

/**
 * 初始化 Gamma 对比图表
 */
function initGammaComparisonChart() {
    const chartDom = document.getElementById('gamma-chart');
    if (!chartDom) return;

    comparisonGammaChart = echarts.init(chartDom, null, {
        renderer: 'canvas',
        devicePixelRatio: window.devicePixelRatio || 2
    });

    const baseOption = getBaseGammaOption();
    comparisonGammaChart.setOption(baseOption);

    window.addEventListener('resize', function() {
        if (comparisonGammaChart) {
            comparisonGammaChart.resize();
        }
    });
}

/**
 * 获取基础 Gamma 图表配置
 */
function getBaseGammaOption() {
    // 构建参考曲线系列（根据选中的预设）
    const referenceGammaSeries = [];
    selectedGammas.forEach(name => {
        const curveData = generateComparisonGammaCurveData(name);
        const color = COMPARISON_GAMMA_COLORS[name] || '#8888a0';
        let curveName = name;
        if (['1.8', '2.0', '2.2', '2.4', '2.6'].includes(name)) {
            curveName = `γ${name}`;
        }

        referenceGammaSeries.push({
            name: curveName,
            type: 'line',
            data: curveData,
            lineStyle: {
                color: color,
                width: 1,
                type: 'dashed',
                opacity: 0.5
            },
            symbol: 'none',
            z: 1
        });
    });

    return {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'item',
            formatter: function(params) {
                return t('{name}<br/>输入: {v0}%<br/>输出: {v1}%', {name: params.name, v0: params.value[0], v1: params.value[1].toFixed(1)});
            },
            backgroundColor: '#1e1e30',
            borderColor: '#3a3a50',
            textStyle: { color: '#ffffff', fontSize: 11 }
        },
        grid: {
            left: 35,
            right: 15,
            top: 10,
            bottom: 25,
            containLabel: false
        },
        xAxis: {
            type: 'value',
            min: 0,
            max: 100,
            name: '输入 (%)',
            nameLocation: 'end',
            nameGap: 20,
            nameTextStyle: { color: '#8888a0', fontSize: 10 },
            axisLine: { lineStyle: { color: '#5a5a7a' } },
            axisLabel: { color: '#8888a0', fontSize: 9 },
            splitLine: { lineStyle: { color: '#2a2a3d', type: 'dashed' } }
        },
        yAxis: {
            type: 'value',
            min: 0,
            max: 100,
            name: '输出 (%)',
            nameLocation: 'end',
            nameGap: 25,
            nameTextStyle: { color: '#8888a0', fontSize: 10 },
            axisLine: { lineStyle: { color: '#5a5a7a' } },
            axisLabel: { color: '#8888a0', fontSize: 9 },
            splitLine: { lineStyle: { color: '#2a2a3d', type: 'dashed' } }
        },
        series: referenceGammaSeries
    };
}

/**
 * 更新 Gamma 对比图表
 */
function updateGammaComparisonChart(data) {
    if (!comparisonGammaChart) {
        initGammaComparisonChart();
    }

    // 清空旧数据
    comparisonGammaChart.clear();

    if (!data.gamma_data || data.gamma_data.length === 0) {
        // 没有数据时只显示基础配置
        comparisonGammaChart.setOption(getBaseGammaOption());
        comparisonGammaChart.resize();
        return;
    }

    // Gamma 曲线连线
    const gammaSeries = data.gamma_data.map(gamma => {
        const curveData = gamma.curve.map(point => [point.input, point.normalizedY]);
        return {
            name: gamma.name,  // 使用完整名称
            type: 'line',
            data: curveData,
            lineStyle: { color: gamma.color, width: 2, opacity: 0.85 },
            symbol: 'circle',
            symbolSize: 4,
            itemStyle: { color: gamma.color },
            z: 10
        };
    });

    const baseOption = getBaseGammaOption();
    const allSeries = [...baseOption.series, ...gammaSeries];

    comparisonGammaChart.setOption({
        ...baseOption,
        series: allSeries
    });
    comparisonGammaChart.resize();
}

/**
 * 更新对比表格（概览）
 */
function updateComparisonTable(data) {
    const tbody = document.getElementById('table-body');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (!data.summary_table || data.summary_table.length === 0) return;

    data.summary_table.forEach(row => {
        const tr = document.createElement('tr');

        tr.innerHTML = `
            <td class="col-color"><span class="color-dot" style="background-color: ${row.color}"></span></td>
            <td class="col-name">${row.name}</td>
            <td class="col-peak numeric-value ${row.bestContrast ? 'best-value' : ''}">${formatVal(row.peakLuminance, 1)}</td>
            <td class="col-black numeric-value">${formatVal(row.blackLuminance, 4)}</td>
            <td class="col-contrast numeric-value ${row.bestContrast ? 'best-value' : ''}">${formatVal(row.contrastRatio, 0, ':1')}</td>
            <td class="col-cct numeric-value">${formatVal(row.whiteCCT, 0, 'K')}</td>
            <td class="col-gamma numeric-value ${row.bestGamma ? 'best-value' : ''}">${formatVal(row.gamma, 2)}</td>
            <td class="col-srgb">${renderCoverageBar(row.gamutCoverage?.sRGB, row.bestSRGB)}</td>
            <td class="col-p3">${renderCoverageBar(row.gamutCoverage?.DCI_P3)}</td>
            <td class="col-adobe">${renderCoverageBar(row.gamutCoverage?.AdobeRGB)}</td>
            <td class="col-2020">${renderCoverageBar(row.gamutCoverage?.Rec2020)}</td>
        `;

        tbody.appendChild(tr);
    });
}

/**
 * 格式化数值
 */
function formatVal(value, decimals = 2, suffix = '') {
    if (value === null || value === undefined) return '--';
    return value.toFixed(decimals) + suffix;
}

/**
 * 渲染覆盖率进度条
 */
function renderCoverageBar(coverage, isBest = false) {
    if (coverage === null || coverage === undefined) return '<span class="no-data">--</span>';

    const percentage = Math.min(coverage, 100);
    const color = isBest ? '#10b981' : '#3b82f6';

    return `
        <div class="coverage-bar">
            <div class="coverage-progress">
                <div class="coverage-fill" style="width: ${percentage}%; background-color: ${color}"></div>
            </div>
            <span class="numeric-value ${isBest ? 'best-value' : ''}">${coverage.toFixed(1)}%</span>
        </div>
    `;
}

/**
 * 更新详细色块表格
 */
function updateDetailTable(data) {
    const thead = document.getElementById('detail-table-head');
    const tbody = document.getElementById('detail-table-body');

    if (!thead || !tbody || !data.detail_data) return;

    // 清空
    thead.innerHTML = '';
    tbody.innerHTML = '';

    const datasets = data.detail_data;
    if (!datasets || datasets.length === 0) return;

    // 判断是否是两个数据对比
    const isTwoDatasets = datasets.length === 2;

    // 构建表头
    let headerHtml = '<tr><th class="color-row-header">色块</th>';
    datasets.forEach(ds => {
        headerHtml += `<th><span class="data-group-color" style="background-color: ${ds.color}"></span>${ds.shortName}</th>`;
    });
    // 如果是两个数据对比，增加偏差对比列
    if (isTwoDatasets) {
        headerHtml += `<th class="delta-compare-header">ΔE2000</th>`;
    }
    headerHtml += '</tr>';
    thead.innerHTML = headerHtml;

    // 色块颜色映射
    const patchTypes = ['red', 'green', 'blue', 'white', 'black'];
    const colorNames = {
        'red': '红',
        'green': '绿',
        'blue': '蓝',
        'white': '白',
        'black': '黑'
    };

    // 按色块类型分组显示
    patchTypes.forEach(patchType => {
        const colorName = colorNames[patchType] || patchType;

        // xyY + ΔE 行（合并显示）
        const row = document.createElement('tr');
        
        // 第一列：色块名称和颜色方块
        let bgColor;
        if (patchType === 'red') bgColor = 'rgb(255, 0, 0)';
        else if (patchType === 'green') bgColor = 'rgb(0, 255, 0)';
        else if (patchType === 'blue') bgColor = 'rgb(0, 0, 255)';
        else if (patchType === 'white') bgColor = 'rgb(255, 255, 255)';
        else if (patchType === 'black') bgColor = 'rgb(0, 0, 0)';
        
        const darkPatchClass = (patchType === 'black' || patchType === 'blue') ? 'dark-patch' : '';
        
        row.innerHTML = `<td class="color-row-header"><div class="patch-row-title"><span class="patch-color-square ${darkPatchClass}" style="background-color: ${bgColor}"></span>${colorName}</div></td>`;

        // 各数据集的 xyY + ΔE 值
        datasets.forEach(ds => {
            const patchData = ds.gamut?.[patchType];
            const xyY = patchData?.xyY;
            const de = ds.deltaE?.[patchType];

            // 构建单元格内容：xyY值 + ΔE值
            let cellContent = '';
            if (xyY) {
                cellContent = `<div class="xyY-value">${xyY[0].toFixed(4)}, ${xyY[1].toFixed(4)}, ${xyY[2].toFixed(1)}</div>`;
                if (de !== null && de !== undefined) {
                    const deClass = de < 2 ? 'delta-e-good' : (de < 5 ? 'delta-e-warning' : 'delta-e-bad');
                    cellContent += `<div class="delta-e-inline ${deClass}">ΔE: ${de.toFixed(2)}</div>`;
                }
            } else {
                cellContent = '<span class="no-data">--</span>';
            }

            row.innerHTML += `<td>${cellContent}</td>`;
        });

        // 如果是两个数据对比，计算并显示偏差对比
        if (isTwoDatasets) {
            const xyY1 = datasets[0]?.gamut?.[patchType]?.xyY;
            const xyY2 = datasets[1]?.gamut?.[patchType]?.xyY;
            
            if (xyY1 && xyY2) {
                // 计算两个测量点之间的 Delta E2000
                const deltaEBetween = calculateDeltaEBetween(xyY1, xyY2);
                const deClass = deltaEBetween < 2 ? 'delta-e-good' : (deltaEBetween < 5 ? 'delta-e-warning' : 'delta-e-bad');
                row.innerHTML += `<td class="delta-compare-cell ${deClass}"><span class="delta-compare-value">${deltaEBetween.toFixed(2)}</span></td>`;
            } else {
                row.innerHTML += `<td class="delta-compare-cell"><span class="no-data">--</span></td>`;
            }
        }

        tbody.appendChild(row);
    });

    // 白点 CCT 行
    const cctRow = document.createElement('tr');
    cctRow.innerHTML = `<td class="color-row-header">白点 CCT</td>`;
    datasets.forEach(ds => {
        const cct = ds.whiteCCT;
        cctRow.innerHTML += `<td class="numeric-value">${cct ? cct + ' K' : '--'}</td>`;
    });
    if (isTwoDatasets) {
        const cct1 = datasets[0]?.whiteCCT;
        const cct2 = datasets[1]?.whiteCCT;
        if (cct1 && cct2) {
            const cctDiff = Math.abs(cct1 - cct2);
            const cctClass = cctDiff < 100 ? 'delta-e-good' : (cctDiff < 500 ? 'delta-e-warning' : 'delta-e-bad');
            cctRow.innerHTML += `<td class="delta-compare-cell ${cctClass}"><span class="delta-compare-value">${cctDiff} K</span></td>`;
        } else {
            cctRow.innerHTML += `<td class="delta-compare-cell"><span class="no-data">--</span></td>`;
        }
    }
    tbody.appendChild(cctRow);

    // 平均 Delta E 行
    if (datasets.some(ds => ds.deltaE && ds.deltaE.avg !== undefined)) {
        const avgDeltaERow = document.createElement('tr');
        avgDeltaERow.innerHTML = `<td class="color-row-header">平均 ΔE</td>`;
        datasets.forEach(ds => {
            const avgDe = ds.deltaE?.avg;
            if (avgDe !== null && avgDe !== undefined) {
                const className = avgDe < 2 ? 'delta-e-good' : (avgDe < 5 ? 'delta-e-warning' : 'delta-e-bad');
                avgDeltaERow.innerHTML += `<td class="numeric-value ${className}">${avgDe.toFixed(2)}</td>`;
            } else {
                avgDeltaERow.innerHTML += '<td class="no-data">--</td>';
            }
        });
        if (isTwoDatasets) {
            const avgDe1 = datasets[0]?.deltaE?.avg;
            const avgDe2 = datasets[1]?.deltaE?.avg;
            if (avgDe1 && avgDe2) {
                const avgDiff = Math.abs(avgDe1 - avgDe2);
                avgDeltaERow.innerHTML += `<td class="delta-compare-cell"><span class="delta-compare-value">${avgDiff.toFixed(2)}</span></td>`;
            } else {
                avgDeltaERow.innerHTML += `<td class="delta-compare-cell"><span class="no-data">--</span></td>`;
            }
        }
        tbody.appendChild(avgDeltaERow);
    }

    // Gamma 数据（灰阶）
    if (datasets.some(ds => ds.gammaPoints && ds.gammaPoints.length > 0)) {
        // 灰阶分隔行
        const separatorRow = document.createElement('tr');
        separatorRow.className = 'data-group-header';
        const colCount = datasets.length + (isTwoDatasets ? 2 : 1);
        separatorRow.innerHTML = `<td colspan="${colCount}">灰阶测量</td>`;
        tbody.appendChild(separatorRow);

        // 平均 Gamma 值行
        const gammaRow = document.createElement('tr');
        gammaRow.innerHTML = `<td class="color-row-header">平均 Gamma</td>`;
        datasets.forEach(ds => {
            const gamma = ds.avgGamma;
            const gammaClass = gamma ? (Math.abs(gamma - 2.2) < 0.1 ? 'delta-e-good' : (Math.abs(gamma - 2.2) < 0.2 ? 'delta-e-warning' : 'delta-e-bad')) : '';
            gammaRow.innerHTML += `<td class="numeric-value ${gammaClass}">${gamma ? gamma.toFixed(2) : '--'}</td>`;
        });
        if (isTwoDatasets) {
            const gamma1 = datasets[0]?.avgGamma;
            const gamma2 = datasets[1]?.avgGamma;
            if (gamma1 && gamma2) {
                const gammaDiff = Math.abs(gamma1 - gamma2);
                const gammaDiffClass = gammaDiff < 0.05 ? 'delta-e-good' : (gammaDiff < 0.1 ? 'delta-e-warning' : 'delta-e-bad');
                gammaRow.innerHTML += `<td class="delta-compare-cell ${gammaDiffClass}"><span class="delta-compare-value">${gammaDiff.toFixed(3)}</span></td>`;
            } else {
                gammaRow.innerHTML += `<td class="delta-compare-cell"><span class="no-data">--</span></td>`;
            }
        }
        tbody.appendChild(gammaRow);

        // 显示完整的灰阶级别测量数据
        // 找出所有数据集的灰阶级别（合并）
        const allInputLevels = [];
        datasets.forEach(ds => {
            if (ds.gammaPoints) {
                ds.gammaPoints.forEach(p => {
                    if (!allInputLevels.includes(p.input)) {
                        allInputLevels.push(p.input);
                    }
                });
            }
        });
        // 按输入值排序
        allInputLevels.sort((a, b) => a - b);

        // 为每个灰阶级别创建一行
        allInputLevels.forEach(inputLevel => {
            const grayRow = document.createElement('tr');

            // 行标题：显示灰阶级别
            let rowTitle = `${inputLevel}%`;
            // 计算对应的 RGB 值（用于显示色块）
            const rgbValue = Math.round(inputLevel * 255 / 100);
            const isDarkPatch = inputLevel < 20;
            const darkPatchClass = isDarkPatch ? 'dark-patch' : '';

            rowTitle = `<div class="patch-row-title"><span class="patch-color-square ${darkPatchClass}" style="background-color: rgb(${rgbValue}, ${rgbValue}, ${rgbValue})"></span>${inputLevel}%</div>`;

            grayRow.innerHTML = `<td class="color-row-header">${rowTitle}</td>`;

            // 各数据集的 Y 值
            datasets.forEach(ds => {
                const point = ds.gammaPoints?.find(p => p.input === inputLevel);
                if (point && point.Y) {
                    // 显示 Y 值（亮度）
                    grayRow.innerHTML += `<td class="numeric-value">${point.Y.toFixed(2)}</td>`;
                } else {
                    grayRow.innerHTML += '<td class="no-data">--</td>';
                }
            });

            // 如果是两个数据对比，显示 Y 值差异
            if (isTwoDatasets) {
                const point1 = datasets[0]?.gammaPoints?.find(p => p.input === inputLevel);
                const point2 = datasets[1]?.gammaPoints?.find(p => p.input === inputLevel);
                if (point1?.Y && point2?.Y) {
                    const yDiff = Math.abs(point1.Y - point2.Y);
                    const yDiffPercent = (yDiff / Math.max(point1.Y, point2.Y) * 100).toFixed(1);
                    const yDiffClass = yDiffPercent < 1 ? 'delta-e-good' : (yDiffPercent < 5 ? 'delta-e-warning' : 'delta-e-bad');
                    grayRow.innerHTML += `<td class="delta-compare-cell ${yDiffClass}"><span class="delta-compare-value">${yDiff.toFixed(2)}</span></td>`;
                } else {
                    grayRow.innerHTML += `<td class="delta-compare-cell"><span class="no-data">--</span></td>`;
                }
            }

            tbody.appendChild(grayRow);
        });
    }
}

/**
 * 计算两个 xyY 点之间的 Delta E2000
 */
function calculateDeltaEBetween(xyY1, xyY2) {
    // 简化的 Delta E 计算方法
    // 将 xyY 转换为 Lab 空间，然后计算 Delta E

    // 假设白点为 D65
    const Xn = 95.047, Yn = 100.0, Zn = 108.883;

    // xyY 转 XYZ
    function xyYtoXYZ(xyY) {
        const x = xyY[0], y = xyY[1], Y = xyY[2];
        if (y === 0) return [0, Y, 0];
        const X = (x / y) * Y;
        const Z = ((1 - x - y) / y) * Y;
        return [X, Y, Z];
    }

    // XYZ 转 Lab
    function XYZtoLab(XYZ) {
        const X = XYZ[0], Y = XYZ[1], Z = XYZ[2];

        const f = t => t > 0.008856 ? Math.pow(t, 1/3) : (903.3 * t + 16) / 116;

        const L = 116 * f(Y / Yn) - 16;
        const a = 500 * (f(X / Xn) - f(Y / Yn));
        const b = 200 * (f(Y / Yn) - f(Z / Zn));

        return [L, a, b];
    }

    // 计算 Delta E2000（简化版）
    function deltaE2000(Lab1, Lab2) {
        const L1 = Lab1[0], a1 = Lab1[1], b1 = Lab1[2];
        const L2 = Lab2[0], a2 = Lab2[1], b2 = Lab2[2];

        const C1 = Math.sqrt(a1*a1 + b1*b1);
        const C2 = Math.sqrt(a2*a2 + b2*b2);
        const Cavg = (C1 + C2) / 2;

        const G = 0.5 * (1 - Math.sqrt(Math.pow(Cavg, 7) / (Math.pow(Cavg, 7) + Math.pow(25, 7))));

        const a1p = (1 + G) * a1;
        const a2p = (1 + G) * a2;

        const C1p = Math.sqrt(a1p*a1p + b1*b1);
        const C2p = Math.sqrt(a2p*a2p + b2*b2);

        const h1p = Math.atan2(b1, a1p) * 180 / Math.PI;
        const h2p = Math.atan2(b2, a2p) * 180 / Math.PI;

        const dLp = L2 - L1;
        const dCp = C2p - C1p;

        let dhp;
        if (C1p * C2p === 0) {
            dhp = 0;
        } else if (Math.abs(h2p - h1p) <= 180) {
            dhp = h2p - h1p;
        } else if (h2p - h1p > 180) {
            dhp = h2p - h1p - 360;
        } else {
            dhp = h2p - h1p + 360;
        }

        const dHp = 2 * Math.sqrt(C1p * C2p) * Math.sin(dhp * Math.PI / 360);

        const Lavgp = (L1 + L2) / 2;
        const Cavgp = (C1p + C2p) / 2;

        let Havgp;
        if (C1p * C2p === 0) {
            Havgp = h1p + h2p;
        } else if (Math.abs(h1p - h2p) <= 180) {
            Havgp = (h1p + h2p) / 2;
        } else if (h1p + h2p < 360) {
            Havgp = (h1p + h2p + 360) / 2;
        } else {
            Havgp = (h1p + h2p - 360) / 2;
        }

        const T = 1 - 0.17 * Math.cos((Havgp - 30) * Math.PI / 180)
                  + 0.24 * Math.cos(2 * Havgp * Math.PI / 180)
                  + 0.32 * Math.cos((3 * Havgp + 6) * Math.PI / 180)
                  - 0.20 * Math.cos((4 * Havgp - 63) * Math.PI / 180);

        const SL = 1 + (0.015 * Math.pow(Lavgp - 50, 2)) / Math.sqrt(20 + Math.pow(Lavgp - 50, 2));
        const SC = 1 + 0.045 * Cavgp;
        const SH = 1 + 0.015 * Cavgp * T;

        const dtheta = 30 * Math.exp(-Math.pow((Havgp - 275) / 25, 2));
        const RC = 2 * Math.sqrt(Math.pow(Cavgp, 7) / (Math.pow(Cavgp, 7) + Math.pow(25, 7)));
        const RT = -RC * Math.sin(2 * dtheta * Math.PI / 180);

        const dE = Math.sqrt(
            Math.pow(dLp / SL, 2) +
            Math.pow(dCp / SC, 2) +
            Math.pow(dHp / SH, 2) +
            RT * (dCp / SC) * (dHp / SH)
        );

        return dE;
    }

    try {
        const XYZ1 = xyYtoXYZ(xyY1);
        const XYZ2 = xyYtoXYZ(xyY2);
        const Lab1 = XYZtoLab(XYZ1);
        const Lab2 = XYZtoLab(XYZ2);
        return deltaE2000(Lab1, Lab2);
    } catch (e) {
        // 简化计算：欧氏距离
        const dx = xyY1[0] - xyY2[0];
        const dy = xyY1[1] - xyY2[1];
        const dY = xyY1[2] - xyY2[2];
        return Math.sqrt(dx*dx * 10000 + dy*dy * 10000 + dY*dY / 100);
    }
}

/**
 * 更新图表图例
 */
function updateChartLegends(data) {
    const cieLegend = document.getElementById('cie-legend');
    if (cieLegend && data.gamut_data) {
        cieLegend.innerHTML = data.gamut_data.map(g => `
            <div class="legend-item" title="${g.name}">
                <span class="legend-color" style="background-color: ${g.color}"></span>
            </div>
        `).join('');
    }

    const gammaLegend = document.getElementById('gamma-legend');
    if (gammaLegend && data.gamma_data) {
        gammaLegend.innerHTML = data.gamma_data.map(g => `
            <div class="legend-item" title="${g.name} γ=${g.avg_gamma || '--'}">
                <span class="legend-color" style="background-color: ${g.color}"></span>
            </div>
        `).join('');
    }
}

/**
 * 执行对比分析
 */
function performComparison() {
    if (selectedMeasurementIds.length < 1) return;

    const idsJson = JSON.stringify(selectedMeasurementIds);
    backend.load_measurements_for_comparison(idsJson);

    console.log('[Comparison] 开始查看:', selectedMeasurementIds);
}

/**
 * 刷新数据列表
 */
function refreshMeasurementList() {
    if (backend) {
        backend.load_measurement_list();
    }
}

/**
 * 初始化预设选择面板
 */
function initPresetPanels() {
    // 色域预设面板
    const gamutPresetToggle = document.getElementById('gamut-preset-toggle');
    const gamutPresetPanel = document.getElementById('gamut-preset-panel');

    if (gamutPresetToggle && gamutPresetPanel) {
        gamutPresetToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            gamutPresetPanel.classList.toggle('show');
            gamutPresetToggle.classList.toggle('active');

            // 关闭Gamma预设面板
            const gammaPanel = document.getElementById('gamma-preset-panel');
            const gammaToggle = document.getElementById('gamma-preset-toggle');
            if (gammaPanel) gammaPanel.classList.remove('show');
            if (gammaToggle) gammaToggle.classList.remove('active');
        });

        // 绑定checkbox变化事件
        gamutPresetPanel.querySelectorAll('input[name="gamut-preset"]').forEach(checkbox => {
            checkbox.addEventListener('change', function() {
                selectedGamuts = Array.from(gamutPresetPanel.querySelectorAll('input[name="gamut-preset"]:checked'))
                    .map(cb => cb.value);
                updateChartsWithPresets();
            });
        });
    }

    // Gamma预设面板
    const gammaPresetToggle = document.getElementById('gamma-preset-toggle');
    const gammaPresetPanel = document.getElementById('gamma-preset-panel');

    if (gammaPresetToggle && gammaPresetPanel) {
        gammaPresetToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            gammaPresetPanel.classList.toggle('show');
            gammaPresetToggle.classList.toggle('active');

            // 关闭色域预设面板
            if (gamutPresetPanel) gamutPresetPanel.classList.remove('show');
            if (gamutPresetToggle) gamutPresetToggle.classList.remove('active');
        });

        // 绑定checkbox变化事件
        gammaPresetPanel.querySelectorAll('input[name="gamma-preset"]').forEach(checkbox => {
            checkbox.addEventListener('change', function() {
                selectedGammas = Array.from(gammaPresetPanel.querySelectorAll('input[name="gamma-preset"]:checked'))
                    .map(cb => cb.value);
                updateChartsWithPresets();
            });
        });
    }

    // 点击其他区域关闭面板
    document.addEventListener('click', function(e) {
        if (!gamutPresetPanel?.contains(e.target) && !gamutPresetToggle?.contains(e.target)) {
            if (gamutPresetPanel) gamutPresetPanel.classList.remove('show');
            if (gamutPresetToggle) gamutPresetToggle.classList.remove('active');
        }
        if (!gammaPresetPanel?.contains(e.target) && !gammaPresetToggle?.contains(e.target)) {
            if (gammaPresetPanel) gammaPresetPanel.classList.remove('show');
            if (gammaPresetToggle) gammaPresetToggle.classList.remove('active');
        }
    });
}

/**
 * 根据预设更新图表
 */
function updateChartsWithPresets() {
    // 更新CIE图表的基础配置
    if (comparisonCieChart) {
        comparisonCieChart.setOption(getBaseCieOption(), true);
        // 如果有对比数据，重新添加测量数据
        if (currentComparisonData) {
            updateCieComparisonChart(currentComparisonData);
        }
    }

    // 更新Gamma图表的基础配置
    if (comparisonGammaChart) {
        comparisonGammaChart.setOption(getBaseGammaOption(), true);
        // 如果有对比数据，重新添加测量数据
        if (currentComparisonData) {
            updateGammaComparisonChart(currentComparisonData);
        }
    }

    console.log('[Comparison] 预设已更新:', { gamuts: selectedGamuts, gammas: selectedGammas });
}

// ========== 导出功能 ==========

/**
 * 显示提示消息（替代 alert）
 */
function showToast(message, type = 'info') {
    // 移除已有的提示
    const existingToast = document.getElementById('toast-message');
    if (existingToast) {
        existingToast.remove();
    }

    // 创建提示元素
    const toast = document.createElement('div');
    toast.id = 'toast-message';
    toast.style.cssText = `
        position: fixed;
        top: 50px;
        left: 50%;
        transform: translateX(-50%);
        padding: 12px 24px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 500;
        z-index: 9999;
        animation: fadeInOut 3s ease forwards;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    `;

    if (type === 'error') {
        toast.style.backgroundColor = '#ef4444';
        toast.style.color = '#ffffff';
    } else if (type === 'success') {
        toast.style.backgroundColor = '#10b981';
        toast.style.color = '#ffffff';
    } else {
        toast.style.backgroundColor = '#3b82f6';
        toast.style.color = '#ffffff';
    }

    toast.textContent = message;
    document.body.appendChild(toast);

    // 3秒后自动消失
    setTimeout(() => {
        toast.remove();
    }, 3000);
}

/**
 * 导出对比报告为 HTML 文件
 */
function exportToHtml() {
    console.log('[Comparison] 导出按钮被点击');

    if (!currentComparisonData) {
        showToast('请先选择数据并点击对比查看后再导出', 'error');
        console.log('[Comparison] 无对比数据，无法导出');
        return;
    }

    if (!backend) {
        showToast('后端通信未初始化', 'error');
        console.log('[Comparison] 后端未初始化');
        return;
    }

    console.log('[Comparison] 开始导出，数据:', currentComparisonData);

    // 获取图表的静态图片（使用白色背景适配样式）
    let cieChartImage = '';
    let gammaChartImage = '';

    try {
        if (comparisonCieChart) {
            // 临时切换为白色背景样式
            const originalOption = comparisonCieChart.getOption();
            applyWhiteThemeToCieChart(comparisonCieChart);

            cieChartImage = comparisonCieChart.getDataURL({
                type: 'png',
                pixelRatio: 3,
                backgroundColor: '#ffffff'
            });

            // 恢复原样式
            comparisonCieChart.setOption(originalOption, true);
            console.log('[Comparison] CIE 图表图片已生成');
        }

        if (comparisonGammaChart) {
            // 临时切换为白色背景样式
            const originalOption = comparisonGammaChart.getOption();
            applyWhiteThemeToGammaChart(comparisonGammaChart);

            gammaChartImage = comparisonGammaChart.getDataURL({
                type: 'png',
                pixelRatio: 3,
                backgroundColor: '#ffffff'
            });

            // 恢复原样式
            comparisonGammaChart.setOption(originalOption, true);
            console.log('[Comparison] Gamma 图表图片已生成');
        }
    } catch (e) {
        console.error('[Comparison] 图表图片生成失败:', e);
    }

    // 生成 HTML 内容
    const htmlContent = generateExportHtmlContent(currentComparisonData, cieChartImage, gammaChartImage);
    console.log('[Comparison] HTML 内容已生成，长度:', htmlContent.length);

    // 生成默认文件名
    const timestamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-');
    const defaultFilename = `comparison-report-${timestamp}.html`;

    // 调用后端保存文件（会弹出保存对话框）
    showToast('正在准备导出...', 'info');

    backend.save_html_file(htmlContent, defaultFilename, function(resultJson) {
        try {
            const result = JSON.parse(resultJson);
            if (result.success) {
                showToast('报告已保存: ' + result.filepath, 'success');
                console.log('[Comparison] 已保存报告:', result.filepath);
            } else {
                if (result.message !== '用户取消保存') {
                    showToast('保存失败: ' + result.message, 'error');
                }
                console.log('[Comparison] 保存结果:', result.message);
            }
        } catch (e) {
            console.error('[Comparison] 解析保存结果失败:', e);
            showToast('保存失败', 'error');
        }
    });
}

/**
 * 为 CIE 图表应用白色主题（用于导出）
 */
function applyWhiteThemeToCieChart(chart) {
    const option = chart.getOption();

    // 白色背景适配的颜色
    const whiteThemeColors = {
        axisLine: '#333333',
        axisLabel: '#555555',
        splitLine: '#e0e0e0',
        spectralLocus: '#000000',  // 马蹄图变为黑色
        d65: '#666666'
    };

    // 更新坐标轴样式
    if (option.xAxis && option.xAxis[0]) {
        option.xAxis[0].axisLine = { lineStyle: { color: whiteThemeColors.axisLine } };
        option.xAxis[0].axisLabel = { color: whiteThemeColors.axisLabel, fontSize: 10 };
        option.xAxis[0].splitLine = { lineStyle: { color: whiteThemeColors.splitLine, type: 'dashed' } };
        option.xAxis[0].nameTextStyle = { color: whiteThemeColors.axisLabel, fontSize: 10 };
    }

    if (option.yAxis && option.yAxis[0]) {
        option.yAxis[0].axisLine = { lineStyle: { color: whiteThemeColors.axisLine } };
        option.yAxis[0].axisLabel = { color: whiteThemeColors.axisLabel, fontSize: 10 };
        option.yAxis[0].splitLine = { lineStyle: { color: whiteThemeColors.splitLine, type: 'dashed' } };
        option.yAxis[0].nameTextStyle = { color: whiteThemeColors.axisLabel, fontSize: 10 };
    }

    // 更新系列样式
    if (option.series) {
        option.series.forEach((series, idx) => {
            // 光谱轨迹（马蹄图）- 变为黑色
            if (series.name === '光谱轨迹' || series.name === 'CIE1931 Spectral Locus') {
                series.lineStyle = { color: whiteThemeColors.spectralLocus, width: 1.5 };
            }
            // D65 白点
            if (series.name === 'D65') {
                series.itemStyle = { color: whiteThemeColors.d65, opacity: 0.6 };
            }
        });
    }

    // 更新提示框样式
    if (option.tooltip) {
        option.tooltip[0] = {
            ...option.tooltip[0],
            backgroundColor: '#ffffff',
            borderColor: '#cccccc',
            textStyle: { color: '#333333', fontSize: 11 }
        };
    }

    chart.setOption(option, true);
}

/**
 * 为 Gamma 图表应用白色主题（用于导出）
 */
function applyWhiteThemeToGammaChart(chart) {
    const option = chart.getOption();

    // 白色背景适配的颜色
    const whiteThemeColors = {
        axisLine: '#333333',
        axisLabel: '#555555',
        splitLine: '#e0e0e0'
    };

    // 更新坐标轴样式
    if (option.xAxis && option.xAxis[0]) {
        option.xAxis[0].axisLine = { lineStyle: { color: whiteThemeColors.axisLine } };
        option.xAxis[0].axisLabel = { color: whiteThemeColors.axisLabel, fontSize: 10 };
        option.xAxis[0].splitLine = { lineStyle: { color: whiteThemeColors.splitLine, type: 'dashed' } };
        option.xAxis[0].nameTextStyle = { color: whiteThemeColors.axisLabel, fontSize: 10 };
    }

    if (option.yAxis && option.yAxis[0]) {
        option.yAxis[0].axisLine = { lineStyle: { color: whiteThemeColors.axisLine } };
        option.yAxis[0].axisLabel = { color: whiteThemeColors.axisLabel, fontSize: 10 };
        option.yAxis[0].splitLine = { lineStyle: { color: whiteThemeColors.splitLine, type: 'dashed' } };
        option.yAxis[0].nameTextStyle = { color: whiteThemeColors.axisLabel, fontSize: 10 };
    }

    // 更新提示框样式
    if (option.tooltip) {
        option.tooltip[0] = {
            ...option.tooltip[0],
            backgroundColor: '#ffffff',
            borderColor: '#cccccc',
            textStyle: { color: '#333333', fontSize: 11 }
        };
    }

    chart.setOption(option, true);
}

/**
 * 生成导出 HTML 文件的内容
 * @param {Object} data - 对比数据
 * @param {string} cieChartImage - CIE 色域图图片 URL (base64)
 * @param {string} gammaChartImage - Gamma 曲线图图片 URL (base64)
 * @returns {string} - 完整的 HTML 文件内容
 */
function generateExportHtmlContent(data, cieChartImage, gammaChartImage) {
    // 格式化时间戳
    const now = new Date();
    const formattedDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

    // 构建汇总表格 HTML
    const summaryTableHtml = generateSummaryTableHtml(data);

    // 构建详细表格 HTML
    const detailTableHtml = generateDetailTableHtml(data);

    // 构建数据名称列表
    const dataNamesHtml = data.summary_table?.map(row =>
        `<span style="display: inline-block; margin: 2px 4px; padding: 2px 8px; background: ${row.color}; color: white; border-radius: 3px; font-size: 11px;">${row.name}</span>`
    ).join('') || '';

    // 构建元数据 HTML
    const metadataHtml = generateMetadataHtml(data);

    // 生成完整的 HTML
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Topos Calibrator - 测量数据对比报告</title>
    <style>
        /* 基础样式 */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #ffffff;
            color: #333333;
            font-size: 13px;
            line-height: 1.4;
            padding: 20px;
            max-width: 1200px;
            margin: 0 auto;
        }

        /* 标题 */
        .report-header {
            text-align: center;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }
        
        .report-title {
            font-size: 24px;
            font-weight: 600;
            color: #1a1a2a;
            margin-bottom: 8px;
        }
        
        .report-meta {
            font-size: 12px;
            color: #666666;
        }
        
        .report-data-names {
            margin-top: 12px;
        }

        /* 元数据区域 */
        .metadata-section {
            margin-bottom: 20px;
        }

        .metadata-section-title {
            font-size: 14px;
            font-weight: 600;
            color: #1a1a2a;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 2px solid #e0e0e0;
        }

        /* 元数据卡片 */
        .metadata-card {
            background: linear-gradient(135deg, #f8f9fa 0%, #ffffff 100%);
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 16px 12px;
            margin-bottom: 12px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            position: relative;
            overflow: hidden;
        }

        .metadata-card:last-child {
            margin-bottom: 0;
        }

        /* 数据名称标签 */
        .metadata-data-name {
            position: absolute;
            top: 0;
            left: 0;
            padding: 3px 8px 3px 5px;
            background: linear-gradient(90deg, rgba(59, 130, 246, 0.1), transparent);
            font-size: 10px;
            font-weight: 600;
            color: #333333;
            border-left: 3px solid #3b82f6;
            border-radius: 0 3px 3px 0;
        }

        .metadata-card:first-child {
            padding-top: 20px;
        }

        .metadata-card:first-child .metadata-data-name {
            top: 0;
        }

        .metadata-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px 6px;
        }

        .metadata-item {
            display: flex;
            flex-direction: column;
            gap: 4px;
            padding-left: 8px;
            position: relative;
        }

        .metadata-item::before {
            content: '';
            position: absolute;
            left: 0;
            top: 4px;
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: var(--dot-color, #3b82f6);
        }

        .metadata-label {
            font-size: 9px;
            color: #999999;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 500;
        }

        .metadata-value {
            font-size: 11px;
            color: #333333;
            font-weight: 500;
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
        }

        .metadata-badge {
            display: inline-block;
            padding: 2px 8px;
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            color: white;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }

        /* 图表区域 */
        .charts-section {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .chart-container {
            flex: 1;
            min-width: 0;
        }
        
        .chart-title {
            font-size: 14px;
            font-weight: 600;
            color: #1a1a2a;
            margin-bottom: 10px;
            padding-bottom: 5px;
            border-bottom: 1px solid #e0e0e0;
        }
        
        .chart-image {
            width: 100%;
            max-width: 500px;
            height: auto;
            border: 1px solid #e0e0e0;
            border-radius: 4px;
            background: #ffffff;
        }

        /* 表格区域 */
        .table-section {
            margin-bottom: 25px;
        }
        
        .section-title {
            font-size: 14px;
            font-weight: 600;
            color: #1a1a2a;
            margin-bottom: 10px;
            padding-bottom: 5px;
            border-bottom: 1px solid #e0e0e0;
        }

        /* 表格样式 */
        .data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            background: #ffffff;
        }
        
        .data-table th {
            background-color: #f5f5f7;
            padding: 8px 10px;
            text-align: left;
            font-weight: 600;
            color: #333333;
            border-bottom: 1px solid #e0e0e0;
            white-space: nowrap;
        }
        
        .data-table td {
            padding: 6px 10px;
            color: #333333;
            border-bottom: 1px solid #f0f0f0;
        }
        
        .data-table tr:hover td {
            background-color: #f8f8fa;
        }
        
        /* 颜色标识 */
        .color-dot {
            width: 14px;
            height: 14px;
            border-radius: 3px;
            display: inline-block;
            vertical-align: middle;
        }
        
        /* 数值样式 */
        .numeric-value {
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
        }
        
        .best-value {
            color: #10b981;
            font-weight: 600;
        }
        
        .no-data {
            color: #999999;
            font-style: italic;
        }
        
        /* 覆盖率进度条 */
        .coverage-bar {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .coverage-progress {
            width: 50px;
            height: 6px;
            background-color: #e0e0e0;
            border-radius: 3px;
            overflow: hidden;
        }
        
        .coverage-fill {
            height: 100%;
            border-radius: 3px;
        }
        
        /* Delta E 状态颜色 */
        .delta-e-good { color: #10b981; }
        .delta-e-warning { color: #f59e0b; }
        .delta-e-bad { color: #ef4444; }
        
        /* 色块颜色方块 */
        .patch-color-square {
            width: 16px;
            height: 16px;
            border-radius: 3px;
            display: inline-block;
            vertical-align: middle;
            margin-right: 6px;
            border: 1px solid #ccc;
        }
        
        .patch-row-title {
            display: flex;
            align-items: center;
        }
        
        /* 页脚 */
        .report-footer {
            text-align: center;
            font-size: 11px;
            color: #999999;
            margin-top: 30px;
            padding-top: 15px;
            border-top: 1px solid #e0e0e0;
        }

        /* 详细表格特殊样式 */
        .detail-table td {
            text-align: center;
        }
        
        .detail-table .color-row-header {
            text-align: left;
            background-color: #f8f8fa;
            font-weight: 500;
        }
        
        .data-group-header {
            background-color: #f0f0f2;
            font-weight: 600;
        }
        
        .data-group-header td {
            text-align: left;
            padding: 8px 10px;
        }
        
        .xyY-value {
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 11px;
        }
        
        .delta-e-inline {
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 10px;
            margin-top: 2px;
            opacity: 0.8;
        }
        
        .delta-compare-header {
            background-color: rgba(59, 130, 246, 0.15) !important;
            color: #3b82f6 !important;
            font-weight: 600 !important;
        }
        
        .delta-compare-cell {
            background-color: rgba(59, 130, 246, 0.08);
            border-left: 2px solid #3b82f6 !important;
        }
        
        .delta-compare-value {
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 11px;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <header class="report-header">
        <h1 class="report-title">Topos Calibrator 测量数据对比报告</h1>
        <div class="report-meta">导出时间: ${formattedDate}</div>
        <div class="report-data-names">${dataNamesHtml}</div>
    </header>

    <!-- 文件元数据 -->
    ${metadataHtml}

    <!-- 图表区域 -->
    <section class="charts-section">
        <div class="chart-container">
            <h2 class="chart-title">CIE 1931 色域对比</h2>
            ${cieChartImage ? `<img class="chart-image" src="${cieChartImage}" alt="CIE 1931 色域图">` : '<p class="no-data">无图表数据</p>'}
        </div>
        <div class="chart-container">
            <h2 class="chart-title">Gamma 曲线对比</h2>
            ${gammaChartImage ? `<img class="chart-image" src="${gammaChartImage}" alt="Gamma 曲线图">` : '<p class="no-data">无图表数据</p>'}
        </div>
    </section>

    <!-- 关键参数汇总 -->
    <section class="table-section">
        <h2 class="section-title">关键参数汇总</h2>
        ${summaryTableHtml}
    </section>

    <!-- 详细色块测量 -->
    <section class="table-section">
        <h2 class="section-title">色块测量详情</h2>
        ${detailTableHtml}
    </section>

    <footer class="report-footer">
        本报告由 Topos Calibrator 生成 | https://github.com/topos-calibrator
    </footer>
</body>
</html>`;
}

/**
 * 生成元数据 HTML 卡片（支持多组数据）
 */
function generateMetadataHtml(data) {
    // 尝试从数据中获取 metadata_list 信息
    const metadataList = data.metadata_list || [];
    
    // 如果 metadata_list 为空，尝试从旧的 metadata 字段获取（向后兼容）
    if (metadataList.length === 0 && data.metadata) {
        const metadata = data.metadata;
        if (Object.keys(metadata).length > 0) {
            metadataList.push({
                color: '#3b82f6',
                name: '',
                timestamp: metadata.timestamp || '',
                probe: metadata.probe || '',
                display_type: metadata.display_type || '',
                display_model: metadata.display_model || '',
                measure_mode: metadata.measure_mode || ''
            });
        }
    }

    // 如果仍然没有元数据，返回空
    if (metadataList.length === 0) {
        return '';
    }

    // 为每组数据生成元数据卡片
    const cardsHtml = metadataList.map((metadata, index) => {
        // 格式化时间戳
        let formattedTimestamp = '';
        if (metadata.timestamp) {
            try {
                const date = new Date(metadata.timestamp);
                formattedTimestamp = date.toLocaleString('zh-CN', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
            } catch {
                formattedTimestamp = metadata.timestamp;
            }
        }

        // 构建元数据项（按指定顺序：显示器型号、测量时间、探头、显示器类型、测量模式）
        const metadataItems = [];

        // 1. 显示器型号（放在最前面）
        if (metadata.display_model) {
            metadataItems.push({
                label: '显示器型号',
                value: metadata.display_model
            });
        }

        // 2. 测量时间
        if (formattedTimestamp) {
            metadataItems.push({
                label: '测量时间',
                value: formattedTimestamp
            });
        }

        // 3. 探头类型
        if (metadata.probe) {
            metadataItems.push({
                label: '探头',
                value: metadata.probe
            });
        }

        // 4. 显示器类型
        if (metadata.display_type) {
            metadataItems.push({
                label: '显示器类型',
                value: metadata.display_type
            });
        }

        // 5. 测量模式
        if (metadata.measure_mode) {
            const modeMap = {
                'gamut': '色域测量',
                'gamma': 'Gamma 测量',
                'icc': 'ICC 配置文件',
                'full': '完整测量'
            };
            metadataItems.push({
                label: '测量模式',
                value: modeMap[metadata.measure_mode] || metadata.measure_mode
            });
        }

        // 如果没有可显示的元数据项，返回空
        if (metadataItems.length === 0) {
            return '';
        }

        // 构建 HTML - 为每个项目添加对应颜色的圆点
        const itemsHtml = metadataItems.map(item => {
            return `
                <div class="metadata-item" style="--dot-color: ${metadata.color}">
                    <span class="metadata-label">${item.label}</span>
                    <span class="metadata-value">${item.value}</span>
                </div>
            `;
        }).join('');

        // 数据名称标签（多组数据时显示）
        const nameLabel = metadataList.length > 1 && metadata.name 
            ? `<div class="metadata-data-name" style="border-left-color: ${metadata.color}; background: linear-gradient(90deg, ${metadata.color}15, transparent)">${metadata.name}</div>`
            : '';

        return `
            <section class="metadata-card">
                ${nameLabel}
                <div class="metadata-grid">
                    ${itemsHtml}
                </div>
            </section>
        `;
    }).filter(html => html !== '').join('');

    if (cardsHtml === '') {
        return '';
    }

    // 标题
    const title = metadataList.length > 1 
        ? `文件元数据 (${metadataList.length} 组测量)`
        : '文件元数据';

    return `
    <div class="metadata-section">
        <div class="metadata-section-title">${title}</div>
        ${cardsHtml}
    </div>
    `;
}

/**
 * 生成汇总表格 HTML
 */
function generateSummaryTableHtml(data) {
    if (!data.summary_table || data.summary_table.length === 0) {
        return '<p class="no-data">无汇总数据</p>';
    }

    const headerHtml = `
        <thead>
            <tr>
                <th style="width: 30px; text-align: center;">色</th>
                <th>名称</th>
                <th>峰值(nit)</th>
                <th>黑场(nit)</th>
                <th>对比度</th>
                <th>CCT(K)</th>
                <th>Gamma</th>
                <th>sRGB</th>
                <th>DCI-P3</th>
                <th>AdobeRGB</th>
                <th>Rec.2020</th>
            </tr>
        </thead>
    `;

    const rowsHtml = data.summary_table.map(row => {
        const colorDot = `<span class="color-dot" style="background-color: ${row.color}"></span>`;
        
        const peakClass = row.bestContrast ? 'best-value' : '';
        const contrastClass = row.bestContrast ? 'best-value' : '';
        const gammaClass = row.bestGamma ? 'best-value' : '';
        
        const peak = row.peakLuminance ? row.peakLuminance.toFixed(1) : '--';
        const black = row.blackLuminance ? row.blackLuminance.toFixed(4) : '--';
        const contrast = row.contrastRatio ? row.contrastRatio.toFixed(0) + ':1' : '--';
        const cct = row.whiteCCT ? row.whiteCCT.toFixed(0) + ' K' : '--';
        const gamma = row.gamma ? row.gamma.toFixed(2) : '--';

        const srgbCoverage = renderExportCoverageBar(row.gamutCoverage?.sRGB, row.bestSRGB);
        const p3Coverage = renderExportCoverageBar(row.gamutCoverage?.DCI_P3);
        const adobeCoverage = renderExportCoverageBar(row.gamutCoverage?.AdobeRGB);
        const rec2020Coverage = renderExportCoverageBar(row.gamutCoverage?.Rec2020);

        return `
            <tr>
                <td style="text-align: center;">${colorDot}</td>
                <td>${row.name}</td>
                <td class="numeric-value ${peakClass}">${peak}</td>
                <td class="numeric-value">${black}</td>
                <td class="numeric-value ${contrastClass}">${contrast}</td>
                <td class="numeric-value">${cct}</td>
                <td class="numeric-value ${gammaClass}">${gamma}</td>
                <td>${srgbCoverage}</td>
                <td>${p3Coverage}</td>
                <td>${adobeCoverage}</td>
                <td>${rec2020Coverage}</td>
            </tr>
        `;
    }).join('');

    return `<table class="data-table">${headerHtml}<tbody>${rowsHtml}</tbody></table>`;
}

/**
 * 生成导出用的覆盖率进度条 HTML
 */
function renderExportCoverageBar(coverage, isBest = false) {
    if (coverage === null || coverage === undefined) return '<span class="no-data">--</span>';

    const percentage = Math.min(coverage, 100);
    const fillColor = isBest ? '#10b981' : '#3b82f6';
    const textClass = isBest ? 'best-value' : '';

    return `
        <div class="coverage-bar">
            <div class="coverage-progress">
                <div class="coverage-fill" style="width: ${percentage}%; background-color: ${fillColor};"></div>
            </div>
            <span class="numeric-value ${textClass}">${coverage.toFixed(1)}%</span>
        </div>
    `;
}

/**
 * 生成详细表格 HTML
 */
function generateDetailTableHtml(data) {
    if (!data.detail_data || data.detail_data.length === 0) {
        return '<p class="no-data">无详细数据</p>';
    }

    const datasets = data.detail_data;
    const isTwoDatasets = datasets.length === 2;

    // 构建表头
    let headerHtml = '<tr><th class="color-row-header">色块</th>';
    datasets.forEach(ds => {
        headerHtml += `<th><span class="color-dot" style="background-color: ${ds.color}; margin-right: 4px;"></span>${ds.shortName}</th>`;
    });
    if (isTwoDatasets) {
        headerHtml += `<th class="delta-compare-header">ΔE2000</th>`;
    }
    headerHtml += '</tr>';

    // 色块类型和颜色
    const patchTypes = ['red', 'green', 'blue', 'white', 'black'];
    const colorNames = {
        'red': '红',
        'green': '绿',
        'blue': '蓝',
        'white': '白',
        'black': '黑'
    };
    const bgColors = {
        'red': 'rgb(255, 0, 0)',
        'green': 'rgb(0, 255, 0)',
        'blue': 'rgb(0, 0, 255)',
        'white': 'rgb(255, 255, 255)',
        'black': 'rgb(0, 0, 0)'
    };

    // 构建行内容
    let rowsHtml = '';

    // 基础色块
    patchTypes.forEach(patchType => {
        const colorName = colorNames[patchType];
        const bgColor = bgColors[patchType];
        const darkClass = (patchType === 'black' || patchType === 'blue') ? 'border: 1px solid #666;' : '';

        let rowHtml = `<tr><td class="color-row-header"><div class="patch-row-title"><span class="patch-color-square" style="background-color: ${bgColor}; ${darkClass}"></span>${colorName}</div></td>`;

        datasets.forEach(ds => {
            const patchData = ds.gamut?.[patchType];
            const xyY = patchData?.xyY;
            const de = ds.deltaE?.[patchType];

            if (xyY) {
                const xyYText = `${xyY[0].toFixed(4)}, ${xyY[1].toFixed(4)}, ${xyY[2].toFixed(1)}`;
                let deText = '';
                if (de !== null && de !== undefined) {
                    const deClass = de < 2 ? 'delta-e-good' : (de < 5 ? 'delta-e-warning' : 'delta-e-bad');
                    deText = `<div class="delta-e-inline ${deClass}">ΔE: ${de.toFixed(2)}</div>`;
                }
                rowHtml += `<td><div class="xyY-value">${xyYText}</div>${deText}</td>`;
            } else {
                rowHtml += '<td><span class="no-data">--</span></td>';
            }
        });

        // 偏差对比列
        if (isTwoDatasets) {
            const xyY1 = datasets[0]?.gamut?.[patchType]?.xyY;
            const xyY2 = datasets[1]?.gamut?.[patchType]?.xyY;
            if (xyY1 && xyY2) {
                const deltaE = calculateDeltaEBetween(xyY1, xyY2);
                const deClass = deltaE < 2 ? 'delta-e-good' : (deltaE < 5 ? 'delta-e-warning' : 'delta-e-bad');
                rowHtml += `<td class="delta-compare-cell ${deClass}"><span class="delta-compare-value">${deltaE.toFixed(2)}</span></td>`;
            } else {
                rowHtml += '<td class="delta-compare-cell"><span class="no-data">--</span></td>';
            }
        }

        rowHtml += '</tr>';
        rowsHtml += rowHtml;
    });

    // 白点 CCT
    let cctRow = '<tr><td class="color-row-header">白点 CCT</td>';
    datasets.forEach(ds => {
        cctRow += `<td class="numeric-value">${ds.whiteCCT ? ds.whiteCCT + ' K' : '--'}</td>`;
    });
    if (isTwoDatasets) {
        const cct1 = datasets[0]?.whiteCCT;
        const cct2 = datasets[1]?.whiteCCT;
        if (cct1 && cct2) {
            const diff = Math.abs(cct1 - cct2);
            const diffClass = diff < 100 ? 'delta-e-good' : (diff < 500 ? 'delta-e-warning' : 'delta-e-bad');
            cctRow += `<td class="delta-compare-cell ${diffClass}"><span class="delta-compare-value">${diff} K</span></td>`;
        } else {
            cctRow += '<td class="delta-compare-cell"><span class="no-data">--</span></td>';
        }
    }
    cctRow += '</tr>';
    rowsHtml += cctRow;

    // 平均 Delta E
    if (datasets.some(ds => ds.deltaE && ds.deltaE.avg !== undefined)) {
        let avgDeRow = '<tr><td class="color-row-header">平均 ΔE</td>';
        datasets.forEach(ds => {
            const avgDe = ds.deltaE?.avg;
            if (avgDe !== null && avgDe !== undefined) {
                const deClass = avgDe < 2 ? 'delta-e-good' : (avgDe < 5 ? 'delta-e-warning' : 'delta-e-bad');
                avgDeRow += `<td class="numeric-value ${deClass}">${avgDe.toFixed(2)}</td>`;
            } else {
                avgDeRow += '<td class="no-data">--</td>';
            }
        });
        if (isTwoDatasets) {
            const avg1 = datasets[0]?.deltaE?.avg;
            const avg2 = datasets[1]?.deltaE?.avg;
            if (avg1 && avg2) {
                avgDeRow += `<td class="delta-compare-cell"><span class="delta-compare-value">${Math.abs(avg1 - avg2).toFixed(2)}</span></td>`;
            } else {
                avgDeRow += '<td class="delta-compare-cell"><span class="no-data">--</span></td>';
            }
        }
        avgDeRow += '</tr>';
        rowsHtml += avgDeRow;
    }

    // Gamma 数据（灰阶）
    if (datasets.some(ds => ds.gammaPoints && ds.gammaPoints.length > 0)) {
        // 灰阶分隔行
        const colCount = datasets.length + (isTwoDatasets ? 2 : 1);
        rowsHtml += `<tr class="data-group-header"><td colspan="${colCount}">灰阶测量</td></tr>`;

        // 平均 Gamma
        let avgGammaRow = '<tr><td class="color-row-header">平均 Gamma</td>';
        datasets.forEach(ds => {
            const gamma = ds.avgGamma;
            const gammaClass = gamma ? (Math.abs(gamma - 2.2) < 0.1 ? 'delta-e-good' : (Math.abs(gamma - 2.2) < 0.2 ? 'delta-e-warning' : 'delta-e-bad')) : '';
            avgGammaRow += `<td class="numeric-value ${gammaClass}">${gamma ? gamma.toFixed(2) : '--'}</td>`;
        });
        if (isTwoDatasets) {
            const g1 = datasets[0]?.avgGamma;
            const g2 = datasets[1]?.avgGamma;
            if (g1 && g2) {
                const gDiff = Math.abs(g1 - g2);
                const gDiffClass = gDiff < 0.05 ? 'delta-e-good' : (gDiff < 0.1 ? 'delta-e-warning' : 'delta-e-bad');
                avgGammaRow += `<td class="delta-compare-cell ${gDiffClass}"><span class="delta-compare-value">${gDiff.toFixed(3)}</span></td>`;
            } else {
                avgGammaRow += '<td class="delta-compare-cell"><span class="no-data">--</span></td>';
            }
        }
        avgGammaRow += '</tr>';
        rowsHtml += avgGammaRow;

        // 灰阶级别测量数据
        const allInputLevels = [];
        datasets.forEach(ds => {
            if (ds.gammaPoints) {
                ds.gammaPoints.forEach(p => {
                    if (!allInputLevels.includes(p.input)) {
                        allInputLevels.push(p.input);
                    }
                });
            }
        });
        allInputLevels.sort((a, b) => a - b);

        allInputLevels.forEach(inputLevel => {
            const rgbValue = Math.round(inputLevel * 255 / 100);
            const darkClass = inputLevel < 20 ? 'border: 1px solid #666;' : '';
            
            let grayRow = `<tr><td class="color-row-header"><div class="patch-row-title"><span class="patch-color-square" style="background-color: rgb(${rgbValue}, ${rgbValue}, ${rgbValue}); ${darkClass}"></span>${inputLevel}%</div></td>`;
            
            datasets.forEach(ds => {
                const point = ds.gammaPoints?.find(p => p.input === inputLevel);
                grayRow += `<td class="numeric-value">${point?.Y ? point.Y.toFixed(2) : '--'}</td>`;
            });

            if (isTwoDatasets) {
                const p1 = datasets[0]?.gammaPoints?.find(p => p.input === inputLevel);
                const p2 = datasets[1]?.gammaPoints?.find(p => p.input === inputLevel);
                if (p1?.Y && p2?.Y) {
                    const yDiff = Math.abs(p1.Y - p2.Y);
                    const yDiffClass = yDiff < 1 ? 'delta-e-good' : (yDiff < 5 ? 'delta-e-warning' : 'delta-e-bad');
                    grayRow += `<td class="delta-compare-cell ${yDiffClass}"><span class="delta-compare-value">${yDiff.toFixed(2)}</span></td>`;
                } else {
                    grayRow += '<td class="delta-compare-cell"><span class="no-data">--</span></td>';
                }
            }

            grayRow += '</tr>';
            rowsHtml += grayRow;
        });
    }

    return `<table class="data-table detail-table"><thead>${headerHtml}</thead><tbody>${rowsHtml}</tbody></table>`;
}

// ========== P6-C 分组显示功能 ==========

// 当前分组类型
let currentGroupType = 'display';

// 分组数据缓存
let groupedMeasurements = null;

// Golden baseline 数据缓存
let goldenBaselines = null;

/**
 * 处理分组后的测量数据列表更新
 * P6-C 功能：按 display、target、workflow、date 分组
 */
function handleGroupedMeasurementListUpdated(listJson) {
    const data = parseJson(listJson);
    if (!data) return;

    groupedMeasurements = data;
    currentGroupType = data.group_type || 'display';

    // 渲染分组列表
    renderGroupedMeasurementList(data);

    // 趋势页分组选择器同步更新
    populateTrendGroups();

    console.log(`[Comparison] 分组数据已更新，分组类型: ${currentGroupType}`);
}

/**
 * 渲染分组后的测量数据列表
 */
function renderGroupedMeasurementList(data) {
    const listContainer = document.getElementById('measurement-list');
    if (!listContainer) return;

    listContainer.innerHTML = '';

    const groups = data.groups || [];

    if (groups.length === 0) {
        const emptyItem = document.createElement('div');
        emptyItem.className = 'empty-list-hint';
        emptyItem.innerHTML = '<span style="color: var(--text-muted); padding: 20px;">暂无数据</span>';
        listContainer.appendChild(emptyItem);
        return;
    }

    groups.forEach(group => {
        // 创建分组容器
        const groupElement = createGroupElement(group);
        listContainer.appendChild(groupElement);
    });

    // 更新分组选择器状态
    updateGroupTypeSelector(currentGroupType);
}

/**
 * 创建分组容器元素
 */
function createGroupElement(group) {
    const groupDiv = document.createElement('div');
    groupDiv.className = 'measurement-group';
    groupDiv.dataset.groupKey = group.group_key;
    groupDiv.dataset.groupType = group.group_type;

    // 分组标题
    const headerDiv = document.createElement('div');
    headerDiv.className = 'group-header';

    // 根据分组类型显示不同的图标和标题样式
    let icon = '';
    let headerClass = '';

    switch (group.group_type) {
        case 'display':
            icon = '🖥';
            headerClass = 'group-header-display';
            break;
        case 'target':
            icon = '🎯';
            headerClass = 'group-header-target';
            break;
        case 'workflow':
            icon = '⚙';
            headerClass = 'group-header-workflow';
            break;
        case 'date':
            icon = '📅';
            headerClass = 'group-header-date';
            break;
    }

    headerDiv.innerHTML = `
        <span class="group-icon">${icon}</span>
        <span class="group-name">${group.display_name}</span>
        <span class="group-count">${group.count} 条</span>
        <button class="group-toggle-btn" title="展开/折叠">▼</button>
    `;
    headerDiv.classList.add(headerClass);

    // 点击标题展开/折叠
    headerDiv.addEventListener('click', function(e) {
        if (e.target.classList.contains('group-toggle-btn')) {
            toggleGroup(groupDiv);
        } else {
            toggleGroup(groupDiv);
        }
    });

    groupDiv.appendChild(headerDiv);

    // 分组内容容器
    const contentDiv = document.createElement('div');
    contentDiv.className = 'group-content';

    // 渲染组内的测量项
    group.measurements.forEach(item => {
        const itemElement = createMeasurementItem(item);
        contentDiv.appendChild(itemElement);
    });

    groupDiv.appendChild(contentDiv);

    // 默认展开第一个组
    if (groups.indexOf(group) === 0) {
        groupDiv.classList.add('expanded');
    } else {
        groupDiv.classList.add('collapsed');
    }

    return groupDiv;
}

/**
 * 展开/折叠分组
 */
function toggleGroup(groupDiv) {
    if (groupDiv.classList.contains('collapsed')) {
        groupDiv.classList.remove('collapsed');
        groupDiv.classList.add('expanded');
    } else {
        groupDiv.classList.remove('expanded');
        groupDiv.classList.add('collapsed');
    }
}

/**
 * 设置分组类型
 */
function setGroupType(groupType) {
    currentGroupType = groupType;

    if (backend) {
        backend.set_group_type(groupType);
    }

    // 更新选择器状态
    updateGroupTypeSelector(groupType);
}

/**
 * 更新分组选择器状态
 */
function updateGroupTypeSelector(groupType) {
    document.querySelectorAll('.group-type-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.groupType === groupType);
    });
}

// ========== P6-C Golden Baseline 功能 ==========

/**
 * 处理 Golden Baseline 状态更新
 */
function handleGoldenBaselineUpdated(dataJson) {
    const data = parseJson(dataJson);
    if (!data) return;

    goldenBaselines = data;

    // 更新测量列表中的 Golden Baseline 标记
    updateGoldenBaselineMarkers(data);

    console.log('[Comparison] Golden Baseline 数据已更新');
}

/**
 * 更新测量列表中的 Golden Baseline 标记
 */
function updateGoldenBaselineMarkers(data) {
    const markedIds = data.marked_measurements || [];

    document.querySelectorAll('.measurement-item').forEach(item => {
        const itemId = item.dataset.id;
        const isGolden = markedIds.some(m => m.measurement_id === itemId);

        // 添加或移除 Golden Baseline 标记
        if (isGolden) {
            if (!item.classList.contains('golden-baseline')) {
                item.classList.add('golden-baseline');

                // 添加标记图标
                const markerDiv = document.createElement('div');
                markerDiv.className = 'golden-marker';
                markerDiv.innerHTML = '⭐';
                markerDiv.title = 'Golden Baseline';
                item.appendChild(markerDiv);
            }
        } else {
            item.classList.remove('golden-baseline');
            const marker = item.querySelector('.golden-marker');
            if (marker) {
                marker.remove();
            }
        }
    });
}

/**
 * 标记为 Golden Baseline
 */
function markAsGoldenBaseline(measurementId) {
    if (!backend) return;

    // 从缓存数据获取 display_id 和 target_standard
    const item = allMeasurementList.find(m => m.id === measurementId);
    if (!item) {
        showErrorToast('未找到测量数据');
        return;
    }

    const displayId = item.display_model || item.display_type || '未知显示器';
    const targetStandard = item.target_standard || item.workflow_target || 'sRGB';

    backend.mark_golden_baseline(measurementId, displayId, targetStandard, '', function(resultJson) {
        const result = parseJson(resultJson);
        if (result && result.success) {
            console.log('[Comparison] Golden Baseline 标记成功');
        } else {
            showErrorToast(result?.message || t('标记失败'));
        }
    });
}

/**
 * 取消 Golden Baseline 标记
 */
function unmarkGoldenBaseline(displayId, targetStandard) {
    if (!backend) return;

    backend.unmark_golden_baseline(displayId, targetStandard, function(resultJson) {
        const result = parseJson(resultJson);
        if (result && result.success) {
            console.log('[Comparison] Golden Baseline 已取消');
        } else {
            showErrorToast(result?.message || t('取消标记失败'));
        }
    });
}

/**
 * 与 Golden Baseline 对比
 */
function compareWithGoldenBaseline(measurementId) {
    if (!backend) return;

    // 从缓存数据获取 target_standard
    const item = allMeasurementList.find(m => m.id === measurementId);
    if (!item) {
        showErrorToast('未找到测量数据');
        return;
    }

    const targetStandard = item.target_standard || item.workflow_target || 'sRGB';

    backend.compare_with_golden_baseline(measurementId, targetStandard, function(resultJson) {
        const result = parseJson(resultJson);
        if (result && result.success) {
            // 显示 Before/After 对比结果
            showBeforeAfterComparison(result.comparison);
        } else {
            showErrorToast(result?.message || t('对比失败'));
        }
    });
}

// ========== P6-C Before/After 对比显示 ==========

/**
 * 显示 Before/After 对比结果
 */
function showBeforeAfterComparison(comparison) {
    // 创建或获取 Before/After 对比面板
    let panel = document.getElementById('before-after-panel');
    if (!panel) {
        panel = createBeforeAfterPanel();
    }

    // 更新面板内容
    updateBeforeAfterPanelContent(panel, comparison);

    // 显示面板
    panel.classList.add('show');

    console.log('[Comparison] Before/After 对比结果显示');
}

/**
 * 创建 Before/After 对比面板
 */
function createBeforeAfterPanel() {
    const panel = document.createElement('div');
    panel.id = 'before-after-panel';
    panel.className = 'before-after-panel';

    panel.innerHTML = `
        <div class="panel-header">
            <h3>校准前后对比</h3>
            <button class="panel-close-btn" onclick="hideBeforeAfterPanel()">✕</button>
        </div>
        <div class="panel-body">
            <div class="comparison-section">
                <h4>Delta E</h4>
                <div class="comparison-row" id="delta-e-comparison"></div>
            </div>
            <div class="comparison-section">
                <h4>白点</h4>
                <div class="comparison-row" id="white-point-comparison"></div>
            </div>
            <div class="comparison-section">
                <h4>Gamma</h4>
                <div class="comparison-row" id="gamma-comparison"></div>
            </div>
            <div class="comparison-section">
                <h4>色域覆盖</h4>
                <div class="comparison-row" id="gamut-comparison"></div>
            </div>
            <div class="comparison-section">
                <h4>对比度</h4>
                <div class="comparison-row" id="contrast-comparison"></div>
            </div>
            <div class="comparison-summary" id="comparison-summary"></div>
        </div>
    `;

    // 插入到对比区域
    const comparisonArea = document.getElementById('comparison-area');
    if (comparisonArea) {
        comparisonArea.appendChild(panel);
    } else {
        document.body.appendChild(panel);
    }

    return panel;
}

/**
 * 更新 Before/After 对比面板内容
 */
function updateBeforeAfterPanelContent(panel, comparison) {
    // Delta E 对比
    const deltaEDiv = panel.querySelector('#delta-e-comparison');
    if (deltaEDiv) {
        deltaEDiv.innerHTML = renderBeforeAfterRow(
            '平均 ΔE',
            comparison.delta_e?.before_avg,
            comparison.delta_e?.after_avg,
            comparison.delta_e?.improvement_avg,
            comparison.delta_e?.improved
        );
    }

    // 白点对比
    const whitePointDiv = panel.querySelector('#white-point-comparison');
    if (whitePointDiv) {
        whitePointDiv.innerHTML = `
            ${renderBeforeAfterRow(
                'CCT',
                comparison.white_point?.before_cct,
                comparison.white_point?.after_cct,
                comparison.white_point?.cct_improvement,
                comparison.white_point?.improved,
                'K'
            )}
            <div class="before-after-detail">
                <span>目标 D65 (6500K)</span>
            </div>
        `;
    }

    // Gamma 对比
    const gammaDiv = panel.querySelector('#gamma-comparison');
    if (gammaDiv) {
        gammaDiv.innerHTML = `
            ${renderBeforeAfterRow(
                'Gamma',
                comparison.gamma?.before,
                comparison.gamma?.after,
                comparison.gamma?.improvement,
                comparison.gamma?.improved
            )}
            <div class="before-after-detail">
                <span>目标 2.2</span>
            </div>
        `;
    }

    // 色域覆盖对比
    const gamutDiv = panel.querySelector('#gamut-comparison');
    if (gamutDiv) {
        gamutDiv.innerHTML = renderBeforeAfterRow(
            '色域覆盖',
            comparison.gamut_coverage?.before,
            comparison.gamut_coverage?.after,
            comparison.gamut_coverage?.improvement,
            comparison.gamut_improved,
            '%'
        );
    }

    // 对比度对比
    const contrastDiv = panel.querySelector('#contrast-comparison');
    if (contrastDiv) {
        contrastDiv.innerHTML = renderBeforeAfterRow(
            '对比度',
            comparison.contrast?.before,
            comparison.contrast?.after,
            comparison.contrast?.improvement,
            null,
            ':1'
        );
    }

    // 摘要
    const summaryDiv = panel.querySelector('#comparison-summary');
    if (summaryDiv) {
        const overallClass = comparison.overall_improved ? 'improved' : 'not-improved';
        const overallIcon = comparison.overall_improved ? '✓' : '⚠';
        summaryDiv.innerHTML = `
            <div class="summary-row ${overallClass}">
                <span class="summary-icon">${overallIcon}</span>
                <span class="summary-text">${comparison.summary || '对比完成'}</span>
            </div>
        `;
    }
}

/**
 * 渲染 Before/After 行
 */
function renderBeforeAfterRow(label, before, after, improvement, improved, suffix = '') {
    const beforeVal = before !== null && before !== undefined ? before.toFixed(2) + suffix : '--';
    const afterVal = after !== null && after !== undefined ? after.toFixed(2) + suffix : '--';
    const improvementVal = improvement !== null && improvement !== undefined ? improvement.toFixed(2) + suffix : '--';

    const arrowClass = improved === true ? 'improved' : (improved === false ? 'degraded' : 'neutral');
    const arrowIcon = improved === true ? '↓' : (improved === false ? '↑' : '→');

    // Delta E 和 Gamma 的改善方向是相反的（值变小才是改善）
    let displayArrowIcon = arrowIcon;
    if (label === '平均 ΔE' || label === 'Gamma') {
        displayArrowIcon = improved === true ? '↓' : (improved === false ? '↑' : '→');
    } else {
        displayArrowIcon = improved === true ? '↑' : (improved === false ? '↓' : '→');
    }

    return `
        <div class="before-after-row">
            <span class="row-label">${label}</span>
            <span class="before-value">${beforeVal}</span>
            <span class="arrow ${arrowClass}">${displayArrowIcon}</span>
            <span class="after-value">${afterVal}</span>
            <span class="improvement-value ${arrowClass}">${improvementVal}</span>
        </div>
    `;
}

/**
 * 隐藏 Before/After 对比面板
 */
function hideBeforeAfterPanel() {
    const panel = document.getElementById('before-after-panel');
    if (panel) {
        panel.classList.remove('show');
    }
}

// ========== P6-C 兼容性检查提示 ==========

/**
 * 处理兼容性检查结果
 */
function handleCompatibilityCheckResult(dataJson) {
    const data = parseJson(dataJson);
    if (!data) return;

    if (!data.compatible) {
        // 显示兼容性警告面板
        showCompatibilityWarning(data);
    } else if (data.warnings && data.warnings.length > 0) {
        // 显示警告提示
        showCompatibilityWarnings(data.warnings);
    }
}

/**
 * 显示兼容性警告面板
 */
function showCompatibilityWarning(data) {
    const panel = document.getElementById('compatibility-warning-panel');
    if (!panel) {
        createCompatibilityWarningPanel();
    }

    const warningPanel = document.getElementById('compatibility-warning-panel');
    if (warningPanel) {
        const errorsDiv = warningPanel.querySelector('.errors-list');
        if (errorsDiv) {
            errorsDiv.innerHTML = data.errors.map(e => `
                <div class="error-item">
                    <span class="error-icon">⚠</span>
                    <span class="error-message">${e.message}</span>
                </div>
            `).join('');
        }

        const warningsDiv = warningPanel.querySelector('.warnings-list');
        if (warningsDiv) {
            warningsDiv.innerHTML = data.warnings.map(w => `
                <div class="warning-item">
                    <span class="warning-icon">⚡</span>
                    <span class="warning-message">${w.message}</span>
                </div>
            `).join('');
        }

        warningPanel.classList.add('show');
    }
}

/**
 * 创建兼容性警告面板
 */
function createCompatibilityWarningPanel() {
    const panel = document.createElement('div');
    panel.id = 'compatibility-warning-panel';
    panel.className = 'compatibility-warning-panel';

    panel.innerHTML = `
        <div class="panel-header warning-header">
            <h3>⚠ 兼容性警告</h3>
            <button class="panel-close-btn" onclick="hideCompatibilityWarning()">✕</button>
        </div>
        <div class="panel-body">
            <div class="errors-section">
                <h4>错误</h4>
                <div class="errors-list"></div>
            </div>
            <div class="warnings-section">
                <h4>警告</h4>
                <div class="warnings-list"></div>
            </div>
            <div class="hint-text">
                <p>不同目标标准的数据对比可能导致误导性结论。</p>
                <p>建议：选择相同目标标准的数据进行对比。</p>
            </div>
        </div>
    `;

    // 插入到对比区域顶部
    const comparisonArea = document.getElementById('comparison-area');
    if (comparisonArea) {
        comparisonArea.insertBefore(panel, comparisonArea.firstChild);
    } else {
        document.body.appendChild(panel);
    }
}

/**
 * 隐藏兼容性警告面板
 */
function hideCompatibilityWarning() {
    const panel = document.getElementById('compatibility-warning-panel');
    if (panel) {
        panel.classList.remove('show');
    }
}

/**
 * 显示兼容性警告提示（Toast）
 */
function showCompatibilityWarnings(warnings) {
    warnings.forEach(w => {
        console.warn('[Comparison]', w.message);
    });

    // 简单的 Toast 提示
    let toast = document.getElementById('warning-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'warning-toast';
        toast.className = 'warning-toast';
        document.body.appendChild(toast);
    }

    toast.textContent = `⚠ ${warnings.length} 个警告：${warnings[0].message}`;
    toast.classList.add('show');

    setTimeout(() => {
        toast.classList.remove('show');
    }, 5000);
}

// ========== P6-C 目标标准标注显示 ==========

/**
 * 在表格中显示目标标准标注
 * 防止误对比功能的一部分
 */
function addTargetStandardLabels(data) {
    const targets = data.target_standards || [];

    // 如果有多个不同的目标标准，显示警告
    if (targets.length > 1) {
        const headerDiv = document.querySelector('.table-header');
        if (headerDiv) {
            // 添加目标标准不一致提示
            let warningDiv = headerDiv.querySelector('.target-warning');
            if (!warningDiv) {
                warningDiv = document.createElement('div');
                warningDiv.className = 'target-warning';
                warningDiv.innerHTML = `
                    <span class="warning-icon">⚠</span>
                    <span class="warning-text">目标标准不一致: ${targets.join(', ')}</span>
                `;
                headerDiv.appendChild(warningDiv);
            }
        }
    }

    // 在汇总表格的每一行添加目标标准标注
    const tbody = document.getElementById('table-body');
    if (tbody) {
        tbody.querySelectorAll('tr').forEach((tr, index) => {
            const row = data.summary_table?.[index];
            if (row && row.target_standard) {
                // 在名称列后添加目标标准标签
                const nameCell = tr.querySelector('.col-name');
                if (nameCell) {
                    const label = document.createElement('span');
                    label.className = 'target-label';
                    label.textContent = row.target_standard;
                    nameCell.appendChild(label);
                }
            }
        });
    }
}

// ========== 页面初始化 ==========

document.addEventListener('DOMContentLoaded', function() {
    // 初始化 QWebChannel
    initWebChannel();

    // 绑定按钮事件
    document.getElementById('btn-refresh')?.addEventListener('click', refreshMeasurementList);
    document.getElementById('btn-select-all')?.addEventListener('click', selectAllMeasurements);
    document.getElementById('btn-clear-all')?.addEventListener('click', clearAllSelections);
    document.getElementById('btn-export')?.addEventListener('click', exportToHtml);

    // P6-C: 绑定分组类型选择按钮
    document.querySelectorAll('.group-type-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            setGroupType(this.dataset.groupType);
        });
    });

    // 绑定搜索输入
    document.getElementById('search-input')?.addEventListener('input', function(e) {
        filterMeasurements(e.target.value);
    });

    // 绑定标签页切换
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            switchTab(this.dataset.tab);
        });
    });

    // 绑定右键菜单事件
    document.getElementById('context-menu-rename')?.addEventListener('click', function() {
        if (contextMenuTargetItem) {
            showRenameDialog(contextMenuTargetItem);
        }
    });

    // P6-C: Golden Baseline 右键菜单事件
    document.getElementById('context-menu-mark-golden')?.addEventListener('click', function() {
        if (contextMenuTargetItem) {
            markAsGoldenBaseline(contextMenuTargetItem.id);
            hideContextMenu();
        }
    });

    document.getElementById('context-menu-compare-golden')?.addEventListener('click', function() {
        if (contextMenuTargetItem) {
            compareWithGoldenBaseline(contextMenuTargetItem.id);
            hideContextMenu();
        }
    });

    document.getElementById('context-menu-unmark-golden')?.addEventListener('click', function() {
        if (contextMenuTargetItem) {
            const displayId = contextMenuTargetItem.display_model || contextMenuTargetItem.display_type || '';
            const targetStandard = contextMenuTargetItem.target_standard || 'sRGB';
            unmarkGoldenBaseline(displayId, targetStandard);
            hideContextMenu();
        }
    });

    // 绑定重命名对话框事件
    document.getElementById('rename-confirm')?.addEventListener('click', executeRename);
    document.getElementById('rename-cancel')?.addEventListener('click', hideRenameDialog);
    document.getElementById('rename-overlay')?.addEventListener('click', hideRenameDialog);

    // 重命名输入框回车确认
    document.getElementById('rename-input')?.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            executeRename();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            hideRenameDialog();
        }
    });

    // 初始化预设选择面板
    initPresetPanels();

    // 初始化图表（默认显示参考色域和曲线）
    initCieComparisonChart();
    initGammaComparisonChart();

    // 默认显示概览标签页（显示图表区域）
    // 空状态提示已在 CSS 中默认隐藏
    const tabOverview = document.getElementById('tab-overview');
    if (tabOverview) {
        tabOverview.classList.add('active');
    }

    // 初始时隐藏表格区域（没有对比数据）
    const tableContainer = document.getElementById('table-container');
    if (tableContainer) {
        tableContainer.style.display = 'none';
    }

    console.log('[Comparison] 页面初始化完成');
});
// ========== 历史趋势（定期复检：同一分组的指标随时间变化） ==========

let trendChart = null;
let trendPoints = [];
let trendEventsBound = false;

/** 分组数据更新时，同步填充趋势页的分组下拉 */
function populateTrendGroups() {
    const select = document.getElementById('trend-group-select');
    if (!select || !groupedMeasurements) return;

    const prev = select.value;
    select.innerHTML = '<option value="">-- 选择分组 --</option>';

    (groupedMeasurements.groups || []).forEach(group => {
        // 只列出有 2 条以上记录的分组（单点无趋势可言）
        if (!group.measurements || group.measurements.length < 2) return;
        const opt = document.createElement('option');
        opt.value = group.group_key;
        opt.textContent = `${group.display_name || group.group_key}（${group.measurements.length} 次）`;
        opt.dataset.groupKey = group.group_key;
        select.appendChild(opt);
    });

    if (prev && [...select.options].some(o => o.value === prev)) {
        select.value = prev;
    }
}

/** 趋势页首次激活：绑定事件并按需加载 */
function initTrendTab() {
    if (!trendEventsBound) {
        trendEventsBound = true;
        document.getElementById('trend-group-select')?.addEventListener('change', loadTrendData);
        document.getElementById('trend-metric-select')?.addEventListener('change', () => renderTrendChart());
        window.addEventListener('resize', () => {
            if (currentTab === 'trend' && trendChart) trendChart.resize();
        });
    }
    if (!trendChart) {
        const el = document.getElementById('trend-chart');
        if (el && typeof echarts !== 'undefined') {
            trendChart = echarts.init(el);
        }
    }
    if (trendChart) trendChart.resize();
    if (trendPoints.length === 0 && !document.getElementById('trend-group-select')?.value) {
        // 未选分组时优先自动选择第一个分组
        const first = document.querySelector('#trend-group-select option:nth-child(2)');
        if (first) {
            document.getElementById('trend-group-select').value = first.value;
        }
    }
    if (document.getElementById('trend-group-select')?.value && trendPoints.length === 0) {
        loadTrendData();
    } else if (trendPoints.length > 0) {
        renderTrendChart();
    }
}

/** 拉取选中分组的趋势数据（后端计算每会话指标） */
function loadTrendData() {
    const groupKey = document.getElementById('trend-group-select')?.value;
    const hint = document.getElementById('trend-hint');
    if (!groupKey || !backend || !backend.get_trend_data) {
        trendPoints = [];
        renderTrendChart();
        return;
    }

    const group = (groupedMeasurements.groups || []).find(g => g.group_key === groupKey);
    if (!group || !group.measurements) return;

    // 按时间戳升序传入，后端亦会排序
    const ids = group.measurements
        .slice()
        .sort((a, b) => String(a.timestamp || '').localeCompare(String(b.timestamp || '')))
        .map(m => m.id);

    if (hint) hint.textContent = `加载中…（${ids.length} 条记录）`;

    backend.get_trend_data(JSON.stringify(ids)).then(function(resultJson) {
        const result = parseJson(resultJson);
        if (!result || !result.success) {
            if (hint) hint.textContent = result?.error || '加载失败';
            return;
        }
        trendPoints = result.points || [];
        if (hint) {
            hint.textContent = trendPoints.length >= 2
                ? `分组「${group.display_name || groupKey}」共 ${trendPoints.length} 条有效记录`
                : '该分组有效数据不足 2 条（需包含白点或灰阶测量）';
        }
        renderTrendChart();
    }).catch(function(e) {
        if (hint) hint.textContent = '加载失败: ' + e;
    });
}

/** xy → CIE 1976 u'v'（用于 Δu'v' 指标） */
function trendXyToUpVp(x, y) {
    const denom = -2 * x + 12 * y + 3;
    if (Math.abs(denom) < 1e-9) return null;
    return { up: 4 * x / denom, vp: 9 * y / denom };
}

/** 根据当前指标选择渲染折线 */
function renderTrendChart() {
    if (!trendChart) return;
    const metric = document.getElementById('trend-metric-select')?.value || 'whiteY';

    const metricDefs = {
        whiteY:  { name: '白点亮度', unit: 'cd/m²', digits: 1 },
        whiteCCT:{ name: '白点 CCT', unit: 'K', digits: 0 },
        gamma:   { name: '平均 Gamma', unit: '', digits: 3 },
        whiteDuv:{ name: "白点 Δu'v'", unit: '', digits: 4 }
    };
    const def = metricDefs[metric] || metricDefs.whiteY;
    const D65 = { up: 0.1978, vp: 0.4683 };

    const labels = trendPoints.map(p => {
        const ts = String(p.timestamp || '');
        // ISO 时间戳取日期部分
        const m = ts.match(/(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})?/);
        return m ? (m[2] ? `${m[1]} ${m[2]}` : m[1]) : (ts || p.id);
    });

    const values = trendPoints.map(p => {
        if (metric === 'whiteDuv') {
            if (p.white_x === undefined || p.white_y === undefined) return null;
            const uv = trendXyToUpVp(p.white_x, p.white_y);
            if (!uv) return null;
            return +(Math.sqrt((uv.up - D65.up) ** 2 + (uv.vp - D65.vp) ** 2)).toFixed(4);
        }
        return p[metric] ?? null;
    });

    trendChart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            formatter: function(params) {
                const idx = params[0]?.dataIndex;
                if (idx === undefined || !trendPoints[idx]) return '';
                const p = trendPoints[idx];
                let html = `<b>${labels[idx]}</b><br/>`;
                if (p.name) html += `显示器: ${p.name}<br/>`;
                if (p.probe) html += `探头: ${p.probe}<br/>`;
                if (p.whiteY !== undefined) html += t('白点亮度: {y} cd/m²<br/>', {y: p.whiteY});
                if (p.whiteCCT !== undefined) html += `CCT: ${p.whiteCCT} K<br/>`;
                if (p.gamma !== undefined) html += `Gamma: ${p.gamma}<br/>`;
                if (p.white_x !== undefined) html += `白点 xy: (${p.white_x}, ${p.white_y})`;
                return html;
            }
        },
        grid: { left: 64, right: 24, top: 40, bottom: 48 },
        xAxis: {
            type: 'category',
            data: labels,
            axisLabel: { rotate: 30, color: '#9aa0b5' }
        },
        yAxis: {
            type: 'value',
            name: `${def.name}${def.unit ? ' (' + def.unit + ')' : ''}`,
            scale: true,
            axisLabel: { color: '#9aa0b5', formatter: v => v.toFixed(def.digits) },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
        },
        series: [{
            name: def.name,
            type: 'line',
            data: values,
            connectNulls: true,
            symbol: 'circle',
            symbolSize: 9,
            lineStyle: { width: 2, color: '#3b82f6' },
            itemStyle: { color: '#3b82f6' },
            label: {
                show: true,
                color: '#c8cad8',
                formatter: p => p.value === null ? '' : Number(p.value).toFixed(def.digits)
            },
            markLine: metric === 'whiteCCT' ? {
                silent: true,
                symbol: 'none',
                lineStyle: { color: '#10b981', type: 'dashed' },
                data: [{ yAxis: 6500, label: { formatter: 'D65', color: '#10b981' } }]
            } : (metric === 'gamma' ? {
                silent: true,
                symbol: 'none',
                lineStyle: { color: '#10b981', type: 'dashed' },
                data: [{ yAxis: 2.2, label: { formatter: '2.2', color: '#10b981' } }]
            } : undefined)
        }]
    }, true);
}
