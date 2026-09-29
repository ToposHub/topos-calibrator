/**
 * Topos Calibrator - ECharts 图表模块
 * 绘制 CIE 1931 色度图和 Gamma 曲线
 */

// 图表实例
let cieChart = null;
let gammaChart = null;

// 测量数据
let measuredGamut = null;
let measuredWhitePoint = null;
let gammaCurveData = [];

// 标准色域数据 - 影视制作常用色域预设
const STANDARD_GAMUTS = {
    // === 基础色域 ===
    sRGB: {
        red: [0.64, 0.33],
        green: [0.30, 0.60],
        blue: [0.15, 0.06],
        white: [0.3127, 0.3290],  // D65
        color: '#00ff00',
        name: 'sRGB',
        category: t('基础'),
        description: 'sRGB (IEC 61966-2-1)'
    },
    Rec709: {
        red: [0.64, 0.33],
        green: [0.30, 0.60],
        blue: [0.15, 0.06],
        white: [0.3127, 0.3290],  // D65
        color: '#00ff88',
        name: 'Rec.709',
        category: t('基础'),
        description: t('Rec.709 (BT.709) - HD视频标准')
    },
    
    // === 宽色域 ===
    DCI_P3: {
        red: [0.68, 0.32],
        green: [0.265, 0.69],
        blue: [0.15, 0.06],
        white: [0.314, 0.351],  // DCI白点 (~6300K)
        color: '#ff6b6b',
        name: 'DCI-P3',
        category: t('宽色域'),
        description: t('DCI-P3 (SMPTE RP 431-2) - 数字影院')
    },
    DisplayP3: {
        red: [0.68, 0.32],
        green: [0.265, 0.69],
        blue: [0.15, 0.06],
        white: [0.3127, 0.3290],  // D65
        color: '#ff8888',
        name: 'Display P3',
        category: t('宽色域'),
        description: t('Display P3 - Apple/DCI-P3 D65版本')
    },
    AdobeRGB: {
        red: [0.64, 0.33],
        green: [0.21, 0.71],
        blue: [0.15, 0.06],
        white: [0.3127, 0.3290],  // D65
        color: '#4ecdc4',
        name: 'Adobe RGB',
        category: t('宽色域'),
        description: 'Adobe RGB (1998)'
    },
    Rec2020: {
        red: [0.708, 0.292],
        green: [0.170, 0.797],
        blue: [0.131, 0.046],
        white: [0.3127, 0.3290],  // D65
        color: '#ffe66d',
        name: 'Rec.2020',
        category: t('宽色域'),
        description: 'Rec.2020 (BT.2020) - UHD/4K/8K'
    },
    
    // === 专业电影色域 ===
    ProPhotoRGB: {
        red: [0.7347, 0.2653],
        green: [0.1596, 0.8404],
        blue: [0.0366, 0.0001],
        white: [0.3457, 0.3585],  // D50
        color: '#9b59b6',
        name: 'ProPhoto RGB',
        category: t('专业'),
        description: t('ProPhoto RGB (ROMM) - 摄影宽色域')
    },
    CinemaGamut: {
        red: [0.7347, 0.2653],
        green: [0.1596, 0.8404],
        blue: [0.0366, 0.0001],
        white: [0.3127, 0.3290],  // D65
        color: '#e74c3c',
        name: 'Cinema Gamut',
        category: t('专业'),
        description: t('Cinema Gamut - Canon电影色域')
    },
    ACES_AP0: {
        red: [0.7347, 0.2653],
        green: [0.0000, 1.0000],
        blue: [0.0001, -0.0770],
        white: [0.32168, 0.33767],  // ACES白点
        color: '#f39c12',
        name: 'ACES AP0',
        category: t('专业'),
        description: t('ACES AP0 - Academy色彩编码系统')
    },
    ACES_AP1: {
        red: [0.713, 0.293],
        green: [0.165, 0.830],
        blue: [0.128, 0.044],
        white: [0.32168, 0.33767],  // ACES白点
        color: '#f1c40f',
        name: 'ACES AP1',
        category: t('专业'),
        description: t('ACES AP1 (ACEScg) - ACES工作色域')
    },
    
    // === 品牌特定色域 ===
    S_Gamut3: {
        red: [0.730, 0.280],
        green: [0.140, 0.850],
        blue: [0.100, 0.050],
        white: [0.3127, 0.3290],  // D65
        color: '#3498db',
        name: 'S-Gamut3',
        category: t('品牌'),
        description: t('S-Gamut3 - Sony电影色域')
    },
    S_Gamut3_Cine: {
        red: [0.766, 0.274],
        green: [0.150, 0.860],
        blue: [0.094, 0.056],
        white: [0.3127, 0.3290],  // D65
        color: '#2980b9',
        name: 'S-Gamut3.Cine',
        category: t('品牌'),
        description: t('S-Gamut3.Cine - Sony电影色域(优化版)')
    },
    V_Gamut: {
        red: [0.730, 0.280],
        green: [0.165, 0.840],
        blue: [0.100, 0.010],
        white: [0.3127, 0.3290],  // D65
        color: '#1abc9c',
        name: 'V-Gamut',
        category: t('品牌'),
        description: 'V-Gamut - Panasonic VariCam'
    },
    C_Gamut: {
        red: [0.740, 0.270],
        green: [0.170, 0.830],
        blue: [0.100, 0.020],
        white: [0.3127, 0.3290],  // D65
        color: '#16a085',
        name: 'C-Gamut',
        category: t('品牌'),
        description: 'C-Gamut - Canon Cinema EOS'
    },
    REDWideGamutRGB: {
        red: [0.780, 0.304],
        green: [0.121, 0.873],
        blue: [0.095, -0.084],
        white: [0.3127, 0.3290],  // D65
        color: '#c0392b',
        name: 'RED WideGamut',
        category: t('品牌'),
        description: 'RED Wide Gamut RGB'
    }
};

// Gamma/EOTF 预设数据 - 影视制作常用曲线
const GAMMA_PRESETS = {
    // === 标准Gamma曲线 ===
    '1.8': {
        color: '#0abde3',
        name: 'Gamma 1.8',
        category: t('标准'),
        description: t('Mac传统Gamma')
    },
    '2.0': {
        color: '#00cec9',
        name: 'Gamma 2.0',
        category: t('标准'),
        description: t('线性近似')
    },
    '2.2': {
        color: '#8888a0',
        name: 'Gamma 2.2',
        category: t('标准'),
        description: t('sRGB/Rec.709标准')
    },
    '2.4': {
        color: '#ff9f43',
        name: 'Gamma 2.4',
        category: t('标准'),
        description: t('BT.1886 (SDR电视)')
    },
    '2.6': {
        color: '#ee5a24',
        name: 'Gamma 2.6',
        category: t('标准'),
        description: t('DCI-P3影院标准')
    },
    
    // === 复合曲线 ===
    'sRGB': {
        color: '#10b981',
        name: 'sRGB 曲线',
        category: t('复合'),
        description: t('IEC 61966-2-1 (线性段+2.4)')
    },
    'BT1886': {
        color: '#fdcb6e',
        name: 'BT.1886',
        category: t('复合'),
        description: t('ITU-R BT.1886 (带黑场补偿)')
    },
    'Rec709': {
        color: '#6c5ce7',
        name: 'Rec.709',
        category: t('复合'),
        description: t('ITU-R BT.709 (线性段+2.4)')
    },
    
    // === HDR曲线 ===
    'PQ': {
        color: '#e17055',
        name: 'ST 2084 PQ',
        category: 'HDR',
        description: 'SMPTE ST 2084 (HDR10/Dolby Vision)'
    },
    'HLG': {
        color: '#00b894',
        name: 'HLG',
        category: 'HDR',
        description: 'Hybrid Log-Gamma (BBC/NHK)'
    },
    'PQ_1000': {
        color: '#d63031',
        name: 'PQ 1000nit',
        category: 'HDR',
        description: t('ST 2084 (1000nit峰值)')
    },
    'PQ_4000': {
        color: '#e84393',
        name: 'PQ 4000nit',
        category: 'HDR',
        description: t('ST 2084 (4000nit峰值)')
    },
    
    // === Log曲线 ===
    'LogC': {
        color: '#74b9ff',
        name: 'ARRI Log C',
        category: 'Log',
        description: t('ARRI Alexa Log曲线')
    },
    'SLog3': {
        color: '#0984e3',
        name: 'S-Log3',
        category: 'Log',
        description: 'Sony S-Log3'
    },
    'VLog': {
        color: '#81ecec',
        name: 'V-Log',
        category: 'Log',
        description: 'Panasonic V-Log'
    },
    'CLog': {
        color: '#55a3ff',
        name: 'C-Log',
        category: 'Log',
        description: 'Canon C-Log'
    },
    'REDLog': {
        color: '#ff7675',
        name: 'RED Log',
        category: 'Log',
        description: 'RED Log3G10'
    },
    'ACEScct': {
        color: '#a29bfe',
        name: 'ACEScct',
        category: 'Log',
        description: t('ACES Log曲线')
    },
    
    // === 线性 ===
    'Linear': {
        color: '#ffeaa7',
        name: 'Linear',
        category: t('线性'),
        description: t('线性响应 (Gamma 1.0)')
    }
};

// 当前选中的预设
let selectedGamuts = ['sRGB'];
let selectedGammas = ['2.2'];

// CIE 1931 2° 标准观察者光谱轨迹数据（1nm 步进，402 点）
// 数据提取自 380nm 到 780nm，已闭合紫红轨迹（起点已添加到末尾）
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
 * 初始化 CIE 1931 色度图
 */
function initCIEChart() {
    let chartDom = document.getElementById('cie-chart');
    if (!chartDom) return;

    cieChart = echarts.init(chartDom, null, {
        renderer: 'canvas',
        devicePixelRatio: window.devicePixelRatio || 1
    });

    updateCIEChart();

    // 绑定预设切换按钮事件
    const gamutPresetToggle = document.getElementById('gamut-preset-toggle');
    const gamutPresetPanel = document.getElementById('gamut-preset-panel');
    
    if (gamutPresetToggle && gamutPresetPanel) {
        // 点击按钮显示/隐藏面板
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
                updateCIEChart();
            });
        });
    }
    
    // 点击其他区域关闭面板
    document.addEventListener('click', function(e) {
        if (!gamutPresetPanel?.contains(e.target) && !gamutPresetToggle?.contains(e.target)) {
            if (gamutPresetPanel) gamutPresetPanel.classList.remove('show');
            if (gamutPresetToggle) gamutPresetToggle.classList.remove('active');
        }
    });

    resizeCharts();
}

/**
 * 更新 CIE 图表（根据选中的预设）
 */
function updateCIEChart() {
    if (!cieChart) return;

    // 构建色域参考线系列
    const gamutSeries = [];
    const legendData = ['CIE1931 Spectral Locus'];

    selectedGamuts.forEach(name => {
        if (STANDARD_GAMUTS[name]) {
            const gamut = STANDARD_GAMUTS[name];
            gamutSeries.push({
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
                z: 2
            });
            legendData.push(gamut.name || name);
        }
    });

    const option = {
        backgroundColor: '#0d0d14',
        title: { show: false },
        tooltip: {
            trigger: 'item',
            formatter: function(params) {
                if (params.seriesName === '测量色域' || params.seriesName === '测量点' || params.seriesName === '测量白点') {
                    return `${params.name}<br/>x: ${params.value[0].toFixed(4)}<br/>y: ${params.value[1].toFixed(4)}`;
                }
                return params.name;
            },
            backgroundColor: '#1e1e30',
            borderColor: '#3a3a50',
            textStyle: { color: '#ffffff' }
        },
        grid: {
            left: 40,
            right: 8,
            top: 16,
            bottom: 30,
            containLabel: false
        },
        xAxis: {
            type: 'value',
            min: 0,
            max: 0.8,
            interval: 0.1,
            name: 'x',
            nameLocation: 'end',
            nameGap: 30,
            nameTextStyle: {
                color: '#8888a0',
                fontSize: 12,
                fontWeight: 'bold'
            },
            axisLine: {
                lineStyle: { color: '#5a5a7a', width: 1.5 }
            },
            axisTick: {
                lineStyle: { color: '#5a5a7a' }
            },
            axisLabel: {
                color: '#8888a0',
                fontSize: 11,
                formatter: function(value) {
                    return value.toFixed(1);
                }
            },
            splitLine: {
                lineStyle: {
                    color: '#2a2a3d',
                    width: 1,
                    type: 'dashed'
                }
            },
            zoomLock: true
        },
        yAxis: {
            type: 'value',
            min: 0,
            max: 0.9,
            interval: 0.1,
            name: 'y',
            nameLocation: 'end',
            nameGap: 35,
            nameTextStyle: {
                color: '#8888a0',
                fontSize: 12,
                fontWeight: 'bold'
            },
            axisLine: {
                lineStyle: { color: '#5a5a7a', width: 1.5 }
            },
            axisTick: {
                lineStyle: { color: '#5a5a7a' }
            },
            axisLabel: {
                color: '#8888a0',
                fontSize: 11,
                formatter: function(value) {
                    return value.toFixed(1);
                }
            },
            splitLine: {
                lineStyle: {
                    color: '#2a2a3d',
                    width: 1,
                    type: 'dashed'
                }
            },
            zoomLock: true
        },
        series: [
            // CIE 1931 光谱轨迹（马蹄形外圈）- 白色实线
            {
                name: 'CIE1931 Spectral Locus',
                type: 'line',
                data: CIE1931_LOCUS_DATA,
                lineStyle: {
                    color: '#ffffff',
                    width: 2
                },
                symbol: 'none',
                smooth: false,
                z: 0
            },
            // D65 白点参考
            {
                name: 'D65',
                type: 'scatter',
                data: [[0.3127, 0.3290]],
                symbol: 'circle',
                symbolSize: 6,
                itemStyle: {
                    color: '#ffffff',
                    borderColor: '#666680',
                    borderWidth: 1,
                    opacity: 0.5
                },
                z: 1
            },
            // 色域参考线（动态）
            ...gamutSeries,
            // 测量点
            {
                name: '测量点',
                type: 'scatter',
                data: [],
                symbol: 'circle',
                symbolSize: 9,
                itemStyle: {
                    color: '#888888',
                    shadowColor: 'rgba(0,0,0,0.5)',
                    shadowBlur: 4
                },
                z: 100
            },
            // 测量色域三角形 - 加粗实线
            {
                name: '测量色域',
                type: 'line',
                data: [],
                lineStyle: {
                    color: '#4da6ff',
                    width: 3.5,
                    shadowColor: 'rgba(77, 166, 255, 0.6)',
                    shadowBlur: 10
                },
                symbol: 'circle',
                symbolSize: 11,
                itemStyle: {
                    color: '#4da6ff',
                    borderColor: '#ffffff',
                    borderWidth: 2,
                    shadowColor: 'rgba(255, 255, 255, 0.8)',
                    shadowBlur: 8
                },
                emphasis: {
                    itemStyle: {
                        color: '#4da6ff',
                        borderColor: '#ffffff',
                        borderWidth: 3,
                        shadowBlur: 15
                    },
                    lineStyle: {
                        width: 5,
                        shadowBlur: 15
                    }
                },
                z: 100
            },
            // 测量白点 - 最高层
            {
                name: '测量白点',
                type: 'scatter',
                data: [],
                symbol: 'diamond',
                symbolSize: 14,
                itemStyle: {
                    color: '#ffffff',
                    borderColor: '#4da6ff',
                    borderWidth: 2.5,
                    shadowColor: 'rgba(255, 255, 255, 0.9)',
                    shadowBlur: 10
                },
                z: 101
            }
        ],
        legend: {
            data: [...legendData, '测量色域'],
            formatter: function (name) { return window.I18N ? I18N.t(name) : name; },
            top: 8,
            right: 10,
            textStyle: {
                color: '#8888a0',
                fontSize: 10
            },
            itemWidth: 15,
            itemHeight: 10,
            z: 100
        }
    };

    cieChart.setOption(option, true);
}

/**
 * 初始化 Gamma 曲线图
 */
function initGammaChart() {
    const chartDom = document.getElementById('gamma-chart');
    if (!chartDom) return;

    gammaChart = echarts.init(chartDom);

    updateGammaChartPresets();

    // 绑定预设切换按钮事件
    const gammaPresetToggle = document.getElementById('gamma-preset-toggle');
    const gammaPresetPanel = document.getElementById('gamma-preset-panel');
    
    if (gammaPresetToggle && gammaPresetPanel) {
        // 点击按钮显示/隐藏面板
        gammaPresetToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            gammaPresetPanel.classList.toggle('show');
            gammaPresetToggle.classList.toggle('active');
            
            // 关闭色域预设面板
            const gamutPanel = document.getElementById('gamut-preset-panel');
            const gamutToggle = document.getElementById('gamut-preset-toggle');
            if (gamutPanel) gamutPanel.classList.remove('show');
            if (gamutToggle) gamutToggle.classList.remove('active');
        });
        
        // 绑定checkbox变化事件
        gammaPresetPanel.querySelectorAll('input[name="gamma-preset"]').forEach(checkbox => {
            checkbox.addEventListener('change', function() {
                selectedGammas = Array.from(gammaPresetPanel.querySelectorAll('input[name="gamma-preset"]:checked'))
                    .map(cb => cb.value);
                updateGammaChartPresets();
            });
        });
    }
    
    // 点击其他区域关闭面板（已在initCIEChart中添加全局监听）
}

/**
 * 生成 Gamma/EOTF 曲线数据
 * 支持标准Gamma、复合曲线、HDR曲线和Log曲线
 */
function generateGammaCurveData(gammaType) {
    const data = [];

    // === 标准Gamma曲线 ===
    if (['1.8', '2.0', '2.2', '2.4', '2.6'].includes(gammaType)) {
        const gamma = parseFloat(gammaType);
        for (let i = 0; i <= 100; i += 2) {
            const input = i / 100;
            const output = Math.pow(input, gamma) * 100;
            data.push([i, output]);
        }
        return data;
    }

    // === 线性 ===
    if (gammaType === 'Linear') {
        for (let i = 0; i <= 100; i += 2) {
            data.push([i, i]);
        }
        return data;
    }

    // === sRGB曲线 (IEC 61966-2-1) ===
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

    // === Rec.709曲线 (ITU-R BT.709) ===
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

    // === BT.1886曲线 (带黑场补偿) ===
    if (gammaType === 'BT1886') {
        // BT.1886: L = a * (V + b)^gamma, 其中gamma=2.4
        // 假设黑场Lb=0, 白场Lw=100
        const gamma = 2.4;
        for (let i = 0; i <= 100; i += 2) {
            const V = i / 100;
            const L = Math.pow(V, gamma) * 100;
            data.push([i, L]);
        }
        return data;
    }

    // === ST 2084 PQ曲线 (HDR) ===
    if (gammaType === 'PQ' || gammaType === 'PQ_1000' || gammaType === 'PQ_4000') {
        // SMPTE ST 2084 PQ EOTF
        // Y = ( (max(N^m1 - c1, 0) / (c2 - c3 * N^m1))^m2 ) * L_max
        const m1 = 2610 / 16384;  // 0.1593017578125
        const m2 = 2523 / 4096 * 128;  // 78.84375
        const c1 = 3424 / 4096;  // 0.8359375 = c3 - c2 + 1
        const c2 = 2413 / 4096 * 32;  // 18.8515625
        const c3 = 2392 / 4096 * 32;  // 18.6875
        
        // 峰值亮度
        let L_max = 10000;  // PQ标准峰值10000nit
        if (gammaType === 'PQ_1000') L_max = 1000;
        if (gammaType === 'PQ_4000') L_max = 4000;
        
        // 归一化到100%显示
        for (let i = 0; i <= 100; i += 2) {
            const N = i / 100;  // PQ信号值 (0-1)
            const N_m1 = Math.pow(N, m1);
            const numerator = Math.max(N_m1 - c1, 0);
            const denominator = c2 - c3 * N_m1;
            const Y = Math.pow(numerator / denominator, m2) * L_max;
            
            // 归一化输出到百分比（相对于峰值）
            data.push([i, (Y / L_max) * 100]);
        }
        return data;
    }

    // === HLG曲线 (Hybrid Log-Gamma) ===
    if (gammaType === 'HLG') {
        // ITU-R BT.2100 HLG OETF
        // 对于SDR部分 (0-1): E = sqrt(3) * E'
        // 对于HDR部分 (>1): E = a * ln(E' - b) + c
        const a = 0.17883277;
        const b = 0.28466892;
        const c = 0.55991073;
        
        for (let i = 0; i <= 100; i += 2) {
            const E = i / 100;  // 场景亮度
            let E_out;
            
            if (E <= 1/12) {
                E_out = Math.sqrt(3 * E);
            } else {
                E_out = a * Math.log(12 * E - b) + c;
            }
            
            data.push([i, E_out * 100]);
        }
        return data;
    }

    // === ARRI Log C曲线 ===
    if (gammaType === 'LogC') {
        // ARRI Alexa Log C (EI 800)
        // LogC曲线参数
        const cut = 0.011563;
        const a = 5.555556;
        const b = 0.052272;
        const c = 0.246191;
        const d = 0.385937;
        const e = 5.367655;
        const f = 0.092809;
        
        for (let i = 0; i <= 100; i += 2) {
            const x = i / 100;
            let y;
            
            if (x < cut) {
                y = (a * x + b) * 100;
            } else {
                y = (c * Math.log10(a * x + b) + d) * 100;
            }
            
            // 归一化到合理范围
            y = Math.max(0, Math.min(100, y * 0.5 + 25));
            data.push([i, y]);
        }
        return data;
    }

    // === Sony S-Log3曲线 ===
    if (gammaType === 'SLog3') {
        // Sony S-Log3
        for (let i = 0; i <= 100; i += 2) {
            const x = i / 100;
            let y;
            
            if (x <= 0.01125) {
                y = (x * 171.629 + 0.0) * 100;
            } else {
                y = (420 + Math.log10((x + 0.01) / (0.19 - x * 0.18)) * 261.5) / 1023 * 100;
            }
            
            // 归一化
            y = Math.max(0, Math.min(100, y));
            data.push([i, y]);
        }
        return data;
    }

    // === Panasonic V-Log曲线 ===
    if (gammaType === 'VLog') {
        // Panasonic V-Log
        const b = 0.00873;
        const c = 0.24151;
        const d = 0.5985;
        
        for (let i = 0; i <= 100; i += 2) {
            const x = i / 100;
            let y;
            
            if (x < b) {
                y = 5.6 * x * 100;
            } else {
                y = (d + c * Math.log10(x - b + 0.01)) * 100;
            }
            
            // 归一化
            y = Math.max(0, Math.min(100, y * 0.4 + 30));
            data.push([i, y]);
        }
        return data;
    }

    // === Canon C-Log曲线 ===
    if (gammaType === 'CLog') {
        // Canon C-Log (C-Log2)
        for (let i = 0; i <= 100; i += 2) {
            const x = i / 100;
            let y;
            
            if (x <= 0.01) {
                y = x * 10 * 100;
            } else {
                y = (0.5 + 0.5 * Math.log10(x) / Math.log10(0.9)) * 100;
            }
            
            // 归一化
            y = Math.max(0, Math.min(100, y * 0.5 + 25));
            data.push([i, y]);
        }
        return data;
    }

    // === RED Log曲线 ===
    if (gammaType === 'REDLog') {
        // RED Log3G10
        for (let i = 0; i <= 100; i += 2) {
            const x = i / 100;
            // 简化的RED Log曲线
            const y = (0.5 + 0.3 * Math.log10(x + 0.01)) * 100;
            data.push([i, Math.max(0, Math.min(100, y + 20))]);
        }
        return data;
    }

    // === ACEScct曲线 ===
    if (gammaType === 'ACEScct') {
        // ACEScct Log曲线
        const a = 0.4255;
        const b = 0.0771;
        const c = 0.155;
        
        for (let i = 0; i <= 100; i += 2) {
            const x = i / 100;
            let y;
            
            if (x <= a) {
                y = (x / 0.4255 * 0.155) * 100;
            } else {
                y = (Math.pow(10, (x - b) / 0.4255) - 1) / 100 * 100;
            }
            
            // 归一化
            y = Math.max(0, Math.min(100, y * 0.5 + 25));
            data.push([i, y]);
        }
        return data;
    }

    // 默认：纯Gamma 2.2
    for (let i = 0; i <= 100; i += 2) {
        const input = i / 100;
        const output = Math.pow(input, 2.2) * 100;
        data.push([i, output]);
    }
    return data;
}

/**
 * 更新 Gamma 图表预设曲线
 */
function updateGammaChartPresets() {
    if (!gammaChart) return;

    // 构建预设曲线系列
    const presetSeries = [];
    const legendData = [];

    selectedGammas.forEach(gammaType => {
        if (GAMMA_PRESETS[gammaType]) {
            const preset = GAMMA_PRESETS[gammaType];
            presetSeries.push({
                name: preset.name,
                type: 'line',
                data: generateGammaCurveData(gammaType),
                lineStyle: {
                    color: preset.color,
                    width: 1,
                    type: 'dashed',
                    opacity: 0.6
                },
                symbol: 'none',
                smooth: false
            });
            legendData.push(preset.name);
        }
    });

    const option = {
        backgroundColor: '#0d0d14',
        title: { show: false },
        tooltip: {
            trigger: 'item',
            formatter: function(params) {
return t('输入：{v}%<br/>输出：{o} cd/m²', {v: params.value[0], o: params.value[1].toFixed(2)});
            },
            backgroundColor: '#1e1e30',
            borderColor: '#3a3a50',
            textStyle: { color: '#ffffff' }
        },
        grid: {
            left: 40,
            right: 12,
            top: 28,
            bottom: 28,
            containLabel: false
        },
        xAxis: {
            type: 'value',
            min: 0,
            max: 100,
            name: t('输入 (%)'),
            nameLocation: 'middle',
            nameGap: 15,
            nameTextStyle: {
                color: '#8888a0',
                fontSize: 10,
                padding: [0, 0, 0, 0]
            },
            axisLine: {
                show: false
            },
            axisTick: {
                show: false
            },
            axisLabel: {
                color: '#8888a0',
                fontSize: 9,
                position: 'insideBottom'
            },
            splitLine: {
                lineStyle: {
                    color: '#2a2a3d'
                }
            }
        },
        yAxis: {
            type: 'value',
            min: 0,
            max: 100,
            name: t('亮度'),
            nameLocation: 'middle',
            nameGap: 15,
            nameTextStyle: {
                color: '#8888a0',
                fontSize: 10,
                padding: [0, 0, 0, 0]
            },
            axisLine: {
                show: false
            },
            axisTick: {
                show: false
            },
            axisLabel: {
                color: '#8888a0',
                fontSize: 9,
                position: 'insideLeft'
            },
            splitLine: {
                lineStyle: {
                    color: '#2a2a3d'
                }
            }
        },
        series: [
            // 预设曲线（动态）
            ...presetSeries,
            // 测量曲线 - 实线
            {
                name: '测量曲线',
                type: 'line',
                data: [],
                lineStyle: {
                    color: '#3b82f6',
                    width: 2
                },
                symbol: 'circle',
                symbolSize: 6,
                itemStyle: {
                    color: '#3b82f6'
                },
                smooth: false
            }
        ],
        legend: {
            data: [...legendData, '测量曲线'],
            formatter: function (name) { return window.I18N ? I18N.t(name) : name; },
            top: 5,
            right: 5,
            textStyle: {
                color: '#8888a0',
                fontSize: 10
            },
            itemWidth: 15,
            itemHeight: 10
        }
    };

    gammaChart.setOption(option, true);
}

/**
 * 更新 CIE 图表 - 添加测量点
 */
function updateCIEChartPoint(result) {
    if (!cieChart) return;

    const x = result.x;
    const y = result.y;
    const name = result.patchName;

    // 根据色块名称确定颜色
    let pointColor = '#3b82f6';
    if (name === '红') pointColor = '#ff4444';
    else if (name === '绿') pointColor = '#44ff44';
    else if (name === '蓝') pointColor = '#4444ff';
    else if (name === '白') pointColor = '#ffffff';
    else if (name === '黑') pointColor = '#333333';
    else if (name && name.includes('%')) pointColor = '#888888';
    else if (name && name.startsWith('采样')) pointColor = '#66aaff';

    // 获取当前图表选项
    const option = cieChart.getOption();

    // 查找测量点系列
    let measurePointsSeries = option.series.find(s => s.name === '测量点');
    if (!measurePointsSeries) {
        // 如果没有找到，创建新的系列
        measurePointsSeries = {
            name: '测量点',
            type: 'scatter',
            data: [],
            symbol: 'circle',
            symbolSize: 9,
            itemStyle: {
                color: pointColor,
                shadowColor: 'rgba(0,0,0,0.5)',
                shadowBlur: 4
            },
            z: 100
        };
        option.series.push(measurePointsSeries);
    }

    // 检查是否已存在同名点，如果存在则替换
    const existingIndex = measurePointsSeries.data.findIndex(p => p.name === name);
    const newPoint = {
        value: [x, y],
        name: name,
        itemStyle: {
            color: pointColor
        }
    };

    if (existingIndex >= 0) {
        // 替换已存在的点（支持单次测量替换）
        measurePointsSeries.data[existingIndex] = newPoint;
    } else {
        // 添加新点
        measurePointsSeries.data.push(newPoint);
    }

    cieChart.setOption(option);

    // 如果有 RGB 数据，尝试更新色域三角形
    if (name === '红' || name === '绿' || name === '蓝' || name === '白') {
        updateGamutTriangleFromMeasurements();
    }
}

/**
 * 从测量数据更新色域三角形
 */
function updateGamutTriangleFromMeasurements() {
    if (!cieChart) return;

    // 从测量点数据中提取 RGB 和白点
    const option = cieChart.getOption();
    const measurePointsSeries = option.series.find(s => s.name === '测量点');

    if (!measurePointsSeries || !measurePointsSeries.data) return;

    const redPoint = measurePointsSeries.data.find(p => p.name === '红');
    const greenPoint = measurePointsSeries.data.find(p => p.name === '绿');
    const bluePoint = measurePointsSeries.data.find(p => p.name === '蓝');
    const whitePoint = measurePointsSeries.data.find(p => p.name === '白');

    // 只有当 RGB 三点都存在时才更新三角形
    if (redPoint && greenPoint && bluePoint) {
        const triangleData = [
            redPoint.value,
            greenPoint.value,
            bluePoint.value,
            redPoint.value  // 闭合
        ];

        const gamutSeries = option.series.find(s => s.name === '测量色域');
        if (gamutSeries) {
            gamutSeries.data = triangleData;
        }

        // 更新白点
        if (whitePoint) {
            const whiteSeries = option.series.find(s => s.name === '测量白点');
            if (whiteSeries) {
                whiteSeries.data = [whitePoint.value];
            }
        }

        cieChart.setOption(option);
    }
}

/**
 * 更新 CIE 图表 - 显示完整色域三角形
 */
function updateCIEChartGamut(coverageData) {
    if (!cieChart) return;

    try {
        // 兼容对象和字符串两种格式
        const data = (typeof coverageData === 'string') ? JSON.parse(coverageData) : coverageData;

        // 更新色域三角形
        if (data.gamutTriangle && data.gamutTriangle.length === 3) {
            const triangleData = [
                data.gamutTriangle[0],  // 红
                data.gamutTriangle[1],  // 绿
                data.gamutTriangle[2],  // 蓝
                data.gamutTriangle[0]   // 闭合
            ];

            const option = cieChart.getOption();
            const gamutSeries = option.series.find(s => s.name === '测量色域');
            if (gamutSeries) {
                gamutSeries.data = triangleData;
            }
            cieChart.setOption(option);
        }

        // 更新白点
        if (data.whitePoint) {
            const option = cieChart.getOption();
            const whiteSeries = option.series.find(s => s.name === '测量白点');
            if (whiteSeries) {
                whiteSeries.data = [data.whitePoint];
            }
            cieChart.setOption(option);
        }

        // 更新色域覆盖率显示
        if (data.sRGB) {
            document.getElementById('gamut-srgb').textContent = data.sRGB + '%';
        }
        if (data.DCI_P3) {
            document.getElementById('gamut-p3').textContent = data.DCI_P3 + '%';
        }
        if (data.AdobeRGB) {
            document.getElementById('gamut-adobe').textContent = data.AdobeRGB + '%';
        }

    } catch (e) {
        console.error('解析色域数据失败:', e);
    }
}

/**
 * 更新 Gamma 曲线图
 */
function updateGammaChart(gammaData) {
    if (!gammaChart) return;

    try {
        const data = (typeof gammaData === 'string') ? JSON.parse(gammaData) : gammaData;

        // 更新 Gamma 值显示
        if (data.gamma) {
            const gammaValue = document.getElementById('gamma-value');
            const displayGamma = document.getElementById('display-gamma');
            if (gammaValue) {
                gammaValue.textContent = data.gamma.toFixed(2);
            }
            if (displayGamma) {
                displayGamma.textContent = data.gamma.toFixed(2);
            }
        }

        // 更新曲线数据
        if (data.curve && data.curve.length > 0) {
            const curvePoints = data.curve.map(point => [
                point.input,
                point.Y
            ]);

            // 按输入级别排序
            curvePoints.sort((a, b) => a[0] - b[0]);

            const option = gammaChart.getOption();
            const measureSeries = option.series.find(s => s.name === '测量曲线');
            if (measureSeries) {
                measureSeries.data = curvePoints;
            }
            gammaChart.setOption(option);
        }

    } catch (e) {
        console.error('解析 Gamma 数据失败:', e);
    }
}

/**
 * 直接从测量结果更新 Gamma 曲线（用于单次测量）
 * @param {Object} result - 测量结果
 */
function updateGammaChartFromResult(result) {
    if (!gammaChart || !result.patchName || !result.patchName.includes('%')) return;

    // 从 patchName 解析输入级别
    const inputLevel = parseFloat(result.patchName.replace('%', ''));

    // 获取当前图表选项
    const option = gammaChart.getOption();
    const measureSeries = option.series.find(s => s.name === '测量曲线');

    if (!measureSeries) return;

    // 检查是否已存在同级别的点，如果存在则替换
    const existingIndex = measureSeries.data.findIndex(p => p[0] === inputLevel);
    const newPoint = [inputLevel, result.Y];

    if (existingIndex >= 0) {
        // 替换已存在的点（支持单次测量替换）
        measureSeries.data[existingIndex] = newPoint;
    } else {
        // 添加新点
        measureSeries.data.push(newPoint);
    }

    // 按输入级别排序
    measureSeries.data.sort((a, b) => a[0] - b[0]);

    gammaChart.setOption(option);
}

/**
 * 清除所有图表数据
 */
function clearCharts() {
    if (cieChart) {
        const option = cieChart.getOption();
        // 清除测量色域
        const gamutSeries = option.series.find(s => s.name === '测量色域');
        if (gamutSeries) gamutSeries.data = [];
        // 清除测量白点
        const whiteSeries = option.series.find(s => s.name === '测量白点');
        if (whiteSeries) whiteSeries.data = [];
        // 清除测量点
        const pointsSeries = option.series.find(s => s.name === '测量点');
        if (pointsSeries) pointsSeries.data = [];
        cieChart.setOption(option);
    }

    if (gammaChart) {
        const option = gammaChart.getOption();
        const measureSeries = option.series.find(s => s.name === '测量曲线');
        if (measureSeries) measureSeries.data = [];
        gammaChart.setOption(option);
    }

    // 清除数据存储
    measuredGamut = null;
    measuredWhitePoint = null;
    gammaCurveData = [];

    // P2 集成：清除饱和度/CCT 追踪数据与图表
    if (typeof clearTrackingCharts === 'function') {
        clearTrackingCharts();
    }
    if (typeof saturationChart !== 'undefined' && saturationChart) {
        saturationChart.setOption({ series: [] });
    }
    if (typeof cctChart !== 'undefined' && cctChart) {
        cctChart.setOption({ xAxis: { data: [] }, series: [{ data: [] }, { data: [] }] });
    }
}

/**
 * 从历史数据重新渲染图表
 * 用于加载历史测量数据后更新图表显示
 *
 * @param {Object} measurementData - 测量数据对象，包含 gamut 和 gamma 数据
 */
function renderChartsFromHistory(measurementData) {
    // 先清空图表
    clearCharts();

    // 渲染色域数据
    if (measurementData.gamut) {
        // 添加测量点
        for (const [chnName, data] of Object.entries(measurementData.gamut)) {
            if (data && data.x && data.y) {
                updateCIEChartPoint({
                    patchName: chnName,
                    x: data.x,
                    y: data.y,
                    Y: data.Y
                });
            }
        }
    }

    // 渲染Gamma数据
    if (measurementData.grayScale && measurementData.grayScale.length > 0) {
        measurementData.grayScale.forEach(point => {
            if (point.patchName && point.patchName.includes('%')) {
                updateGammaChartFromResult({
                    patchName: point.patchName,
                    Y: point.Y
                });
            }
        });

        // 计算并显示Gamma值（简化计算）
        const curvePoints = measurementData.grayScale.map(point => {
            let inputLevel = 50;
            if (point.patchName && point.patchName.includes('%')) {
                inputLevel = parseFloat(point.patchName.replace('%', ''));
            }
            return [inputLevel, point.Y];
        }).sort((a, b) => a[0] - b[0]);

        // 获取白色Y值用于归一化（使用测量数据中的白色，而不是gamma数组的最后一个点）
        const whiteY = measurementData.gamut && measurementData.gamut['白'] ? measurementData.gamut['白'].Y : null;

        if (curvePoints.length >= 2) {
            const gamma = calculateGammaFromCurve(curvePoints, whiteY);
            const gammaValue = document.getElementById('gamma-value');
            const displayGamma = document.getElementById('display-gamma');
            if (gammaValue) {
                gammaValue.textContent = gamma.toFixed(2);
            }
            if (displayGamma) {
                displayGamma.textContent = gamma.toFixed(2);
            }
        }
    }
}

/**
 * 从曲线数据计算Gamma值
 * @param {Array} curvePoints - 曲线点数组 [[inputLevel, Y], ...]
 * @param {number|null} whiteY - 白色Y值（用于归一化），如果为null则使用最后一个点
 * @returns {number} Gamma值
 */
function calculateGammaFromCurve(curvePoints, whiteY = null) {
    if (curvePoints.length < 2) return 2.2;

    // 使用白色Y值进行归一化，如果没有则使用最后一个点
    const normalizeY = whiteY !== null ? whiteY : curvePoints[curvePoints.length - 1][1];

    // 使用50%附近的点计算Gamma
    const midPoints = curvePoints.filter(p => p[0] >= 40 && p[0] <= 60);

    if (midPoints.length < 2) {
        // 如果没有中间点，使用所有点计算平均Gamma
        let totalGamma = 0;
        let count = 0;

        for (const point of curvePoints) {
            if (point[0] > 0 && point[1] > 0) {
                const inputNorm = point[0] / 100;
                const outputNorm = point[1] / normalizeY;  // 相对于白色亮度
                if (inputNorm > 0 && outputNorm > 0) {
                    const gamma = Math.log(outputNorm) / Math.log(inputNorm);
                    if (gamma >= 1.5 && gamma <= 3.5) {
                        totalGamma += gamma;
                        count++;
                    }
                }
            }
        }

        return count > 0 ? totalGamma / count : 2.2;
    }

    // 使用中间点计算
    const p1 = midPoints[0];
    const p2 = midPoints[midPoints.length - 1];

    const input1 = p1[0] / 100;
    const input2 = p2[0] / 100;
    const output1 = p1[1] / normalizeY;  // 使用白色Y值归一化
    const output2 = p2[1] / normalizeY;

    if (input1 > 0 && input2 > 0 && output1 > 0 && output2 > 0) {
        // 使用两点法计算Gamma
        const avgInput = (input1 + input2) / 2;
        const avgOutput = (output1 + output2) / 2;
        return Math.log(avgOutput) / Math.log(avgInput);
    }

    return 2.2;
}

/**
 * 显示完整的 EOTF 误差报告（目标曲线 + 实测曲线）
 *
 * @param {Object} reportData - EOTF 报告数据
 *   - average_gamma: 平均 Gamma 值
 *   - black_luminance: 黑场亮度 Lb
 *   - white_luminance: 白场亮度 Lw
 *   - contrast_ratio: 对比度
 *   - curve_errors: 各曲线误差 {gamma2.2, gamma2.4, sRGB, BT.1886}
 *   - bt1886: BT.1886 详细报告
 *   - points: 测量点数据 [{input, Y, patchName}, ...]
 */
function displayEOTFReport(reportData) {
    if (!reportData) return;

    // 解析数据（支持字符串和对象格式；畸形数据不中断图表更新）
    let data;
    if (typeof reportData === 'string') {
        try {
            data = JSON.parse(reportData);
        } catch (e) {
            console.error('[charts] displayEOTFReport JSON 解析失败:', e);
            return;
        }
    } else {
        data = reportData;
    }

    // 更新 Gamma 值显示
    if (data.average_gamma) {
        const gammaValue = document.getElementById('gamma-value');
        const displayGamma = document.getElementById('display-gamma');
        if (gammaValue) {
            gammaValue.textContent = data.average_gamma.toFixed(2);
        }
        if (displayGamma) {
            displayGamma.textContent = data.average_gamma.toFixed(2);
        }
    }

    // 更新亮度显示
    if (data.white_luminance) {
        const peakLum = document.getElementById('peak-luminance');
        if (peakLum) {
            peakLum.textContent = data.white_luminance.toFixed(1) + ' cd/m²';
        }
    }

    if (data.black_luminance) {
        const blackLum = document.getElementById('black-luminance');
        if (blackLum) {
            blackLum.textContent = data.black_luminance.toFixed(3) + ' cd/m²';
        }
    }

    if (data.contrast_ratio) {
        const contrast = document.getElementById('contrast-ratio');
        if (contrast) {
            contrast.textContent = data.contrast_ratio.toFixed(0) + ':1';
        }
    }

    // 更新曲线误差显示
    if (data.curve_errors) {
        updateCurveErrorDisplay(data.curve_errors);
    }

    // 更新 BT.1886 详细数据
    if (data.bt1886) {
        updateBT1886Display(data.bt1886);
    }

    // 更新 Gamma 图表显示实测曲线
    if (data.points && data.points.length > 0) {
        updateGammaChartWithEOTF(data);
    }
}

/**
 * 更新曲线误差显示
 */
function updateCurveErrorDisplay(curveErrors) {
    // Gamma 2.2
    if (curveErrors.gamma2_2 || curveErrors['gamma2.2']) {
        const err = curveErrors.gamma2_2 || curveErrors['gamma2.2'];
        const elem = document.getElementById('gamma2-2-error');
        if (elem) {
            elem.textContent = t('平均误差: ') + err.mean_error.toFixed(2) + ' cd/m²';
        }
    }

    // Gamma 2.4
    if (curveErrors.gamma2_4 || curveErrors['gamma2.4']) {
        const err = curveErrors.gamma2_4 || curveErrors['gamma2.4'];
        const elem = document.getElementById('gamma2-4-error');
        if (elem) {
            elem.textContent = t('平均误差: ') + err.mean_error.toFixed(2) + ' cd/m²';
        }
    }

    // sRGB
    if (curveErrors.sRGB) {
        const elem = document.getElementById('srgb-error');
        if (elem) {
            elem.textContent = t('平均误差: ') + curveErrors.sRGB.mean_error.toFixed(2) + ' cd/m²';
        }
    }

    // BT.1886
    if (curveErrors['BT.1886'] || curveErrors.BT1886) {
        const err = curveErrors['BT.1886'] || curveErrors.BT1886;
        const elem = document.getElementById('bt1886-error');
        if (elem) {
            elem.textContent = t('平均误差: ') + err.mean_error.toFixed(2) + ' cd/m²';
        }
    }
}

/**
 * 更新 BT.1886 详细数据显示
 */
function updateBT1886Display(bt1886Data) {
    // 显示 Lb 和 Lw 参数
    const lbElem = document.getElementById('bt1886-lb');
    if (lbElem && bt1886Data.Lb) {
        lbElem.textContent = bt1886Data.Lb.toFixed(3) + ' cd/m²';
    }

    const lwElem = document.getElementById('bt1886-lw');
    if (lwElem && bt1886Data.Lw) {
        lwElem.textContent = bt1886Data.Lw.toFixed(1) + ' cd/m²';
    }

    // 显示误差统计
    if (bt1886Data.errors) {
        const meanElem = document.getElementById('bt1886-mean-error');
        if (meanElem) {
            meanElem.textContent = bt1886Data.errors.mean_error.toFixed(2) + ' cd/m²';
        }

        const maxElem = document.getElementById('bt1886-max-error');
        if (maxElem) {
            maxElem.textContent = bt1886Data.errors.max_error.toFixed(2) + ' cd/m²';
        }

        const darkElem = document.getElementById('bt1886-dark-error');
        if (darkElem) {
            darkElem.textContent = bt1886Data.errors.dark_error.toFixed(2) + ' cd/m²';
        }
    }
}

/**
 * 更新 Gamma 图表，显示实测曲线与目标曲线对比
 */
function updateGammaChartWithEOTF(reportData) {
    if (!gammaChart) return;

    // 构建实测曲线数据
    const measuredCurve = [];
    if (reportData.points) {
        reportData.points.forEach(point => {
            measuredCurve.push([
                point.input * 100,  // 输入百分比
                point.Y             // 实测亮度
            ]);
        });
        measuredCurve.sort((a, b) => a[0] - b[0]);
    }

    // 构建目标曲线数据（使用 BT.1886 参数）
    let targetCurve = [];
    if (reportData.bt1886 && reportData.bt1886.Lw && reportData.bt1886.Lb) {
        const Lw = reportData.bt1886.Lw;
        const Lb = reportData.bt1886.Lb;
        const gamma = 2.4;

        for (let i = 0; i <= 100; i += 2) {
            const V = i / 100;
            const L = (Lw - Lb) * Math.pow(V, gamma) + Lb;
            targetCurve.push([i, L]);
        }
    }

    // 更新图表
    const option = gammaChart.getOption();

    // 更新实测曲线
    const measureSeries = option.series.find(s => s.name === '测量曲线');
    if (measureSeries) {
        measureSeries.data = measuredCurve;
    }

    // 如果有目标曲线数据，更新预设曲线（BT.1886）
    if (targetCurve.length > 0) {
        const bt1886Series = option.series.find(s => s.name === 'BT.1886');
        if (bt1886Series) {
            bt1886Series.data = targetCurve;
            bt1886Series.lineStyle = {
                color: '#fdcb6e',
                width: 1.5,
                type: 'dashed',
                opacity: 0.8
            };
        }
    }

    gammaChart.setOption(option);
}

/**
 * 生成目标曲线数据（用于图表）
 *
 * @param {string} curveType - 曲线类型
 * @param {Object} params - 曲线参数 {Lw, Lb, L_max}
 * @returns {Array} 曲线数据 [[input%, luminance], ...]
 */
function generateTargetCurve(curveType, params = {}) {
    const data = [];

    // 获取参数
    const Lw = params.Lw || 100;
    const Lb = params.Lb || 0;
    const L_max = params.L_max || 10000;

    for (let i = 0; i <= 100; i += 2) {
        const V = i / 100;
        let L;

        switch (curveType) {
            case 'gamma2.2':
                L = Math.pow(V, 2.2) * Lw;
                break;

            case 'gamma2.4':
                L = Math.pow(V, 2.4) * Lw;
                break;

            case 'sRGB':
                if (V <= 0.04045) {
                    L = (V / 12.92) * Lw;
                } else {
                    L = Math.pow((V + 0.055) / 1.055, 2.4) * Lw;
                }
                break;

            case 'BT.1886':
                L = (Lw - Lb) * Math.pow(V, 2.4) + Lb;
                break;

            case 'PQ':
                // SMPTE ST 2084 PQ
                const m1 = 2610 / 16384;
                const m2 = 2523 / 4096 * 128;
                const c1 = 3424 / 4096;
                const c2 = 2413 / 4096 * 32;
                const c3 = 2392 / 4096 * 32;

                const N_m1 = Math.pow(V, m1);
                const numerator = Math.max(N_m1 - c1, 0);
                const denominator = c2 - c3 * N_m1;
                L = Math.pow(numerator / denominator, m2) * L_max;
                // 归一化到白场亮度
                L = (L / L_max) * Lw;
                break;

            case 'HLG':
                // ITU-R BT.2100 HLG
                const a = 0.17883277;
                const b = 0.28466892;
                const c = 0.55991073;

                if (V <= 0.5) {
                    L = 3 * V * V * Lw;
                } else {
                    L = (Math.exp((V - c) / a) + b) * Lw * 0.1;
                }
                break;

            default:
                L = Math.pow(V, 2.2) * Lw;
        }

        data.push([i, L]);
    }

    return data;
}

/**
 * 重新调整图表大小
 * CSS aspect-ratio 已强制锁定容器宽高比，只需调用 ECharts resize
 */
function resizeCharts() {
    if (cieChart) {
        cieChart.resize();
    }
    if (gammaChart) {
        gammaChart.resize();
    }
    if (validationDeltaEChart) {
        validationDeltaEChart.resize();
    }
    if (validationComparisonChart) {
        validationComparisonChart.resize();
    }
}

/**
 * 页面加载完成后初始化图表
 */
document.addEventListener('DOMContentLoaded', function() {
    // 等待一小段时间确保 DOM 完全加载
    setTimeout(function() {
        initCIEChart();
        initGammaChart();
    }, 100);
});

// ==============================================================================
// P4-D 验证图表支持
// ==============================================================================

// 验证图表实例
let validationDeltaEChart = null;
let validationComparisonChart = null;

// 验证阈值预设
const VALIDATION_THRESHOLDS = {
    'sRGB': {
        delta_e_avg: 2.0,
        delta_e_max: 6.0,
        white_point_cct_tolerance: 200,
        white_point_duv_tolerance: 0.005,
        gamma_tolerance: 0.05,
        gamut_coverage_threshold: 95,
        name: 'sRGB (IEC 61966-2-1)'
    },
    'Rec.709': {
        delta_e_avg: 2.0,
        delta_e_max: 6.0,
        white_point_cct_tolerance: 200,
        white_point_duv_tolerance: 0.005,
        gamma_tolerance: 0.05,
        gamut_coverage_threshold: 95,
        name: 'Rec.709 (BT.709)'
    },
    'DCI-P3': {
        delta_e_avg: 3.0,
        delta_e_max: 8.0,
        white_point_cct_tolerance: 300,
        white_point_duv_tolerance: 0.007,
        gamma_tolerance: 0.05,
        gamut_coverage_threshold: 90,
        name: 'DCI-P3 (SMPTE RP 431-2)'
    },
    'Rec.2020': {
        delta_e_avg: 3.0,
        delta_e_max: 8.0,
        white_point_cct_tolerance: 200,
        white_point_duv_tolerance: 0.005,
        gamma_tolerance: 0.05,
        gamut_coverage_threshold: 80,
        name: 'Rec.2020 (BT.2020)'
    },
    'AdobeRGB': {
        delta_e_avg: 2.5,
        delta_e_max: 7.0,
        white_point_cct_tolerance: 200,
        white_point_duv_tolerance: 0.005,
        gamma_tolerance: 0.05,
        gamut_coverage_threshold: 90,
        name: 'Adobe RGB (1998)'
    }
};

/**
 * 初始化验证 Delta E 图表
 * 显示各色块的 Delta E 值分布
 */
function initValidationDeltaEChart() {
    const chartDom = document.getElementById('validation-delta-e-chart');
    if (!chartDom) return;

    validationDeltaEChart = echarts.init(chartDom);

    const option = {
        backgroundColor: '#0d0d14',
        title: {
            text: t('验证 Delta E 分布'),
            left: 'center',
            top: 10,
            textStyle: {
                color: '#8888a0',
                fontSize: 14
            }
        },
        tooltip: {
            trigger: 'item',
            backgroundColor: '#1e1e30',
            borderColor: '#3a3a50',
            textStyle: { color: '#ffffff' },
            formatter: function(params) {
                if (params.seriesName === 'Delta E') {
return t('色块: {name}<br/>Delta E: {de}', {name: params.name, de: params.value.toFixed(2)});
                }
                return params.name;
            }
        },
        grid: {
            left: 50,
            right: 20,
            top: 50,
            bottom: 40
        },
        xAxis: {
            type: 'category',
            data: [],
            axisLine: { lineStyle: { color: '#5a5a7a' } },
            axisLabel: {
                color: '#8888a0',
                fontSize: 10,
                interval: 0,
                rotate: 45
            }
        },
        yAxis: {
            type: 'value',
            name: 'Delta E',
            nameTextStyle: { color: '#8888a0' },
            axisLine: { lineStyle: { color: '#5a5a7a' } },
            axisLabel: { color: '#8888a0' },
            splitLine: {
                lineStyle: { color: '#2a2a3d', type: 'dashed' }
            }
        },
        series: [
            {
                name: 'Delta E',
                type: 'bar',
                data: [],
                itemStyle: {
                    color: function(params) {
                        // 根据 Delta E 值设置颜色
                        const value = params.value;
                        const threshold = VALIDATION_THRESHOLDS['sRGB'];
                        if (value < threshold.delta_e_avg) {
                            return '#10b981'; // 绿色 - 合格
                        } else if (value < threshold.delta_e_max) {
                            return '#f59e0b'; // 黄色 - 警告
                        } else {
                            return '#ef4444'; // 红色 - 不合格
                        }
                    }
                },
                markLine: {
                    silent: true,
                    data: [
                        { yAxis: 2.0, name: '平均阈值', lineStyle: { color: '#f59e0b', type: 'dashed' } },
                        { yAxis: 6.0, name: '最大阈值', lineStyle: { color: '#ef4444', type: 'dashed' } }
                    ],
                    label: {
                        show: true,
                        position: 'end',
                        formatter: '{b}',
                        color: '#8888a0'
                    }
                }
            }
        ]
    };

    validationDeltaEChart.setOption(option);
}

/**
 * 更新验证 Delta E 图表数据
 *
 * @param {Object} validationData - 验证数据
 *   { verification_points: [{name, delta_e, rgb}, ...], threshold: {...}, standard: 'sRGB' }
 */
function updateValidationDeltaEChart(validationData) {
    if (!validationDeltaEChart || !validationData) return;

    const points = validationData.verification_points || [];
    const standard = validationData.standard || 'sRGB';
    const threshold = VALIDATION_THRESHOLDS[standard] || VALIDATION_THRESHOLDS['sRGB'];

    const categories = points.map(p => p.name || `Patch ${p.rgb.join(',')}`);
    const values = points.map(p => p.delta_e || 0);

    validationDeltaEChart.setOption({
        title: {
            text: t('验证 Delta E 分布 ({threshold_name})', {threshold_name: threshold.name})
        },
        xAxis: {
            data: categories
        },
        yAxis: {
            max: Math.max(Math.max(...values) * 1.2, threshold.delta_e_max * 1.2)
        },
        series: [{
            data: values,
            markLine: {
                data: [
                    { yAxis: threshold.delta_e_avg, name: '平均阈值', lineStyle: { color: '#f59e0b' } },
                    { yAxis: threshold.delta_e_max, name: '最大阈值', lineStyle: { color: '#ef4444' } }
                ]
            }
        }]
    });
}

/**
 * 初始化 Before/After 对比图表
 * 显示校准前后指标对比
 */
function initValidationComparisonChart() {
    const chartDom = document.getElementById('validation-comparison-chart');
    if (!chartDom) return;

    validationComparisonChart = echarts.init(chartDom);

    const option = {
        backgroundColor: '#0d0d14',
        title: {
            text: t('校准前后对比'),
            left: 'center',
            top: 10,
            textStyle: {
                color: '#8888a0',
                fontSize: 14
            }
        },
        tooltip: {
            trigger: 'axis',
            backgroundColor: '#1e1e30',
            borderColor: '#3a3a50',
            textStyle: { color: '#ffffff' },
            axisPointer: {
                type: 'shadow'
            }
        },
        legend: {
            data: ['校准前', '校准后', '改善'],
            formatter: function (name) { return window.I18N ? I18N.t(name) : name; },
            top: 40,
            textStyle: { color: '#8888a0' }
        },
        grid: {
            left: 50,
            right: 20,
            top: 70,
            bottom: 40
        },
        xAxis: {
            type: 'category',
            data: ['Delta E (avg)', '白点 Duv', 'Gamma 偏移', '色域覆盖率', '对比度'],
            axisLine: { lineStyle: { color: '#5a5a7a' } },
            axisLabel: {
                color: '#8888a0',
                fontSize: 11
            }
        },
        yAxis: {
            type: 'value',
            name: t('数值'),
            nameTextStyle: { color: '#8888a0' },
            axisLine: { lineStyle: { color: '#5a5a7a' } },
            axisLabel: { color: '#8888a0' },
            splitLine: {
                lineStyle: { color: '#2a2a3d', type: 'dashed' }
            }
        },
        series: [
            {
                name: '校准前',
                type: 'bar',
                data: [],
                itemStyle: { color: '#ef4444' },
                barGap: '10%'
            },
            {
                name: '校准后',
                type: 'bar',
                data: [],
                itemStyle: { color: '#10b981' }
            },
            {
                name: '改善',
                type: 'line',
                data: [],
                itemStyle: { color: '#4da6ff' },
                lineStyle: { width: 2 },
                symbol: 'circle',
                symbolSize: 8
            }
        ]
    };

    validationComparisonChart.setOption(option);
}

/**
 * 更新 Before/After 对比图表数据
 *
 * @param {Object} comparisonData - 对比数据
 *   { before: {...}, after: {...}, improvements: {...} }
 */
function updateValidationComparisonChart(comparisonData) {
    if (!validationComparisonChart || !comparisonData) return;

    const before = comparisonData.before || {};
    const after = comparisonData.after || {};
    const improvements = comparisonData.improvements || {};

    // 构建对比数据
    // 注意：不同指标的单位不同，需要适当归一化或分组显示
    const beforeValues = [
        before.delta_e_avg || 0,
        Math.abs(before.white_point?.duv || 0) * 100, // Duv * 100 放大显示
        Math.abs(before.gamma_offset || 0) * 10, // Gamma offset * 10 放大
        before.gamut_coverage || 0,
        Math.log10(before.contrast_ratio || 1000) // 对比度用 log10 显示
    ];

    const afterValues = [
        after.delta_e_avg || 0,
        Math.abs(after.white_point?.duv || 0) * 100,
        Math.abs(after.gamma_offset || 0) * 10,
        after.gamut_coverage || 0,
        Math.log10(after.contrast_ratio || 1000)
    ];

    // 改善值（百分比）
    const improvementValues = [
        (improvements.delta_e_avg?.improvement || 0) > 0 ? 1 : -1,
        (improvements.white_point_duv?.improvement || 0) > 0 ? 1 : -1,
        (improvements.gamma_offset?.improvement || 0) > 0 ? 1 : -1,
        (improvements.gamut_coverage?.improvement || 0) > 0 ? 1 : -1,
        (improvements.contrast_ratio?.improvement || 0) > 0 ? 1 : -1
    ];

    validationComparisonChart.setOption({
        series: [
            { data: beforeValues },
            { data: afterValues },
            {
                data: improvementValues,
                // 改善用不同颜色标记
                itemStyle: {
                    color: function(params) {
                        return params.value > 0 ? '#10b981' : '#ef4444';
                    }
                }
            }
        ]
    });
}

/**
 * 显示验证结果摘要
 *
 * @param {Object} validationResult - 验证结果
 *   { status: 'PASSED'|'FAILED'|'WARNING', summary: {...}, metrics: {...} }
 */
function displayValidationSummary(validationResult) {
    const container = document.getElementById('validation-summary');
    if (!container || !validationResult) return;

    const summary = validationResult.summary || {};
    const status = summary.status || 'UNKNOWN';
    const passedCount = summary.passed_count || 0;
    const totalCount = summary.total_count || 4;

    // 状态颜色
    let statusColor, statusText, statusIcon;
    if (status === 'PASSED') {
        statusColor = '#10b981';
        statusText = t('合格');
        statusIcon = '&#10004;'; // ✓
    } else if (status === 'WARNING') {
        statusColor = '#f59e0b';
        statusText = t('警告');
        statusIcon = '&#9888;'; // ⚠
    } else {
        statusColor = '#ef4444';
        statusText = t('不合格');
        statusIcon = '&#10008;'; // ✗
    }

    container.innerHTML = `
        <div class="validation-status" style="text-align: center; margin: 20px;">
            <span style="font-size: 48px; color: ${statusColor};">${statusIcon}</span>
            <div style="font-size: 24px; color: ${statusColor}; margin-top: 10px;">${statusText}</div>
            <div style="color: #8888a0; margin-top: 5px;">${passedCount}/${totalCount} 项指标合格</div>
            <div style="color: #8888a0; margin-top: 10px; font-size: 14px;">${summary.summary_text || ''}</div>
        </div>
        <div class="validation-details" style="margin-top: 20px;">
            ${generateValidationDetailsHTML(validationResult)}
        </div>
    `;
}

/**
 * 生成验证详情 HTML
 */
function generateValidationDetailsHTML(validationResult) {
    const validation = validationResult.validation || {};
    const metrics = validationResult.metrics || {};

    let html = '<table style="width: 100%; border-collapse: collapse;">';
    html += '<tr style="border-bottom: 1px solid #3a3a50;">';
    html += '<th style="color: #8888a0; padding: 8px; text-align: left;">指标</th>';
    html += '<th style="color: #8888a0; padding: 8px; text-align: center;">测量值</th>';
    html += '<th style="color: #8888a0; padding: 8px; text-align: center;">阈值</th>';
    html += '<th style="color: #8888a0; padding: 8px; text-align: center;">状态</th>';
    html += '</tr>';

    // Delta E
    if (validation.delta_e) {
        html += generateValidationRowHTML('Delta E (平均)', validation.delta_e.avg, validation.delta_e.threshold_avg, validation.delta_e.passed);
        html += generateValidationRowHTML('Delta E (最大)', validation.delta_e.max, validation.delta_e.threshold_max, validation.delta_e.passed);
    }

    // 白点
    if (validation.white_point) {
        html += generateValidationRowHTML('白点 CCT', validation.white_point.cct, '6500K ±' + validation.white_point.threshold_cct + 'K', validation.white_point.passed);
        html += generateValidationRowHTML('白点 Duv', validation.white_point.duv.toFixed(4), '< ' + validation.white_point.threshold_duv, validation.white_point.passed);
    }

    // Gamma
    if (validation.gamma) {
        html += generateValidationRowHTML('Gamma', validation.gamma.gamma.toFixed(2), '2.2 ±' + validation.gamma.threshold, validation.gamma.passed);
    }

    // 色域
    if (validation.gamut) {
        html += generateValidationRowHTML('色域覆盖率', validation.gamut.coverage.toFixed(1) + '%', '> ' + validation.gamut.threshold + '%', validation.gamut.passed);
    }

    html += '</table>';
    return html;
}

/**
 * 生成验证行 HTML
 */
function generateValidationRowHTML(name, value, threshold, passed) {
    const color = passed ? '#10b981' : '#ef4444';
    const icon = passed ? '&#10004;' : '&#10008;';

    return `
        <tr style="border-bottom: 1px solid #2a2a3d;">
            <td style="color: #a0a0b8; padding: 8px;">${name}</td>
            <td style="color: #ffffff; padding: 8px; text-align: center;">${value}</td>
            <td style="color: #8888a0; padding: 8px; text-align: center;">${threshold}</td>
            <td style="color: ${color}; padding: 8px; text-align: center;">${icon}</td>
        </tr>
    `;
}

/**
 * 初始化所有验证图表
 */
function initValidationCharts() {
    setTimeout(function() {
        initValidationDeltaEChart();
        initValidationComparisonChart();
    }, 100);
}

// 导出验证相关函数（供全局调用）
window.updateValidationDeltaEChart = updateValidationDeltaEChart;
window.updateValidationComparisonChart = updateValidationComparisonChart;
window.displayValidationSummary = displayValidationSummary;
window.initValidationCharts = initValidationCharts;
window.VALIDATION_THRESHOLDS = VALIDATION_THRESHOLDS;

// ==============================================================================
// P6-B 实时图表更新（使用 requestAnimationFrame，不阻塞主线程）
// ==============================================================================

/**
 * 实时图表更新管理器
 *
 * 性能优化策略：
 * 1. 使用 requestAnimationFrame 代替 setTimeout，与浏览器渲染周期同步
 * 2. 批量更新：累积多个数据点后一次性更新，减少重绘次数
 * 3. 节流控制：限制最小更新间隔（默认 50ms），确保 UI 响应性
 * 4. 数据缓存：使用 pendingUpdates 缓存待更新数据，避免频繁操作 ECharts
 * 5. 按需渲染：只在数据变化时触发更新，避免无效渲染
 */

// 实时更新状态
const realtimeChartState = {
    isUpdating: false,
    pendingUpdates: {
        ciePoints: [],       // 待添加的 CIE 点
        gammaPoints: [],     // 待添加的 Gamma 点
        lastUpdateTime: 0    // 上次更新时间戳
    },
    minUpdateInterval: 50,   // 最小更新间隔（ms），确保 UI 响应性
    maxBatchSize: 20,        // 单次批量更新最大数据点数
    rafId: null,            // requestAnimationFrame ID
    updateCount: 0,         // 更新计数（用于性能监控）
    frameCount: 0           // 帧计数
};

/**
 * 添加实时测量数据到更新队列
 *
 * @param {Object} result - 测量结果
 *   { patchName, x, y, Y, rgb, cct, deltaE }
 */
function addRealtimeChartData(result) {
    if (!result || !result.x || !result.y) return;

    // 添加到待更新队列
    realtimeChartState.pendingUpdates.ciePoints.push({
        name: result.patchName,
        x: result.x,
        y: result.y,
        Y: result.Y,
        rgb: result.rgb
    });

    // 如果是灰阶测量，添加到 Gamma 曲线队列
    if (result.patchName && result.patchName.includes('%')) {
        const inputLevel = parseFloat(result.patchName.replace('%', ''));
        realtimeChartState.pendingUpdates.gammaPoints.push({
            input: inputLevel,
            Y: result.Y
        });
    }

    // 触发异步更新（使用 requestAnimationFrame）
    scheduleRealtimeUpdate();
}

/**
 * 安排实时更新（使用 requestAnimationFrame）
 */
function scheduleRealtimeUpdate() {
    if (realtimeChartState.isUpdating) return;

    // 使用 requestAnimationFrame 进行异步更新
    if (realtimeChartState.rafId === null) {
        realtimeChartState.rafId = requestAnimationFrame(processRealtimeUpdates);
    }
}

/**
 * 处理实时更新（在下一帧执行）
 */
function processRealtimeUpdates() {
    realtimeChartState.rafId = null;
    realtimeChartState.frameCount++;

    const now = performance.now();
    const elapsed = now - realtimeChartState.pendingUpdates.lastUpdateTime;

    // 节流控制：确保最小更新间隔
    if (elapsed < realtimeChartState.minUpdateInterval &&
        realtimeChartState.pendingUpdates.ciePoints.length < realtimeChartState.maxBatchSize) {
        // 未达到更新条件，重新安排
        scheduleRealtimeUpdate();
        return;
    }

    realtimeChartState.isUpdating = true;
    realtimeChartState.updateCount++;

    try {
        // 执行批量更新
        batchUpdateCIEChart(realtimeChartState.pendingUpdates.ciePoints);
        batchUpdateGammaChart(realtimeChartState.pendingUpdates.gammaPoints);

        // 清空待更新队列
        realtimeChartState.pendingUpdates.ciePoints = [];
        realtimeChartState.pendingUpdates.gammaPoints = [];
        realtimeChartState.pendingUpdates.lastUpdateTime = now;

    } finally {
        realtimeChartState.isUpdating = false;

        // 如果还有待处理数据，继续安排更新
        if (realtimeChartState.pendingUpdates.ciePoints.length > 0 ||
            realtimeChartState.pendingUpdates.gammaPoints.length > 0) {
            scheduleRealtimeUpdate();
        }
    }
}

/**
 * 批量更新 CIE 图表（高性能版本）
 *
 * @param {Array} points - 待添加的点 [{name, x, y, Y, rgb}, ...]
 */
function batchUpdateCIEChart(points) {
    if (!cieChart || points.length === 0) return;

    const option = cieChart.getOption();
    const measurePointsSeries = option.series.find(s => s.name === '测量点');

    if (!measurePointsSeries) return;

    // 批量添加新点
    for (const point of points) {
        // 确定点颜色
        let pointColor = '#3b82f6';
        if (point.name === '红') pointColor = '#ff4444';
        else if (point.name === '绿') pointColor = '#44ff44';
        else if (point.name === '蓝') pointColor = '#4444ff';
        else if (point.name === '白') pointColor = '#ffffff';
        else if (point.name === '黑') pointColor = '#333333';
        else if (point.name && point.name.includes('%')) pointColor = '#888888';

        // 检查是否已存在同名点
        const existingIndex = measurePointsSeries.data.findIndex(p => p.name === point.name);
        const newPoint = {
            value: [point.x, point.y],
            name: point.name,
            itemStyle: { color: pointColor }
        };

        if (existingIndex >= 0) {
            measurePointsSeries.data[existingIndex] = newPoint;
        } else {
            measurePointsSeries.data.push(newPoint);
        }
    }

    // 单次设置 option，避免多次渲染
    cieChart.setOption(option, {
        lazyUpdate: true  // 懒更新，减少渲染次数
    });

    // 显示图表更新指示器
    showChartUpdateIndicator('cie-chart');
}

/**
 * 批量更新 Gamma 图表（高性能版本）
 *
 * @param {Array} points - 待添加的点 [{input, Y}, ...]
 */
function batchUpdateGammaChart(points) {
    if (!gammaChart || points.length === 0) return;

    const option = gammaChart.getOption();
    const measureSeries = option.series.find(s => s.name === '测量曲线');

    if (!measureSeries) return;

    // 批量添加新点
    for (const point of points) {
        const existingIndex = measureSeries.data.findIndex(p => p[0] === point.input);
        const newPoint = [point.input, point.Y];

        if (existingIndex >= 0) {
            measureSeries.data[existingIndex] = newPoint;
        } else {
            measureSeries.data.push(newPoint);
        }
    }

    // 排序
    measureSeries.data.sort((a, b) => a[0] - b[0]);

    // 单次设置 option
    gammaChart.setOption(option, {
        lazyUpdate: true
    });

    // 显示图表更新指示器
    showChartUpdateIndicator('gamma-chart');
}

/**
 * 显示图表更新指示器（短暂闪烁）
 */
function showChartUpdateIndicator(chartId) {
    const chartDom = document.getElementById(chartId);
    if (!chartDom) return;

    // 查找或创建指示器
    let indicator = chartDom.querySelector('.chart-update-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.className = 'chart-update-indicator';
        indicator.textContent = t('更新');
        chartDom.appendChild(indicator);
    }

    // 闪烁效果
    indicator.classList.add('active');
    setTimeout(() => {
        indicator.classList.remove('active');
    }, 500);
}

/**
 * 获取实时更新性能统计
 */
function getRealtimeUpdateStats() {
    return {
        updateCount: realtimeChartState.updateCount,
        frameCount: realtimeChartState.frameCount,
        avgUpdatesPerFrame: realtimeChartState.frameCount > 0 ?
            realtimeChartState.updateCount / realtimeChartState.frameCount : 0,
        pendingPoints: realtimeChartState.pendingUpdates.ciePoints.length +
                       realtimeChartState.pendingUpdates.gammaPoints.length,
        lastUpdateTime: realtimeChartState.pendingUpdates.lastUpdateTime
    };
}

/**
 * 重置实时更新状态
 */
function resetRealtimeUpdateState() {
    realtimeChartState.isUpdating = false;
    realtimeChartState.pendingUpdates.ciePoints = [];
    realtimeChartState.pendingUpdates.gammaPoints = [];
    realtimeChartState.pendingUpdates.lastUpdateTime = 0;
    realtimeChartState.updateCount = 0;
    realtimeChartState.frameCount = 0;

    if (realtimeChartState.rafId !== null) {
        cancelAnimationFrame(realtimeChartState.rafId);
        realtimeChartState.rafId = null;
    }
}

/**
 * 强制刷新所有待更新数据（用于测量结束）
 */
function flushRealtimeUpdates() {
    // 取消待处理的 RAF
    if (realtimeChartState.rafId !== null) {
        cancelAnimationFrame(realtimeChartState.rafId);
        realtimeChartState.rafId = null;
    }

    // 立即处理所有待更新数据
    if (realtimeChartState.pendingUpdates.ciePoints.length > 0 ||
        realtimeChartState.pendingUpdates.gammaPoints.length > 0) {
        realtimeChartState.isUpdating = true;

        try {
            batchUpdateCIEChart(realtimeChartState.pendingUpdates.ciePoints);
            batchUpdateGammaChart(realtimeChartState.pendingUpdates.gammaPoints);

            realtimeChartState.pendingUpdates.ciePoints = [];
            realtimeChartState.pendingUpdates.gammaPoints = [];

        } finally {
            realtimeChartState.isUpdating = false;
        }
    }
}

// 导出实时更新相关函数
window.addRealtimeChartData = addRealtimeChartData;
window.flushRealtimeUpdates = flushRealtimeUpdates;
window.resetRealtimeUpdateState = resetRealtimeUpdateState;
window.getRealtimeUpdateStats = getRealtimeUpdateStats;
// ==============================================================================
// 饱和度追踪图 + 色温(CCT)追踪图 (P2 集成)
// ==============================================================================

let saturationChart = null;
let cctChart = null;

// 饱和度扫描测量累积数据: {color: [{level, deltaE, x, y, Y, patchName}]}
const saturationData = {};
// 色相扫描数据: [{angle, deltaE, patchName}]
const hueSweepData = [];
// 灰阶 CCT 追踪数据: [{level, cct, duv, patchName}]
let cctTrackData = [];

const SATURATION_COLORS = {
    'R': '#e74c3c', 'G': '#2ecc71', 'B': '#3498db',
    'Y': '#f1c40f', 'M': '#e056fd', 'C': '#00d2d3'
};
const SATURATION_COLOR_NAMES = { 'R': '红', 'G': '绿', 'B': '蓝', 'Y': '黄', 'M': '品红', 'C': '青' };

/**
 * 初始化饱和度追踪图
 */
function initSaturationChart() {
    const chartDom = document.getElementById('saturation-chart');
    if (!chartDom) return;

    saturationChart = echarts.init(chartDom);
    saturationChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { bottom: 0, formatter: function (name) { return window.I18N ? I18N.t(name) : name; }, textStyle: { fontSize: 11 } },
        grid: { left: 44, right: 16, top: 30, bottom: 46 },
        xAxis: {
            type: 'category',
            name: t('饱和度 %'),
            data: ['25', '50', '75', '100'],
            nameTextStyle: { fontSize: 11 }
        },
        yAxis: {
            type: 'value',
            name: 'ΔE 2000',
            nameTextStyle: { fontSize: 11 }
        },
        series: []
    });

    // 参考色域切换时重绘
    const gamutSelect = document.getElementById('saturation-chart-gamut');
    if (gamutSelect) {
        gamutSelect.addEventListener('change', () => updateSaturationChart());
    }
}

/**
 * 添加一条测量结果到饱和度追踪数据
 * 匹配 "R-25%"（六色饱和度）或 "色相-120°"（色相扫描）
 */
function addSaturationMeasurement(result) {
    if (!result || !result.patchName) return false;
    const name = String(result.patchName);

    const satMatch = name.match(/^([RGBYMC])-(\d+)%$/);
    if (satMatch) {
        const color = satMatch[1];
        const level = parseInt(satMatch[2]);
        if (!saturationData[color]) saturationData[color] = [];
        // 同级别重复测量则替换
        saturationData[color] = saturationData[color].filter(p => p.level !== level);
        saturationData[color].push({
            level,
            deltaE: result.deltaE ?? 0,
            x: result.x, y: result.y, Y: result.Y,
            patchName: name
        });
        saturationData[color].sort((a, b) => a.level - b.level);
        updateSaturationChart();
        return true;
    }

    const hueMatch = name.match(/^色相-(\d+)°$/);
    if (hueMatch) {
        const angle = parseInt(hueMatch[1]);
        const idx = hueSweepData.findIndex(p => p.angle === angle);
        const entry = { angle, deltaE: result.deltaE ?? 0, patchName: name };
        if (idx >= 0) hueSweepData[idx] = entry; else hueSweepData.push(entry);
        hueSweepData.sort((a, b) => a.angle - b.angle);
        updateSaturationChart();
        return true;
    }
    return false;
}

/**
 * 更新饱和度追踪图（六色 ΔE 曲线 + 色相扫描 ΔE）
 */
function updateSaturationChart() {
    if (!saturationChart) initSaturationChart();
    if (!saturationChart) return;

    const levels = ['25', '50', '75', '100'];
    const series = [];

    Object.keys(SATURATION_COLORS).forEach(color => {
        const points = saturationData[color] || [];
        if (points.length === 0) return;
        series.push({
            name: SATURATION_COLOR_NAMES[color],
            type: 'line',
            data: levels.map(lv => {
                const p = points.find(pt => String(pt.level) === lv);
                return p ? Number(p.deltaE.toFixed(2)) : null;
            }),
            symbol: 'circle',
            symbolSize: 7,
            lineStyle: { width: 2 },
            itemStyle: { color: SATURATION_COLORS[color] },
            connectNulls: false
        });
    });

    // 色相扫描作为虚线参考系列
    if (hueSweepData.length > 0) {
        series.push({
            name: '色相扫描',
            type: 'line',
            data: levels.map(() => null),
            markLine: {
                silent: true,
                symbol: 'none',
                lineStyle: { color: '#888', type: 'dashed' },
                data: [{ yAxis: 3.0, name: 'ΔE 3.0' }]
            },
            itemStyle: { color: '#888' }
        });
    }

    saturationChart.setOption({
        xAxis: { data: levels },
        yAxis: { name: 'ΔE 2000' },
        series: series.length > 0 ? series : []
    });
}

/**
 * 色相扫描明细（在图表 tooltip 外提供数据查询）
 */
function getHueSweepData() {
    return hueSweepData.slice();
}

/**
 * 初始化色温 (CCT) 追踪图
 */
function initCCTChart() {
    const chartDom = document.getElementById('cct-chart');
    if (!chartDom) return;

    cctChart = echarts.init(chartDom);
    cctChart.setOption({
        tooltip: {
            trigger: 'axis',
            formatter: (params) => {
let html = t('{axis}% 信号', {axis: params[0].axisValue});
                params.forEach(p => {
                    if (p.value === null || p.value === undefined) return;
                    if (p.seriesName === 'CCT') {
                        html += `<br/>${p.marker}CCT: ${Number(p.value).toFixed(0)} K`;
                    } else if (p.seriesName === 'Duv') {
                        html += `<br/>${p.marker}Duv: ${Number(p.value).toFixed(4)}`;
                    }
                });
                return html;
            }
        },
        legend: { bottom: 0, formatter: function (name) { return window.I18N ? I18N.t(name) : name; }, textStyle: { fontSize: 11 } },
        grid: { left: 52, right: 52, top: 30, bottom: 46 },
        xAxis: {
            type: 'category',
            name: t('信号 %'),
            data: [],
            nameTextStyle: { fontSize: 11 }
        },
        yAxis: [
            { type: 'value', name: 'CCT (K)', scale: true, nameTextStyle: { fontSize: 11 } },
            { type: 'value', name: 'Duv', scale: true, nameTextStyle: { fontSize: 11 } }
        ],
        series: [
            {
                name: 'CCT', type: 'line', yAxisIndex: 0,
                data: [], symbol: 'circle', symbolSize: 7,
                lineStyle: { width: 2, color: '#f39c12' },
                itemStyle: { color: '#f39c12' },
                markLine: {
                    silent: true, symbol: 'none',
                    lineStyle: { color: '#f39c12', type: 'dashed', opacity: 0.6 },
                    data: [{ yAxis: 6500 }]
                }
            },
            {
                name: 'Duv', type: 'bar', yAxisIndex: 1, barWidth: '35%',
                data: [],
                itemStyle: {
                    color: (p) => Math.abs(p.value) <= 0.003 ? '#2ecc71' : '#e74c3c'
                }
            }
        ]
    });
}

/**
 * 添加灰阶测量结果到 CCT 追踪（patchName 形如 "50%"）
 */
function addCCTTrackMeasurement(result) {
    if (!result || !result.patchName) return false;
    const m = String(result.patchName).match(/^(\d+(?:\.\d+)?)%$/);
    if (!m) return false;
    const level = parseFloat(m[1]);
    cctTrackData = cctTrackData.filter(p => p.level !== level);
    cctTrackData.push({
        level,
        cct: result.cct ?? null,
        duv: result.duv ?? null,
        patchName: result.patchName
    });
    cctTrackData.sort((a, b) => a.level - b.level);
    updateCCTChart();
    return true;
}

/**
 * 更新色温追踪图
 */
function updateCCTChart() {
    if (!cctChart) initCCTChart();
    if (!cctChart) return;

    if (cctTrackData.length === 0) return;

    // 清除占位提示
    const placeholder = document.querySelector('#cct-chart > div');
    if (placeholder && cctTrackData.length > 0) {
        const chartDom = document.getElementById('cct-chart');
        const ph = chartDom && chartDom.querySelector('div[style*="justify-content"]');
        if (ph) ph.remove();
    }

    cctChart.setOption({
        xAxis: { data: cctTrackData.map(p => String(p.level)) },
        series: [
            { data: cctTrackData.map(p => p.cct) },
            { data: cctTrackData.map(p => p.duv) }
        ]
    });
}

/**
 * 清空饱和度/CCT 追踪数据（新测量会话开始时）
 */
function clearTrackingCharts() {
    Object.keys(saturationData).forEach(k => delete saturationData[k]);
    hueSweepData.length = 0;
    cctTrackData = [];
}

// 挂到 resize / 初始化链
const _origResizeCharts = typeof resizeCharts === 'function' ? resizeCharts : null;
if (_origResizeCharts) {
    resizeCharts = function() {
        _origResizeCharts();
        if (saturationChart) saturationChart.resize();
        if (cctChart) cctChart.resize();
    };
}

document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {
        initSaturationChart();
        initCCTChart();
    }, 150);
});

// 导出（供 main.js 调用）
window.initSaturationChart = initSaturationChart;
window.initCCTChart = initCCTChart;
window.addSaturationMeasurement = addSaturationMeasurement;
window.addCCTTrackMeasurement = addCCTTrackMeasurement;
window.updateSaturationChart = updateSaturationChart;
window.updateCCTChart = updateCCTChart;
window.clearTrackingCharts = clearTrackingCharts;
window.getHueSweepData = getHueSweepData;



// ========== 语言切换时重绘图表 ==========
// ECharts option 中的静态文案在构建时经 t() 翻译，切换语言后需重建 option。
if (window.I18N) {
    I18N.onChange(function () {
        try { if (typeof updateCIEChart === 'function') updateCIEChart(); } catch (e) { /* 数据未就绪时忽略 */ }
        try { if (typeof updateGammaChartPresets === 'function') updateGammaChartPresets(); } catch (e) { /* 忽略 */ }
        try { if (typeof updateSaturationChart === 'function') updateSaturationChart(); } catch (e) { /* 忽略 */ }
        try { if (typeof updateCCTChart === 'function') updateCCTChart(); } catch (e) { /* 忽略 */ }
        try {
            // 已有测量数据时，基于全局 measurementData 全量重绘
            if (typeof renderChartsFromHistory === 'function' && typeof measurementData !== 'undefined' && measurementData) {
                var hasData = (measurementData.grayScale && measurementData.grayScale.length) ||
                              measurementData.gamma || (measurementData.lutPatches && measurementData.lutPatches.length) ||
                              (measurementData.gamut && measurementData.gamut.red);
                if (hasData) renderChartsFromHistory(measurementData);
            }
        } catch (e) { /* 忽略 */ }
    });
}
