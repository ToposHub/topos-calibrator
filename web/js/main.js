/**
 * Topos Calibrator - 前端 JavaScript
 * 处理 QWebChannel 通信和 UI 交互
 */

// 后端对象引用
let backend = null;

// 测量状态
let isMeasuring = false;
let isCycleMeasuring = false;
let currentPatchName = '';
let currentPatchRGB = null;  // 当前选中的色块RGB值
let probeConnected = false;
let probeConnecting = false;   // 连接进行中（枚举/握手实测可达 30-60 秒）
let probeLastType = '';        // 最近一次连接成功的探头类型（如 i1d3）

// 当前测量模式
let currentMeasureMode = 'gamut';

// ========== 双模式 UI ==========
// UI 模式: 'guided'(引导模式,默认) / 'advanced'(专业自由模式)
let uiMode = 'guided';
// 当前测量来源: 'free'(自由模式触发) / 'wizard'(向导触发)
// 用于区分循环测量完成回调的归属，避免自由测量误改向导步骤状态
let measurementSource = 'free';

const UI_MODE_STORAGE_KEY = 'topos.uiMode';
const NEW_USER_TIPS_STORAGE_KEY = 'topos.newUserTips';

// 当前导出模式（用于决定文件对话框类型）
let currentExportMode = 'icc';

// 校准后待执行的测量模式（ICC/LUT 校准完成后自动开始测量）
let pendingMeasurementMode = null;
let isCalibrating = false;
let calibrationDone = false;  // 标记校准是否已完成（用于区分是否需要再次校准）

// 当前色块列表（动态更新）
let currentPatchList = [];

// 所有可测量的色块列表（按顺序）- 初始为空，由后端动态下发
// 后端通过 patchListUpdated 信号发送色块列表，前端被动接收并渲染
let allPatchList = [];

// ========== CCMX 矩阵制作（使用历史数据选择方式） ==========

// 测量数据存储
const measurementData = {
    gamut: {
        red: null,
        green: null,
        blue: null,
        white: null,
        black: null
    },
    grayScale: [],
    gamma: null,
    lutPatches: []  // LUT 色块测量数据
};

// 已测量色块跟踪（用于外框标记）
const measuredPatches = {};  // {patchName: {rgb: [r,g,b], result: {...}}}

// 历史测量数据列表
let historyMeasurements = [];
let currentHistoryId = '';  // 当前选中的历史数据ID

// 偏好设置相关变量（全局作用域）
let autoSaveEnabled = null;
let autoSavePath = null;

// ========== P1-D: 统一 JSON 解析 Helper 函数 ==========
/**
 * parsePayload - 统一的 JSON 解析 Helper
 * 
 * P1-D 任务: 统一信号序列化策略
 * 短期保留 JSON 字符串方案，因为大量代码依赖 JSON.parse
 * 
 * 此函数封装 JSON 解析，统一错误处理：
 * - 兼容 Qt WebChannel 可能传递对象或字符串的情况
 * - 解析失败时返回默认值（空对象或空数组）
 * - 集中日志输出便于调试
 * 
 * @param {*} payload - 可能是字符串或对象的数据
 * @param {*} defaultValue - 解析失败时的默认值（默认为空对象 {}）
 * @returns {Object|Array} - 解析后的数据对象或默认值
 * 
 * Usage:
 *   const data = parsePayload(resultJson);           // 返回解析后的对象，失败时返回 {}
 *   const list = parsePayload(listJson, []);         // 失败时返回空数组 []
 */
function parsePayload(payload, defaultValue = {}) {
    try {
        // Qt WebChannel 可能直接传递对象或 JSON 字符串
        if (typeof payload === 'string') {
            return JSON.parse(payload);
        }
        // 如果已经是对象，直接返回
        if (typeof payload === 'object' && payload !== null) {
            return payload;
        }
        // null/undefined 是后端"暂无数据"的正常返回（如启动时未枚举设备），静默使用默认值
        if (payload === null || payload === undefined) {
            return defaultValue;
        }
        // 其他意外类型，记录日志便于调试
        console.warn('parsePayload: 预期字符串或对象，收到:', typeof payload, payload);
        return defaultValue;
    } catch (e) {
        console.error('parsePayload 解析失败:', e, 'payload:', payload);
        return defaultValue;
    }
}

/**
 * 初始化 QWebChannel 连接
 */
function initWebChannel() {
    if (typeof qt !== 'undefined') {
        new QWebChannel(qt.webChannelTransport, function(channel) {
            backend = channel.objects.backend;
            // Python detects the system language on first launch and is authoritative
            // for the native app; web-only mode continues to use navigator.language.
            const syncLanguage = (backendLang) => {
                try {
                    if (window.I18N && I18N.isLanguageAvailable(backendLang) &&
                        I18N.getLanguage() !== backendLang) {
                        I18N.setLanguage(backendLang);
                    }
                    if (typeof backend.setLanguage === 'function') {
                        backend.setLanguage(window.I18N ? I18N.getLanguage() : backendLang);
                    }
                } catch (e) { /* ignore language-sync failures */ }
                if (typeof refreshLocalizedDynamicUi === 'function') {
                    refreshLocalizedDynamicUi();
                }
                updateStatus(t('已连接到后端'));
            };
            if (backend.languageReady && typeof backend.requestLanguage === 'function') {
                // A signal avoids return-value differences between Qt WebChannel versions.
                backend.languageReady.connect(syncLanguage);
                backend.requestLanguage();
            } else if (typeof backend.getLanguage === 'function') {
                try {
                    const languageResult = backend.getLanguage();
                    if (languageResult && typeof languageResult.then === 'function') {
                        languageResult.then(syncLanguage).catch(() => syncLanguage(I18N.getLanguage()));
                    } else {
                        // Some Qt WebChannel versions return primitive values directly.
                        syncLanguage(languageResult);
                    }
                } catch (e) {
                    syncLanguage(window.I18N ? I18N.getLanguage() : 'en');
                }
            } else {
                syncLanguage(window.I18N ? I18N.getLanguage() : 'en');
            }

            // 连接信号
            backend.logMessage.connect(handleLogMessage);
            backend.measurementResult.connect(handleMeasurementResult);
            backend.measurementStarted.connect(handleMeasurementStarted);
            backend.measurementCompleted.connect(handleMeasurementCompleted);
            backend.probeStatusChanged.connect(handleProbeStatusChanged);
            backend.cycleMeasurementProgress.connect(handleCycleProgress);
            backend.calibrationProgress.connect(handleCalibrationProgress);  // dispcal 校准进度
            backend.patchColorChanged.connect(handlePatchColorChanged);
            backend.gamutCoverageUpdated.connect(handleGamutCoverageUpdated);
            backend.gammaUpdated.connect(handleGammaUpdated);
            backend.delayConfigUpdated.connect(handleDelayConfigUpdated);
            backend.patchListUpdated.connect(handlePatchListUpdated);
            backend.displayBasicDataUpdated.connect(handleDisplayBasicDataUpdated);

            // 设备枚举相关信号
            backend.probeTypeAutoSwitched.connect(handleProbeTypeAutoSwitched);
            backend.instrumentsEnumerated.connect(handleInstrumentsEnumerated);

            // 数据存储相关信号
            backend.measurementListUpdated.connect(handleMeasurementListUpdated);
            backend.calFileListUpdated.connect(handleCalFileListUpdated);
            backend.calFileLoaded.connect(handleCalFileLoaded);  // cal 文件加载结果
            backend.measurementSaved.connect(handleMeasurementSaved);
            backend.measurementLoaded.connect(handleMeasurementLoaded);
            backend.dataExported.connect(handleDataExported);
            backend.fileCreated.connect(handleFileCreated);  // 文件创建结果（包括校准文件）
            backend.filePathSelected.connect(handleFilePathSelected);  // 文件路径选择结果
            backend.sessionAutoSaved.connect(handleSessionAutoSaved);  // 自动保存完成
            backend.sessionListUpdated.connect(handleSessionListUpdated);  // 会话列表更新

            // Web测量服务器相关信号
            backend.webMeasurementServerStarted.connect((result) => {
                let data;
                try { data = JSON.parse(result); } catch (e) { return; }
                if (data.success) {
                    webMeasurementServerRunning = true;
                    window._webServerStatus = { running: true, url: data.url };
                    updateStatus(t('Web测量服务器已启动: ') + data.url);
                    const infoDiv = document.getElementById('web-server-info');
                    const urlLink = document.getElementById('web-server-url');
                    if (infoDiv && urlLink) {
                        infoDiv.style.display = 'block';
                        urlLink.href = data.url;
                        urlLink.textContent = data.url;
                    }
                } else {
                    webMeasurementServerRunning = false;
                    window._webServerStatus = { running: false, url: null };
                    updateStatus(t('Web测量服务器启动失败: ') + data.message);
                }
                updatePrefsWebServerUI();
                // 与后端实际状态对账，保证菜单/偏好设置/地址条三处一致
                refreshWebServerStatus();
            });
            backend.webMeasurementServerStopped.connect((result) => {
                let data;
                try { data = JSON.parse(result); } catch (e) { return; }
                if (data.success) {
                    webMeasurementServerRunning = false;
                    window._webServerStatus = { running: false, url: null };
                    updateStatus(t('Web测量服务器已停止'));
                    const infoDiv = document.getElementById('web-server-info');
                    if (infoDiv) infoDiv.style.display = 'none';
                }
                updatePrefsWebServerUI();
                // 与后端实际状态对账，保证菜单/偏好设置/地址条三处一致
                refreshWebServerStatus();
            });

            // ========== 预检相关信号连接 (P3-C) ==========
            backend.preflightCheckStarted.connect(handlePreflightCheckStarted);
            backend.preflightCheckCompleted.connect(handlePreflightCheckCompleted);
            backend.preflightCheckProgress.connect(handlePreflightCheckProgress);
            backend.preflightOverrideChanged.connect(handlePreflightOverrideChanged);

            // ========== ICC Workflow 信号连接 (P4-B 集成) ==========
            backend.iccWorkflowStateChanged.connect(handleICCWorkflowStateChanged);
            backend.iccWorkflowProgress.connect(handleICCWorkflowProgress);
            backend.iccWorkflowCompleted.connect(handleICCWorkflowCompleted);
            backend.iccWorkflowFailed.connect(handleICCWorkflowFailed);
            backend.iccWorkflowSessionInfo.connect(handleICCWorkflowSessionInfo);

            // ========== 报告导出信号连接 ==========
            backend.reportExportCompleted.connect(handleReportExportCompleted);

            // ========== AutoCal 自动校准闭环信号连接 (P1 集成) ==========
            backend.autocalStateChanged.connect(handleAutoCalStateChanged);
            backend.autocalProgress.connect(handleAutoCalProgress);
            backend.autocalFinished.connect(handleAutoCalFinished);
            backend.displayControlUpdated.connect(handleDisplayControlUpdated);

            // 初始化完成
            backend.ping();
            updateProbeStatus('disconnected');

            // 初始化参数设置
            initSettings();

            // P6-A: 初始化向导 UI
            initWizardUI();

            // 双模式 UI：绑定切换入口并恢复上次模式（默认引导模式）
            initUiModeControls();
            initUiMode();

            // 初始化测量模式（请求默认色块列表）
            backend.set_measure_mode('gamut');

            // 枚举显示器，填充 ICC/AutoCal 显示器下拉
            loadDisplayList();

            // 初始化历史数据列表（延迟以确保信号连接已建立）
            setTimeout(() => {
                backend.refresh_measurement_list();
            }, 100);

            // 启动时后台自动连接探头（预热：用户走到"探头/修正"步骤时通常已连接好；
            // 若已连接则仅同步状态到前端）。失败静默降级，不打扰用户。
            // 可在偏好设置 → 通用中关闭（localStorage: topos.autoConnectProbe）
            let autoConnect = true;
            try { autoConnect = localStorage.getItem('topos.autoConnectProbe') !== '0'; } catch (e) { /* 默认开 */ }
            if (autoConnect && typeof backend.auto_connect_probe === 'function') {
                setTimeout(() => {
                    backend.auto_connect_probe();
                }, 800);
            }

            // 同步 Web 测量服务器运行状态（页面刷新后恢复地址条与菜单勾选）
            refreshWebServerStatus();
        });
    } else {
        updateStatus(t('浏览器模式 - 后端不可用'));
        updateProbeStatus('disconnected');
    }
}

/**
 * 将校正文件列表按探头系列分组填入 select（内置官方校正库分组显示）
 * formatLabel(file, grouped) 返回每个选项的显示文本
 */
function appendCorrectionOptionsGrouped(select, files, formatLabel) {
    function probeGroup(file) {
        const inst = (file.instrument || '').toLowerCase();
        const name = (file.name || '').toLowerCase();
        if (file.type === 'ccss') return '通用光谱 CCSS (i1 Display Pro 等)';
        if (inst.includes('dtp94') || inst.includes('dtp-94') || name.includes('dtp-94')) return 'X-Rite DTP94';
        if (inst.includes('i1 display') || name.includes('eyeone_display')) return 'i1 Display 1 / 2';
        if (inst.includes('spyder') || name.includes('spyder')) return 'Datacolor Spyder';
        if (inst.includes('huey') || name.includes('huey')) return 'Pantone Huey';
        return file.instrument || '其他';
    }

    const groups = {};
    files.forEach(file => {
        const g = probeGroup(file);
        (groups[g] = groups[g] || []).push(file);
    });

    const groupNames = Object.keys(groups);
    const useOptgroups = groupNames.length > 1;

    groupNames.sort().forEach(g => {
        let parent = select;
        if (useOptgroups) {
            const og = document.createElement('optgroup');
            og.label = `${g} (${groups[g].length})`;
            select.appendChild(og);
            parent = og;
        }

        groups[g].forEach(file => {
            const option = document.createElement('option');
            option.value = file.path;
            option.textContent = formatLabel(file, useOptgroups);

            // 存储元数据以供兼容性检查使用
            option.dataset.type = file.type || '';
            option.dataset.descriptor = file.descriptor || '';
            option.dataset.instrument = file.instrument || '';
            option.dataset.technology = file.technology || '';
            option.dataset.technologyDisplay = file.technology_display || '';
            option.dataset.reference = file.reference || '';
            option.dataset.created = file.created || '';
            option.dataset.hash = file.hash || '';
            option.dataset.isValid = file.is_valid ? 'true' : 'false';

            parent.appendChild(option);
        });
    });
}

/**
 * 枚举显示器并填充前端下拉（ICC 目标显示器 + AutoCal DDC 通道）
 */
function loadDisplayList() {
    if (!backend || !backend.list_displays) return;
    backend.list_displays().then(function(json) {
        const data = parsePayload(json, {});
        const displays = data.displays || [];
        if (!displays.length) return;
        const current = data.current || 1;

        function fillSelect(select, keepValue) {
            const prev = keepValue ? select.value : null;
            select.innerHTML = '';
            displays.forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.index;
                let label = `${d.index}. ${d.model || d.name}`;
                if (d.width && d.height) label += ` (${d.width}×${d.height})`;
                if (d.primary) label += ' [主]';
                opt.textContent = label;
                select.appendChild(opt);
            });
            if (prev && displays.some(d => String(d.index) === prev)) {
                select.value = prev;
            } else {
                select.value = String(current);
            }
        }

        const iccSelect = document.getElementById('display-index');
        if (iccSelect) fillSelect(iccSelect, false);
        const ddcSelect = document.getElementById('autocal-display-id');
        if (ddcSelect) fillSelect(ddcSelect, true);
    }).catch(function(e) {
        console.warn('枚举显示器失败:', e);
    });
}

/**
 * 初始化参数设置
 */
function initSettings() {
    if (!backend) return;

    // 探头类型选择
    document.getElementById('probe-type').addEventListener('change', function() {
        backend.set_probe_type(this.value);
    });

    // 显示器类型选择
    document.getElementById('display-type').addEventListener('change', function() {
        backend.set_display_type(this.value);
    });

    // 测量延迟
    document.getElementById('measure-delay').addEventListener('change', function() {
        backend.set_measure_delay(parseInt(this.value) || 500);
    });

    // ========== 测量质量控制 ==========
    // 每色块重复测量次数（>1 时后端取 XYZ 线性平均）
    document.getElementById('measure-repeat-count').addEventListener('change', function() {
        const v = Math.max(1, Math.min(10, parseInt(this.value) || 1));
        this.value = v;
        backend.set_measure_repeat_count(v);
    });

    // 暗部多重采样：开关 + 阈值 + 最大重测次数
    document.getElementById('dark-sample-enabled').addEventListener('change', function() {
        backend.set_dark_sample_enabled(this.checked);
    });
    document.getElementById('dark-sample-threshold').addEventListener('change', function() {
        const v = Math.max(0.01, Math.min(5, parseFloat(this.value) || 0.2));
        this.value = v;
        backend.set_dark_sample_threshold(v);
    });
    document.getElementById('dark-sample-retries').addEventListener('change', function() {
        const v = Math.max(0, Math.min(9, parseInt(this.value) || 3));
        this.value = v;
        backend.set_dark_sample_max_retries(v);
    });

    // ========== 光谱校正文件选择器 ==========
    // 加载 corrections 目录中的文件列表（含详细元数据）
    function loadCorrectionFiles() {
        if (!backend) return;
        backend.get_correction_files().then(function(filesJson) {
            // P1-D: 使用统一的 parsePayload helper（数组类型）
            const files = parsePayload(filesJson, []);
            const select = document.getElementById('correction-file-select');
            if (!select) return;

            // 清空现有选项（保留"无"选项）
            select.innerHTML = '<option value="" selected>无 (不启用)</option>';

            appendCorrectionOptionsGrouped(select, files, function(file, grouped) {
                let displayText = file.name;
                if (!grouped && file.instrument) {
                    displayText += ` (${file.instrument})`;
                }
                if (file.technology_display) {
                    displayText += ` [${file.technology_display}]`;
                }
                if (file.created) {
                    displayText += ` ${file.created}`;
                }
                if (!file.is_valid) {
                    displayText = `⚠️ ${displayText}`;
                }
                return displayText;
            });

            // 更新修正文件信息显示区域（如果有）
            updateCorrectionInfoDisplay(null);
        }).catch(function(e) {
            console.error('加载校正文件列表失败:', e);
        });
    }

    // 初始化加载
    loadCorrectionFiles();

    // EDR 导入：X-Rite .edr → oeminst 转换 → corrections/ 目录
    document.getElementById('btn-import-edr')?.addEventListener('click', function() {
        if (!backend || !backend.import_edr_file) {
            updateStatus(t('后端不支持 EDR 导入'));
            return;
        }
        updateStatus(t('请选择 .edr 文件（i1Profiler 安装目录或仪器光盘）…'));
        backend.import_edr_file().then(function(resultJson) {
            const result = parsePayload(resultJson, {});
            if (result.success) {
                const n = (result.added || []).length;
                updateStatus(t('EDR 导入成功：新增 {n} 个校正文件，请重新选择光谱校正', {n: n}) + (n ? '（' + result.added.join(', ') + '）' : ''));
                if (typeof loadCorrectionFiles === 'function') loadCorrectionFiles();
            } else if (result.error === 'cancelled') {
                updateStatus(t('已取消 EDR 导入'));
            } else {
                updateStatus(t('EDR 导入失败: ') + (result.error || t('未知错误')));
                showAlertDialog('导入失败', String(result.error || '未知错误'), 'error');
            }
        }).catch(function(e) {
            updateStatus(t('EDR 导入异常: ') + e);
        });
    });

    // 选择框变化事件（显示详细元数据和兼容性检查）
    document.getElementById('correction-file-select').addEventListener('change', function() {
        if (!backend) return;
        const selectedPath = this.value;
        const selectedOption = this.options[this.selectedIndex];

        if (selectedPath) {
            // 获取当前探头和显示器类型进行兼容性检查
            const probeType = document.getElementById('probe-type')?.value || '';
            const displayTech = document.getElementById('display-type')?.value || '';

            // 检查兼容性
            backend.check_correction_compatibility(selectedPath, probeType, displayTech).then(function(resultJson) {
                const result = parsePayload(resultJson);

                // 显示兼容性警告（如果有）
                if (!result.is_compatible) {
                    showCompatibilityWarning(result, selectedOption.dataset);
                }

                // 设置修正文件
                backend.set_correction_file_path(selectedPath);

                // 更新修正文件信息显示
                updateCorrectionInfoDisplay(selectedOption.dataset);
            }).catch(function(e) {
                // 即使兼容性检查失败，也允许设置修正文件
                console.warn('兼容性检查失败:', e);
                backend.set_correction_file_path(selectedPath);
                updateCorrectionInfoDisplay(selectedOption.dataset);
            });

            const fileName = selectedPath.split('/').pop().split('\\').pop();
            updateStatus(t('已选择光谱校正文件: {fileName}', {fileName: fileName}));
        } else {
            backend.set_correction_file_path('');
            updateStatus(t('光谱校正已禁用'));
            updateCorrectionInfoDisplay(null);
        }
    });

    // 显示兼容性警告
    function showCompatibilityWarning(result, metadata) {
        const messages = [];

        if (result.errors && result.errors.length > 0) {
            messages.push('❌ 不兼容：');
            result.errors.forEach(err => messages.push(`  ${err}`));
        }

        if (result.warnings && result.warnings.length > 0) {
            messages.push('⚠️ 警告：');
            result.warnings.forEach(warn => messages.push(`  ${warn}`));
        }

        if (result.suggestions && result.suggestions.length > 0) {
            messages.push('💡 建议：');
            result.suggestions.forEach(sug => messages.push(`  ${sug}`));
        }

        // 在状态栏或消息区域显示
        if (messages.length > 0) {
            console.warn('修正文件兼容性问题:', messages.join('\n'));
            // 可选：弹出一个简短提示
            updateStatus(t(`⚠️ 修正文件兼容性警告 - 请检查控制台日志`));
        }
    }

    // 更新修正文件信息显示区域
    function updateCorrectionInfoDisplay(metadata) {
        const infoDiv = document.getElementById('correction-file-info');
        if (!infoDiv) return;

        if (!metadata) {
            infoDiv.innerHTML = '<span class="info-placeholder">未选择修正文件</span>';
            infoDiv.classList.add('hidden');
            return;
        }

        infoDiv.classList.remove('hidden');

        // 构建信息显示
        let html = '<div class="correction-info-grid">';
        html += `<div class="info-row"><span class="label">类型:</span><span class="value">${metadata.type === 'ccmx' ? 'CCMX (矩阵修正)' : 'CCSS (光谱修正)'}</span></div>`;
        if (metadata.descriptor) {
            html += `<div class="info-row"><span class="label">描述:</span><span class="value">${metadata.descriptor}</span></div>`;
        }
        if (metadata.instrument) {
            html += `<div class="info-row"><span class="label">目标探头:</span><span class="value">${metadata.instrument}</span></div>`;
        }
        if (metadata.technologyDisplay) {
            html += `<div class="info-row"><span class="label">目标显示技术:</span><span class="value">${metadata.technologyDisplay}</span></div>`;
        }
        if (metadata.reference) {
            html += `<div class="info-row"><span class="label">基准探头:</span><span class="value">${metadata.reference}</span></div>`;
        }
        if (metadata.created) {
            html += `<div class="info-row"><span class="label">创建时间:</span><span class="value">${metadata.created}</span></div>`;
        }
        if (metadata.hash) {
            html += `<div class="info-row"><span class="label">哈希:</span><span class="value hash">${metadata.hash}</span></div>`;
        }
        html += '</div>';

        infoDiv.innerHTML = html;
    }

    // 加载当前自动保存状态（用于初始化偏好设置）
    if (backend) {
        backend.get_auto_save_status().then(function(statusJson) {
            // P1-D: 使用统一的 parsePayload helper
            const status = parsePayload(statusJson);
            if (autoSaveEnabled) {
                autoSaveEnabled.checked = status.enabled;
            }
            if (autoSavePath && status.base_dir) {
                autoSavePath.value = status.base_dir;
            }
        }).catch(function(e) {
            console.error('加载自动保存状态失败:', e);
        });
    }
}

/**
 * 更新状态栏
 */
function updateStatus(status) {
    document.getElementById('status-text').textContent = status;
}

/**
 * 更新探头状态指示器
 */
function updateProbeStatus(status) {
    const indicator = document.getElementById('probe-indicator');
    const statusText = document.getElementById('probe-status-text');
    const btnCalibrate = document.getElementById('btn-calibrate');
    const btnMeasureSingle = document.getElementById('btn-measure-single');
    const btnCustomMeasure = document.getElementById('btn-custom-measure');

    indicator.classList.remove('connected', 'error');

    switch (status) {
        case 'connected':
            indicator.classList.add('connected');
            statusText.textContent = t('已连接');
            btnCalibrate.disabled = false;
            btnMeasureSingle.disabled = false;
            if (btnCustomMeasure) btnCustomMeasure.disabled = false;
            probeConnected = true;
            break;
        case 'disconnected':
            statusText.textContent = t('未连接');
            btnCalibrate.disabled = true;
            btnMeasureSingle.disabled = true;
            if (btnCustomMeasure) btnCustomMeasure.disabled = true;
            probeConnected = false;
            break;
        case 'connecting':
            statusText.textContent = t('连接中...');
            btnCalibrate.disabled = true;
            btnMeasureSingle.disabled = true;
            if (btnCustomMeasure) btnCustomMeasure.disabled = true;
            probeConnected = false;
            break;
        case 'error':
            indicator.classList.add('error');
            statusText.textContent = t('错误');
            btnCalibrate.disabled = true;
            btnMeasureSingle.disabled = true;
            if (btnCustomMeasure) btnCustomMeasure.disabled = true;
            probeConnected = false;
            break;
        case 'measuring':
            statusText.textContent = t('测量中...');
            btnCalibrate.disabled = true;
            btnMeasureSingle.disabled = true;
            if (btnCustomMeasure) btnCustomMeasure.disabled = true;
            break;
        case 'calibrating':
            statusText.textContent = t('校准中...');
            btnCalibrate.disabled = true;
            btnMeasureSingle.disabled = true;
            break;
    }
}

/**
 * 处理日志消息
 */
function handleLogMessage(message) {
    const displayMessage = translateBackendLogMessage(message);
    document.getElementById('log-output').textContent = displayMessage;

    // 向导 CCMX 生成没有独立完成信号，通过日志关键字判定结果
    if (window._ccmxGeneratePending) {
        if (message.includes('CCMX 校正文件已保存至')) {
            window._ccmxGeneratePending = false;
            maybeCompleteWizardGenerateStep({ filepath: '', format: 'CCMX' });
        } else if (message.includes('CCMX 生成失败')) {
            window._ccmxGeneratePending = false;
            maybeFailWizardGenerateStep();
            updateStatus(t('CCMX 生成失败，详见日志'));
        }
    }
}

/** Translate backend status messages that contain runtime values. */
function translateBackendLogMessage(message) {
    if (typeof message !== 'string' || !window.I18N) return message;
    const probeLookup = message.match(/^查找 (.+) 类型设备\.\.\.$/);
    if (probeLookup) {
        return t('查找 {probeType} 类型设备...', {probeType: probeLookup[1]});
    }
    return t(message);
}

/**
 * 处理色块颜色变化
 */
function handlePatchColorChanged(colorJson) {
    const color = parsePayload(colorJson);
    if (!color.r && !color.g && !color.b) {
        // 允许纯黑 (0,0,0) 但跳过解析失败
        if (color.r === undefined) return;
    }

    const patchDisplay = document.getElementById('patch-display');
    const patchInfo = document.getElementById('patch-info');
    if (!patchDisplay || !patchInfo) return;

    // 更新色块显示
    patchDisplay.style.backgroundColor = `rgb(${color.r}, ${color.g}, ${color.b})`;

    // 均匀性 zone 定位：在预览区按比例渲染色块位置（周围黑底）
    let zoneBox = document.getElementById('patch-zone-box');
    if (color.zoneX !== undefined && color.zoneY !== undefined) {
        patchDisplay.style.backgroundColor = '#000';
        if (!zoneBox) {
            zoneBox = document.createElement('div');
            zoneBox.id = 'patch-zone-box';
            zoneBox.style.cssText = 'position:absolute; border-radius:4px; pointer-events:none;';
            patchDisplay.appendChild(zoneBox);
        }
        zoneBox.style.display = 'block';
        zoneBox.style.backgroundColor = `rgb(${color.r}, ${color.g}, ${color.b})`;
        const sizePct = Math.sqrt(Math.max(1, color.zoneSize || 15));  // 面积百分比 → 边长百分比
        zoneBox.style.width = `${sizePct}%`;
        zoneBox.style.height = `${sizePct}%`;
        zoneBox.style.left = `${(color.zoneX * 100) - sizePct / 2}%`;
        zoneBox.style.top = `${(color.zoneY * 100) - sizePct / 2}%`;
    } else if (zoneBox) {
        zoneBox.style.display = 'none';
    }

    // 更新信息标签
    patchInfo.textContent = `RGB(${color.r}, ${color.g}, ${color.b})`;

    // 文字颜色始终为白色
    patchInfo.style.color = '#ffffff';
}

/**
 * 处理测量开始
 */
function handleMeasurementStarted(patchName) {
    isMeasuring = true;
    currentPatchName = patchName;
    updateStatus(t('正在测量: {patchName}', {patchName: patchName}));
    // 更新色块名称显示
    document.getElementById('patch-name').textContent = patchName;
}

/**
 * 处理测量完成
 */
function handleMeasurementCompleted() {
    isMeasuring = false;

    // ========== CCMX 模式：测量完成后提示保存 ==========
    if (isCycleMeasuring && currentMeasureMode === 'ccmx') {
        isCycleMeasuring = false;
        setCycleButtonsState(false);

        // 提示用户保存测量数据
        updateStatus(t('CCMX 测量完成！请点击"保存数据"按钮保存当前测量，然后可更换探头继续测量'));

        // 自动弹出保存提示（可选）
        if (backend && confirm(t('CCMX测量完成！是否立即保存当前测量数据？\n保存后可在CCMX设置区域选择两次测量数据生成矩阵。'))) {
            saveCurrentData();
        }

        // 集成向导更新（仅向导发起的测量才驱动向导流程）
        if (measurementSource === 'wizard' && typeof handleMeasurementCompletedForWizard === 'function') {
            handleMeasurementCompletedForWizard();
        }
        // 测量结束退出色块全屏（恢复浮动窗口）
        backend?.exit_patch_window_fullscreen?.();
        clearPatchMeasuringHighlight();

        return; // 阻止后续的常规完成逻辑
    }

    // 如果是循环测量完成，更新状态
    if (isCycleMeasuring) {
        isCycleMeasuring = false;
        setCycleButtonsState(false);
        updateStatus(t('循环测量完成'));

        // 均匀性检测：测量完成后渲染热力图报告
        if (window.uniformityData && window.uniformityData.length > 0) {
            renderUniformityReport();
        }

        // 测量结束退出色块全屏（恢复浮动窗口）
        backend?.exit_patch_window_fullscreen?.();
        clearPatchMeasuringHighlight();

        // 集成向导更新（仅向导发起的测量才驱动向导流程）
        if (measurementSource === 'wizard' && typeof handleMeasurementCompletedForWizard === 'function') {
            handleMeasurementCompletedForWizard();
        }
    } else {
        updateStatus(t('测量完成'));
    }

    if (probeConnected) {
        updateProbeStatus('connected');
    }

    // 更新向导内的探头状态
    if (typeof updateWizardProbeStatus === 'function') {
        updateWizardProbeStatus();
    }

    // ========== ICC/LUT 模式：测量完成后自动弹出快速生成窗口 ==========
    if (currentMeasureMode === 'icc') {
        // ICC 模式测量完成，自动弹出快速生成窗口
        setTimeout(() => {
            showICCModal();
            updateStatus(t('ICC 测量完成，请设置保存路径并快速生成'));
        }, 500);
    } else if (currentMeasureMode === 'lut') {
        // LUT 模式测量完成，自动弹出快速生成窗口
        setTimeout(() => {
            showLUTModal();
            updateStatus(t('LUT 测量完成，请设置保存路径并快速生成'));
        }, 500);
    }
}

/**
 * 计算CIE 1976 u'v'坐标
 * 从CIE 1931 xy坐标转换
 */
function xyToUV(x, y) {
    if (x + y === 0) return { u: 0, v: 0 };
    const u = (4 * x) / (12 * y - 2 * x + 3);
    const v = (9 * y) / (12 * y - 2 * x + 3);
    return { u, v };
}

/**
 * 处理测量结果
 */
function handleMeasurementResult(resultJson) {
    // P1-D: 使用统一的 parsePayload helper
    const result = parsePayload(resultJson);
    if (!result.rgb) return;  // 解析失败时跳过

    // 更新实时色块数据显示
    updatePatchDataDisplay(result);

    // 存储数据
    storeMeasurementResult(result);

    // 更新已测量色块跟踪（用于外框标记）
    const patchName = result.patchName;
    if (patchName) {
        measuredPatches[patchName] = {
            rgb: [result.rgb.r, result.rgb.g, result.rgb.b],
            result: result
        };
        // 更新色块按钮的外框样式
        updatePatchButtonMeasuredStyle(patchName);
    }

    // 更新 CIE 图表 - 添加测量点
    if (typeof updateCIEChartPoint === 'function') {
        updateCIEChartPoint(result);
    }

    // 更新 Gamma 曲线（如果是灰阶测量）
    if (patchName && patchName.includes('%') && typeof updateGammaChartFromResult === 'function') {
        updateGammaChartFromResult(result);
    }

    // P2 集成：饱和度/色相扫描追踪图
    if (typeof addSaturationMeasurement === 'function') {
        addSaturationMeasurement(result);
    }
    // P2 集成：灰阶 CCT/Duv 追踪图
    if (typeof addCCTTrackMeasurement === 'function') {
        addCCTTrackMeasurement(result);
    }
    // P3 集成：HDR 灰阶测量累积（供 EOTF 追踪报告）
    if (patchName && patchName.startsWith('HDR-') && typeof window.hdrMeasurements !== 'undefined') {
        const code = patchName.split('-', 2)[1];
        window.hdrMeasurements = window.hdrMeasurements.filter(m => m.patchName !== patchName);
        window.hdrMeasurements.push({
            patchName,
            x: result.x, y: result.y, Y: result.Y
        });
        const reportBtn = document.getElementById('btn-hdr-report');
        if (reportBtn) reportBtn.disabled = window.hdrMeasurements.length < 5;
    }

    // 均匀性测量累积（供热力图渲染）
    if (patchName && patchName.startsWith('U-')) {
        addUniformityMeasurement(result);
    }

    // 更新显示器基础数据（如果测量了关键色块）
    updateDisplayBasicData(result);
}

/**
 * 更新实时色块数据显示
 */
function updatePatchDataDisplay(result) {
    // 色块名称
    document.getElementById('patch-name').textContent = result.patchName || '--';

    // RGB值
    const r = result.rgb.r;
    const g = result.rgb.g;
    const b = result.rgb.b;
    document.getElementById('patch-rgb').textContent = `RGB(${r}, ${g}, ${b})`;

    // xyY值（x、y 合并为一项，与 u'v' 显示格式一致）
    document.getElementById('patch-xy').textContent = `${result.x.toFixed(4)}, ${result.y.toFixed(4)}`;
    document.getElementById('patch-Y').textContent = result.Y.toFixed(2) + ' cd/m²';

    // 色温
    document.getElementById('patch-cct').textContent = result.cct ? Math.round(result.cct) + ' K' : '-- K';

    // Delta E
    document.getElementById('patch-deltae').textContent = result.deltaE ? result.deltaE.toFixed(2) : '--';

    // u'v'坐标
    const uv = xyToUV(result.x, result.y);
    document.getElementById('patch-uv').textContent = `${uv.u.toFixed(4)}, ${uv.v.toFixed(4)}`;
}

/**
 * 更新显示器基础数据
 */
function updateDisplayBasicData(result) {
    const patchName = result.patchName;

    // 更新峰值亮度（白色测量）
    if (patchName === '白' && result.Y > 0) {
        measurementData.gamut.white = result;
        document.getElementById('display-peak-luminance').textContent = result.Y.toFixed(2) + ' cd/m²';

        // 更新白点xy值
        document.getElementById('display-white-x').textContent = result.x.toFixed(4);
        document.getElementById('display-white-y').textContent = result.y.toFixed(4);

        // 如果有黑场数据，计算对比度
        if (measurementData.gamut.black && measurementData.gamut.black.Y > 0) {
            const contrast = result.Y / measurementData.gamut.black.Y;
            document.getElementById('display-contrast').textContent = contrast.toFixed(1) + ':1';
        }
    }

    // 更新黑场亮度
    if (patchName === '黑') {
        measurementData.gamut.black = result;
        document.getElementById('display-black-luminance').textContent = result.Y.toFixed(4) + ' cd/m²';

        // 如果有白场数据，计算对比度
        if (measurementData.gamut.white && measurementData.gamut.white.Y > 0 && result.Y > 0) {
            const contrast = measurementData.gamut.white.Y / result.Y;
            document.getElementById('display-contrast').textContent = contrast.toFixed(1) + ':1';
        }
    }

    // 更新白点色温和偏差
    if (patchName === '白' && result.cct) {
        document.getElementById('display-white-cct').textContent = Math.round(result.cct) + ' K';

        // 计算白点偏差（相对于D65）
        const d65 = { x: 0.3127, y: 0.3290 };
        const deltaE = calculateWhitePointDeltaE(result.x, result.y, d65.x, d65.y);
        document.getElementById('display-white-deviation').textContent = deltaE.toFixed(2) + ' ΔE';
    }
}

/**
 * 计算白点偏差（简化版Delta E 2000）
 * 使用CIE 1976 u'v'距离计算
 */
function calculateWhitePointDeltaE(x1, y1, x2, y2) {
    const uv1 = xyToUV(x1, y1);
    const uv2 = xyToUV(x2, y2);
    // u'v'距离乘以13转换为近似Delta E
    const distance = Math.sqrt(Math.pow(uv1.u - uv2.u, 2) + Math.pow(uv1.v - uv2.v, 2));
    return distance * 13;
}

/**
 * 处理色域覆盖率更新
 */
function handleGamutCoverageUpdated(coverageJson) {
    // P1-D: 使用统一的 parsePayload helper
    const coverage = parsePayload(coverageJson);

    // 更新色域覆盖率显示
    document.getElementById('gamut-srgb').textContent = coverage.sRGB ? coverage.sRGB.toFixed(1) + '%' : '--%';
    document.getElementById('gamut-p3').textContent = coverage['DCI-P3'] ? coverage['DCI-P3'].toFixed(1) + '%' : '--%';
    document.getElementById('gamut-adobe').textContent = coverage.AdobeRGB ? coverage.AdobeRGB.toFixed(1) + '%' : '--%';
    document.getElementById('gamut-rec2020').textContent = coverage.Rec2020 ? coverage.Rec2020.toFixed(1) + '%' : '--%';

    // 更新CIE图表 - 传递解析后的对象
    if (typeof updateCIEChartGamut === 'function') {
        updateCIEChartGamut(coverage);
    }

    // 后备方案：如果后端的 gamutTriangle 数据缺失，从测量点中重新构建
    if (!coverage.gamutTriangle || coverage.gamutTriangle.length !== 3) {
        if (typeof updateGamutTriangleFromMeasurements === 'function') {
            updateGamutTriangleFromMeasurements();
        }
    }
}

/**
 * 处理 Gamma 更新
 */
function handleGammaUpdated(gammaJson) {
    // P1-D: 使用统一的 parsePayload helper
    const gammaData = parsePayload(gammaJson);

    // 更新Gamma值显示（两个位置同步更新）
    if (gammaData.gamma) {
        const gammaStr = gammaData.gamma.toFixed(2);
        const displayGamma = document.getElementById('display-gamma');
        const gammaValue = document.getElementById('gamma-value');
        if (displayGamma) displayGamma.textContent = gammaStr;
        if (gammaValue) gammaValue.textContent = gammaStr;
    }

    // 更新Gamma图表 - 传递解析后的对象
    if (typeof updateGammaChart === 'function') {
        updateGammaChart(gammaData);
    }
}

/**
 * 处理显示器基础数据更新
 */
function handleDisplayBasicDataUpdated(dataJson) {
    // P1-D: 使用统一的 parsePayload helper
    const data = parsePayload(dataJson);

    // 更新峰值亮度
    if (data.peakLuminance !== null && data.peakLuminance !== undefined) {
        document.getElementById('display-peak-luminance').textContent = data.peakLuminance.toFixed(2) + ' cd/m²';
    }

    // 更新黑场亮度
    if (data.blackLuminance !== null && data.blackLuminance !== undefined) {
        document.getElementById('display-black-luminance').textContent = data.blackLuminance.toFixed(4) + ' cd/m²';
    }

    // 更新对比度
    if (data.contrastRatio !== null && data.contrastRatio !== undefined) {
        document.getElementById('display-contrast').textContent = data.contrastRatio.toFixed(1) + ':1';
    }

    // 更新白点色温
    if (data.whiteCct !== null && data.whiteCct !== undefined) {
        document.getElementById('display-white-cct').textContent = Math.round(data.whiteCct) + ' K';
    }

    // 更新白点x值
    if (data.whiteX !== null && data.whiteX !== undefined) {
        document.getElementById('display-white-x').textContent = data.whiteX.toFixed(4);
    }

    // 更新白点y值
    if (data.whiteY !== null && data.whiteY !== undefined) {
        document.getElementById('display-white-y').textContent = data.whiteY.toFixed(4);
    }

    // 更新白点偏差
    if (data.whiteDeviation !== null && data.whiteDeviation !== undefined) {
        document.getElementById('display-white-deviation').textContent = data.whiteDeviation.toFixed(2) + ' ΔE';
    }

    // 更新Gamma值
    if (data.gamma !== null && data.gamma !== undefined) {
        const el = document.getElementById('display-gamma');
        if (el) el.textContent = data.gamma.toFixed(2);
    }
}

/**
 * 处理延迟配置更新
 */
function handleDelayConfigUpdated(delayMs) {
    // 更新延迟输入框的值
    const delayInput = document.getElementById('measure-delay');
    if (delayInput) {
        delayInput.value = delayMs;
    }
    updateStatus(t('自动配置测量延迟: {delayMs}ms', {delayMs: delayMs}));
}

/**
 * 处理探头类型自动切换通知
 * 当后端自动检测到探头类型并切换时，更新前端 UI
 */
function handleProbeTypeAutoSwitched(probeType) {
    const probeSelect = document.getElementById('probe-type');
    if (probeSelect) {
        // 设置选择框的值
        probeSelect.value = probeType;
        updateStatus(t('探头类型已自动切换为: {probeType}', {probeType: probeType}));
    }
}

/**
 * 处理设备枚举结果
 */
function handleInstrumentsEnumerated(devicesJson) {
    // P1-D: 使用统一的 parsePayload helper
    const data = parsePayload(devicesJson);
    if (data.devices && data.devices.length > 0) {
        const deviceList = data.devices.map(d => t('{d_name} ({d_probe_type})', {d_name: d.name, d_probe_type: d.probe_type || t('未知')})).join(', ');
        updateStatus(t('检测到设备: {deviceList}', {deviceList: deviceList}));
    } else {
        updateStatus(t('未检测到仪器设备'));
    }
}

/**
 * 处理色块列表更新
 */
function handlePatchListUpdated(patchListJson) {
    // P1-D: 使用统一的 parsePayload helper
    const patchList = parsePayload(patchListJson);
    if (!patchList.mode) return;  // 解析失败时跳过
    
    currentMeasureMode = patchList.mode;
    currentPatchList = patchList;

    // ========== CCMX 模式：使用 5 个基础色块（含黑场） ==========
    if (currentMeasureMode === 'ccmx') {
        allPatchList.length = 0;
        allPatchList = [
            {name:'白', rgb:[255,255,255]},
            {name:'红', rgb:[255,0,0]},
            {name:'绿', rgb:[0,255,0]},
            {name:'蓝', rgb:[0,0,255]},
            {name:'黑', rgb:[0,0,0]}
        ];

        // 更新状态栏提示
        updateStatus(t('CCMX 矩阵制作 - 请测量5个基础色块后保存数据'));
    } else {
        // 非 CCMX 模式：使用后端下发的色块列表
        allPatchList.length = 0;  // 清空旧数据
        if (patchList.groups && patchList.groups.length > 0) {
            patchList.groups.forEach(group => {
                group.patches.forEach(patch => {
                    // zone 为均匀性测量的区域定位 [x, y, size]，其他模式为 null
                    allPatchList.push({ name: patch.name, rgb: patch.rgb, zone: patch.zone || null });
                });
            });
        }
    }

    // 更新底部色块栏
    updatePatchBar(patchList);

    // 更新状态
    const modeNames = {
        'gamut': t('屏幕检测(色彩空间)'),
        'icc': t('屏幕校正(ICC制作)'),
        'lut': t('硬件校准(3DLUT制作)'),
        'custom': t('自定义颜色'),
        'ccmx': t('CCMX 矩阵制作'),
        'saturation': t('饱和度/色相扫描'),
        'hdr': t('HDR EOTF 追踪'),
        'uniformity': t('均匀性检测'),
        'autocal': t('自动校准(AutoCal闭环)'),
        'dispcal': t('显示器校准')
    };

    if (patchList.customMode) {
        updateStatus(t('自定义颜色模式 - 请输入 RGB 值'));
    } else if (currentMeasureMode === 'ccmx') {
        // CCMX 模式显示特殊提示
        updateStatus(t('CCMX 矩阵制作 - 请测量5个基础色块后保存数据'));
    } else {
        // 其他模式显示常规状态
        updateStatus(t('{modeNames_patchList_mode_____patchList_mode} - 共 {patchList_total} 个色块', {modeNames_patchList_mode_____patchList_mode: modeNames[patchList.mode] || patchList.mode, patchList_total: patchList.total}));
    }
}

/**
 * 更新底部色块栏（只更新色块列表区域，测量按钮保持固定）
 */
function updatePatchBar(patchList) {
    const patchListArea = document.getElementById('patch-list-area');
    if (!patchListArea) return;

    // 清空色块列表区域
    patchListArea.innerHTML = '';

    // 如果是自定义模式，显示提示或已加载的色块
    if (patchList.customMode) {
        // 如果有已加载的色块（来自 loadedPatches 标记），显示它们
        if (patchList.loadedPatches && patchList.groups && patchList.groups.length > 0) {
            // 渲染已加载的自定义色块
            patchList.groups.forEach(group => {
                const groupDiv = document.createElement('div');
                groupDiv.className = 'patch-group';

                const label = document.createElement('span');
                label.className = 'patch-group-label';
                label.textContent = group.label;
                groupDiv.appendChild(label);

                group.patches.forEach(patch => {
                    const patchItem = document.createElement('div');
                    patchItem.className = 'patch-item';

                    const button = document.createElement('button');
                    button.className = 'patch-btn';
                    button.dataset.color = patch.rgb.join(',');
                    button.dataset.name = patch.name;
                    button.style.background = `rgb(${patch.rgb[0]}, ${patch.rgb[1]}, ${patch.rgb[2]})`;

                    // 为深色色块添加边框
                    const brightness = (patch.rgb[0] + patch.rgb[1] + patch.rgb[2]) / 3;
                    if (brightness < 30) {
                        button.style.border = '1px solid rgba(255, 255, 255, 0.3)';
                    }

                    // 检查是否已测量
                    if (measuredPatches[patch.name]) {
                        button.classList.add('measured');
                    }

                    button.addEventListener('click', () => onPatchButtonClick(button));
                    patchItem.appendChild(button);

                    const patchLabel = document.createElement('span');
                    patchLabel.className = 'patch-label';
                    patchLabel.textContent = patch.name;
                    patchItem.appendChild(patchLabel);

                    groupDiv.appendChild(patchItem);
                });

                patchListArea.appendChild(groupDiv);
            });
        } else {
            // 没有加载色块时显示提示
            const hintGroup = document.createElement('div');
            hintGroup.className = 'patch-group custom-mode-hint';
            hintGroup.innerHTML = `
                <span class="patch-group-label">自定义颜色</span>
                <div class="hint-text">请在左侧面板添加色块后点击"加载色块"</div>
            `;
            patchListArea.appendChild(hintGroup);
        }
    } else {
        // CCMX 模式：使用 allPatchList 渲染色块（含黑场）
        if (currentMeasureMode === 'ccmx' && allPatchList.length > 0) {
            const groupDiv = document.createElement('div');
            groupDiv.className = 'patch-group';

            const label = document.createElement('span');
            label.className = 'patch-group-label';
            label.textContent = t('基础色块');
            groupDiv.appendChild(label);

            allPatchList.forEach(patch => {
                const patchItem = document.createElement('div');
                patchItem.className = 'patch-item';

                const button = document.createElement('button');
                button.className = 'patch-btn';
                button.dataset.color = patch.rgb.join(',');
                button.dataset.name = patch.name;
                button.style.background = `rgb(${patch.rgb[0]}, ${patch.rgb[1]}, ${patch.rgb[2]})`;

                // 为深色色块添加边框
                const brightness = (patch.rgb[0] + patch.rgb[1] + patch.rgb[2]) / 3;
                if (brightness < 30) {
                    button.style.border = '1px solid rgba(255, 255, 255, 0.3)';
                }

                // 检查是否已测量
                if (measuredPatches[patch.name]) {
                    button.classList.add('measured');
                }

                button.addEventListener('click', () => onPatchButtonClick(button));
                patchItem.appendChild(button);

                const patchLabel = document.createElement('span');
                patchLabel.className = 'patch-label';
                patchLabel.textContent = patch.name;
                patchItem.appendChild(patchLabel);

                groupDiv.appendChild(patchItem);
            });

            patchListArea.appendChild(groupDiv);
        } else if (patchList.groups && patchList.groups.length > 0) {
            // 其他模式：根据分组生成色块按钮
            patchList.groups.forEach(group => {
            const groupDiv = document.createElement('div');
            groupDiv.className = 'patch-group';

            // 分组标签
            const label = document.createElement('span');
            label.className = 'patch-group-label';
            label.textContent = group.label;
            groupDiv.appendChild(label);

            // 色块按钮
            group.patches.forEach(patch => {
                const patchItem = document.createElement('div');
                patchItem.className = 'patch-item';

                const button = document.createElement('button');
                button.className = 'patch-btn';
                button.dataset.color = patch.rgb.join(',');
                button.dataset.name = patch.name;
                button.style.background = `rgb(${patch.rgb[0]}, ${patch.rgb[1]}, ${patch.rgb[2]})`;

                // 为深色色块添加边框
                const brightness = (patch.rgb[0] + patch.rgb[1] + patch.rgb[2]) / 3;
                if (brightness < 30) {
                    button.style.border = '1px solid rgba(255, 255, 255, 0.3)';
                }

                // 检查是否已测量，添加已测量样式
                if (measuredPatches[patch.name]) {
                    button.classList.add('measured');
                }

                button.addEventListener('click', () => onPatchButtonClick(button));
                patchItem.appendChild(button);

                const patchLabel = document.createElement('span');
                patchLabel.className = 'patch-label';
                patchLabel.textContent = patch.name;
                patchItem.appendChild(patchLabel);

                groupDiv.appendChild(patchItem);
            });

            patchListArea.appendChild(groupDiv);
        });
        }  // 关闭其他模式的 else 分支
    }  // 关闭非自定义模式的 else 分支

    // 重新初始化滚动
    initPatchBarScroll();
}

/**
 * 更新色块按钮的已测量样式（绿色外框）
 * @param {string} patchName - 色块名称
 */
function updatePatchButtonMeasuredStyle(patchName) {
    // 查找对应的色块按钮
    const buttons = document.querySelectorAll('.patch-btn[data-name]');
    buttons.forEach(button => {
        if (button.dataset.name === patchName) {
            button.classList.add('measured');
        }
    });
}

/**
 * 高亮底部色块栏：当前正在测量的色块 + 下一个待测色块
 * @param {string} patchName - 当前色块名
 * @param {number} current - 当前序号（1-based）
 * @param {number} total - 总数
 * @param {Array} rgb - 当前色块 RGB
 */
function updatePatchMeasuringHighlight(patchName, current, total, rgb) {
    clearPatchMeasuringHighlight();

    const buttons = document.querySelectorAll('.patch-btn[data-name]');
    let currentBtn = null;
    buttons.forEach(button => {
        if (button.dataset.name === patchName) {
            currentBtn = button;
        }
    });
    if (currentBtn) {
        currentBtn.classList.add('measuring');
    }

    // 下一块预高亮：从后端下发的色块顺序列表推断
    const nextPatch = (current > 0 && current < total && allPatchList[current])
        ? allPatchList[current]
        : null;
    if (nextPatch && nextPatch.name) {
        buttons.forEach(button => {
            if (button.dataset.name === nextPatch.name) {
                button.classList.add('up-next');
            }
        });
    }

    // 同步步骤 4 面板中的色块预览（原先从未被更新）
    if (Array.isArray(rgb)) {
        const previewBox = document.getElementById('wizard-patch-display');
        const previewInfo = document.getElementById('wizard-patch-info');
        if (previewBox) {
            previewBox.style.background = `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
            previewBox.classList.toggle('dark-patch', (rgb[0] + rgb[1] + rgb[2]) / 3 < 30);
        }
        if (previewInfo && patchName) {
            previewInfo.textContent = `${patchName} · RGB(${rgb.join(', ')})`;
        }
    }
}

/**
 * 清除底部色块栏的测量高亮
 */
function clearPatchMeasuringHighlight() {
    document.querySelectorAll('.patch-btn.measuring, .patch-btn.up-next').forEach(btn => {
        btn.classList.remove('measuring', 'up-next');
    });
    const previewInfo = document.getElementById('wizard-patch-info');
    if (previewInfo) {
        previewInfo.textContent = t('准备测量');
    }
}

/**
 * 初始化底部自定义颜色输入事件
 */
function initCustomBarEvents() {
    const customR = document.getElementById('custom-r-bar');
    const customG = document.getElementById('custom-g-bar');
    const customB = document.getElementById('custom-b-bar');
    const previewBar = document.getElementById('custom-preview-bar');
    const btnShow = document.getElementById('btn-custom-show-bar');

    // 实时更新预览
    function updatePreview() {
        const r = clamp(parseInt(customR?.value) || 0);
        const g = clamp(parseInt(customG?.value) || 0);
        const b = clamp(parseInt(customB?.value) || 0);
        if (previewBar) {
            previewBar.style.background = `rgb(${r}, ${g}, ${b})`;
        }
    }

    [customR, customG, customB].forEach(input => {
        if (input) {
            input.addEventListener('input', updatePreview);
            input.addEventListener('change', updatePreview);
        }
    });

    // 显示按钮
    if (btnShow) {
        btnShow.addEventListener('click', () => {
            const r = clamp(parseInt(customR?.value) || 0);
            const g = clamp(parseInt(customG?.value) || 0);
            const b = clamp(parseInt(customB?.value) || 0);

            currentPatchName = '自定义';
            currentPatchRGB = [r, g, b];

            if (backend) {
                backend.show_patch(r, g, b);
            }

            updateStatus(t('显示自定义色块: RGB({r}, {g}, {b})', {r: r, g: g, b: b}));
        });
    }

    // 初始化预览
    updatePreview();
}

/**
 * 存储测量结果
 */
function storeMeasurementResult(result) {
    const name = result.patchName;

    // 色域测量
    if (name === '红') measurementData.gamut.red = result;
    else if (name === '绿') measurementData.gamut.green = result;
    else if (name === '蓝') measurementData.gamut.blue = result;
    else if (name === '白') measurementData.gamut.white = result;
    else if (name === '黑') measurementData.gamut.black = result;

    // 灰阶测量
    if (name && name.includes('%')) {
        // 清除之前的相同灰阶数据，避免重复
        const existingIndex = measurementData.grayScale.findIndex(r => r.patchName === name);
        if (existingIndex >= 0) {
            measurementData.grayScale[existingIndex] = result;
        } else {
            measurementData.grayScale.push(result);
        }
    }
}

/**
 * 处理循环测量进度
 */
function handleCycleProgress(progressJson) {
    // P1-D: 使用统一的 parsePayload helper
    const progress = parsePayload(progressJson);
    if (!progress.current) return;  // 解析失败时跳过

    // 引导式测量：等待用户确认探头就位（全屏控制条与 WebUI 进度面板同步显示确认按钮）
    const confirmArea = document.getElementById('guided-confirm-area');
    if (confirmArea) {
        confirmArea.style.display = (progress.guided && progress.waitingConfirm) ? 'flex' : 'none';
    }
    if (progress.guided && progress.waitingConfirm) {
        updateStatus(t('引导测量 {progress_current}/{progress_total}: 请将探头对准 {progress_patchName} 区域，确认后测量', {progress_current: progress.current, progress_total: progress.total, progress_patchName: progress.patchName}));
    } else {
        updateStatus(t('循环测量: {progress_current}/{progress_total} - {progress_patchName}', {progress_current: progress.current, progress_total: progress.total, progress_patchName: progress.patchName}));
    }

    // 底部色块高亮：当前块"测量中" + 下一块"即将测量"（真实循环走此信号，
    // handleCycleProgressEnhanced 仅兼容旧路径）
    const patch = (allPatchList || []).find(p => p.name === progress.patchName);
    updatePatchMeasuringHighlight(progress.patchName, progress.current, progress.total, patch?.rgb);

    // 更新进度条或显示（可选）
    const progressPercent = Math.round((progress.current / progress.total) * 100);
    console.log(`测量进度: ${progressPercent}% (${progress.current}/${progress.total})`);
}

/**
 * 处理 dispcal 校准进度
 */
function handleCalibrationProgress(progressJson) {
    // P1-D: 使用统一的 parsePayload helper
    const progress = parsePayload(progressJson);

    // 检查是否被取消
    if (progress.cancelled) {
        isCalibrating = false;
        calibrationDone = false;
        setCycleButtonsState(false);
        hideDispcalSpinner();
        updateStatus(t('显示器校准已取消'));
        // 恢复底部色块栏显示阶段二的待测量色块
        if (currentPatchList && currentPatchList.mode) {
            updatePatchBar(currentPatchList);
        }
        return;
    }

    // 检查是否需要打开测量窗口
    if (progress.need_patch_window) {
        updateStatus(t('请先打开测量窗口：视图 → 测量窗口'));
        // 显示提示对话框
        showPatchWindowRequiredDialog();
        return;
    }

    // 检查 Web Server 阶段是否完成（dispcal 正在生成校准文件）
    if (progress.web_server_complete) {
        updateStatus(t('色块测量完成，正在生成校准文件...'));
        // 更新 patchListArea 显示中间状态
        const patchListArea = document.getElementById('patch-list-area');
        if (patchListArea) {
            patchListArea.innerHTML = `
                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center;
                            min-height: 52px; padding: 8px 16px; text-align: center; width: 100%;">
                    <div style="font-size: 13px; color: #8b949e;">
                        <span class="spinner" style="display: inline-block; width: 16px; height: 16px;
                            border: 2px solid rgba(139,148,158,0.3); border-top-color: #8b949e;
                            border-radius: 50%; animation: spin 1s linear infinite; vertical-align: middle; margin-right: 6px;"></span>
                        色块测量完成，正在生成校准文件...
                    </div>
                </div>
            `;
        }
        return;
    }

    // 显示校准进度信息
    if (progress.message) {
        updateStatus(t('显示器校准: {progress_message}', {progress_message: progress.message}));
    } else if (progress.current && progress.total) {
        const percent = Math.round((progress.current / progress.total) * 100);
        updateStatus(t('显示器校准进度: {percent}% ({progress_current}/{progress_total})', {percent: percent, progress_current: progress.current, progress_total: progress.total}));
    }

    console.log(`校准进度: ${JSON.stringify(progress)}`);
}

/**
 * 隐藏 dispcal 校准加载动画
 */
function hideDispcalSpinner() {
    const spinner = document.getElementById('dispcal-spinner');
    if (spinner) {
        spinner.remove();
    }
}

/**
 * 显示需要打开测量窗口的提示对话框
 */
function showPatchWindowRequiredDialog() {
    const dialog = document.createElement('div');
    dialog.className = 'alert-dialog';
    dialog.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: #1c2128;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 20px;
        z-index: 10000;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
        min-width: 300px;
    `;

    dialog.innerHTML = `
        <div style="margin-bottom: 15px; font-size: 14px; color: #cdd9f5;">
            <h3 style="margin: 0 0 10px 0; color: #ffffff;">需要打开测量窗口</h3>
            <p style="margin: 5px 0;">ICC 制作模式需要使用测量窗口显示色块。</p>
            <p style="margin: 5px 0;">请按以下步骤操作：</p>
            <ol style="margin: 5px 0; padding-left: 20px;">
                <li>点击菜单 <strong>视图 → 测量窗口</strong> 打开浮动窗口</li>
                <li>将窗口拖动到要测量的显示器上</li>
                <li>点击 <strong>制作ICC文件</strong> 按钮重新开始</li>
            </ol>
        </div>
        <button id="btn-close-dialog" class="btn btn-primary" style="width: 100%;">我知道了</button>
    `;

    document.body.appendChild(dialog);

    document.getElementById('btn-close-dialog').addEventListener('click', () => {
        document.body.removeChild(dialog);
    });

    // 自动关闭（8秒后）
    setTimeout(() => {
        if (document.body.contains(dialog)) {
            document.body.removeChild(dialog);
        }
    }, 8000);
}

/**
 * 处理探头状态变化
 */
function handleProbeStatusChanged(statusJson) {
    // P1-D: 使用统一的 parsePayload helper
    const status = parsePayload(statusJson);

    // 维护全局连接状态（向导第3步的三态显示依赖）
    probeConnecting = (status.status === 'connecting');
    if (status.connected) {
        probeConnected = true;
        if (status.probeType) probeLastType = status.probeType;
    } else if (status.status === 'error' || status.status === 'disconnected') {
        probeConnected = false;
    }

    // 在页面上显示调试信息
    const statusText = document.getElementById('status-text');
    if (statusText && status.connected) {
        statusText.textContent = t('[DEBUG] 收到探头连接信号: {JSON_stringify_status}', {JSON_stringify_status: JSON.stringify(status)});
        setTimeout(() => {
            if (statusText.textContent.startsWith('[DEBUG]')) {
                statusText.textContent = t('已连接');
            }
        }, 2000);
    }

    if (status.connected) {
        updateProbeStatus('connected');

        // ========== 探头类型自动判断：禁用/启用光谱校正选择框 ==========
        updateCorrectionUIState(status.probeType);
    } else if (status.status === 'connecting') {
        updateProbeStatus('connecting');
    } else if (status.status === 'error') {
        updateProbeStatus('error');
        if (status.error) {
            console.error('探头错误:', status.error);
        }
    } else {
        updateProbeStatus('disconnected');
    }

    // 更新向导内的探头状态
    if (typeof updateWizardProbeStatus === 'function') {
        updateWizardProbeStatus();
    }
}

/**
 * 根据探头类型更新光谱校正 UI 状态
 * @param {string} probeType - 探头类型（如 'i1d3', 'i1pro2' 等）
 */
function updateCorrectionUIState(probeType) {
    const correctionSelect = document.getElementById('correction-file-select');

    if (!correctionSelect) return;

    // 分光光度计列表（不需要光谱校正）
    const spectrophotometers = [
        'i1pro', 'i1pro2', 'i1pro3',
        'colormunki', 'colormunki_smile',
        'specbos', 'spectraval',
        'spectro', 'spectroscan'
    ];

    // 判断是否为分光光度计
    const isSpectrophotometer = probeType && spectrophotometers.includes(probeType.toLowerCase());

    if (isSpectrophotometer) {
        // 分光仪：禁用光谱校正选择框
        correctionSelect.disabled = true;
        correctionSelect.value = '';
        if (backend) backend.set_correction_file_path('');
    } else {
        // 色度计（如 i1d3, spyder 等）：启用光谱校正选择框
        correctionSelect.disabled = false;
    }
}

/**
 * 点击色块按钮 - 显示色块
 */
function onPatchButtonClick(button) {
    if (!backend) {
        updateStatus(t('错误: 后端未连接'));
        return;
    }

    const color = button.dataset.color;
    const name = button.dataset.name;
    const [r, g, b] = color.split(',').map(Number);

    // 保存当前选中的色块信息
    currentPatchName = name;
    currentPatchRGB = [r, g, b];

    // 显示色块
    backend.show_patch(r, g, b);

    // ========== 关键：设置色块名称（用于单次测量替换循环测量数据） ==========
    // 必须在 show_patch 之后调用，因为 show_patch 会清空后端的显式名称
    backend.set_current_patch_name(name);

    // 高亮当前按钮
    document.querySelectorAll('.patch-btn').forEach(btn => btn.classList.remove('active'));
    button.classList.add('active');

    // 如果该色块已被测量，显示历史测量数据
    if (measuredPatches[name] && measuredPatches[name].result) {
        updatePatchDataDisplay(measuredPatches[name].result);
        updateStatus(t('显示色块: {name} RGB({r},{g},{b}) (已测量，可重新测量替换)', {name: name, r: r, g: g, b: b}));
    } else {
        // 清除当前色块数据显示（等待新测量）
        document.getElementById('patch-name').textContent = name;
        document.getElementById('patch-rgb').textContent = `RGB(${r}, ${g}, ${b})`;
        document.getElementById('patch-xy').textContent = '--, --';
        document.getElementById('patch-Y').textContent = '-- cd/m²';
        document.getElementById('patch-cct').textContent = '-- K';
        document.getElementById('patch-deltae').textContent = '--';
        document.getElementById('patch-uv').textContent = '--, --';
        updateStatus(t('显示色块: {name} RGB({r},{g},{b}) (待测量)', {name: name, r: r, g: g, b: b}));
    }
}

/**
 * 显示自定义 RGB 色块
 */
function showCustomPatch() {
    if (!backend) return;

    const r = clamp(parseInt(document.getElementById('custom-r').value) || 0);
    const g = clamp(parseInt(document.getElementById('custom-g').value) || 0);
    const b = clamp(parseInt(document.getElementById('custom-b').value) || 0);

    // 保存当前选中的色块信息
    currentPatchName = '自定义';
    currentPatchRGB = [r, g, b];

    backend.show_patch(r, g, b);

    // 清除其他按钮的高亮状态
    document.querySelectorAll('.patch-btn').forEach(btn => btn.classList.remove('active'));

    updateStatus(t('显示自定义色块: RGB({r},{g},{b})', {r: r, g: g, b: b}));
}

/**
 * 更新自定义颜色预览
 */
function updateCustomPreview() {
    const r = clamp(parseInt(document.getElementById('custom-r').value) || 0);
    const g = clamp(parseInt(document.getElementById('custom-g').value) || 0);
    const b = clamp(parseInt(document.getElementById('custom-b').value) || 0);

    const previewBox = document.getElementById('custom-preview-box');
    if (previewBox) {
        previewBox.style.backgroundColor = `rgb(${r}, ${g}, ${b})`;
    }
}

/**
 * 初始化自定义颜色模式
 */
function initCustomMode() {
    const customR = document.getElementById('custom-r');
    const customG = document.getElementById('custom-g');
    const customB = document.getElementById('custom-b');

    // 实时更新预览
    [customR, customG, customB].forEach(input => {
        if (input) {
            input.addEventListener('input', updateCustomPreview);
            input.addEventListener('change', updateCustomPreview);
        }
    });

    // 初始化预览
    updateCustomPreview();

    // ========== 新增：自定义色块管理功能 ==========

    // 自定义色块列表
    customPatchesList = [];

    // 绑定事件
    initCustomPatchesEvents();
}

// 自定义色块列表（全局）
let customPatchesList = [];

// 当前选中的色块索引（-1 表示未选中）
let selectedPatchIndex = -1;

// 已加载的自定义色块组文件名
let loadedCustomPatchesFilename = '';

/**
 * 初始化自定义色块管理事件
 */
function initCustomPatchesEvents() {
    // 添加色块按钮
    const btnAddPatch = document.getElementById('btn-add-custom-patch');
    if (btnAddPatch) {
        btnAddPatch.addEventListener('click', addCustomPatch);
    }

    // 清空列表按钮
    const btnClearPatches = document.getElementById('btn-clear-patches');
    if (btnClearPatches) {
        btnClearPatches.addEventListener('click', clearCustomPatches);
    }

    // 保存色块组按钮
    const btnSavePatches = document.getElementById('btn-save-patches-file');
    if (btnSavePatches) {
        btnSavePatches.addEventListener('click', saveCustomPatchesFile);
    }

    // 加载文件按钮
    const btnLoadFile = document.getElementById('btn-load-patches-file');
    if (btnLoadFile) {
        btnLoadFile.addEventListener('click', loadCustomPatchesFile);
    }

    // 删除文件按钮
    const btnDeleteFile = document.getElementById('btn-delete-patches-file');
    if (btnDeleteFile) {
        btnDeleteFile.addEventListener('click', deleteCustomPatchesFile);
    }

    // 文件选择框变化事件
    const fileSelect = document.getElementById('custom-patches-file-select');
    if (fileSelect) {
        fileSelect.addEventListener('change', function() {
            const btnDelete = document.getElementById('btn-delete-patches-file');
            if (btnDelete) {
                btnDelete.disabled = !this.value;
            }
        });
    }

    // RGB 输入变化时，更新选中色块的颜色
    ['custom-r', 'custom-g', 'custom-b'].forEach(id => {
        const input = document.getElementById(id);
        if (input) {
            input.addEventListener('input', () => {
                updateCustomPreview();
                // 如果有选中的色块，实时更新它的颜色
                if (selectedPatchIndex >= 0 && selectedPatchIndex < customPatchesList.length) {
                    updateSelectedPatchColor();
                }
            });

            // 滚轮事件：滚动改变数值
            input.addEventListener('wheel', (e) => {
                e.preventDefault();

                let value = parseInt(input.value) || 0;
                // 向下滚动减少，向上滚动增加
                // 按住 Shift 时步进为 10，否则为 1
                const step = e.shiftKey ? 10 : 1;

                if (e.deltaY > 0) {
                    // 向下滚动：减少数值
                    value = Math.max(0, value - step);
                } else {
                    // 向上滚动：增加数值
                    value = Math.min(255, value + step);
                }

                input.value = value;

                // 触发更新
                updateCustomPreview();
                if (selectedPatchIndex >= 0 && selectedPatchIndex < customPatchesList.length) {
                    updateSelectedPatchColor();
                }
            });
        }
    });

    // 初始化右键菜单
    initPatchContextMenu();

    // 初始化加载文件列表
    if (backend) {
        backend.get_custom_patches_file_list();
    }
}

/**
 * 初始化右键菜单
 */
function initPatchContextMenu() {
    const contextMenu = document.getElementById('patch-context-menu');
    if (!contextMenu) return;

    // 点击其他地方隐藏菜单
    document.addEventListener('click', (e) => {
        if (!contextMenu.contains(e.target)) {
            contextMenu.classList.remove('visible');
        }
    });

    // 重命名
    const renameItem = document.getElementById('ctx-rename');
    if (renameItem) {
        renameItem.addEventListener('click', () => {
            contextMenu.classList.remove('visible');
            renameSelectedPatch();
        });
    }

    // 删除
    const deleteItem = document.getElementById('ctx-delete');
    if (deleteItem) {
        deleteItem.addEventListener('click', () => {
            contextMenu.classList.remove('visible');
            deleteSelectedPatch();
        });
    }
}

/**
 * 显示右键菜单
 * @param {number} x - 鼠标 X 坐标
 * @param {number} y - 鼠标 Y 坐标
 */
function showPatchContextMenu(x, y) {
    const contextMenu = document.getElementById('patch-context-menu');
    if (!contextMenu) return;

    contextMenu.style.left = x + 'px';
    contextMenu.style.top = y + 'px';
    contextMenu.classList.add('visible');
}

/**
 * 重命名选中的色块
 */
function renameSelectedPatch() {
    if (selectedPatchIndex < 0 || selectedPatchIndex >= customPatchesList.length) return;

    const patch = customPatchesList[selectedPatchIndex];
    const newName = prompt('请输入色块名称:', patch.name);

    if (newName !== null && newName.trim() !== '') {
        patch.name = newName.trim();
        updateCustomPatchesListDisplay();
        updateStatus(t('已重命名为: {newName_trim}', {newName_trim: newName.trim()}));
    }
}

/**
 * 删除选中的色块
 */
function deleteSelectedPatch() {
    if (selectedPatchIndex < 0 || selectedPatchIndex >= customPatchesList.length) return;

    const removed = customPatchesList.splice(selectedPatchIndex, 1)[0];
    selectedPatchIndex = -1;  // 清除选中状态
    updateCustomPatchesListDisplay();
    updateStatus(t('已删除色块: {removed_name}', {removed_name: removed.name}));
}

/**
 * 添加自定义色块
 */
function addCustomPatch() {
    const r = clamp(parseInt(document.getElementById('custom-r').value) || 0);
    const g = clamp(parseInt(document.getElementById('custom-g').value) || 0);
    const b = clamp(parseInt(document.getElementById('custom-b').value) || 0);

    const patch = { name: t('色块{n}', {n: customPatchesList.length + 1}), rgb: [r, g, b] };
    customPatchesList.push(patch);

    // 选中新添加的色块
    selectedPatchIndex = customPatchesList.length - 1;

    updateCustomPatchesListDisplay();
    updateStatus(t('已添加色块 RGB({r},{g},{b})', {r: r, g: g, b: b}));
}

/**
 * 更新选中色块的颜色
 */
function updateSelectedPatchColor() {
    if (selectedPatchIndex < 0 || selectedPatchIndex >= customPatchesList.length) return;

    const r = clamp(parseInt(document.getElementById('custom-r').value) || 0);
    const g = clamp(parseInt(document.getElementById('custom-g').value) || 0);
    const b = clamp(parseInt(document.getElementById('custom-b').value) || 0);

    customPatchesList[selectedPatchIndex].rgb = [r, g, b];

    // 更新列表显示
    updateCustomPatchesListDisplay();
}

/**
 * 选中色块
 * @param {number} index - 色块索引
 */
function selectPatch(index) {
    if (index < 0 || index >= customPatchesList.length) return;

    selectedPatchIndex = index;
    const patch = customPatchesList[index];

    // 更新 RGB 输入框
    document.getElementById('custom-r').value = patch.rgb[0];
    document.getElementById('custom-g').value = patch.rgb[1];
    document.getElementById('custom-b').value = patch.rgb[2];

    // 更新预览
    updateCustomPreview();

    // 更新列表显示（高亮选中项）
    updateCustomPatchesListDisplay();
}

/**
 * 清空自定义色块列表
 */
function clearCustomPatches() {
    customPatchesList = [];
    selectedPatchIndex = -1;
    loadedCustomPatchesFilename = '';
    updateCustomPatchesListDisplay();
    updateStatus(t('已清空色块列表'));
}

/**
 * 更新自定义色块列表显示（同时更新底部测量栏）
 */
function updateCustomPatchesListDisplay() {
    const listContainer = document.getElementById('custom-patches-list');
    const countBadge = document.getElementById('custom-patch-count');
    const btnSave = document.getElementById('btn-save-patches-file');

    if (!listContainer) return;

    // 更新计数
    if (countBadge) {
        countBadge.textContent = t('{customPatchesList_length} 个', {customPatchesList_length: customPatchesList.length});
    }

    // 更新按钮状态
    if (btnSave) {
        btnSave.disabled = customPatchesList.length === 0;
    }

    // 清空列表容器
    listContainer.innerHTML = '';

    if (customPatchesList.length === 0) {
        listContainer.innerHTML = '<div class="empty-hint">点击上方 + 添加色块</div>';
    } else {
        // 渲染每个色块项（只显示色块颜色）
        customPatchesList.forEach((patch, index) => {
            const item = document.createElement('div');
            item.className = 'custom-patch-item';
            if (index === selectedPatchIndex) {
                item.classList.add('selected');
            }

            const brightness = (patch.rgb[0] + patch.rgb[1] + patch.rgb[2]) / 3;
            const rgbText = `RGB(${patch.rgb[0]}, ${patch.rgb[1]}, ${patch.rgb[2]})`;

            item.innerHTML = `
                <div class="patch-preview-small"
                     style="background: rgb(${patch.rgb[0]},${patch.rgb[1]},${patch.rgb[2]});${brightness < 30 ? ' border: 1px solid rgba(255,255,255,0.3);' : ''}"
                     title="${patch.name}\n${rgbText}">
                </div>
            `;

            // 左键点击：选中并编辑
            item.addEventListener('click', () => {
                selectPatch(index);
            });

            // 右键菜单
            item.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                selectPatch(index);
                showPatchContextMenu(e.clientX, e.clientY);
            });

            listContainer.appendChild(item);
        });
    }

    // 同时更新底部测量栏
    updateBottomPatchBar();
}

/**
 * 更新底部测量栏显示自定义色块
 */
function updateBottomPatchBar() {
    const patchListArea = document.getElementById('patch-list-area');
    if (!patchListArea) return;

    // 清空色块列表区域
    patchListArea.innerHTML = '';

    // 如果不是自定义模式，不更新
    if (currentMeasureMode !== 'custom') return;

    if (customPatchesList.length === 0) {
        // 显示提示
        const hintGroup = document.createElement('div');
        hintGroup.className = 'patch-group custom-mode-hint';
        hintGroup.innerHTML = `
            <span class="patch-group-label">自定义色块</span>
            <div class="hint-text">请在左侧面板添加色块</div>
        `;
        patchListArea.appendChild(hintGroup);
    } else {
        // 创建色块组
        const groupDiv = document.createElement('div');
        groupDiv.className = 'patch-group';

        const label = document.createElement('span');
        label.className = 'patch-group-label';
        label.textContent = t('自定义色块');
        groupDiv.appendChild(label);

        // 添加每个色块
        customPatchesList.forEach(patch => {
            const patchItem = document.createElement('div');
            patchItem.className = 'patch-item';

            const button = document.createElement('button');
            button.className = 'patch-btn';
            button.dataset.color = patch.rgb.join(',');
            button.dataset.name = patch.name;
            button.style.background = `rgb(${patch.rgb[0]}, ${patch.rgb[1]}, ${patch.rgb[2]})`;

            // 为深色色块添加边框
            const brightness = (patch.rgb[0] + patch.rgb[1] + patch.rgb[2]) / 3;
            if (brightness < 30) {
                button.style.border = '1px solid rgba(255, 255, 255, 0.3)';
            }

            // 检查是否已测量
            if (measuredPatches[patch.name]) {
                button.classList.add('measured');
            }

            button.addEventListener('click', () => onPatchButtonClick(button));
            patchItem.appendChild(button);

            const patchLabel = document.createElement('span');
            patchLabel.className = 'patch-label';
            patchLabel.textContent = patch.name;
            patchItem.appendChild(patchLabel);

            groupDiv.appendChild(patchItem);
        });

        patchListArea.appendChild(groupDiv);

        // 更新 allPatchList 供循环测量使用
        allPatchList = customPatchesList.map(p => ({name: p.name, rgb: p.rgb}));
    }

    // 重新初始化滚动
    initPatchBarScroll();
}

/**
 * 保存自定义色块组到文件（弹窗输入名称）
 */
function saveCustomPatchesFile() {
    if (!backend || customPatchesList.length === 0) return;

    const defaultName = loadedCustomPatchesFilename ?
        loadedCustomPatchesFilename.replace('.patches', '') : '自定义色块组';
    const name = prompt('请输入色块组名称:', defaultName);

    if (name === null) return;  // 用户取消

    const finalName = name.trim() || '自定义色块组';

    const data = {
        name: finalName,
        patches: customPatchesList
    };

    backend.save_custom_patches_file(JSON.stringify(data));
    updateStatus(t('正在保存色块组: {finalName}', {finalName: finalName}));
}

/**
 * 加载自定义色块组文件
 */
function loadCustomPatchesFile() {
    const fileSelect = document.getElementById('custom-patches-file-select');
    const filename = fileSelect?.value;

    if (!filename) {
        updateStatus(t('请选择要加载的色块组文件'));
        return;
    }

    if (backend) {
        backend.load_custom_patches_file(filename);
        updateStatus(t('正在加载: {filename}', {filename: filename}));
    }
}

/**
 * 删除自定义色块组文件
 */
function deleteCustomPatchesFile() {
    const fileSelect = document.getElementById('custom-patches-file-select');
    const filename = fileSelect?.value;

    if (!filename) return;

    if (confirm(t('确定要删除色块组文件 "{filename}" 吗？', {filename: filename}))) {
        if (backend) {
            backend.delete_custom_patches_file(filename);
            updateStatus(t('已删除: {filename}', {filename: filename}));
        }
    }
}

/**
 * 处理自定义色块组文件列表更新
 * @param {object} data - {type: 'custom_patches', files: [...]}
 */
function handleCustomPatchesFileListUpdated(data) {
    if (data.type !== 'custom_patches') return;

    const fileSelect = document.getElementById('custom-patches-file-select');
    if (!fileSelect) return;

    // 清空并重新填充选项
    fileSelect.innerHTML = '<option value="">-- 新建色块组 --</option>';

    data.files.forEach(file => {
        const option = document.createElement('option');
        option.value = file.filename;
        option.textContent = t('{file_name} ({file_patch_count}个)', {file_name: file.name, file_patch_count: file.patch_count});
        fileSelect.appendChild(option);
    });
}

/**
 * 处理自定义色块组文件加载结果
 * @param {object} result - {success, filename, data: {...}}
 */
function handleCustomPatchesFileLoaded(result) {
    if (!result.success || !result.data) {
        updateStatus(t('加载色块组文件失败'));
        return;
    }

    // 加载色块列表
    customPatchesList = result.data.patches || [];
    loadedCustomPatchesFilename = result.filename;
    selectedPatchIndex = -1;

    // 更新显示
    updateCustomPatchesListDisplay();

    updateStatus(t('已加载: {result_data_name} ({customPatchesList_length}个色块)', {result_data_name: result.data.name, customPatchesList_length: customPatchesList.length}));
}

/**
 * 打开独立浮动窗口
 */
function openFloatingWindow() {
    if (!backend) return;
    backend.open_floating_window();
    updateStatus(t('已打开独立浮动窗口'));
}

/**
 * 启动/停止Web测量服务器
 */
let webMeasurementServerRunning = false;
function toggleWebMeasurementServer() {
    if (!backend) {
        updateStatus(t('后端未连接，无法启动Web测量服务器'));
        return;
    }

    if (!webMeasurementServerRunning) {
        // 启动服务器
        try {
            backend.start_web_measurement_server();
        } catch (e) {
            console.error('启动Web测量服务器失败:', e);
        }
    } else {
        // 停止服务器
        try {
            backend.stop_web_measurement_server();
        } catch (e) {
            console.error('停止Web测量服务器失败:', e);
        }
    }
}

/**
 * 从后端查询Web测量服务器状态并刷新偏好设置面板
 */
function refreshWebServerStatus() {
    if (!backend || !backend.get_web_measurement_status) return;
    backend.get_web_measurement_status().then(function(statusJson) {
        try {
            window._webServerStatus = JSON.parse(statusJson);
            webMeasurementServerRunning = !!(window._webServerStatus && window._webServerStatus.running);
        } catch (e) {
            return;
        }
        updatePrefsWebServerUI();
    }).catch(function() {});
}

/**
 * 用缓存的 Web 服务状态刷新偏好设置面板控件
 */
function updatePrefsWebServerUI() {
    const status = window._webServerStatus || { running: webMeasurementServerRunning, url: null };
    const enabled = document.getElementById('prefs-web-server-enabled');
    const state = document.getElementById('prefs-web-server-state');
    const urlInput = document.getElementById('prefs-web-server-url');
    const copyBtn = document.getElementById('prefs-copy-web-url');
    if (!enabled || !state || !urlInput || !copyBtn) return;

    enabled.checked = !!status.running;
    state.textContent = status.running ? t('运行中') : t('未启动');
    state.classList.toggle('running', !!status.running);
    urlInput.value = status.url || '';
    copyBtn.disabled = !status.url;
    if (!status.url) {
        copyBtn.textContent = t('复制');
    }

    updateWebServerAddressBar(status);
}

/**
 * 菜单栏下方的 Web 测量服务器地址条：
 * 运行时显示 IP 地址（点击/按钮可复制），并提供一键"关闭"
 */
function updateWebServerAddressBar(status) {
    const bar = document.getElementById('web-server-address-bar');
    const urlEl = document.getElementById('web-server-bar-url');
    const check = document.getElementById('web-server-check');
    if (!bar || !urlEl) return;

    status = status || window._webServerStatus || { running: webMeasurementServerRunning, url: null };

    // 菜单项勾选标记（运行中显示 ✓，再次点击菜单即关闭）
    if (check) check.textContent = status.running ? '✓' : '';

    if (status.running && status.url) {
        urlEl.textContent = status.url;
        bar.style.display = 'flex';
    } else {
        bar.style.display = 'none';
    }
}

/**
 * 初始化地址条按钮事件（复制 / 点击地址复制 / 关闭服务器）
 */
function initWebServerAddressBar() {
    const bar = document.getElementById('web-server-address-bar');
    if (!bar || bar.dataset.bound) return;
    bar.dataset.bound = '1';

    const copyUrl = function() {
        const url = document.getElementById('web-server-bar-url')?.textContent;
        if (!url) return;
        copyTextToClipboard(url).then(function(ok) {
            updateStatus(ok ? t('已复制Web测量地址: ') + url : t('复制失败，请手动选择地址复制'));
        });
    };

    document.getElementById('web-server-bar-copy')?.addEventListener('click', copyUrl);
    document.getElementById('web-server-bar-url')?.addEventListener('click', copyUrl);
    document.getElementById('web-server-bar-close')?.addEventListener('click', function() {
        if (backend && webMeasurementServerRunning) {
            backend.stop_web_measurement_server();
        }
    });
}

/**
 * 复制文本到剪贴板（clipboard API 不可用时回退 execCommand）
 */
function copyTextToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).then(function() {
            return true;
        }).catch(function() {
            return copyTextViaExecCommand(text);
        });
    }
    return Promise.resolve(copyTextViaExecCommand(text));
}

function copyTextViaExecCommand(text) {
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        return ok;
    } catch (e) {
        return false;
    }
}

/**
 * 打开数据对比窗口
 */
function openComparisonWindow() {
    if (!backend) return;
    backend.open_comparison_window();
    updateStatus(t('已打开数据对比窗口'));
}

/**
 * 连接探头
 */
function connectProbe() {
    if (!backend) return;

    if (probeConnected) {
        // 如果已连接，则断开
        backend.disconnect_probe();
        document.getElementById('btn-connect-probe').textContent = t('连接探头');
    } else {
        // 连接探头
        updateProbeStatus('connecting');
        backend.connect_probe();
        document.getElementById('btn-connect-probe').textContent = t('断开探头');
    }
}

/**
 * 校准探头
 */
function calibrateProbe() {
    if (!backend || !probeConnected) return;

    updateProbeStatus('calibrating');
    backend.calibrate_probe();
}

/**
 * 测量当前色块
 */
function measureCurrentPatch() {
    if (!backend || !probeConnected) {
        updateStatus(t('请先连接探头'));
        return;
    }

    if (!currentPatchRGB) {
        updateStatus(t('请先选择要测量的色块'));
        return;
    }

    isMeasuring = true;
    updateProbeStatus('measuring');
    backend.measure_current_patch();
}

/**
 * 开始循环测量（测量当前模式的所有色块）
 */
function startCycleAll() {
    if (!backend || !probeConnected) {
        updateStatus(t('请先连接探头'));
        return;
    }

    // 并发保护：向导测量进行中时不允许自由模式循环测量
    if (wizardState.isWorkflowRunning) {
        updateStatus(t('向导测量进行中，请先在向导中停止测量'));
        return;
    }

    // 标记测量来源为自由模式
    measurementSource = 'free';

    // 智能全屏：多屏幕在副屏全屏（主屏保持可操作），单屏幕保持浮动窗口
    if (uiMode === 'guided') {
        backend.auto_fullscreen_for_measurement?.();
    }

    dispatchCycleStart();
}

/**
 * 按当前测量模式分发循环测量（自由测量与向导测量共用）。
 * 调用方负责设置 measurementSource、全屏策略与并发守卫。
 */
function dispatchCycleStart() {
    // 根据当前测量模式选择循环测量方法
    if (currentMeasureMode === 'gamut') {
        backend.start_cycle_all();
    } else if (currentMeasureMode === 'ccmx') {
        // CCMX 模式使用 allPatchList（含黑场的5个基础色块）
        if (allPatchList && allPatchList.length > 0) {
            const patches = allPatchList.map(patch => [patch.rgb[0], patch.rgb[1], patch.rgb[2], patch.name]);
            backend.start_custom_cycle(patches);
            updateStatus(t('开始循环测量: 共 {patches_length} 个色块', {patches_length: patches.length}));
        } else {
            updateStatus(t('错误: CCMX 色块列表为空'));
            return;
        }
    } else if (currentMeasureMode === 'saturation') {
        // 饱和度/色相扫描模式：使用后端生成的扫描色块列表
        if (allPatchList && allPatchList.length > 0) {
            const patches = allPatchList.map(patch => [patch.rgb[0], patch.rgb[1], patch.rgb[2], patch.name]);
            backend.start_custom_cycle(patches);
            updateStatus(t('开始饱和度扫描测量: 共 {patches_length} 个色块', {patches_length: patches.length}));
        } else {
            updateStatus(t('错误: 饱和度扫描色块列表为空，请重新切换模式'));
            return;
        }
    } else if (currentMeasureMode === 'hdr') {
        // HDR EOTF 追踪模式：同步配置到后端后重新生成色块并测量
        if (backend) {
            const eotf = document.getElementById('hdr-eotf')?.value || 'PQ';
            const peak = parseFloat(document.getElementById('hdr-peak-nits')?.value) || 1000;
            backend.set_hdr_config(eotf, peak);
            backend.set_measure_mode('hdr');
        }
        // 等色块列表更新后 allPatchList 才有数据；若为空则提示
        setTimeout(() => {
            if (allPatchList && allPatchList.length > 0) {
                const patches = allPatchList.map(patch => [patch.rgb[0], patch.rgb[1], patch.rgb[2], patch.name]);
                window.hdrMeasurements = [];  // 新一轮测量，清空累积
                backend.start_custom_cycle(patches);
                updateStatus(t('开始 HDR EOTF 追踪测量: 共 {patches_length} 级灰阶', {patches_length: patches.length}));
                const reportBtn = document.getElementById('btn-hdr-report');
                if (reportBtn) reportBtn.disabled = true;
            } else {
                updateStatus(t('错误: HDR 灰阶列表为空，请重新切换模式'));
            }
        }, 300);
    } else if (currentMeasureMode === 'uniformity') {
        // 均匀性检测模式：同步配置 → 重新生成网格色块 → 循环测量（带区域定位）
        if (backend) {
            const grid = parseInt(document.getElementById('uniformity-grid')?.value) || 3;
            const level = parseFloat(document.getElementById('uniformity-level')?.value) || 100;
            const size = parseFloat(document.getElementById('uniformity-patch-size')?.value) || 15;
            backend.set_uniformity_config(grid, level, size);
            backend.set_measure_mode('uniformity');
        }
        setTimeout(() => {
            if (allPatchList && allPatchList.length > 0) {
                window.uniformityData = [];
                const patches = allPatchList.map(patch => {
                    const base = [patch.rgb[0], patch.rgb[1], patch.rgb[2], patch.name];
                    return patch.zone ? base.concat([patch.zone[0], patch.zone[1], patch.zone[2]]) : base;
                });
                const guided = document.getElementById('uniformity-guided')?.checked !== false;
                if (guided && backend.start_guided_cycle) {
                    backend.start_guided_cycle(patches);
                    updateStatus(t('开始引导式均匀性测量: {patches_length} 个测点（每点确认后再测量）', {patches_length: patches.length}));
                } else {
                    backend.start_custom_cycle(patches);
                    updateStatus(t('开始均匀性测量: {patches_length} 个测点（请将探头依次移到各区域中心）', {patches_length: patches.length}));
                }
            } else {
                updateStatus(t('错误: 均匀性测点列表为空，请重新切换模式'));
            }
        }, 300);
    } else if (currentMeasureMode === 'autocal') {
        updateStatus(t('AutoCal 模式请在左侧面板点击「启动自动校准」'));
        return;
    } else if (currentMeasureMode === 'dispcal') {
        // dispcal 模式 - 这是校准阶段完成后的状态
        // 此时应该开始 ICC/LUT 测量
        updateStatus(t('校准阶段已完成，请切换到 ICC/LUT 模式后点击循环测量'));
        return;
    } else if (currentMeasureMode === 'icc') {
        // ICC 模式 - 根据用户选择处理校准源
        const calParams = getCalibrationParams(currentMeasureMode);

        if (calParams.source === 'calibrate' && !isCalibrating && !calibrationDone) {
            // 选择 "测量前校准显示器"，需要先运行 dispcal
            startCalibrationThenMeasure(calParams, currentMeasureMode);
            return;
        } else if (calParams.source === 'load') {
            // 选择 "加载cal校正文件"，需要先加载已有的 .cal 文件
            if (!calParams.cal_file) {
                updateStatus(t('请选择要加载的 .cal 校准文件'));
                return;
            }
            loadCalFileThenMeasure(calParams.cal_file, currentMeasureMode);
            return;
        }

        // source === 'none' 或校准已完成，直接开始测量
        startICCLUTMeasurement();
    } else if (currentMeasureMode === 'lut') {
        // LUT 模式 - 直接测量色块，无需dispcal预校准
        // 高质量3DLUT制作可以跳过校准阶段，直接进入测量
        startICCLUTMeasurement();
    } else if (currentMeasureMode === 'custom') {
        // 自定义模式：使用加载的自定义色块进行循环测量
        if (customPatchesList.length > 0) {
            // 使用后端的自定义色块循环测量方法
            backend.start_custom_patches_cycle(JSON.stringify(customPatchesList));
            updateStatus(t('开始自定义色块循环测量: 共 {customPatchesList_length} 个色块', {customPatchesList_length: customPatchesList.length}));
        } else {
            // 如果没有加载色块，只测量当前显示的色块
            measureCurrentPatch();
            return;
        }
    }

    isCycleMeasuring = true;
    setCycleButtonsState(true);
}

/**
 * 先校准再测量（ICC/LUT 模式）
 * @param {object} calParams - 校准参数
 * @param {string} mode - 'icc' 或 'lut'
 */
function startCalibrationThenMeasure(calParams, mode) {
    if (!backend) {
        updateStatus(t('错误: 后端未连接'));
        return;
    }

    // 验证自定义白点
    if (calParams.white_point === 'custom') {
        if (!calParams.custom_white_x || !calParams.custom_white_y) {
            updateStatus(t('请输入自定义白点坐标'));
            return;
        }
    }

    // 标记正在校准，测量将在校准完成后开始
    pendingMeasurementMode = mode;
    isCalibrating = true;

    // ========== 设置按钮状态 ==========
    // 校准期间禁用测量按钮，启用停止按钮
    setCycleButtonsState(true);
    updateStatus(t('正在校准显示器...'));

    // ========== 显示等待消息（隐藏色块列表） ==========
    // dispcal 阶段由 ArgyllCMS 自动完成校准测量，无需前端显示色块
    // 在色块列表区域显示等待提示信息
    const patchListArea = document.getElementById('patch-list-area');
    if (patchListArea) {
        patchListArea.innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center;
                        min-height: 52px; padding: 8px 16px; text-align: center; width: 100%;">
                <div style="font-size: 13px; color: #8b949e;">
                    <span class="spinner" style="display: inline-block; width: 16px; height: 16px;
                        border: 2px solid rgba(139,148,158,0.3); border-top-color: #8b949e;
                        border-radius: 50%; animation: spin 1s linear infinite; vertical-align: middle; margin-right: 6px;"></span>
                    显示器校准中请耐心等待校准完成...
                </div>
            </div>
        `;
    }

    // 添加旋转动画（如果尚未添加）
    if (!document.getElementById('dispcal-spinner-style')) {
        const style = document.createElement('style');
        style.id = 'dispcal-spinner-style';
        style.textContent = `@keyframes spin { to { transform: rotate(360deg); } }`;
        document.head.appendChild(style);
    }

    backend.calibrate_display(JSON.stringify(calParams));
}

/**
 * 加载已有 .cal 文件后开始测量（ICC 模式）
 * @param {string} calFilePath - .cal 校准文件路径
 * @param {string} mode - 'icc' 或 'lut'
 */
function loadCalFileThenMeasure(calFilePath, mode) {
    if (!backend) {
        updateStatus(t('错误: 后端未连接'));
        return;
    }

    // 设置按钮状态
    setCycleButtonsState(true);
    updateStatus(t('正在加载校准文件: {calFilePath}...', {calFilePath: calFilePath}));

    // 标记测量模式，等待 cal 文件加载完成
    pendingMeasurementMode = mode;

    // 调用后端加载 cal 文件
    backend.load_cal_file(calFilePath);
}

/**
 * 开始 ICC/LUT 测量（不含校准）
 */
function startICCLUTMeasurement() {
    if (currentPatchList && currentPatchList.groups && currentPatchList.groups.length > 0) {
        const patches = [];
        currentPatchList.groups.forEach(group => {
            group.patches.forEach(patch => {
                patches.push([patch.rgb[0], patch.rgb[1], patch.rgb[2], patch.name]);
            });
        });

        if (patches.length > 0) {
            // 设置按钮状态（测量期间禁用测量按钮，启用停止按钮）
            setCycleButtonsState(true);

            backend.start_custom_cycle(patches);
            updateStatus(t('开始循环测量: 共 {patches_length} 个色块', {patches_length: patches.length}));

            // 清除校准状态
            pendingMeasurementMode = null;
            calibrationDone = false;
        } else {
            updateStatus(t('错误: 色块列表为空'));
            setCycleButtonsState(false);
            return;
        }
    } else {
        updateStatus(t('错误: 请先选择测量模式并等待色块列表加载'));
        setCycleButtonsState(false);
        return;
    }

    isCycleMeasuring = true;
    setCycleButtonsState(true);
}

/**
 * 停止循环测量
 */
function stopCycle() {
    if (!backend) return;

    // 向导发起的测量：走向导停止路径（同步复位向导按钮与状态）
    if (wizardState.isWorkflowRunning && measurementSource === 'wizard') {
        stopWizardMeasurement();
        return;
    }

    // ========== 判断当前状态并执行相应操作 ==========
    if (isCalibrating) {
        // 正在进行 dispcal 校准，调用停止校准方法
        backend.stop_calibration();
        isCalibrating = false;
        updateStatus(t('校准已取消'));
    } else {
        // 正在进行色块测量，调用停止测量方法
        backend.stop_cycle();
        isCycleMeasuring = false;
    }

    measurementSource = 'free';
    setCycleButtonsState(false);
    clearPatchMeasuringHighlight();
    backend?.exit_patch_window_fullscreen?.();
}

/**
 * 设置循环按钮状态
 */
function setCycleButtonsState(isRunning) {
    document.querySelectorAll('.btn-cycle').forEach(btn => btn.disabled = isRunning);
    document.getElementById('btn-stop').disabled = !isRunning;
}

/**
 * 导出数据
 */
function exportData() {
    const data = {
        gamut: measurementData.gamut,
        grayScale: measurementData.grayScale,
        exportTime: new Date().toISOString()
    };

    const jsonStr = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `topos_calibrator_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();

    URL.revokeObjectURL(url);
    updateStatus(t('数据已导出'));
}

/**
 * 重置数据
 */
function resetData() {
    measurementData.gamut = { red: null, green: null, blue: null, white: null, black: null };
    measurementData.grayScale = [];
    measurementData.gamma = null;

    // 清除已测量色块跟踪
    for (const key in measuredPatches) {
        delete measuredPatches[key];
    }

    // 清除色块按钮的已测量样式
    document.querySelectorAll('.patch-btn.measured').forEach(btn => {
        btn.classList.remove('measured');
    });

    // 清除显示器基础数据显示
    document.getElementById('display-peak-luminance').textContent = '-- cd/m²';
    document.getElementById('display-black-luminance').textContent = '-- cd/m²';
    document.getElementById('display-contrast').textContent = '--';
    document.getElementById('display-white-cct').textContent = '-- K';
    document.getElementById('display-white-x').textContent = '--';
    document.getElementById('display-white-y').textContent = '--';
    document.getElementById('display-white-deviation').textContent = '-- ΔE';
    document.getElementById('display-gamma').textContent = '--';
    document.getElementById('gamma-value').textContent = '--';
    document.getElementById('gamut-srgb').textContent = '--%';
    document.getElementById('gamut-p3').textContent = '--%';
    document.getElementById('gamut-adobe').textContent = '--%';
    document.getElementById('gamut-rec2020').textContent = '--%';

    // 清除实时色块数据显示
    document.getElementById('patch-name').textContent = '--';
    document.getElementById('patch-rgb').textContent = 'RGB(--, --, --)';
    document.getElementById('patch-xy').textContent = '--, --';
    document.getElementById('patch-Y').textContent = '-- cd/m²';
    document.getElementById('patch-cct').textContent = '-- K';
    document.getElementById('patch-deltae').textContent = '--';
    document.getElementById('patch-uv').textContent = '--, --';

    // 清除图表
    if (typeof clearCharts === 'function') {
        clearCharts();
    }

    updateStatus(t('数据已重置'));
}

/**
 * 数值限制
 */
function clamp(value) {
    return Math.max(0, Math.min(255, value));
}

/**
 * 页面初始化
 */
document.addEventListener('DOMContentLoaded', function() {
    // 初始化 WebChannel
    initWebChannel();

    // 绑定色块按钮事件
    document.querySelectorAll('.patch-btn[data-color]').forEach(button => {
        button.addEventListener('click', () => onPatchButtonClick(button));
    });

    // 绑定打开独立窗口按钮
    document.getElementById('btn-open-window').addEventListener('click', openFloatingWindow);

    // 绑定探头操作
    document.getElementById('btn-connect-probe').addEventListener('click', connectProbe);
    document.getElementById('btn-calibrate').addEventListener('click', calibrateProbe);

    // 绑定测量按钮
    document.getElementById('btn-measure-single').addEventListener('click', measureCurrentPatch);
    document.getElementById('btn-cycle-all').addEventListener('click', startCycleAll);
    document.getElementById('btn-stop').addEventListener('click', stopCycle);

    // 绑定导出和重置
    document.getElementById('btn-export').addEventListener('click', showExportModal);
    document.getElementById('btn-reset').addEventListener('click', resetData);
    
    // 绑定保存数据按钮
    document.getElementById('btn-save').addEventListener('click', saveCurrentData);

    // 初始化测量模式切换
    initMeasureMode();

    // 初始化历史数据选择
    initHistorySelect();

    // 初始化自定义颜色模式
    initCustomMode();

    // 初始化菜单栏事件
    initMenuBar();

    // 初始化面板拖动调整宽度功能
    initResizablePanels();

    // 初始化底部色块栏滚动
    initPatchBarScroll();

    updateStatus(t('初始化完成'));
});

/**
 * 初始化测量模式切换
 */
function initMeasureMode() {
    const modeSelect = document.getElementById('measure-mode-select');

    if (!modeSelect) return;

    modeSelect.addEventListener('change', function() {
        const mode = this.value;

        // 切换模式时重置校准状态
        calibrationDone = false;
        isCalibrating = false;
        pendingMeasurementMode = null;

        // 显示对应的设置面板
        document.querySelectorAll('.mode-settings').forEach(settings => {
            settings.classList.add('hidden');
        });

        // 切换模式时隐藏上一模式的专属报告区
        document.getElementById('uniformity-section')?.classList.add('hidden');
        window.uniformityData = null;

        const targetSettings = document.getElementById(`${mode}-settings`);
        if (targetSettings) {
            targetSettings.classList.remove('hidden');
        }

        // 调用后端设置测量模式
        if (backend) {
            backend.set_measure_mode(mode);
        }

        // CCMX 模式时刷新测量列表，确保下拉框有最新数据
        if (mode === 'ccmx' && backend) {
            backend.get_measurement_list();
        }

        // AutoCal 模式时查询 DDC/CI 通道状态
        if (mode === 'autocal' && backend) {
            backend.display_control_get_capabilities();
        }
    });

    // ========== AutoCal 自动校准闭环 UI (P1 集成) ==========
    // 状态变量 ddcConnected/autocalRunning 与 updateAutoCalButtons 定义在文件末尾顶层作用域

    document.getElementById('btn-ddc-connect')?.addEventListener('click', () => {
        if (!backend) return;
        const displayId = parseInt(document.getElementById('autocal-display-id')?.value) || 1;
        const statusEl = document.getElementById('ddc-status');
        if (statusEl) statusEl.textContent = t('正在连接...');
        backend.display_control_connect(displayId, false);
    });

    document.getElementById('btn-autocal-start')?.addEventListener('click', () => {
        if (!backend) return;
        const config = {
            target: {
                white_point: document.getElementById('autocal-white')?.value || 'D65',
                target_Y_white: parseFloat(document.getElementById('autocal-target-y')?.value) || 120,
                target_gamma: parseFloat(document.getElementById('autocal-gamma')?.value) || 2.2,
                delta_e_threshold: parseFloat(document.getElementById('autocal-de-threshold')?.value) || 2.0
            },
            config: {
                dry_run: document.getElementById('autocal-dry-run')?.checked || false,
                max_iterations: parseInt(document.getElementById('autocal-max-iter')?.value) || 5,
                settling_time: parseFloat(document.getElementById('autocal-settling')?.value) || 5,
                grayscale_steps: 5,
                include_primaries: true,
                enable_rollback: true,
                enable_manual_guide: true
            }
        };
        const container = document.getElementById('autocal-progress-container');
        if (container) container.style.display = 'block';
        backend.autocal_start(JSON.stringify(config));
    });

    document.getElementById('btn-autocal-stop')?.addEventListener('click', () => {
        if (backend) backend.autocal_stop();
    });

    document.getElementById('btn-ddc-snapshot')?.addEventListener('click', () => {
        if (backend) backend.display_control_save_snapshot();
    });

    document.getElementById('btn-ddc-rollback')?.addEventListener('click', () => {
        if (backend) backend.display_control_rollback();
    });

    // ========== HDR EOTF 追踪 UI (P3 集成) ==========
    // HDR 灰阶测量累积器（顶层供 handleMeasurementResult 写入）
    window.hdrMeasurements = [];

    document.getElementById('hdr-eotf')?.addEventListener('change', () => {
        if (backend) {
            const peak = parseFloat(document.getElementById('hdr-peak-nits')?.value) || 1000;
            backend.set_hdr_config(document.getElementById('hdr-eotf').value, peak);
            backend.set_measure_mode('hdr');  // 触发后端重新生成色块
        }
    });
    document.getElementById('hdr-peak-nits')?.addEventListener('change', () => {
        if (backend) {
            const eotf = document.getElementById('hdr-eotf')?.value || 'PQ';
            backend.set_hdr_config(eotf, parseFloat(this.value) || 1000);
            backend.set_measure_mode('hdr');
        }
    });

    document.getElementById('btn-hdr-report')?.addEventListener('click', () => {
        if (!backend || !window.hdrMeasurements || window.hdrMeasurements.length === 0) {
            updateStatus(t('没有 HDR 测量数据，请先执行循环测量'));
            return;
        }
        const payload = {
            eotf: document.getElementById('hdr-eotf')?.value || 'PQ',
            peak_nits: parseFloat(document.getElementById('hdr-peak-nits')?.value) || 1000,
            measurements: window.hdrMeasurements
        };
        updateStatus(t('正在生成 HDR EOTF 追踪报告...'));
        backend.analyze_hdr_eotf(JSON.stringify(payload), (resultJson) => {
            renderHdrEotfReport(resultJson);
        });
    });

    // 灰阶级数变化
    document.getElementById('gray-steps')?.addEventListener('change', function() {
        const steps = parseInt(this.value) || 21;
        if (backend) {
            backend.set_gray_steps(steps);
        }
    });

    // 目标白点/目标 Gamma（原先无事件处理，属于死 UI；高级/自由模式直接可用）
    document.getElementById('target-white')?.addEventListener('change', function() {
        if (backend) {
            backend.set_target_white(this.value);
        }
        updateStatus(t('目标白点: {this_value}', {this_value: this.value}));
    });
    document.getElementById('target-gamma')?.addEventListener('change', function() {
        if (backend) {
            backend.set_target_gamma(this.value);
        }
        updateStatus(t('目标 Gamma: {this_value}', {this_value: this.value}));
    });

    // ICC 色块数变化
    document.getElementById('icc-patch-count')?.addEventListener('change', function() {
        const selectedValue = this.value;
        const customRow = document.getElementById('icc-custom-patch-row');

        // 显示/隐藏自定义输入框
        if (selectedValue === 'custom') {
            if (customRow) customRow.classList.remove('hidden');
        } else {
            if (customRow) customRow.classList.add('hidden');
        }

        // 获取实际色块数量
        let count;
        if (selectedValue === 'custom') {
            const customInput = document.getElementById('icc-custom-patch-count');
            count = parseInt(customInput?.value) || 2500;
        } else {
            count = parseInt(selectedValue) || 99;
        }

        // 获取采样策略
        const strategySelect = document.getElementById('icc-sample-strategy');
        const strategy = strategySelect?.value || 'balanced';

        if (backend) {
            backend.set_icc_patch_count(count);
            backend.set_icc_sample_strategy(strategy);
        }

        updateStatus(t('ICC 测试色块: {count} 个, 采样策略: {strategy}', {count: count, strategy: strategy}));
    });

    // ICC 自定义色块数变化
    document.getElementById('icc-custom-patch-count')?.addEventListener('change', function() {
        const count = parseInt(this.value) || 2500;
        const strategySelect = document.getElementById('icc-sample-strategy');
        const strategy = strategySelect?.value || 'balanced';

        if (backend) {
            backend.set_icc_patch_count(count);
            backend.set_icc_sample_strategy(strategy);
        }

        updateStatus(t('ICC 测试色块: {count} 个 (自定义), 采样策略: {strategy}', {count: count, strategy: strategy}));
    });

    // ICC 采样策略变化
    document.getElementById('icc-sample-strategy')?.addEventListener('change', function() {
        const strategy = this.value || 'balanced';
        const patchCountSelect = document.getElementById('icc-patch-count');
        const customInput = document.getElementById('icc-custom-patch-count');

        let count;
        if (patchCountSelect?.value === 'custom') {
            count = parseInt(customInput?.value) || 2500;
        } else {
            count = parseInt(patchCountSelect?.value) || 99;
        }

        if (backend) {
            backend.set_icc_sample_strategy(strategy);
        }

        updateStatus(t('ICC 采样策略: {strategy}', {strategy: strategy}));
    });

    // LUT 色块数变化
    document.getElementById('lut-patch-count')?.addEventListener('change', function() {
        const selectedValue = this.value;
        const customRow = document.getElementById('lut-custom-patch-row');

        // 显示/隐藏自定义输入框
        if (selectedValue === 'custom') {
            if (customRow) customRow.classList.remove('hidden');
        } else {
            if (customRow) customRow.classList.add('hidden');
        }

        // 获取实际色块数量
        let count;
        if (selectedValue === 'custom') {
            const customInput = document.getElementById('lut-custom-patch-count');
            count = parseInt(customInput?.value) || 2500;
        } else {
            count = parseInt(selectedValue) || 99;
        }

        // 获取采样策略
        const strategySelect = document.getElementById('lut-sample-strategy');
        const strategy = strategySelect?.value || 'balanced';

        if (backend) {
            backend.set_lut_patch_count(count);
            backend.set_lut_sample_strategy(strategy);
        }

        updateStatus(t('LUT 测试色块: {count} 个, 采样策略: {strategy}', {count: count, strategy: strategy}));
    });

    // LUT 自定义色块数变化
    document.getElementById('lut-custom-patch-count')?.addEventListener('change', function() {
        const count = parseInt(this.value) || 2500;
        const strategySelect = document.getElementById('lut-sample-strategy');
        const strategy = strategySelect?.value || 'balanced';

        if (backend) {
            backend.set_lut_patch_count(count);
            backend.set_lut_sample_strategy(strategy);
        }

        updateStatus(t('LUT 测试色块: {count} 个 (自定义), 采样策略: {strategy}', {count: count, strategy: strategy}));
    });

    // LUT 采样策略变化
    document.getElementById('lut-sample-strategy')?.addEventListener('change', function() {
        const strategy = this.value || 'balanced';
        const patchCountSelect = document.getElementById('lut-patch-count');
        const customInput = document.getElementById('lut-custom-patch-count');

        let count;
        if (patchCountSelect?.value === 'custom') {
            count = parseInt(customInput?.value) || 2500;
        } else {
            count = parseInt(patchCountSelect?.value) || 99;
        }

        if (backend) {
            backend.set_lut_sample_strategy(strategy);
        }

        updateStatus(t('LUT 采样策略: {strategy}', {strategy: strategy}));
    });

    // LUT 渲染意图变化 - 自动调整 BPC 提示
    document.getElementById('lut-intent')?.addEventListener('change', function() {
        const intent = this.value;
        const bpcCheckbox = document.getElementById('lut-use-bpc');
        const hintText = document.querySelector('.hint-text');
        
        if (intent === 'r') {
            // 相对色度时，BPC 自动启用并显示提示
            if (bpcCheckbox) bpcCheckbox.checked = true;
            if (hintText) hintText.textContent = t('防止暗部死黑，相对色度时自动启用');
        } else if (intent === 'p') {
            // 绝对色度时，BPC 可能不需要
            if (hintText) hintText.textContent = t('绝对色度时 BPC 可能影响准确性');
        } else {
            // 感知匹配时
            if (hintText) hintText.textContent = t('感知匹配通常包含暗部映射');
        }
    });

    // CCMX 选择变化事件
    document.getElementById('ccmx-ref-select')?.addEventListener('change', checkCCMXSelection);
    document.getElementById('ccmx-target-select')?.addEventListener('change', checkCCMXSelection);

    // CCMX 制作按钮
    document.getElementById('btn-create-ccmx')?.addEventListener('click', () => {
        createCCMXFromSelected();
    });

    // ========== ICC/LUT 预校准选项事件 ==========

    // 标准白点坐标
    const WHITE_POINT_COORDS = {
        'D65': { x: 0.3127, y: 0.3290 },
        'D63': { x: 0.314, y: 0.351 },   // DCI-P3 白点（人为定义值，相比D63偏绿）
        'D50': { x: 0.3457, y: 0.3585 },
        'D75': { x: 0.2990, y: 0.3150 }
    };

    // ICC 校准源选项互斥逻辑（单选按钮）
    const iccEnableCalibration = document.getElementById('icc-enable-calibration');
    const iccLoadCalFile = document.getElementById('icc-load-cal-file');
    const iccCalibrationOptions = document.getElementById('icc-calibration-options');
    const iccCalFileOptions = document.getElementById('icc-cal-file-options');

    // 处理单选按钮变化
    const handleIccCalSourceChange = () => {
        if (iccEnableCalibration?.checked) {
            // 选中"测量前校准显示器"
            iccCalibrationOptions?.classList.remove('hidden');
            iccCalFileOptions?.classList.add('hidden');
        } else if (iccLoadCalFile?.checked) {
            // 选中"加载cal校正文件"
            iccCalibrationOptions?.classList.add('hidden');
            iccCalFileOptions?.classList.remove('hidden');
            // 加载cal文件列表
            if (backend && backend.get_cal_file_list) {
                backend.get_cal_file_list();
            }
        }
    };

    iccEnableCalibration?.addEventListener('change', handleIccCalSourceChange);
    iccLoadCalFile?.addEventListener('change', handleIccCalSourceChange);

    // ICC 白点选择 - 自动更新 xy 值
    const iccCalWhitePoint = document.getElementById('icc-cal-white-point');
    const iccCalCustomWhiteRow = document.getElementById('icc-cal-custom-white-row');
    const iccCalWhiteX = document.getElementById('icc-cal-white-x');
    const iccCalWhiteY = document.getElementById('icc-cal-white-y');

    iccCalWhitePoint?.addEventListener('change', (e) => {
        const value = e.target.value;
        if (value === 'custom') {
            iccCalCustomWhiteRow?.classList.remove('hidden');
            if (iccCalWhiteX) iccCalWhiteX.disabled = false;
            if (iccCalWhiteY) iccCalWhiteY.disabled = false;
        } else if (value === 'native') {
            iccCalCustomWhiteRow?.classList.add('hidden');
        } else {
            iccCalCustomWhiteRow?.classList.add('hidden');
            const coords = WHITE_POINT_COORDS[value];
            if (coords) {
                if (iccCalWhiteX) iccCalWhiteX.value = coords.x.toFixed(4);
                if (iccCalWhiteY) iccCalWhiteY.value = coords.y.toFixed(4);
            }
        }
    });

    // ICC 从测量填入白点
    document.getElementById('btn-icc-fill-white')?.addEventListener('click', () => {
        fillWhiteFromMeasurement('icc-cal-white-x', 'icc-cal-white-y');
        const select = document.getElementById('icc-cal-white-point');
        if (select) select.value = 'custom';
        iccCalCustomWhiteRow?.classList.remove('hidden');
        if (iccCalWhiteX) iccCalWhiteX.disabled = false;
        if (iccCalWhiteY) iccCalWhiteY.disabled = false;
    });

    // LUT 校准选项已移除 - 高质量3DLUT制作无需dispcal预校准
    // LUT模式直接测量色块，跳过校准阶段

    // LUT 目标白点选择 - 自动更新 xy 值（用于LUT输出的目标白点）
    const lutTargetWhite = document.getElementById('lut-target-white');
    const lutTargetCustomWhiteRow = document.getElementById('lut-target-custom-white-row');
    const lutTargetWhiteX = document.getElementById('lut-target-white-x');
    const lutTargetWhiteY = document.getElementById('lut-target-white-y');

    lutTargetWhite?.addEventListener('change', (e) => {
        const value = e.target.value;
        if (value === 'custom') {
            lutTargetCustomWhiteRow?.classList.remove('hidden');
            if (lutTargetWhiteX) lutTargetWhiteX.disabled = false;
            if (lutTargetWhiteY) lutTargetWhiteY.disabled = false;
        } else if (value === 'native') {
            lutTargetCustomWhiteRow?.classList.add('hidden');
        } else {
            lutTargetCustomWhiteRow?.classList.add('hidden');
            const coords = WHITE_POINT_COORDS[value];
            if (coords) {
                if (lutTargetWhiteX) lutTargetWhiteX.value = coords.x.toFixed(4);
                if (lutTargetWhiteY) lutTargetWhiteY.value = coords.y.toFixed(4);
            }
        }
    });

    // LUT 目标白点从测量填入
    document.getElementById('btn-lut-target-fill-white')?.addEventListener('click', () => {
        fillWhiteFromMeasurement('lut-target-white-x', 'lut-target-white-y');
        const select = document.getElementById('lut-target-white');
        if (select) select.value = 'custom';
        lutTargetCustomWhiteRow?.classList.remove('hidden');
        if (lutTargetWhiteX) lutTargetWhiteX.disabled = false;
        if (lutTargetWhiteY) lutTargetWhiteY.disabled = false;
    });

    // 初始化弹窗事件
    initModalEvents();
}

/**
 * 初始化菜单栏事件
 */
function initMenuBar() {
    // 文件菜单
    document.getElementById('menu-export-csv')?.addEventListener('click', exportData);
    document.getElementById('menu-quit')?.addEventListener('click', () => {
        if (backend) backend.quit_app();
    });

    // 测量菜单
    document.getElementById('menu-connect-probe')?.addEventListener('click', connectProbe);
    document.getElementById('menu-calibrate-probe')?.addEventListener('click', calibrateProbe);
    document.getElementById('menu-measure-all')?.addEventListener('click', startCycleAll);
    document.getElementById('menu-stop')?.addEventListener('click', stopCycle);

    // 视图菜单
    document.getElementById('menu-toggle-settings')?.addEventListener('click', () => togglePanel('settings-panel'));
    document.getElementById('menu-toggle-patch')?.addEventListener('click', () => toggleSection('patch-section'));
    document.getElementById('menu-toggle-results')?.addEventListener('click', () => toggleSection('results-section'));
    document.getElementById('menu-open-patch-window')?.addEventListener('click', openFloatingWindow);
    document.getElementById('menu-web-measurement-server')?.addEventListener('click', toggleWebMeasurementServer);
    initWebServerAddressBar();
    // 顶栏齿轮按钮：打开偏好设置
    document.getElementById('btn-open-prefs')?.addEventListener('click', showPreferencesModal);
    document.getElementById('menu-open-comparison')?.addEventListener('click', openComparisonWindow);

    // 设置菜单
    document.getElementById('menu-preferences')?.addEventListener('click', () => {
        showPreferencesModal();
    });
    document.getElementById('menu-probe-config')?.addEventListener('click', () => {
        updateStatus(t('探头配置功能开发中...'));
    });

    // 语言切换菜单
    document.getElementById('menu-language-zh')?.addEventListener('click', () => switchLanguage('zh-CN'));
    document.getElementById('menu-language-en')?.addEventListener('click', () => switchLanguage('en'));
    updateLanguageMenu();

    // 帮助菜单
    document.getElementById('menu-docs')?.addEventListener('click', () => {
        showDocsModal();
    });
    document.getElementById('menu-about')?.addEventListener('click', () => {
        showAboutDialog();
    });

    // 全局键盘快捷键
    initMenuShortcuts();
}

/**
 * 全局键盘快捷键（⌘K 连接探头 / ⌘M 循环测量 / Esc 停止测量与关闭文档）
 */
function initMenuShortcuts() {
    document.addEventListener('keydown', function (e) {
        const meta = e.metaKey || e.ctrlKey;
        const key = (e.key || '').toLowerCase();

        if (meta && key === 'k') {
            e.preventDefault();
            connectProbe();
        } else if (meta && key === 'm') {
            e.preventDefault();
            startCycleAll();
        } else if (e.key === 'Escape') {
            // 文档弹窗优先关闭
            const docsOverlay = document.getElementById('docs-modal-overlay');
            if (docsOverlay && docsOverlay.classList.contains('show')) {
                closeDocsModal();
                return;
            }
            if (isMeasuring) stopCycle();
        }
    });
}

/**
 * 切换界面语言（并同步到 Python 后端，使日志/状态消息跟随语言）
 */
function switchLanguage(lang) {
    if (!window.I18N) return;
    if (!I18N.setLanguage(lang)) return;
    updateLanguageMenu();
    refreshLocalizedDynamicUi();
    // 偏好面板里由 JS 写入的动态文案（运行状态/复制按钮）不经过 DOM 翻译器，手动刷新
    updatePrefsWebServerUI();
    // 预检结果由后端以英文生成、前端按语言渲染，切换语言后需重渲染
    if (typeof preflightReport !== 'undefined' && preflightReport) {
        const wizardResults = document.getElementById('preflight-results');
        if (wizardResults && wizardResults.childElementCount > 0) {
            renderWizardPreflightResults(preflightReport);
        }
        const freeResults = document.getElementById('preflight-results-container');
        if (freeResults && freeResults.style.display === 'block') {
            renderPreflightResults(preflightReport);
        }
    }
    // 同步后端语言偏好（backend.setLanguage 由 src/backend.py 提供）
    if (backend && typeof backend.setLanguage === 'function') {
        try { backend.setLanguage(lang); } catch (e) { /* 后端未就绪时忽略 */ }
    }
}

/** Re-render dynamic labels that are assigned through textContent/templates. */
function refreshLocalizedDynamicUi() {
    if (typeof wizardState !== 'undefined' && typeof syncWizardCta === 'function') {
        syncWizardCta(wizardState.currentStep);
    }
    if (typeof wizardState !== 'undefined' && typeof syncWizardWorkspace === 'function') {
        syncWizardWorkspace(wizardState.currentStep);
    }
    const logOutput = document.getElementById('log-output');
    if (logOutput && logOutput.textContent) {
        logOutput.textContent = translateBackendLogMessage(logOutput.textContent);
    }
}

/**
 * 更新语言菜单的勾选标记
 */
function updateLanguageMenu() {
    if (!window.I18N) return;
    const cur = I18N.getLanguage();
    const zh = document.getElementById('lang-check-zh');
    const en = document.getElementById('lang-check-en');
    if (zh) zh.textContent = cur === 'zh-CN' ? '✓' : '';
    if (en) en.textContent = cur === 'en' ? '✓' : '';
}

/**
 * 切换面板显示/隐藏
 */
function togglePanel(panelId) {
    const panel = document.getElementById(panelId);
    if (!panel) return;

    panel.style.display = panel.style.display === 'none' ? '' : 'none';
    triggerChartResize();
}

/**
 * 切换区域折叠
 */
function toggleSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (!section) return;

    const content = section.querySelector('.section-content');
    const btn = section.querySelector('.collapse-btn');

    if (content) {
        content.classList.toggle('collapsed');
        if (btn) btn.classList.toggle('collapsed');
    }
    triggerChartResize();
}

/**
 * 显示关于对话框
 */
function showAboutDialog() {
    updateStatus(t('Topos Calibrator v0.1.0-preview - 显示器校正与测量软件'));
}

/* ==================== 使用文档弹窗 ==================== */

let docsCurrentChapter = null;   // 当前阅读章节 id（跨语言一致）
let docsSearchQuery = '';        // 目录搜索关键词
const DOCS_CHAPTER_KEY = 'topos.docs.chapter';

/**
 * 打开使用文档弹窗
 */
function showDocsModal() {
    if (!window.DOCS_CONTENT) return;
    if (!window._docsModalInitialized) {
        initDocsModalEvents();
        window._docsModalInitialized = true;
    }

    const book = getDocsBook();
    if (!book || !book.chapters.length) return;

    // 恢复上次阅读的章节（跨语言记忆）
    let last = null;
    try { last = localStorage.getItem(DOCS_CHAPTER_KEY); } catch (e) { /* 忽略 */ }
    docsCurrentChapter = (last && book.chapters.some(c => c.id === last))
        ? last : book.chapters[0].id;

    renderDocsSidebar();
    renderDocsChapter();
    document.getElementById('docs-modal-overlay').classList.add('show');
    updateStatus(t('使用文档'));
}

/**
 * 关闭使用文档弹窗
 */
function closeDocsModal() {
    document.getElementById('docs-modal-overlay')?.classList.remove('show');
}

/**
 * 获取当前语言的文档内容（缺语言时回退中文）
 */
function getDocsBook() {
    if (!window.DOCS_CONTENT) return null;
    return DOCS_CONTENT[getDocsLanguage()] || null;
}

/**
 * 章节是否命中搜索关键词（标题或正文纯文本包含即可）
 */
function docsChapterMatches(chapter, query) {
    if (!query) return true;
    const plain = chapter.title + ' ' + chapter.html.replace(/<[^>]*>/g, ' ');
    return plain.toLowerCase().indexOf(query) !== -1;
}

/**
 * 渲染左侧目录（搜索框 + 章节列表）
 */
function renderDocsSidebar() {
    const book = getDocsBook();
    const sidebar = document.getElementById('docs-sidebar');
    if (!book || !sidebar) return;

    sidebar.innerHTML = '';

    // 搜索框（仅创建一次绑定，输入时只刷新列表，避免丢失焦点）
    const searchBox = document.createElement('div');
    searchBox.className = 'docs-search';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = t('搜索文档...');
    input.value = docsSearchQuery;
    input.addEventListener('input', function () {
        docsSearchQuery = this.value;
        renderDocsNav();
    });
    searchBox.appendChild(input);
    sidebar.appendChild(searchBox);

    sidebar.appendChild(buildDocsNav());
}

/**
 * 构建章节列表（根据 docsSearchQuery 过滤）
 */
function buildDocsNav() {
    const book = getDocsBook();
    const nav = document.createElement('nav');
    nav.className = 'docs-nav';
    if (!book) return nav;

    const query = docsSearchQuery.trim().toLowerCase();
    let visible = 0;

    book.chapters.forEach(chapter => {
        if (!docsChapterMatches(chapter, query)) return;
        visible++;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'docs-nav-item' + (chapter.id === docsCurrentChapter ? ' active' : '');

        const icon = document.createElement('span');
        icon.className = 'docs-nav-icon';
        icon.textContent = chapter.icon;
        const title = document.createElement('span');
        title.className = 'docs-nav-title';
        title.textContent = chapter.title;

        btn.appendChild(icon);
        btn.appendChild(title);
        btn.addEventListener('click', () => {
            docsCurrentChapter = chapter.id;
            try { localStorage.setItem(DOCS_CHAPTER_KEY, chapter.id); } catch (e) { /* 忽略 */ }
            renderDocsNav();
            renderDocsChapter();
        });
        nav.appendChild(btn);
    });

    if (!visible) {
        const empty = document.createElement('div');
        empty.className = 'docs-nav-empty';
        empty.textContent = t('未找到匹配的章节');
        nav.appendChild(empty);
    }
    return nav;
}

/**
 * 仅刷新章节列表（搜索输入时保持焦点不抖动）
 */
function renderDocsNav() {
    const sidebar = document.getElementById('docs-sidebar');
    if (!sidebar) return;
    const oldNav = sidebar.querySelector('.docs-nav');
    if (!oldNav) return;
    const nav = buildDocsNav();
    oldNav.replaceWith(nav);
}

/**
 * 渲染右侧章节正文与翻页按钮
 */
function renderDocsChapter() {
    const book = getDocsBook();
    const content = document.getElementById('docs-content');
    if (!book || !content || !book.chapters.length) return;

    const chapter = book.chapters.find(c => c.id === docsCurrentChapter) || book.chapters[0];
    docsCurrentChapter = chapter.id;
    const index = book.chapters.indexOf(chapter);

    content.innerHTML = '';

    // 章节标题
    const header = document.createElement('div');
    header.className = 'docs-chapter-header';
    const icon = document.createElement('span');
    icon.className = 'docs-chapter-icon';
    icon.textContent = chapter.icon;
    const title = document.createElement('h4');
    title.className = 'docs-chapter-title';
    title.textContent = chapter.title;
    header.appendChild(icon);
    header.appendChild(title);
    content.appendChild(header);

    // 正文（按语言整体编写，不经过 DOM 翻译器）
    const body = document.createElement('div');
    body.className = 'docs-chapter-body';
    body.innerHTML = chapter.html;
    content.appendChild(body);

    // 上一章 / 下一章
    const footer = document.createElement('div');
    footer.className = 'docs-footer-nav';
    const prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'btn btn-secondary btn-sm';
    prevBtn.textContent = '← ' + t('上一章');
    prevBtn.disabled = index <= 0;
    prevBtn.addEventListener('click', () => {
        if (index > 0) {
            docsCurrentChapter = book.chapters[index - 1].id;
            try { localStorage.setItem(DOCS_CHAPTER_KEY, docsCurrentChapter); } catch (e) { /* 忽略 */ }
            renderDocsNav();
            renderDocsChapter();
        }
    });
    const nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'btn btn-secondary btn-sm';
    nextBtn.textContent = t('下一章') + ' →';
    nextBtn.disabled = index >= book.chapters.length - 1;
    nextBtn.addEventListener('click', () => {
        if (index < book.chapters.length - 1) {
            docsCurrentChapter = book.chapters[index + 1].id;
            try { localStorage.setItem(DOCS_CHAPTER_KEY, docsCurrentChapter); } catch (e) { /* 忽略 */ }
            renderDocsNav();
            renderDocsChapter();
        }
    });
    footer.appendChild(prevBtn);
    footer.appendChild(nextBtn);
    content.appendChild(footer);

    content.scrollTop = 0;
}

/**
 * 文档弹窗事件（关闭按钮 / 点击遮罩关闭 / 语言切换时重渲染）
 */
function initDocsModalEvents() {
    document.getElementById('docs-modal-close')?.addEventListener('click', closeDocsModal);

    const overlay = document.getElementById('docs-modal-overlay');
    overlay?.addEventListener('mousedown', function (e) {
        if (e.target === overlay) closeDocsModal();
    });

    // 标题旁的语言选择框：切换整个界面语言（文档/标题/菜单同步跟随）
    const langSelect = document.getElementById('docs-lang-select');
    if (langSelect) {
        const docLangs = window.DOCS_CONTENT ? Object.keys(DOCS_CONTENT) : [];
        const langs = (window.I18N && I18N.getSupportedLanguages)
            ? I18N.getSupportedLanguages().filter(l => docLangs.indexOf(l.code) !== -1)
            : docLangs.map(code => ({ code: code, name: code }));
        langs.forEach(l => {
            const opt = document.createElement('option');
            opt.value = l.code;
            opt.textContent = l.name;
            langSelect.appendChild(opt);
        });
        langSelect.value = getDocsLanguage();
        langSelect.addEventListener('change', function () {
            switchLanguage(this.value);
        });
    }

    // 语言切换：文档内容按语言整体编写，直接重渲染（保持当前章节）
    if (window.I18N && I18N.onChange) {
        I18N.onChange((lang) => {
            const docsOverlay = document.getElementById('docs-modal-overlay');
            if (docsOverlay && docsOverlay.classList.contains('show')) {
                renderDocsSidebar();
                renderDocsChapter();
            }
            // 选择框与当前语言保持同步（含从设置菜单切换的路径）
            const select = document.getElementById('docs-lang-select');
            if (select) select.value = getDocsLanguage();
        });
    }
}

/**
 * 当前文档语言（界面语言；内容缺失时回退中文）
 */
function getDocsLanguage() {
    const lang = (window.I18N && I18N.getLanguage) ? I18N.getLanguage() : 'zh-CN';
    return (window.DOCS_CONTENT && DOCS_CONTENT[lang]) ? lang : 'zh-CN';
}

/**
 * 初始化面板拖动调整功能
 * 支持水平拖拽调整面板宽度，垂直拖拽调整上下比例
 */
function initResizablePanels() {
    // 水平拖拽（调整面板宽度）
    initHorizontalResize();

    // 垂直拖拽（调整上下比例）
    initVerticalResize();

    // 折叠功能
    initCollapseButtons();
}

/**
 * 初始化折叠按钮
 */
function initCollapseButtons() {
    const collapseButtons = document.querySelectorAll('.collapse-btn');

    collapseButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();

            const targetId = this.dataset.target;
            const targetElement = document.getElementById(targetId);

            if (!targetElement) return;

            // 切换折叠状态
            const isCollapsed = targetElement.classList.toggle('collapsed');
            this.classList.toggle('collapsed', isCollapsed);

            // 触发图表 resize
            triggerChartResize();
        });
    });
}

/**
 * 水平拖拽 - 调整面板宽度
 */
function initHorizontalResize() {
    const handles = document.querySelectorAll('.resize-handle-h');
    let isDragging = false;
    let currentHandle = null;
    let currentPanel = null;
    let startX = 0;
    let startWidth = 0;

    handles.forEach(handle => {
        handle.addEventListener('mousedown', function(e) {
            isDragging = true;
            currentHandle = handle;
            currentPanel = handle.parentElement;

            startX = e.clientX;
            startWidth = currentPanel.offsetWidth;

            handle.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';

            e.preventDefault();
        });
    });

    document.addEventListener('mousemove', function(e) {
        if (!isDragging || !currentPanel) return;

        const deltaX = e.clientX - startX;
        const newWidth = startWidth + deltaX;

        // 获取面板的最小/最大宽度限制
        const styles = getComputedStyle(currentPanel);
        const minWidth = parseInt(styles.minWidth) || 200;
        const maxWidth = parseInt(styles.maxWidth) || 600;

        // 应用宽度限制
        const constrainedWidth = Math.max(minWidth, Math.min(maxWidth, newWidth));
        currentPanel.style.flex = 'none';
        currentPanel.style.width = constrainedWidth + 'px';

        // 触发图表 resize
        triggerChartResize();
    });

    document.addEventListener('mouseup', function() {
        if (isDragging) {
            isDragging = false;
            if (currentHandle) {
                currentHandle.classList.remove('dragging');
            }
            document.body.style.cursor = '';
            document.body.style.userSelect = '';

            currentHandle = null;
            currentPanel = null;
        }
    });
}

/**
 * 垂直拖拽 - 调整上下比例
 */
function initVerticalResize() {
    const handles = document.querySelectorAll('.resize-handle-v');
    let isDragging = false;
    let currentHandle = null;
    let parentPanel = null;
    let topSection = null;
    let bottomSection = null;
    let startY = 0;
    let startTopHeight = 0;
    let startBottomHeight = 0;

    handles.forEach(handle => {
        handle.addEventListener('mousedown', function(e) {
            isDragging = true;
            currentHandle = handle;
            parentPanel = handle.parentElement;

            // 根据 data-section 确定上下区域
            const sectionType = handle.dataset.section;

            if (sectionType === 'middle') {
                topSection = parentPanel.querySelector('.patch-section');
                // 下部是"测量结果 + 步骤详情"的统一滚动区，整体调整高度
                bottomSection = parentPanel.querySelector('#lower-scroll-area')
                    || parentPanel.querySelector('.results-section');
            } else if (sectionType === 'right') {
                topSection = parentPanel.querySelector('.chart-section');
                bottomSection = parentPanel.querySelector('.gamma-section');
            }

            if (!topSection || !bottomSection) return;

            startY = e.clientY;
            startTopHeight = topSection.offsetHeight;
            startBottomHeight = bottomSection.offsetHeight;

            handle.classList.add('dragging');
            document.body.style.cursor = 'row-resize';
            document.body.style.userSelect = 'none';

            e.preventDefault();
        });
    });

    document.addEventListener('mousemove', function(e) {
        if (!isDragging || !topSection || !bottomSection) return;

        const deltaY = e.clientY - startY;

        // 计算新的高度
        const newTopHeight = startTopHeight + deltaY;
        const newBottomHeight = startBottomHeight - deltaY;

        // 获取最小高度限制
        const minTopHeight = parseInt(getComputedStyle(topSection).minHeight) || 120;
        const minBottomHeight = parseInt(getComputedStyle(bottomSection).minHeight) || 150;

        // 应用高度限制
        if (newTopHeight >= minTopHeight && newBottomHeight >= minBottomHeight) {
            topSection.style.flex = 'none';
            topSection.style.height = newTopHeight + 'px';
            bottomSection.style.flex = 'none';
            bottomSection.style.height = newBottomHeight + 'px';
        }

        // 触发图表 resize
        triggerChartResize();
    });

    document.addEventListener('mouseup', function() {
        if (isDragging) {
            isDragging = false;
            if (currentHandle) {
                currentHandle.classList.remove('dragging');
            }
            document.body.style.cursor = '';
            document.body.style.userSelect = '';

            currentHandle = null;
            topSection = null;
            bottomSection = null;
        }
    });
}

/**
 * 触发图表 resize（延迟执行避免频繁调用）
 */
function triggerChartResize() {
    clearTimeout(window._resizeTimeout);
    window._resizeTimeout = setTimeout(() => {
        if (typeof resizeCharts === 'function') {
            resizeCharts();
        }
    }, 100);
}

/**
 * 初始化底部色块栏滚轮横向滚动
 */
function initPatchBarScroll() {
    const patchListArea = document.getElementById('patch-list-area');

    if (!patchListArea) return;

    // 该函数会在每次色块列表重渲染时被调用：
    // 元素是持久的，只绑定一次监听器，避免重复绑定导致滚动量成倍放大
    if (patchListArea.dataset.scrollBound) {
        updateScrollIndicator(patchListArea);
        return;
    }
    patchListArea.dataset.scrollBound = '1';

    // 监听滚轮事件，转换为横向滚动
    patchListArea.addEventListener('wheel', function(e) {
        // 只有当内容超出容器宽度时才启用横向滚动
        if (patchListArea.scrollWidth > patchListArea.clientWidth) {
            e.preventDefault();

            // 将垂直滚轮转换为横向滚动
            const scrollAmount = e.deltaY || e.deltaX;
            patchListArea.scrollLeft += scrollAmount;
        }
    }, { passive: false });

    // 添加滚动指示器样式（当有隐藏内容时）
    updateScrollIndicator(patchListArea);

    // 监听滚动更新指示器
    patchListArea.addEventListener('scroll', function() {
        updateScrollIndicator(patchListArea);
    });
}

/**
 * 更新滚动指示器
 */
function updateScrollIndicator(element) {
    const scrollLeft = element.scrollLeft;
    const scrollWidth = element.scrollWidth;
    const clientWidth = element.clientWidth;

    // 如果有隐藏内容，添加视觉提示
    if (scrollWidth > clientWidth) {
        // 左侧有隐藏内容
        if (scrollLeft > 0) {
            element.classList.add('has-left-hidden');
        } else {
            element.classList.remove('has-left-hidden');
        }

        // 右侧有隐藏内容
        if (scrollLeft < scrollWidth - clientWidth - 5) {
            element.classList.add('has-right-hidden');
        } else {
            element.classList.remove('has-right-hidden');
        }
    } else {
        element.classList.remove('has-left-hidden', 'has-right-hidden');
    }
}

// ========== 历史数据管理 ==========

/**
 * 初始化历史数据选择功能
 */
function initHistorySelect() {
    const historySelect = document.getElementById('history-select');
    const btnRefresh = document.getElementById('btn-refresh-history');
    const btnLoad = document.getElementById('btn-load-history');
    const btnDelete = document.getElementById('btn-delete-history');
    const btnCompare = document.getElementById('btn-compare-history');

    // 选择变化时更新信息显示
    historySelect?.addEventListener('change', function() {
        currentHistoryId = this.value;
        updateHistoryInfo();

        // 启用/禁用按钮
        btnLoad.disabled = !currentHistoryId;
        btnDelete.disabled = !currentHistoryId;
    });

    // 刷新按钮
    btnRefresh?.addEventListener('click', function() {
        if (backend) {
            backend.refresh_measurement_list();
            updateStatus(t('正在刷新历史数据列表...'));
        }
    });

    // 加载按钮
    btnLoad?.addEventListener('click', function() {
        if (currentHistoryId && backend) {
            backend.load_measurement(currentHistoryId);
            updateStatus(t('正在加载历史数据: {currentHistoryId}', {currentHistoryId: currentHistoryId}));
        }
    });

    // 删除按钮
    btnDelete?.addEventListener('click', function() {
        if (currentHistoryId && backend) {
            if (confirm(t('确定要删除测量数据 {currentHistoryId} 吗？', {currentHistoryId: currentHistoryId}))) {
                backend.delete_measurement(currentHistoryId);
                updateStatus(t('已删除历史数据: {currentHistoryId}', {currentHistoryId: currentHistoryId}));
            }
        }
    });

    // 数据对比按钮
    btnCompare?.addEventListener('click', function() {
        openComparisonWindow();
    });
}

/**
 * 处理测量数据列表更新
 */
function handleMeasurementListUpdated(listJson) {
    console.log('[handleMeasurementListUpdated] 收到数据:', listJson?.substring(0, 200));
    console.log('[handleMeasurementListUpdated] 数据类型:', typeof listJson);
    // P1-D: 使用统一的 parsePayload helper（数组类型）
    const data = parsePayload(listJson, []);
    console.log('[handleMeasurementListUpdated] 解析后数据:', data);
    console.log('[handleMeasurementListUpdated] data.measurements 存在:', !!data.measurements);
    console.log('[handleMeasurementListUpdated] data.measurements 类型:', Array.isArray(data.measurements) ? 'Array' : typeof data.measurements);
    // 支持两种格式：直接数组或 {measurements: [...]}
    historyMeasurements = data.measurements || data;
    console.log('[handleMeasurementListUpdated] historyMeasurements 数量:', historyMeasurements.length);
    console.log('[handleMeasurementListUpdated] historyMeasurements 第一条:', historyMeasurements[0]);
    updateHistorySelect();
    updateStatus(t('已加载 {historyMeasurements_length} 条历史测量记录', {historyMeasurements_length: historyMeasurements.length}));
}

/**
 * 处理会话列表更新
 */
function handleSessionListUpdated(listJson) {
    // P1-D: 使用统一的 parsePayload helper（数组类型）
    const sessions = parsePayload(listJson, []);
    updateSessionSelect(sessions);
    updateStatus(t('已加载 {sessions_length} 个会话', {sessions_length: sessions.length}));
}

/**
 * 更新会话选择下拉框
 */
function updateSessionSelect(sessions) {
    const select = document.getElementById('session-select');
    if (!select) return;

    // 清空现有选项
    select.innerHTML = '<option value="">-- 选择会话 --</option>';

    // 添加会话选项
    sessions.forEach(session => {
        const option = document.createElement('option');
        const mode = session.measure_mode ? session.measure_mode.toUpperCase() : 'UNKNOWN';
        const name = session.display_name || t('会话 {session_session_id}', {session_session_id: session.session_id.substring(0, 17)});
        option.value = session.session_id;
        option.textContent = `${name} (${mode})`;
        select.appendChild(option);
    });
}

/**
 * 处理cal校准文件列表更新
 */
function handleCalFileListUpdated(listJson) {
    // P1-D: 使用统一的 parsePayload helper
    const data = parsePayload(listJson);

    // 检查是否是自定义色块组文件列表
    if (data.type === 'custom_patches') {
        handleCustomPatchesFileListUpdated(data);
        return;
    }

    // 普通cal文件列表
    updateCalFileSelect(data);
}

/**
 * 处理cal文件加载结果
 * 加载成功后自动开始 ICC/LUT 测量
 */
function handleCalFileLoaded(resultJson) {
    // P1-D: 使用统一的 parsePayload helper
    const result = parsePayload(resultJson);

    if (result.success) {
        updateStatus(t('校准文件已加载: {result_cal_path}', {result_cal_path: result.cal_path}));
        // 标记校准完成（实际上是加载了已有的校准）
        calibrationDone = true;

        // ========== 自动进入第二阶段测量 ==========
        // cal 文件加载完成后自动开始 ICC/LUT 色块测量
        if (pendingMeasurementMode) {
            updateStatus(t(`校准文件已加载！等待系统稳定后开始测量...`));
            // 增加延迟确保显卡 LUT 完全生效
            setTimeout(() => {
                updateStatus(t('自动开始 {pendingMeasurementMode_toUpperCase} 测量...', {pendingMeasurementMode_toUpperCase: pendingMeasurementMode.toUpperCase()}));
                startICCLUTMeasurement();
            }, 2000);  // 增加到 2 秒
        }
    } else {
        updateStatus(t('加载校准文件失败: {result_message}', {result_message: result.message}));
        // 重置状态
        pendingMeasurementMode = null;
        calibrationDone = false;
        // 重置按钮状态
        setCycleButtonsState(false);
    }
}

/**
 * 更新cal文件选择下拉框
 */
function updateCalFileSelect(calFiles) {
    const calFileSelect = document.getElementById('icc-cal-file-select');
    if (!calFileSelect) return;

    // 清空现有选项
    calFileSelect.innerHTML = '<option value="">-- 请选择 .cal 文件 --</option>';

    // 添加cal文件选项
    calFiles.forEach(item => {
        const option = document.createElement('option');
        option.value = item.filepath;
        // 格式化时间显示
        const timestamp = new Date(item.timestamp);
        const timeStr = timestamp.toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
        option.textContent = `${item.filename} (${timeStr})`;
        calFileSelect.appendChild(option);
    });

    // ========== 自动选择待选中的cal文件 ==========
    // 如果有待选中的cal文件路径（dispcal完成后自动设置），自动选中它
    if (window._pendingCalFilePath) {
        calFileSelect.value = window._pendingCalFilePath;
        if (calFileSelect.value === window._pendingCalFilePath) {
            console.log(`[自动选择cal文件] 成功选中: ${window._pendingCalFilePath}`);
        } else {
            console.log(`[自动选择cal文件] 文件不在列表中: ${window._pendingCalFilePath}`);
        }
        // 清除待选中的路径
        window._pendingCalFilePath = null;
    }
}

/**
 * 更新历史数据选择下拉框
 */
function updateHistorySelect() {
    const historySelect = document.getElementById('history-select');
    console.log('[updateHistorySelect] historySelect 存在:', !!historySelect);
    if (!historySelect) return;
    
    console.log('[updateHistorySelect] historyMeasurements 数量:', historyMeasurements.length);
    console.log('[updateHistorySelect] historyMeasurements 数据:', historyMeasurements);

    // 清空现有选项
    historySelect.innerHTML = '<option value="">-- 当前测量 --</option>';

    // 添加历史数据选项
    historyMeasurements.forEach((item, index) => {
        const option = document.createElement('option');
        option.value = item.id;

        // 确定显示名称：优先使用用户自定义名称
        let displayText;
        if (item.display_name && item.display_name.trim()) {
            // 使用用户自定义名称
            displayText = item.display_name;
        } else {
            // 格式化默认显示文本：时间 - 模式 - 探头
            const time = formatTimestamp(item.timestamp);
            const modeDisplay = getModeDisplayText(item.measure_mode);
            const dataType = [];
            if (item.has_gamut) dataType.push('色域');
            if (item.has_gamma) dataType.push('Gamma');
            if (item.has_lut) dataType.push('LUT色块');

            // 显示格式：时间 - [模式] - 探头 (数据类型)
            const modeText = modeDisplay ? `[${modeDisplay}] ` : '';
            displayText = `${time} - ${modeText}${item.probe} (${dataType.join('+')})`;
        }

        option.textContent = displayText;
        historySelect.appendChild(option);
        
        if (index < 3) {
            console.log(`[updateHistorySelect] 添加选项 ${index}:`, {
                id: item.id,
                text: displayText
            });
        }
    });

    console.log('[updateHistorySelect] 完成，选项数量:', historySelect.options.length);
    
    // 同时更新 CCMX 数据选择下拉框
    updateCCMXDataSelects();
}

/**
 * 获取测量模式的显示文本
 */
function getModeDisplayText(mode) {
    const modeNames = {
        'gamut': t('色域'),
        'icc': 'ICC',
        'lut': 'LUT',
        'custom': t('自定义'),
        'ccmx': 'CCMX',
        'saturation': t('饱和度扫描'),
        'hdr': 'HDR',
        'uniformity': t('均匀性')
    };
    return modeNames[mode] || '';
}

/**
 * 更新 CCMX 数据选择下拉框（分光仪和色度计）
 */
function updateCCMXDataSelects() {
    const refSelect = document.getElementById('ccmx-ref-select');
    const targetSelect = document.getElementById('ccmx-target-select');

    if (!refSelect || !targetSelect) return;

    // 清空现有选项
    refSelect.innerHTML = '<option value="">-- 请选择分光仪测量数据 --</option>';
    targetSelect.innerHTML = '<option value="">-- 请选择色度计测量数据 --</option>';

    // 添加测量数据选项（只包含色域数据的记录）
    const validMeasurements = historyMeasurements.filter(item => item.has_gamut);

    validMeasurements.forEach(item => {
        // 确定显示名称：优先使用用户自定义名称
        let displayText;
        if (item.display_name && item.display_name.trim()) {
            displayText = item.display_name;
        } else {
            const time = formatTimestamp(item.timestamp);
            const modeDisplay = getModeDisplayText(item.measure_mode);
            const modeText = modeDisplay ? `[${modeDisplay}] ` : '';
            displayText = `${time} - ${modeText}${item.probe}`;
        }

        // 分光仪选择
        const refOption = document.createElement('option');
        refOption.value = item.id;
        refOption.textContent = displayText;
        refSelect.appendChild(refOption);

        // 色度计选择
        const targetOption = document.createElement('option');
        targetOption.value = item.id;
        targetOption.textContent = displayText;
        targetSelect.appendChild(targetOption);
    });
}

/**
 * 检查 CCMX 选项是否有效，更新按钮状态
 */
function checkCCMXSelection() {
    const refSelect = document.getElementById('ccmx-ref-select');
    const targetSelect = document.getElementById('ccmx-target-select');
    const createBtn = document.getElementById('btn-create-ccmx');

    if (!refSelect || !targetSelect || !createBtn) return;

    const refId = refSelect.value;
    const targetId = targetSelect.value;

    // 两个选择都不为空且不相同才能启用按钮
    createBtn.disabled = !refId || !targetId || refId === targetId;
}

/**
 * 从选中的测量数据创建 CCMX 矩阵
 */
function createCCMXFromSelected() {
    const refSelect = document.getElementById('ccmx-ref-select');
    const targetSelect = document.getElementById('ccmx-target-select');

    if (!refSelect || !targetSelect || !backend) return;

    const refId = refSelect.value;
    const targetId = targetSelect.value;

    if (!refId || !targetId || refId === targetId) {
        updateStatus(t('请选择不同的分光仪和色度计测量数据'));
        return;
    }

    // 调用后端生成 CCMX
    backend.generate_ccmx_from_measurements(refId, targetId);
    updateStatus(t('正在生成 CCMX 矩阵...'));
}

/**
 * 获取显示器类型的友好显示名称
 */
function getDisplayTypeLabel(typeCode) {
    const typeMap = {
        'l': 'LCD',
        'e': 'LCD White LED',
        'b': 'LCD RGB LED',
        'o': 'OLED',
        'w': 'WOLED',
        'c': 'CRT',
        'p': 'DLP',
        'm': 'Plasma',
        '1': 'LCD CCFL',
        '2': 'LCD CCFL IPS',
        '3': 'LCD CCFL PVA',
        '4': 'LCD CCFL TFT',
        'L': 'LCD CCFL Wide Gamut',
        '8': 'LCD White LED IPS',
        '9': 'LCD White LED PVA',
        'a': 'LCD White LED TFT',
        'h': 'LCD RG Phosphor',
        'r': 'LCD PFS Phosphor',
        'i': 'LCD GB-R Phosphor'
    };
    return typeMap[typeCode] || typeCode || '';
}

/**
 * 更新历史数据信息显示
 */
function updateHistoryInfo() {
    const probeEl = document.getElementById('history-probe');
    const displayEl = document.getElementById('history-display');
    const timeEl = document.getElementById('history-time');
    const dataTypeEl = document.getElementById('history-data-type');

    if (!currentHistoryId) {
        // 显示当前测量信息
        const probeValue = document.getElementById('probe-type').value || '--';
        probeEl.textContent = t('探头: {probeValue}', {probeValue: probeValue});
        const currentType = document.getElementById('display-type').value || '';
        displayEl.textContent = t('显示器: {getDisplayTypeLabel_currentType}', {getDisplayTypeLabel_currentType: getDisplayTypeLabel(currentType)});
        timeEl.textContent = t(`时间: 当前`);

        const hasGamut = Object.values(measurementData.gamut).some(v => v !== null);
        const hasGamma = measurementData.grayScale.length > 0;
        const hasLutPatches = measurementData.lutPatches.length > 0;

        const dataType = [];
        if (hasGamut) dataType.push('色域');
        if (hasGamma) dataType.push('Gamma');
        if (hasLutPatches) dataType.push(`LUT色块(${measurementData.lutPatches.length})`);

        dataTypeEl.textContent = t('数据: {data_str}', {data_str: dataType.join('+') || '--'});
        return;
    }

    // 查找选中的历史数据
    const item = historyMeasurements.find(h => h.id === currentHistoryId);
    if (item) {
        probeEl.textContent = t('探头: {item_probe}', {item_probe: item.probe || '--'});
        // 合并显示型号和显示器类型，例如 "PHL 439P1 LCD"
        const model = item.display_model || '';
        const typeLabel = getDisplayTypeLabel(item.display_type);
        let displayValue = '--';
        if (model && typeLabel) {
            displayValue = `${model} ${typeLabel}`;
        } else if (model) {
            displayValue = model;
        } else {
            displayValue = typeLabel || '--';
        }
        displayEl.textContent = t('显示器: {displayValue}', {displayValue: displayValue});
        timeEl.textContent = t('时间: {formatTimestamp_item_timestamp}', {formatTimestamp_item_timestamp: formatTimestamp(item.timestamp)});

        const dataType = [];
        if (item.has_gamut) dataType.push('色域');
        if (item.has_gamma) dataType.push('Gamma');
        if (item.has_lut) dataType.push('LUT色块');
        dataTypeEl.textContent = t('数据: {data_str}', {data_str: dataType.join('+') || '--'});
    }
}

/**
 * 格式化时间戳
 */
function formatTimestamp(timestamp) {
    if (!timestamp) return '--';
    
    try {
        const date = new Date(timestamp);
        return date.toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (e) {
        return timestamp;
    }
}

/**
 * 处理测量数据保存结果
 */
function handleMeasurementSaved(resultJson) {
    // P1-D: 使用统一的 parsePayload helper
    const result = parsePayload(resultJson);

    if (result.success) {
        updateStatus(t('数据已保存: {result_id}', {result_id: result.id}));
        // 刷新历史列表
        if (backend) {
            backend.get_measurement_list();
        }
    } else {
        updateStatus(t('保存失败: {result_message}', {result_message: result.message}));
    }
}

/**
 * 处理测量数据加载结果
 */
function handleMeasurementLoaded(dataJson) {
    // P1-D: 使用统一的 parsePayload helper
    const data = parsePayload(dataJson);

    // 检查是否是自定义色块组文件加载结果
    if (data.success && data.data && data.data.patches) {
        handleCustomPatchesFileLoaded(data);
        return;
    }

    // 检查是否是错误响应
    if (data.success === false) {
        updateStatus(t('加载失败: {data_message}', {data_message: data.message}));
        return;
    }

    // 清空当前数据
    clearCurrentData();

    // 加载测量数据
    const measurements = data.measurements;
    const metadata = data.metadata;

    // 更新元数据显示（安全检查元素是否存在）
    const historyProbe = document.getElementById('history-probe');
    const historyDisplay = document.getElementById('history-display');
    const historyTime = document.getElementById('history-time');
    const historyDataType = document.getElementById('history-data-type');

    if (historyProbe) historyProbe.textContent = t('探头: {metadata_probe}', {metadata_probe: metadata.probe || '--'});
    if (historyDisplay) historyDisplay.textContent = t('显示器: {metadata_display_type}', {metadata_display_type: metadata.display_type || '--'});
    if (historyTime) historyTime.textContent = t('时间: {formatTimestamp_metadata_timestamp}', {formatTimestamp_metadata_timestamp: formatTimestamp(metadata.timestamp)});
    if (historyDataType) historyDataType.textContent = t(`数据: 色域+Gamma`);

    // 加载色域数据
    const gamut = measurements.gamut;
    if (gamut) {
        const colorMap = {
            'red': '红',
            'green': '绿',
            'blue': '蓝',
            'white': '白',
            'black': '黑'
        };

        for (const [key, chnName] of Object.entries(colorMap)) {
            if (gamut[key] && gamut[key].xyY) {
                const xyY = gamut[key].xyY;
                const rgb = gamut[key].RGB;

                measurementData.gamut[chnName] = {
                    patchName: chnName,
                    rgb: { r: rgb[0], g: rgb[1], b: rgb[2] },
                    x: xyY[0],
                    y: xyY[1],
                    Y: xyY[2]
                };
            }
        }
    }

    // 加载Gamma数据
    const gamma = measurements.gamma;
    if (gamma && gamma.length > 0) {
        measurementData.grayScale = gamma.map(point => ({
            patchName: point.patch_name || `${point.input}%`,
            rgb: { r: point.RGB[0], g: point.RGB[1], b: point.RGB[2] },
            x: 0.3127,
            y: 0.3290,
            Y: point.Y
        }));
    }

    // 加载 LUT 色块数据
    const lutPatches = measurements.lut_patches || [];
    if (lutPatches.length > 0) {
        measurementData.lutPatches = lutPatches.map(patch => ({
            sampleId: patch.sample_id || patch.patch_name || '',
            patchName: patch.patch_name || patch.sample_id || '',
            rgb: { r: patch.RGB[0], g: patch.RGB[1], b: patch.RGB[2] },
            x: patch.xyY?.[0] || 0.3127,
            y: patch.xyY?.[1] || 0.3290,
            Y: patch.xyY?.[2] || 0
        }));
    } else {
        measurementData.lutPatches = [];
    }

    // 更新数据类型显示
    const hasGamut = Object.values(measurementData.gamut).some(v => v !== null);
    const hasGamma = measurementData.grayScale.length > 0;
    const hasLutPatches = measurementData.lutPatches.length > 0;

    if (historyDataType) {
        const dataTypes = [];
        if (hasGamut) dataTypes.push('色域');
        if (hasGamma) dataTypes.push('Gamma');
        if (hasLutPatches) dataTypes.push(`LUT色块(${measurementData.lutPatches.length})`);
        historyDataType.textContent = t('数据: {data_str}', {data_str: dataTypes.join('+') || '--'});
    }

    // 使用历史数据重新渲染图表
    if (typeof renderChartsFromHistory === 'function') {
        renderChartsFromHistory(measurementData);
    }

    updateStatus(t('已加载历史数据: {metadata_measurement_id}', {metadata_measurement_id: metadata.measurement_id}));
}

/**
 * 处理数据导出结果
 */
function handleDataExported(resultJson) {
    // P1-D: 使用统一的 parsePayload helper
    const result = parsePayload(resultJson);

    if (result.success) {
        let statusMsg = t('{result_format}文件已导出: {result_filepath}', {result_format: result.format, result_filepath: result.filepath});
        if (result.format === 'ICC' && result.applied === true) {
            statusMsg += ' (已安装并应用到系统)';
            updateStatus(statusMsg);
            hideExportModal();  // 成功时关闭弹窗
        } else if (result.format === 'ICC' && result.applied === false) {
            // ICC 应用失败的情况
            if (result.error_type === 'permission') {
                // 权限错误，显示详细提示弹窗
                statusMsg += ' (安装失败: 需要管理员权限)';
                updateStatus(statusMsg);
                showPermissionErrorDialog(result.message);
            } else if (result.message) {
                statusMsg += ` (${result.message})`;
                updateStatus(statusMsg);
                hideExportModal();  // 非权限错误，关闭弹窗
            } else {
                updateStatus(statusMsg);
                hideExportModal();
            }
        } else {
            updateStatus(statusMsg);
            hideExportModal();  // 其他格式成功，关闭弹窗
        }
    } else {
        updateStatus(t('导出失败: {result_message}', {result_message: result.message}));
        hideExportModal();
    }
}

/**
 * 显示权限错误对话框
 */
function showPermissionErrorDialog(message) {
    // 创建一个模态对话框显示权限错误信息
    const dialog = document.createElement('div');
    dialog.className = 'modal-overlay show';
    dialog.id = 'permission-error-dialog';
    dialog.innerHTML = `
        <div class="modal-dialog" style="max-width: 500px;">
            <div class="modal-header">
                <h3>⚠️ ICC 安装失败</h3>
                <button class="modal-close-btn" onclick="this.closest('.modal-overlay').remove()">×</button>
            </div>
            <div class="modal-body">
                <div class="error-message-content">
                    <pre style="white-space: pre-wrap; font-family: inherit; font-size: 12px; color: var(--text-primary); background: var(--bg-tertiary); padding: 12px; border-radius: 6px;">${message}</pre>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-primary" onclick="this.closest('.modal-overlay').remove()">我知道了</button>
            </div>
        </div>
    `;
    document.body.appendChild(dialog);
    // 点击背景关闭
    dialog.addEventListener('click', (e) => {
        if (e.target === dialog) {
            dialog.remove();
        }
    });
}

/**
 * 保存当前测量数据
 */
function saveCurrentData() {
    if (!backend) {
        updateStatus(t('错误: 后端未连接'));
        return;
    }

    // 检查是否有有效数据
    const hasGamut = Object.values(measurementData.gamut).some(v => v !== null);
    const hasGamma = measurementData.grayScale.length > 0;
    const hasLutPatches = measurementData.lutPatches.length > 0;

    if (!hasGamut && !hasGamma && !hasLutPatches) {
        updateStatus(t('没有有效的测量数据可保存'));
        return;
    }

    backend.save_current_measurement();
    updateStatus(t('正在保存测量数据...'));
}

/**
 * 导出TI3格式数据
 */
function exportTi3Data() {
    if (!backend) {
        updateStatus(t('错误: 后端未连接'));
        return;
    }

    // 检查是否有有效数据
    const hasGamut = Object.values(measurementData.gamut).some(v => v !== null);
    const hasGamma = measurementData.grayScale.length > 0;
    const hasLutPatches = measurementData.lutPatches.length > 0;

    if (!hasGamut && !hasGamma && !hasLutPatches) {
        updateStatus(t('没有有效的测量数据可导出'));
        return;
    }
    
    // 生成默认文件名
    const timestamp = new Date().toISOString().slice(0, 10);
    const defaultFilename = `topos_calibrator_${timestamp}.ti3`;
    
    // 使用文件保存对话框（通过后端）
    backend.export_measurement_ti3(defaultFilename);
    updateStatus(t('正在导出TI3文件...'));
}

/**
 * 清空当前数据（不触发后端）
 */
function clearCurrentData() {
    measurementData.gamut = { red: null, green: null, blue: null, white: null, black: null };
    measurementData.grayScale = [];
    measurementData.gamma = null;
    measurementData.lutPatches = [];

    // 清除显示
    document.getElementById('result-patch').textContent = '--';
    document.getElementById('result-x').textContent = '--';
    document.getElementById('result-y').textContent = '--';
    document.getElementById('result-Y').textContent = '--';
    document.getElementById('result-cct').textContent = '--';
    document.getElementById('result-deltae').textContent = '--';
    document.getElementById('gamut-srgb').textContent = '--';
    document.getElementById('gamut-p3').textContent = '--';
    document.getElementById('gamut-adobe').textContent = '--';
    document.getElementById('gamma-value').textContent = '--';

    // 清除图表
    if (typeof clearCharts === 'function') {
        clearCharts();
    }
}

// ========== 弹窗管理 ==========

/**
 * 初始化弹窗事件
 */
function initModalEvents() {
    // ICC 弹窗事件
    initICCModalEvents();

    // LUT 弹窗事件
    initLUTModalEvents();

    // 统一导出弹窗事件
    initExportModalEvents();
}

/**
 * 初始化 ICC 弹窗事件
 */
function initICCModalEvents() {
    const overlay = document.getElementById('icc-modal-overlay');
    const modal = document.getElementById('icc-modal');
    const closeBtn = document.getElementById('icc-modal-close');
    const cancelBtn = document.getElementById('icc-modal-cancel');
    const createBtn = document.getElementById('icc-modal-create');
    const browseBtn = document.getElementById('icc-browse-btn');

    // 关闭按钮
    closeBtn?.addEventListener('click', hideICCModal);
    cancelBtn?.addEventListener('click', hideICCModal);

    // 点击遮罩关闭
    overlay?.addEventListener('click', (e) => {
        if (e.target === overlay) {
            hideICCModal();
        }
    });

    // 浏览按钮 - 选择保存路径
    browseBtn?.addEventListener('click', () => {
        if (backend) {
            backend.browse_save_path('icc');
        }
    });

    // 格式选择切换
    document.querySelectorAll('input[name="icc-format"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const iccParams = document.getElementById('icc-params-section');
            const ti3Params = document.getElementById('ti3-params-section');

            if (e.target.value === 'icc') {
                iccParams?.classList.remove('hidden');
                ti3Params?.classList.add('hidden');
                // 更新创建按钮文本
                createBtn.textContent = t('快速生成');
            } else {
                iccParams?.classList.add('hidden');
                ti3Params?.classList.remove('hidden');
                // 更新创建按钮文本
                createBtn.textContent = t('导出 TI3');
            }
        });
    });

    // 创建按钮
    createBtn?.addEventListener('click', () => {
        createICCFile();
    });
}

/**
 * 初始化 LUT 弹窗事件
 */
function initLUTModalEvents() {
    const overlay = document.getElementById('lut-modal-overlay');
    const modal = document.getElementById('lut-modal');
    const closeBtn = document.getElementById('lut-modal-close');
    const cancelBtn = document.getElementById('lut-modal-cancel');
    const createBtn = document.getElementById('lut-modal-create');
    const browseBtn = document.getElementById('lut-browse-btn');
    const blackLiftSlider = document.getElementById('lut-black-lift');
    const blackLiftValue = document.getElementById('lut-black-lift-value');

    // 关闭按钮
    closeBtn?.addEventListener('click', hideLUTModal);
    cancelBtn?.addEventListener('click', hideLUTModal);

    // 点击遮罩关闭
    overlay?.addEventListener('click', (e) => {
        if (e.target === overlay) {
            hideLUTModal();
        }
    });

    // 浏览按钮 - 选择保存路径
    browseBtn?.addEventListener('click', () => {
        if (backend) {
            backend.browse_save_path('lut');
        }
    });

    // 黑场提升滑块
    blackLiftSlider?.addEventListener('input', (e) => {
        blackLiftValue.textContent = e.target.value + '%';
    });

    // 格式选择切换 - 更新文件扩展名提示
    document.querySelectorAll('input[name="lut-format"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const fileNameInput = document.getElementById('lut-file-name');
            if (fileNameInput) {
                const currentName = fileNameInput.value.replace(/\.[^.]+$/, '');
                fileNameInput.value = currentName + '.' + e.target.value.toLowerCase();
            }
        });
    });

    // 创建按钮
    createBtn?.addEventListener('click', () => {
        createLUTFile();
    });
}

/**
 * 同步目标白点：将icc-target-white的值同步到icc-output-white-point
 * 当选择"同步"时，使用icc-cal-white-point的值
 */
function syncTargetWhitePoint() {
    const targetWhiteSelect = document.getElementById('icc-target-white');
    const calWhiteSelect = document.getElementById('icc-cal-white-point');
    const outputWhiteSelect = document.getElementById('icc-output-white-point');
    
    if (!targetWhiteSelect || !outputWhiteSelect) return;
    
    const targetValue = targetWhiteSelect.value;
    const outputValue = outputWhiteSelect.value;
    
    // 检查是否是同步模式（主界面或弹窗中选择了sync）
    const isSyncMode = targetValue === 'sync' || outputValue === 'sync';
    
    if (isSyncMode) {
        // 同步模式：使用校准白点的值
        const calValue = calWhiteSelect?.value || 'D65';
        outputWhiteSelect.value = calValue;
        
        // 如果校准白点是自定义，需要同步xy坐标
        if (calValue === 'custom') {
            const calWhiteX = document.getElementById('icc-cal-white-x')?.value;
            const calWhiteY = document.getElementById('icc-cal-white-y')?.value;
            const customWhiteX = document.getElementById('custom-white-x');
            const customWhiteY = document.getElementById('custom-white-y');
            const customWhiteRow = document.getElementById('custom-white-row');
            
            if (calWhiteX && calWhiteY && customWhiteX && customWhiteY) {
                customWhiteX.value = calWhiteX;
                customWhiteY.value = calWhiteY;
                customWhiteRow?.classList.remove('hidden');
            }
        } else {
            const customWhiteRow = document.getElementById('custom-white-row');
            customWhiteRow?.classList.add('hidden');
        }
    }
    // 如果不是sync模式，保持icc-output-white-point的原值不变
}

/**
 * 显示 ICC 弹窗
 */
function showICCModal() {
    // 检查是否有测量数据
    const hasGamut = Object.values(measurementData.gamut).some(v => v !== null);
    const hasGamma = measurementData.grayScale.length > 0;
    const hasLutPatches = measurementData.lutPatches.length > 0;

    if (!hasGamut && !hasGamma && !hasLutPatches) {
        updateStatus(t('请先完成测量再制作 ICC 文件'));
        return;
    }

    // 设置默认保存路径
    const timestamp = new Date().toISOString().slice(0, 10);
    document.getElementById('icc-file-name').value = `display_profile_${timestamp}.icc`;

    // 显示弹窗
    document.getElementById('icc-modal-overlay').classList.add('show');
    updateStatus(t('ICC 文件制作选项'));
}

/**
 * 隐藏 ICC 弹窗
 */
function hideICCModal() {
    document.getElementById('icc-modal-overlay').classList.remove('show');
}

/**
 * 显示 LUT 弹窗
 */
function showLUTModal() {
    // 检查是否有测量数据
    const hasGamut = Object.values(measurementData.gamut).some(v => v !== null);
    const hasGamma = measurementData.grayScale.length > 0;
    const hasLutPatches = measurementData.lutPatches.length > 0;

    if (!hasGamut && !hasGamma && !hasLutPatches) {
        updateStatus(t('请先完成测量再制作 LUT 文件'));
        return;
    }

    // 设置默认保存路径
    const timestamp = new Date().toISOString().slice(0, 10);
    document.getElementById('lut-file-name').value = `display_lut_${timestamp}.cube`;

    // 显示弹窗
    document.getElementById('lut-modal-overlay').classList.add('show');
    updateStatus(t('LUT 文件制作选项'));
}

/**
 * 隐藏 LUT 弹窗
 */
function hideLUTModal() {
    document.getElementById('lut-modal-overlay').classList.remove('show');
}

/**
 * 从当前测量填入白点坐标
 */
function fillWhitePointFromMeasurement() {
    // 尝试从最近测量的白色色块获取 xy 值
    const whiteData = measurementData.gamut?.white;

    if (whiteData && whiteData.x && whiteData.y) {
        const xInput = document.getElementById('custom-white-x');
        const yInput = document.getElementById('custom-white-y');
        if (xInput && yInput) {
            xInput.value = whiteData.x.toFixed(4);
            yInput.value = whiteData.y.toFixed(4);
            updateStatus(t('已填入白点坐标: x={whiteData_x_toFixed_4}, y={whiteData_y_toFixed_4}', {whiteData_x_toFixed_4: whiteData.x.toFixed(4), whiteData_y_toFixed_4: whiteData.y.toFixed(4)}));
        }
    } else {
        updateStatus(t('未找到白色测量数据，请先测量白色色块'));
    }
}

/**
 * 从测量数据中获取白点坐标
 * @returns {{x: number, y: number} | null} 白点 xy 坐标，如果没有白色测量数据则返回 null
 */
function getMeasuredWhitePoint() {
    const white = measurementData?.gamut?.white;
    if (!white) {
        console.log('[getMeasuredWhitePoint] 未找到白色测量数据');
        return null;
    }

    const { X, Y, Z } = white;
    const sum = X + Y + Z;
    if (sum === 0) {
        console.log('[getMeasuredWhitePoint] 白色 XYZ 和为 0');
        return null;
    }

    const x = X / sum;
    const y = Y / sum;

    console.log(`[getMeasuredWhitePoint] 测量白点: x=${x.toFixed(4)}, y=${y.toFixed(4)}`);
    return { x, y };
}

/**
 * 创建 ICC 文件
 */
function createICCFile() {
    if (!backend) {
        updateStatus(t('错误: 后端未连接'));
        return;
    }

    // 收集参数
    const format = document.querySelector('input[name="icc-format"]:checked')?.value || 'icc';
    const filePath = document.getElementById('icc-file-path')?.value || '';
    const fileName = document.getElementById('icc-file-name')?.value || 'display_profile';

    // 从测量数据中获取白点
    const measuredWP = getMeasuredWhitePoint();
    const whitePointX = measuredWP?.x || 0.3127;  // 默认 D65
    const whitePointY = measuredWP?.y || 0.3290;

    // 从测量设置区获取 Gamma
    const gamma = document.getElementById('icc-target-gamma')?.value || '2.2';

    console.log(`[createICCFile] 使用白点: x=${whitePointX.toFixed(4)}, y=${whitePointY.toFixed(4)}, Gamma=${gamma}`);

    const params = {
        format: format,
        file_path: filePath,
        file_name: fileName,
        profile_type: document.getElementById('icc-output-profile-type')?.value || 'lut',
        quality: document.getElementById('icc-output-quality')?.value || 'h',
        white_point: 'custom',  // 使用自定义白点模式
        custom_white_x: whitePointX,
        custom_white_y: whitePointY,
        gamma: gamma,
        gamut_mapping: document.getElementById('icc-output-gamut-mapping')?.value || 'perceptual',
        black_compensation: document.getElementById('icc-black-compensation')?.checked || false,
        apply_profile: document.getElementById('icc-apply-profile')?.checked || false,  // 应用ICC选项
        // TI3 参数
        include_gamut: document.getElementById('ti3-include-gamut')?.checked || true,
        include_gamma: document.getElementById('ti3-include-gamma')?.checked || true
    };

    // 调用后端创建 ICC 文件
    backend.create_icc_file(JSON.stringify(params));

    // 关闭弹窗
    hideICCModal();
    updateStatus(t(`正在生成 ICC 文件...`));
}

/**
 * 创建 LUT 文件
 */
function createLUTFile() {
    if (!backend) {
        updateStatus(t('错误: 后端未连接'));
        return;
    }

    // 收集参数
    const format = document.querySelector('input[name="lut-format"]:checked')?.value || 'cube';
    const filePath = document.getElementById('lut-file-path')?.value || '';
    const fileName = document.getElementById('lut-file-name')?.value || 'display_lut';

    // 从测量设置区获取色域和 Gamma（快速生成复用测量时的配置）
    const targetGamut = document.getElementById('lut-target-gamut')?.value || 'sRGB';
    const targetGamma = document.getElementById('lut-target-gamma')?.value || '2.2';
    const targetWhitePoint = document.getElementById('lut-target-white')?.value || 'D65';

    const params = {
        format: format,
        file_path: filePath,
        file_name: fileName,
        lut_size: document.getElementById('lut-output-size')?.value || '33',
        quality: document.getElementById('lut-output-quality')?.value || 'h',
        target_gamut: targetGamut,
        target_white_point: targetWhitePoint,
        target_gamma: targetGamma,
        input_range: document.getElementById('lut-input-range')?.value || 'full',
        interpolation: document.getElementById('lut-interpolation')?.value || 'tetrahedral',
        black_lift: document.getElementById('lut-black-lift')?.value || 0
    };

    // 调用后端创建 LUT 文件
    backend.create_lut_file(JSON.stringify(params));

    // 关闭弹窗
    hideLUTModal();
    updateStatus(t(`正在生成 LUT 文件...`));
}

/**
 * 处理文件路径选择结果
 */
function handleFilePathSelected(resultJson) {
    // P1-D: 使用统一的 parsePayload helper
    const result = parsePayload(resultJson);
    console.log('[handleFilePathSelected] 收到路径:', result);

    if (result.type === 'icc') {
        document.getElementById('icc-file-path').value = result.path;
    } else if (result.type === 'lut') {
        document.getElementById('lut-file-path').value = result.path;
    } else if (result.type === 'export') {
        const filePathInput = document.getElementById('export-file-path');

        if (filePathInput) {
            filePathInput.value = result.path;
            console.log('[handleFilePathSelected] 设置路径输入框:', result.path);
        }

        // 从完整路径中提取文件名和扩展名，同步更新格式选择
        if (result.path) {
            const pathSeparator = result.path.includes('/') ? '/' : '\\';
            const parts = result.path.split(pathSeparator);
            const fileNameWithExt = parts[parts.length - 1];

            if (fileNameWithExt && fileNameWithExt.includes('.')) {
                // 检查文件名是否匹配当前模式的格式
                const ext = fileNameWithExt.split('.').pop().toLowerCase();
                const mode = currentExportMode || 'icc';

                // 根据扩展名判断是否更新格式选择
                const extToFormat = {
                    'icc': 'icc',
                    'cube': 'cube',
                    '3dl': '3dl',
                    'mga': 'mga',
                    'clf': 'clf',
                    'csv': 'csv',
                    'json': 'json',
                    'ti3': 'ti3',
                    'ccmx': 'ccmx'
                };

                if (extToFormat[ext]) {
                    // 使用 select 元素更新格式选择
                    const formatSelect = document.getElementById(`${mode}-export-format`);
                    if (formatSelect) {
                        formatSelect.value = extToFormat[ext];
                        console.log('[handleFilePathSelected] 更新格式选择:', extToFormat[ext]);
                    }
                }
            }
        }
    } else if (result.type === 'auto_save') {
        const autoSavePath = document.getElementById('prefs-auto-save-path');
        if (autoSavePath) {
            autoSavePath.value = result.path;
            // 触发 change 事件以更新后端设置
            autoSavePath.dispatchEvent(new Event('change'));
        }
    }
}

/**
 * 处理 ICC/LUT 文件创建结果
 */
function handleFileCreated(resultJson) {
    try {
        const result = (typeof resultJson === 'string') ? JSON.parse(resultJson) : resultJson;

        // 调试信息：在状态栏短暂显示
        const statusText = document.getElementById('status-text');
        if (statusText) {
            statusText.textContent = `[DEBUG] handleFileCreated: ${JSON.stringify(result)}`;
            setTimeout(() => {
                if (statusText.textContent.startsWith('[DEBUG]')) {
                    statusText.textContent = t('就绪');
                }
            }, 3000);
        }

        if (result.success) {
            if (result.type === 'calibration') {
                updateStatus(t('校准完成: {result_cal_path}', {result_cal_path: result.cal_path}));
                isCalibrating = false;
                calibrationDone = true;  // 标记校准已完成

                // ========== 自动切换UI到"加载cal校正文件"选项 ==========
                // 这样用户可以看到当前状态，并且UI与实际操作一致
                const loadCalRadio = document.getElementById('icc-load-cal-file');
                if (loadCalRadio) {
                    // 先设置待选中的cal文件路径，供 updateCalFileSelect 使用
                    window._pendingCalFilePath = result.cal_path;

                    // 切换到"加载cal校正文件"选项
                    loadCalRadio.checked = true;
                    // 触发 change 事件以更新UI显示（这会调用 handleIccCalSourceChange）
                    // handleIccCalSourceChange 会调用 backend.get_cal_file_list()
                    // 后端返回后会调用 updateCalFileSelect，updateCalFileSelect 会自动选中待选中的文件
                    loadCalRadio.dispatchEvent(new Event('change'));
                }

                // 恢复 patchListArea 显示
                if (currentPatchList && currentPatchList.mode) {
                    updatePatchBar(currentPatchList);
                }

                // ========== 自动进入第二阶段测量 ==========
                // dispcal 完成后先加载 cal 文件，然后自动开始 ICC/LUT 色块测量
                // 这样可以避免 spotread 重连时的时序问题
                if (pendingMeasurementMode) {
                    updateStatus(t(`校准完成！等待系统稳定后加载校准文件...`));
                    // 增加延迟确保后端完成所有操作（自动保存、文件复制等）
                    setTimeout(() => {
                        updateStatus(t(`正在加载校准文件到显卡 LUT...`));
                        // 自动加载刚才生成的 cal 文件
                        // load_cal_file 会：
                        // 1. 加载 cal 文件到显卡 LUT
                        // 2. 发送 calFileLoaded 信号
                        // 3. calFileLoaded 会触发自动测量
                        backend.load_cal_file(result.cal_path);
                    }, 3000);  // 增加到 3 秒，确保后端完全完成
                }
            } else {
                updateStatus(t('文件已创建: {result_filepath}', {result_filepath: result.filepath}));

                // 向导步骤 5：生成完成 → 记录产物、启用"下一步"、自动进入验证（引导模式）
                // 仅限生成类产物（ICC/LUT）；TI3/JSON 等导出不算
                if (['ICC', 'CUBE', '3DL'].includes(result.format)
                    && typeof maybeCompleteWizardGenerateStep === 'function') {
                    maybeCompleteWizardGenerateStep(result);
                }

                // 如果是 ICC/LUT 导出完成，关闭导出弹窗
                if (result.format === 'ICC' || result.format === 'LUT' || result.format === 'CUBE' || result.format === '3DL') {
                    hideExportStatus();
                    disableExportModalButtons(false);
                    hideExportModal();
                }
            }
        } else {
            // 失败时也要关闭状态提示和弹窗
            hideExportStatus();
            disableExportModalButtons(false);
            hideExportModal();
            updateStatus(t('创建失败: {result_message}', {result_message: result.message}));

            // 向导步骤 5：恢复生成按钮
            if (typeof maybeFailWizardGenerateStep === 'function') {
                maybeFailWizardGenerateStep();
            }
            isCalibrating = false;
            pendingMeasurementMode = null;
            calibrationDone = false;
            // 重置按钮状态
            setCycleButtonsState(false);
            // 恢复 patchListArea
            if (currentPatchList && currentPatchList.mode) {
                updatePatchBar(currentPatchList);
            }
        }
    } catch (e) {
        console.error('解析创建结果失败:', e);
        isCalibrating = false;
        pendingMeasurementMode = null;
        calibrationDone = false;
        // 重置按钮状态
        setCycleButtonsState(false);
        // 恢复导出弹窗状态
        hideExportStatus();
        disableExportModalButtons(false);
    }
}

/**
 * 处理自动保存完成事件
 */
function handleSessionAutoSaved(resultJson) {
    try {
        const result = (typeof resultJson === 'string') ? JSON.parse(resultJson) : resultJson;

        if (result.success) {
            const fileCount = result.files ? result.files.length : 0;
            const modeName = {
                'gamut': '色域测量',
                'gamma': '灰阶测量',
                'lut': 'LUT 色块',
                'dispcal': 'ICC 校准'
            }[result.measure_mode] || result.measure_mode;

            updateStatus(t('自动保存完成: {modeName} ({fileCount} 个文件) → {result_path}', {modeName: modeName, fileCount: fileCount, result_path: result.path}));

            // 可以在侧边栏或状态栏显示最近保存的文件
            console.log('自动保存文件:', result.files);
        } else {
            console.error('自动保存失败:', result.error);
        }
    } catch (e) {
        console.error('解析自动保存结果失败:', e);
    }
}

/**
 * 从当前测量填入白点坐标（通用函数）
 * @param {string} xInputId - x 坐标输入框 ID
 * @param {string} yInputId - y 坐标输入框 ID
 */
function fillWhiteFromMeasurement(xInputId, yInputId) {
    const whiteData = measurementData.gamut?.white;

    if (whiteData && whiteData.x && whiteData.y) {
        const xInput = document.getElementById(xInputId);
        const yInput = document.getElementById(yInputId);
        if (xInput && yInput) {
            xInput.value = whiteData.x.toFixed(4);
            yInput.value = whiteData.y.toFixed(4);
            updateStatus(t('已填入白点坐标: x={whiteData_x_toFixed_4}, y={whiteData_y_toFixed_4}', {whiteData_x_toFixed_4: whiteData.x.toFixed(4), whiteData_y_toFixed_4: whiteData.y.toFixed(4)}));
        }
    } else {
        updateStatus(t('未找到白色测量数据，请先测量白色色块'));
    }
}

// ========== 统一导出弹窗 ==========

/**
 * 显示统一导出弹窗
 * 自动识别当前测量模式并定位到对应标签页
 */
function showExportModal() {
    // 移除数据检查，允许用户随时打开导出窗口使用校准数据
    // 校准数据可以在导出时选择使用

    // 根据当前测量模式定位标签页
    switchExportTab(currentMeasureMode);

    // 设置默认文件名和路径
    updateExportFileName();

    const filePathInput = document.getElementById('export-file-path');

    // 如果路径栏为空，设置默认路径（项目的 measurements 目录）
    if (filePathInput && !filePathInput.value) {
        // 默认文件名会在 updateExportFileName 中设置到路径栏
    }

    // 显示弹窗
    document.getElementById('export-modal-overlay').classList.add('show');
    updateStatus(t('导出文件选项'));

    // 加载校准数据列表
    loadCalibrationList();
}

/**
 * 显示导出状态提示
 */
function showExportStatus(format, message) {
    const statusArea = document.getElementById('export-status-area');
    const statusTitle = document.getElementById('export-status-title');
    const statusMessage = document.getElementById('export-status-message');

    if (statusArea && statusTitle && statusMessage) {
        statusTitle.textContent = t('正在制作 {format_toUpperCase} 文件...', {format_toUpperCase: format.toUpperCase()});
        statusMessage.textContent = message;
        statusArea.style.display = 'flex';
    }
}

/**
 * 隐藏导出状态提示
 */
function hideExportStatus() {
    const statusArea = document.getElementById('export-status-area');
    if (statusArea) {
        statusArea.style.display = 'none';
    }
}

/**
 * 禁用/启用导出弹窗按钮
 */
function disableExportModalButtons(disabled) {
    const cancelBtn = document.getElementById('export-modal-cancel');
    const createBtn = document.getElementById('export-modal-create');

    if (cancelBtn) cancelBtn.disabled = disabled;
    if (createBtn) {
        createBtn.disabled = disabled;
        createBtn.textContent = disabled ? t('制作中...') : t('导出文件');
    }
}

/**
 * 加载测量数据列表
 */
function loadCalibrationList() {
    if (!backend) return;

    console.log('[loadCalibrationList] 开始加载测量数据列表...');

    // 获取所有测量数据（包括 ICC、LUT、gamut、dispcal 等）
    if (backend.get_measurement_list) {
        backend.get_measurement_list((resultJson) => {
            console.log('[loadCalibrationList] 收到后端响应:', resultJson?.substring(0, 200));
            try {
                const result = JSON.parse(resultJson);
                console.log('[loadCalibrationList] 解析结果:', result);
                const measurements = result.measurements || [];
                console.log(`[loadCalibrationList] 测量数据数量: ${measurements.length}`);
                if (measurements.length > 0) {
                    console.log('[loadCalibrationList] 第一条数据:', measurements[0]);
                }
                populateMeasurementSelect('icc', measurements);
                populateMeasurementSelect('lut', measurements);
                updateStatus(t('已加载 {measurements_length} 条测量数据', {measurements_length: measurements.length}));
            } catch (e) {
                console.error('解析测量数据列表失败:', e);
                console.error('原始响应:', resultJson);
                updateStatus(t('加载测量数据列表失败'));
            }
        });
    } else {
        console.error('[loadCalibrationList] backend.get_measurement_list 不存在');
    }
}

/**
 * 填充测量数据选择框（用于 ICC/LUT 导出时选择已有的测量数据）
 * @param {string} exportType - 导出类型 ('icc' 或 'lut')
 * @param {Array} measurements - 测量数据列表
 */
function populateMeasurementSelect(exportType, measurements) {
    const selectId = `${exportType}-measurement-select`;
    let select = document.getElementById(selectId);

    console.log(`[populateMeasurementSelect] ${exportType}: 开始填充，select元素=`, select);
    console.log(`[populateMeasurementSelect] ${exportType}: 测量数据=`, measurements);

    if (!select) {
        console.error(`找不到选择框: ${selectId}`);
        return;
    }

    // 清空现有选项
    select.innerHTML = '';

    if (!measurements || measurements.length === 0) {
        const option = document.createElement('option');
        option.text = '暂无测量数据';
        option.disabled = true;
        select.add(option);
        console.log(`[populateMeasurementSelect] ${exportType}: 无测量数据`);
        return;
    }

    console.log(`[populateMeasurementSelect] ${exportType}: 找到 ${measurements.length} 条数据`);

    // 根据导出类型过滤数据
    let filteredMeasurements = measurements;
    if (exportType === 'icc') {
        // ICC导出：只显示ICC类型的数据
        filteredMeasurements = measurements.filter(m => m.measure_mode === 'icc');
        console.log(`[populateMeasurementSelect] ICC: 过滤后剩余 ${filteredMeasurements.length} 条ICC数据`);
    } else if (exportType === 'lut') {
        // LUT导出：显示LUT和ICC类型的数据
        filteredMeasurements = measurements.filter(m => m.measure_mode === 'lut' || m.measure_mode === 'icc');
        console.log(`[populateMeasurementSelect] LUT: 过滤后剩余 ${filteredMeasurements.length} 条LUT/ICC数据`);
    }

    if (filteredMeasurements.length === 0) {
        const option = document.createElement('option');
        option.text = '无符合类型的测量数据';
        option.disabled = true;
        select.add(option);
        console.log(`[populateMeasurementSelect] ${exportType}: 无符合类型的测量数据`);
        return;
    }

    // 添加默认选项
    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.text = '-- 请选择测量数据 --';
    select.add(defaultOption);

    // 添加测量数据选项
    filteredMeasurements.forEach(meas => {
        const option = document.createElement('option');
        // 只存储路径信息，不存储整个对象（避免超出value长度限制）
        option.value = JSON.stringify({
            json_path: meas.json_path,
            ti3_path: meas.ti3_path,
            measure_mode: meas.measure_mode
        });
        // 使用 name 字段作为显示名称，如果没有则使用文件名
        option.text = meas.name || meas.filename || meas.measure_mode;
        select.add(option);
        console.log(`[populateMeasurementSelect] ${exportType}: 添加选项 "${option.text}" (模式: ${meas.measure_mode})`);
    });

    // 默认选择最新的测量数据
    if (filteredMeasurements.length > 0) {
        const latest = filteredMeasurements[0];
        // 使用 selectedIndex 而不是直接设置 value，更可靠
        select.selectedIndex = 1;  // 0 是默认选项，1 是第一条数据

        // 存储选中的数据供后续使用（使用简化格式，与手动选择时一致）
        if (!window.exportData) {
            window.exportData = {};
        }
        if (!window.exportData[exportType]) {
            window.exportData[exportType] = {};
        }
        // 存储简化的数据（只包含路径），与 handleMeasurementChange 中的格式一致
        window.exportData[exportType].selectedMeasurement = {
            json_path: latest.json_path,
            ti3_path: latest.ti3_path,
            cal_path: latest.cal_path,
            measure_mode: latest.measure_mode
        };

        console.log(`[populateMeasurementSelect] ${exportType}: 默认选择`, latest.name || latest.filename);
    }

    // 添加事件监听
    select.removeEventListener('change', handleMeasurementChange);
    select.addEventListener('change', handleMeasurementChange);
}

/**
 * 处理测量数据选择变化
 */
function handleMeasurementChange(e) {
    const exportType = e.target.id.includes('icc') ? 'icc' : 'lut';
    const selectedValue = e.target.value;

    if (selectedValue) {
        try {
            const meas = JSON.parse(selectedValue);

            // 存储选中的数据供后续使用
            if (!window.exportData) {
                window.exportData = {};
            }
            if (!window.exportData[exportType]) {
                window.exportData[exportType] = {};
            }
            // 存储简化的数据（只包含路径）
            window.exportData[exportType].selectedMeasurement = meas;

            // 取消"使用当前测量"复选框
            const checkbox = document.getElementById(`${exportType}-use-current-measurement`);
            if (checkbox) {
                checkbox.checked = false;
            }

            console.log(`[handleMeasurementChange] ${exportType}: 选择了测量数据`, meas);
        } catch (err) {
            console.error('解析测量数据失败:', err);
        }
    }
}

/**
 * 填充校准数据选择框（已废弃，保留用于兼容）
 * @param {string} exportType - 导出类型 ('icc' 或 'lut')
 * @param {Array} calibrations - 校准数据列表
 * @param {Object} latest - 最新的校准数据
 */
function populateCalibrationSelect(exportType, calibrations, latest) {
    // 此函数已废弃，不再使用
    // 所有数据统一通过 populateMeasurementSelect 处理
}

/**
 * 处理校准数据选择变化（已废弃，保留用于兼容）
 */
function handleCalibrationChange(e) {
    // 此函数已废弃，不再使用
}

/**
 * 检查当前是否有测量数据
 * @returns {boolean} 是否有可用的当前测量数据
 */
function hasCurrentMeasurementData() {
    // 检查是否有 gamut 或 gamma 测量数据
    return (currentMeasurements && currentMeasurements.gamut && Object.keys(currentMeasurements.gamut).length > 0) ||
           (currentMeasurements && currentMeasurements.gamma && currentMeasurements.gamma.length > 0);
}

/**
 * 获取选中的测量数据
 * @param {string} exportType - 导出类型 ('icc' 或 'lut')
 * @returns {Object|null} 选中的测量数据（包含 json_path 或 ti3_path）
 */
function getSelectedCalibration(exportType) {
    const useCurrentCheckbox = document.getElementById(`${exportType}-use-current-measurement`);

    // 如果勾选了"使用当前测量"，返回 null
    if (useCurrentCheckbox && useCurrentCheckbox.checked) {
        return null;
    }

    // 从 window.exportData 获取选中的数据
    if (window.exportData && window.exportData[exportType] && window.exportData[exportType].selectedMeasurement) {
        return window.exportData[exportType].selectedMeasurement;
    }

    // 兼容旧方式：直接从select元素获取
    const select = document.getElementById(`${exportType}-measurement-select`);
    if (!select || !select.value) {
        return null;
    }

    try {
        return JSON.parse(select.value);
    } catch {
        return null;
    }
}

/**
 * 隐藏统一导出弹窗
 */
function hideExportModal() {
    document.getElementById('export-modal-overlay').classList.remove('show');
}

/**
 * 切换导出标签页
 * @param {string} mode - 测量模式 (gamut/icc/lut/custom/ccmx)
 */
function switchExportTab(mode) {
    // 更新当前导出模式（用于文件对话框）
    currentExportMode = mode;

    // 更新标签页样式
    document.querySelectorAll('.export-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.exportMode === mode);
    });

    // 显示对应面板
    document.querySelectorAll('.export-panel').forEach(panel => {
        panel.classList.add('hidden');
    });

    const targetPanel = document.getElementById(`export-panel-${mode}`);
    if (targetPanel) {
        targetPanel.classList.remove('hidden');
    }

    // 更新默认文件名
    updateExportFileName();
}

/**
 * 根据当前选中的标签页和格式更新默认文件名
 */
function updateExportFileName() {
    const activeTab = document.querySelector('.export-tab.active');
    const mode = activeTab?.dataset.exportMode || 'gamut';
    const timestamp = new Date().toISOString().slice(0, 10);
    const filePathInput = document.getElementById('export-file-path');

    // 获取当前选中的格式 - 使用 select 而非 radio
    const formatSelect = document.getElementById(`${mode}-export-format`);
    const format = formatSelect?.value || 'ti3';

    console.log(`[updateExportFileName] mode=${mode}, format=${format}`);

    // 格式扩展名映射
    const extMap = {
        'ti3': '.ti3',
        'csv': '.csv',
        'json': '.json',
        'icc': '.icc',
        'cube': '.cube',
        '3dl': '.3dl',
        'mga': '.mga',
        'clf': '.clf',
        'ccmx': '.ccmx'
    };

    // 文件名前缀映射
    const prefixMap = {
        'gamut': 'measurement',
        'icc': 'display_profile',
        'lut': 'display_lut',
        'custom': 'custom_measurement',
        'ccmx': 'correction_matrix'
    };

    const prefix = prefixMap[mode] || 'export';
    const ext = extMap[format] || '.txt';
    const fileName = `${prefix}_${timestamp}${ext}`;

    // 更新路径栏（如果路径栏为空，设置默认文件名）
    if (filePathInput && !filePathInput.value) {
        filePathInput.value = fileName;
        filePathInput.placeholder = '选择保存路径或直接输入完整文件路径...';
    } else if (filePathInput && filePathInput.value) {
        // 如果已有路径，更新其文件名部分
        const currentPath = filePathInput.value;
        const dirSeparator = currentPath.includes('/') ? '/' : '\\';
        const parts = currentPath.split(dirSeparator);
        // 如果路径末尾看起来像文件名（有扩展名），则更新它
        const lastPart = parts[parts.length - 1];
        if (lastPart.includes('.')) {
            parts[parts.length - 1] = fileName;
            filePathInput.value = parts.join(dirSeparator);
        }
    }
}

/**
 * 初始化统一导出弹窗事件
 */
function initExportModalEvents() {
    const overlay = document.getElementById('export-modal-overlay');
    const closeBtn = document.getElementById('export-modal-close');
    const cancelBtn = document.getElementById('export-modal-cancel');
    const createBtn = document.getElementById('export-modal-create');
    const browseBtn = document.getElementById('export-browse-btn');

    // 关闭按钮
    closeBtn?.addEventListener('click', hideExportModal);
    cancelBtn?.addEventListener('click', hideExportModal);

    // 点击遮罩关闭
    overlay?.addEventListener('click', (e) => {
        if (e.target === overlay) {
            hideExportModal();
        }
    });

    // 浏览按钮 - 选择保存路径
    browseBtn?.addEventListener('click', () => {
        if (backend) {
            backend.browse_save_path('export');
        }
    });

    // 标签页切换
    document.querySelectorAll('.export-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            switchExportTab(tab.dataset.exportMode);
        });
    });

    // 格式选择变化时更新文件名 - 监听各格式的 select 元素
    const formatSelects = ['gamut-export-format', 'icc-export-format', 'lut-export-format', 'custom-export-format', 'ccmx-export-format'];
    formatSelects.forEach(selectId => {
        const select = document.getElementById(selectId);
        select?.addEventListener('change', () => {
            updateExportFileName();
        });
    });

    // ICC 导出 - 白点选择切换
    const iccExportWhitePoint = document.getElementById('icc-export-white-point');
    const iccExportCustomWhiteRow = document.getElementById('icc-export-custom-white-row');
    iccExportWhitePoint?.addEventListener('change', (e) => {
        if (e.target.value === 'custom') {
            iccExportCustomWhiteRow?.classList.remove('hidden');
        } else {
            iccExportCustomWhiteRow?.classList.add('hidden');
        }
    });

    // ICC 导出 - 从测量填入白点
    document.getElementById('btn-icc-export-fill-white')?.addEventListener('click', () => {
        fillWhiteFromMeasurement('icc-export-white-x', 'icc-export-white-y');
    });

    // ICC 导出 - 格式切换显示不同参数面板
    const iccExportFormat = document.getElementById('icc-export-format');
    iccExportFormat?.addEventListener('change', (e) => {
        const iccParams = document.getElementById('icc-export-params-section');
        const ti3Params = document.getElementById('icc-export-ti3-section');
        if (e.target.value === 'icc') {
            iccParams?.classList.remove('hidden');
            ti3Params?.classList.add('hidden');
        } else {
            iccParams?.classList.add('hidden');
            ti3Params?.classList.remove('hidden');
        }
        updateExportFileName();
    });

    // 刷新校准数据列表按钮
    const refreshBtn = document.getElementById('btn-refresh-cal-list');
    const refreshBtnLut = document.getElementById('btn-refresh-cal-list-lut');

    const handleRefresh = () => {
        updateStatus(t('正在刷新测量数据列表...'));
        loadCalibrationList();
    };

    refreshBtn?.addEventListener('click', handleRefresh);
    refreshBtnLut?.addEventListener('click', handleRefresh);

    // ICC 使用当前测量复选框
    document.getElementById('icc-use-current-measurement')?.addEventListener('change', (e) => {
        if (e.target.checked) {
            document.getElementById('icc-measurement-select').value = '';
        }
    });

    // LUT 使用当前测量复选框
    document.getElementById('lut-use-current-measurement')?.addEventListener('change', (e) => {
        if (e.target.checked) {
            document.getElementById('lut-measurement-select').value = '';
        }
    });

    // LUT 导出方式切换
    const lutExportMethod = document.getElementById('lut-export-method');
    lutExportMethod?.addEventListener('change', (e) => {
        const advancedOptions = document.getElementById('lut-advanced-options');
        if (e.target.value === 'advanced') {
            advancedOptions?.classList.remove('hidden');
        } else {
            advancedOptions?.classList.add('hidden');
        }
    });

    // 导出按钮
    createBtn?.addEventListener('click', () => {
        executeExport();
    });
}

/**
 * 应用界面外观（暗房模式 / 字体缩放，存于 localStorage）
 */
function applyUiAppearance() {
    document.body.classList.toggle('dark-room', localStorage.getItem('ui-dark-room') === '1');
    const scale = localStorage.getItem('ui-font-scale') || 'normal';
    document.body.classList.toggle('large-font', scale === 'large');
    document.body.classList.toggle('xlarge-font', scale === 'xlarge');
    // zoom 改变布局后图表需要重排
    if (typeof resizeCharts === 'function') setTimeout(resizeCharts, 150);
}

// 启动即应用外观偏好（脚本在 body 末尾加载，DOM 已就绪）
applyUiAppearance();

/**
 * 初始化界面外观控件（偏好设置弹窗内）
 */
function initUiAppearanceControls() {
    const darkCheckbox = document.getElementById('prefs-dark-room');
    const fontSelect = document.getElementById('prefs-font-scale');
    if (darkCheckbox) {
        darkCheckbox.checked = localStorage.getItem('ui-dark-room') === '1';
        darkCheckbox.addEventListener('change', function() {
            localStorage.setItem('ui-dark-room', this.checked ? '1' : '0');
            applyUiAppearance();
        });
    }
    if (fontSelect) {
        fontSelect.value = localStorage.getItem('ui-font-scale') || 'normal';
        fontSelect.addEventListener('change', function() {
            localStorage.setItem('ui-font-scale', this.value);
            applyUiAppearance();
        });
    }
}

/**
 * 初始化偏好设置弹窗事件
 */
function initPreferencesModalEvents() {
    const overlay = document.getElementById('preferences-modal-overlay');
    const closeBtn = document.getElementById('preferences-modal-close');
    const okBtn = document.getElementById('preferences-modal-ok');

    // 界面外观（暗房模式 / 字体缩放）
    initUiAppearanceControls();

    // 通用 / 测量默认参数：偏好设置作为集中管理入口。
    // 修改后写入对应功能控件并触发 change 事件（复用既有后端同步逻辑），
    // 打开弹窗时由 showPreferencesModal 反向读取当前值。
    bindPrefsMirror('prefs-probe-type', 'probe-type');
    bindPrefsMirror('prefs-display-type', 'display-type');
    bindPrefsMirror('prefs-measure-delay', 'measure-delay');
    bindPrefsMirror('prefs-measure-repeat-count', 'measure-repeat-count');
    bindPrefsMirror('prefs-dark-sample-enabled', 'dark-sample-enabled');

    // 界面语言
    const prefsLang = document.getElementById('prefs-language');
    prefsLang?.addEventListener('change', function() {
        if (typeof switchLanguage === 'function') switchLanguage(this.value);
    });

    // 启动时自动连接探头（持久化在 localStorage，启动逻辑读取）
    const autoConn = document.getElementById('prefs-auto-connect-probe');
    autoConn?.addEventListener('change', function() {
        try {
            localStorage.setItem('topos.autoConnectProbe', this.checked ? '1' : '0');
        } catch (e) { /* 忽略存储失败 */ }
        updateStatus(this.checked
            ? t('已启用：启动时后台自动连接探头')
            : t('已关闭：启动时自动连接探头，需手动连接'));
    });

    // 关闭按钮
    closeBtn?.addEventListener('click', hidePreferencesModal);
    okBtn?.addEventListener('click', hidePreferencesModal);

    // 点击遮罩关闭
    overlay?.addEventListener('click', (e) => {
        if (e.target === overlay) {
            hidePreferencesModal();
        }
    });

    // ========== 自动保存设置 ==========
    // 自动保存开关
    autoSaveEnabled = document.getElementById('prefs-auto-save-enabled');
    if (autoSaveEnabled) {
        autoSaveEnabled.addEventListener('change', function() {
            if (!backend) return;
            backend.enable_auto_save(this.checked);
            updateStatus(this.checked ? t('自动保存已启用') : t('自动保存已禁用'));
        });
    }

    // 自动保存路径
    autoSavePath = document.getElementById('prefs-auto-save-path');
    const browseAutoSaveBtn = document.getElementById('prefs-browse-auto-save');
    if (autoSavePath && browseAutoSaveBtn) {
        browseAutoSaveBtn.addEventListener('click', function() {
            if (!backend) return;
            backend.browse_save_path('auto_save');
        });

        autoSavePath.addEventListener('change', function() {
            if (!backend) return;
            const path = this.value.trim() || 'measurements/auto_save';
            backend.set_auto_save_path(path);
            updateStatus(t('自动保存目录: {path}', {path: path}));
        });
    }

    // ========== Web测量服务器端口设置 ==========
    const webServerPort = document.getElementById('prefs-web-server-port');
    if (webServerPort) {
        webServerPort.addEventListener('change', function() {
            if (!backend) return;
            const port = parseInt(this.value) || 8080;
            if (port >= 1024 && port <= 65535) {
                backend.set_web_measurement_port(port);
                updateStatus(t('Web测量服务器端口: {port}', {port: port}));
                if (webMeasurementServerRunning) {
                    // 服务运行中改端口：重启使新端口生效
                    backend.stop_web_measurement_server();
                    backend.start_web_measurement_server();
                }
            } else {
                updateStatus(t('端口号必须在 1024-65535 之间'));
            }
        });
    }

    // Web测量服务开关
    const webServerEnabled = document.getElementById('prefs-web-server-enabled');
    if (webServerEnabled) {
        webServerEnabled.addEventListener('change', function() {
            if (!backend) return;
            if (this.checked) {
                updateStatus(t('正在启动Web测量服务器...'));
                backend.start_web_measurement_server();
            } else {
                backend.stop_web_measurement_server();
            }
        });
    }

    // 一键复制服务地址
    const copyWebUrlBtn = document.getElementById('prefs-copy-web-url');
    if (copyWebUrlBtn) {
        copyWebUrlBtn.addEventListener('click', function() {
            const urlInput = document.getElementById('prefs-web-server-url');
            const url = urlInput ? urlInput.value.trim() : '';
            if (!url) return;
            const done = function(ok) {
                if (ok) {
                    updateStatus(t('已复制服务地址: {url}', {url: url}));
                    copyWebUrlBtn.textContent = t('已复制');
                    setTimeout(function() {
                        copyWebUrlBtn.textContent = t('复制');
                    }, 2000);
                } else {
                    updateStatus(t('复制失败，请手动选择地址复制'));
                }
            };
            // 后台窗口无焦点时 JS 剪贴板 API 不可靠，优先走 Qt 原生剪贴板
            if (backend && typeof backend.copy_to_clipboard === 'function') {
                try {
                    backend.copy_to_clipboard(url);
                    done(true);
                } catch (e) {
                    copyTextToClipboard(url).then(done);
                }
            } else {
                copyTextToClipboard(url).then(done);
            }
        });
    }

    // ========== 色彩管理高级选项 ==========
    const autoClearLut = document.getElementById('prefs-auto-clear-lut');
    const useNullProfile = document.getElementById('prefs-use-null-profile');

    if (autoClearLut) {
        autoClearLut.addEventListener('change', function() {
            if (!backend) return;
            backend.set_auto_clear_lut(this.checked);
            updateStatus(this.checked ? t('自动清除ICC已启用') : t('自动清除ICC已禁用'));
        });
    }

    if (useNullProfile) {
        useNullProfile.addEventListener('change', function() {
            if (!backend) return;
            backend.set_use_null_profile_for_measurement(this.checked);
            updateStatus(this.checked ? t('Null Profile已启用') : t('Null Profile已禁用'));
        });
    }

    // 加载当前自动保存状态
    if (backend) {
        backend.get_auto_save_status().then(function(statusJson) {
            try {
                const status = JSON.parse(statusJson);
                if (document.getElementById('prefs-auto-save-enabled')) {
                    document.getElementById('prefs-auto-save-enabled').checked = status.enabled;
                }
                if (document.getElementById('prefs-auto-save-path')) {
                    document.getElementById('prefs-auto-save-path').value = status.base_dir || 'measurements/auto_save';
                }
            } catch (e) {
                console.error('解析自动保存状态失败:', e);
            }
        }).catch(function(e) {
            console.error('获取自动保存状态失败:', e);
        });

        // 加载Web测量服务器端口
        if (document.getElementById('prefs-web-server-port')) {
            document.getElementById('prefs-web-server-port').value = backend.get_web_measurement_port();
        }

        // 加载色彩管理高级选项状态
        backend.get_color_management_status().then(function(statusJson) {
            try {
                const status = JSON.parse(statusJson);
                if (autoClearLut) autoClearLut.checked = status.auto_clear_lut || false;
                if (useNullProfile) useNullProfile.checked = status.use_null_profile || false;
            } catch (e) {
                console.error('解析色彩管理状态失败:', e);
            }
        }).catch(function(e) {
            console.error('获取色彩管理状态失败:', e);
        });
    }
}

/**
 * 显示偏好设置弹窗
 */
/**
 * 偏好设置镜像控件：prefs 值变化时写入目标控件并触发其 change 事件，
 * 使偏好设置成为全局参数的集中管理入口（后端同步由目标控件既有逻辑完成）
 */
function bindPrefsMirror(prefsId, targetId) {
    const prefsEl = document.getElementById(prefsId);
    const targetEl = document.getElementById(targetId);
    if (!prefsEl || !targetEl) return;

    prefsEl.addEventListener('change', function() {
        if (String(targetEl.value) === String(this.value)) return;
        targetEl.value = this.value;
        targetEl.dispatchEvent(new Event('change'));
    });
}

/**
 * 打开偏好设置时，把各功能控件的当前值回填到镜像控件
 */
function populatePrefsMirrorControls() {
    const pairs = [
        ['prefs-probe-type', 'probe-type'],
        ['prefs-display-type', 'display-type'],
        ['prefs-measure-delay', 'measure-delay'],
        ['prefs-measure-repeat-count', 'measure-repeat-count'],
        ['prefs-dark-sample-enabled', 'dark-sample-enabled'],
    ];
    pairs.forEach(([prefsId, targetId]) => {
        const prefsEl = document.getElementById(prefsId);
        const targetEl = document.getElementById(targetId);
        if (prefsEl && targetEl) prefsEl.value = targetEl.value;
    });

    // 界面语言
    const prefsLang = document.getElementById('prefs-language');
    if (prefsLang && window.I18N) prefsLang.value = I18N.getLanguage();

    // 启动自动连接探头
    const autoConn = document.getElementById('prefs-auto-connect-probe');
    if (autoConn) {
        let enabled = true;
        try { enabled = localStorage.getItem('topos.autoConnectProbe') !== '0'; } catch (e) { /* 默认开 */ }
        autoConn.checked = enabled;
    }
}

function showPreferencesModal() {
    if (!backend) return;

    // 初始化事件（如果尚未初始化）
    if (!window._preferencesModalInitialized) {
        initPreferencesModalEvents();
        window._preferencesModalInitialized = true;
    }

    // 回填当前值（每次打开都刷新，保证与功能面板一致）
    populatePrefsMirrorControls();

    // 显示弹窗
    document.getElementById('preferences-modal-overlay').classList.add('show');
    // 同步 Web 测量服务的真实运行状态
    refreshWebServerStatus();
    updateStatus(t('偏好设置'));
}

/**
 * 隐藏偏好设置弹窗
 */
function hidePreferencesModal() {
    document.getElementById('preferences-modal-overlay').classList.remove('show');
}

/**
 * 执行导出操作
 */
function executeExport() {
    if (!backend) {
        updateStatus(t('错误: 后端未连接'));
        return;
    }

    const activeTab = document.querySelector('.export-tab.active');
    const mode = activeTab?.dataset.exportMode || 'gamut';
    const filePath = document.getElementById('export-file-path')?.value || '';

    // 从路径中提取文件名（如果路径包含文件名）
    let fileName = 'export';
    if (filePath) {
        const dirSeparator = filePath.includes('/') ? '/' : '\\';
        const parts = filePath.split(dirSeparator);
        const lastPart = parts[parts.length - 1];
        if (lastPart && lastPart.includes('.')) {
            fileName = lastPart;
        }
    }

    switch (mode) {
        case 'gamut':
            exportGamutData(filePath, fileName);
            break;
        case 'icc':
            exportICCData(filePath, fileName);
            break;
        case 'lut':
            exportLUTData(filePath, fileName);
            break;
        case 'custom':
            exportCustomData(filePath, fileName);
            break;
        case 'ccmx':
            exportCCMXData(filePath, fileName);
            break;
    }
}

/**
 * 导出色彩空间数据
 */
function exportGamutData(filePath, fileName) {
    const format = document.getElementById('gamut-export-format')?.value || 'ti3';

    if (format === 'ti3') {
        backend.export_measurement_ti3(fileName);
    } else if (format === 'csv' || format === 'json') {
        const params = {
            format: format,
            file_path: filePath,
            file_name: fileName,
            include_gamut: document.getElementById('gamut-export-gamut')?.checked || true,
            include_gamma: document.getElementById('gamut-export-gray')?.checked || true
        };
        backend.export_measurement(JSON.stringify(params));
    }

    hideExportModal();
    updateStatus(t('正在导出 {format_toUpperCase} 文件...', {format_toUpperCase: format.toUpperCase()}));
}

/**
 * 导出 ICC 数据
 */
function exportICCData(filePath, fileName) {
    const format = document.getElementById('icc-export-format')?.value || 'icc';
    const whitePoint = document.getElementById('icc-export-white-point')?.value || 'D65';

    // 获取选中的校准数据
    const selectedCal = getSelectedCalibration('icc');

    // 验证：如果没有选中校准数据且当前没有测量数据，提示用户
    if (!selectedCal && !hasCurrentMeasurementData()) {
        updateStatus(t('请先进行测量或选择历史测量数据'));
        return;
    }

    const params = {
        format: format,
        file_path: filePath,
        file_name: fileName,
        profile_type: document.getElementById('icc-export-profile-type')?.value || 'lut',
        quality: document.getElementById('icc-export-quality')?.value || 'h',
        white_point: whitePoint,
        gamma: document.getElementById('icc-export-gamma')?.value || '2.2',
        black_compensation: document.getElementById('icc-export-black-compensation')?.checked || false,
        apply_profile: document.getElementById('icc-export-apply-profile')?.checked || false,  // 应用ICC选项
        include_gamut: document.getElementById('icc-export-ti3-gamut')?.checked || true,
        include_gamma: document.getElementById('icc-export-ti3-gray')?.checked || true
    };

    // 添加校准数据路径（支持新旧两种格式）
    if (selectedCal) {
        // 旧格式：cal_path, ti3_path, json_path
        // 新格式：json_path, ti3_path（可能只有其中一个）
        if (selectedCal.cal_path) {
            params.cal_path = selectedCal.cal_path;
        }
        if (selectedCal.ti3_path) {
            params.ti3_path = selectedCal.ti3_path;
        }
        if (selectedCal.json_path) {
            params.json_path = selectedCal.json_path;
        }

        console.log('[exportICCData] 使用选中的测量数据:', selectedCal);
    } else {
        console.log('[exportICCData] 使用当前测量数据');
    }

    if (whitePoint === 'custom') {
        const customX = document.getElementById('icc-export-white-x')?.value;
        const customY = document.getElementById('icc-export-white-y')?.value;
        if (customX && customY) {
            params.custom_white_x = parseFloat(customX);
            params.custom_white_y = parseFloat(customY);
        }
    }

    // 显示导出状态，不关闭弹窗
    const applyMsg = params.apply_profile ? ' (将自动安装并应用)' : '';
    showExportStatus('ICC', '这可能需要几分钟时间，请耐心等待...' + applyMsg);
    disableExportModalButtons(true);

    backend.create_icc_file(JSON.stringify(params));
}

/**
 * 导出 LUT 数据
 */
function exportLUTData(filePath, fileName) {
    const format = document.getElementById('lut-export-format')?.value || 'cube';
    const exportMethod = document.getElementById('lut-export-method')?.value || 'fast';

    // 获取选中的校准数据
    const selectedCal = getSelectedCalibration('lut');

    // 验证：如果没有选中校准数据且当前没有测量数据，提示用户
    if (!selectedCal && !hasCurrentMeasurementData()) {
        updateStatus(t('请先进行测量或选择历史测量数据'));
        return;
    }

    const params = {
        format: format,
        file_path: filePath,
        file_name: fileName,
        lut_size: document.getElementById('lut-export-size')?.value || '33',
        quality: document.getElementById('lut-export-quality')?.value || 'h',
        target_gamut: document.getElementById('lut-export-gamut')?.value || 'sRGB',
        target_gamma: document.getElementById('lut-export-gamma')?.value || '2.2',
        interpolation: document.getElementById('lut-export-interpolation')?.value || 'trilinear',
        input_range: document.getElementById('lut-export-input-range')?.value || 'full',
        export_method: exportMethod  // 'fast' 或 'advanced'
    };

    // 添加校准数据路径（支持新旧两种格式）
    if (selectedCal) {
        // 旧格式：cal_path, ti3_path, json_path
        // 新格式：json_path, ti3_path（可能只有其中一个）
        if (selectedCal.cal_path) {
            params.cal_path = selectedCal.cal_path;
        }
        if (selectedCal.ti3_path) {
            params.ti3_path = selectedCal.ti3_path;
        }
        if (selectedCal.json_path) {
            params.json_path = selectedCal.json_path;
        }

        console.log('[exportLUTData] 使用选中的测量数据:', selectedCal);
    } else {
        console.log('[exportLUTData] 使用当前测量数据');
    }

    // 高级模式额外参数
    if (exportMethod === 'advanced') {
        params.source_gamut = document.getElementById('lut-source-gamut')?.value || 'Rec709';
        params.rendering_intent = document.getElementById('lut-rendering-intent')?.value || 'r';
        params.use_bpc = document.getElementById('lut-export-use-bpc')?.checked ?? true;
    }

    // 显示导出状态，不关闭弹窗
    showExportStatus('LUT', `这可能需要几分钟时间，请耐心等待... (${exportMethod === 'fast' ? '快速模式' : '高级模式'})`);
    disableExportModalButtons(true);

    backend.create_lut_file(JSON.stringify(params));
}

/**
 * 导出自定义颜色数据
 */
function exportCustomData(filePath, fileName) {
    const format = document.getElementById('custom-export-format')?.value || 'csv';

    const params = {
        format: format,
        file_path: filePath,
        file_name: fileName,
        include_gamut: true,
        include_gamma: true
    };

    backend.export_measurement(JSON.stringify(params));
    hideExportModal();
    updateStatus(t('正在导出 {format_toUpperCase} 文件...', {format_toUpperCase: format.toUpperCase()}));
}

/**
 * 导出 CCMX 数据
 */
function exportCCMXData(filePath, fileName) {
    const format = document.getElementById('ccmx-export-format')?.value || 'ccmx';

    const params = {
        format: format,
        file_path: filePath,
        file_name: fileName
    };

    backend.export_measurement(JSON.stringify(params));
    hideExportModal();
    updateStatus(t('正在导出 {format_toUpperCase} 文件...', {format_toUpperCase: format.toUpperCase()}));
}

/**
 * 获取校准参数（支持 radio button 选择）
 * @param {string} mode - 'icc' 或 'lut'
 * @returns {object} 包含 source 和相应参数的对象
 *   - source: 'calibrate' | 'load' | 'none'
 *   - calibrate 模式: 包含 white_point, gamma, quality
 *   - load 模式: 包含 cal_file 路径
 */
function getCalibrationParams(mode) {
    // 检查 radio button 选择状态
    const calibrateRadio = document.getElementById(`${mode}-enable-calibration`);
    const loadRadio = document.getElementById(`${mode}-load-cal-file`);

    // 确定校准源
    let source = 'none';
    if (calibrateRadio?.checked) {
        source = 'calibrate';
    } else if (loadRadio?.checked) {
        source = 'load';
    }

    const params = { source };

    if (source === 'calibrate') {
        // dispcal 校准参数
        const whitePoint = document.getElementById(`${mode}-cal-white-point`)?.value || 'D65';
        const gamma = document.getElementById(`${mode}-cal-gamma`)?.value || '2.2';
        const quality = document.getElementById(`${mode}-cal-quality`)?.value || 'm';

        params.white_point = whitePoint;
        params.gamma = parseFloat(gamma);
        params.quality = quality;

        if (whitePoint === 'custom') {
            const customX = document.getElementById(`${mode}-cal-white-x`)?.value;
            const customY = document.getElementById(`${mode}-cal-white-y`)?.value;
            if (customX && customY) {
                params.custom_white_x = parseFloat(customX);
                params.custom_white_y = parseFloat(customY);
            }
        }
    } else if (source === 'load') {
        // 加载已有 .cal 文件
        const calFileSelect = document.getElementById(`${mode}-cal-file-select`);
        const calFile = calFileSelect?.value || '';
        params.cal_file = calFile;
    }

    return params;
}

// ========== Tooltip 智能定位系统 ==========

/**
 * 创建全局 tooltip 容器
 */
(function initTooltipContainer() {
    const tooltipEl = document.createElement('div');
    tooltipEl.className = 'tooltip-container';
    tooltipEl.id = 'global-tooltip';
    
    const arrowEl = document.createElement('div');
    arrowEl.className = 'tooltip-arrow';
    tooltipEl.appendChild(arrowEl);
    
    document.body.appendChild(tooltipEl);
    
    // 将 tooltip 元素暴露到全局
    window.tooltipContainer = tooltipEl;
    window.tooltipArrow = arrowEl;
})();

/**
 * 解析 tooltip 文本，支持换行符 \n
 */
function parseTooltipText(text) {
    if (!text) return '';
    
    const lines = text.split('\n');
    if (lines.length === 1) return text;
    
    return lines.map(line => {
        // 处理强调文本（**文本** 或 *文本*）
        line = line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        line = line.replace(/\*(.+?)\*/g, '<strong>$1</strong>');
        return line;
    }).join('<br>');
}

/**
 * 显示 tooltip（智能定位）
 * @param {HTMLElement} targetEl - 目标元素
 * @param {string} text - tooltip 文本
 */
function showTooltip(targetEl, text) {
    const tooltip = window.tooltipContainer;
    const arrow = window.tooltipArrow;
    
    if (!tooltip || !text) return;
    
    // 设置内容
    tooltip.innerHTML = parseTooltipText(text) + arrow.outerHTML;
    tooltip.classList.add('visible');
    
    // 计算位置
    const rect = targetEl.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportHeight = window.innerHeight;
    const spaceAbove = rect.top;
    const spaceBelow = viewportHeight - rect.bottom;
    const tooltipHeight = tooltipRect.height || 100; // 估算高度
    
    // 智能判断：优先向上显示，如果空间不够则向下显示
    let position = 'top';
    if (spaceAbove < tooltipHeight + 20 && spaceBelow > tooltipHeight + 20) {
        position = 'bottom';
    }
    
    // 设置位置
    tooltip.classList.remove('tooltip-top', 'tooltip-bottom');
    tooltip.classList.add(position === 'top' ? 'tooltip-top' : 'tooltip-bottom');
    
    const centerX = rect.left + rect.width / 2;
    
    if (position === 'top') {
        tooltip.style.left = (centerX - tooltipRect.width / 2) + 'px';
        tooltip.style.top = (rect.top - tooltipRect.height - 8) + 'px';
    } else {
        tooltip.style.left = (centerX - tooltipRect.width / 2) + 'px';
        tooltip.style.top = (rect.bottom + 8) + 'px';
    }
    
    // 确保不超出左右边界
    const tooltipRect2 = tooltip.getBoundingClientRect();
    if (tooltipRect2.left < 10) {
        tooltip.style.left = (10) + 'px';
    }
    if (tooltipRect2.right > window.innerWidth - 10) {
        tooltip.style.left = (window.innerWidth - tooltipRect2.width - 10) + 'px';
    }
}

/**
 * 隐藏 tooltip
 */
function hideTooltip() {
    const tooltip = window.tooltipContainer;
    if (tooltip) {
        tooltip.classList.remove('visible');
    }
}

/**
 * 初始化所有 tooltip 事件
 */
function initTooltips() {
    // 为所有带有 data-tooltip 属性的元素添加事件监听
    const tooltipElements = document.querySelectorAll('[data-tooltip]');
    
    tooltipElements.forEach(el => {
        el.addEventListener('mouseenter', function() {
            const text = this.getAttribute('data-tooltip');
            showTooltip(this, text);
        });
        
        el.addEventListener('mouseleave', function() {
            hideTooltip();
        });
        
        el.addEventListener('focus', function() {
            const text = this.getAttribute('data-tooltip');
            showTooltip(this, text);
        });
        
        el.addEventListener('blur', function() {
            hideTooltip();
        });
    });
}

// 在 DOM 加载完成后初始化 tooltip
document.addEventListener('DOMContentLoaded', function() {
    // 延迟初始化，确保后端连接完成
    setTimeout(initTooltips, 500);
});

// ========== 预检相关变量和函数 (P3-C) ==========

// 预检状态
let preflightReport = null;
let preflightOverrideEnabled = false;
let preflightCheckInProgress = false;

/**
 * 处理预检开始信号
 */
function handlePreflightCheckStarted() {
    preflightCheckInProgress = true;
    updateStatus(t('正在执行环境预检...'));
    showPreflightProgressUI();
}

/**
 * 处理预检完成信号
 */
function handlePreflightCheckCompleted(resultJson) {
    preflightCheckInProgress = false;
    preflightReport = parsePayload(resultJson);

    console.log('预检完成:', preflightReport);

    // 更新 UI（引导模式：结果渲染到中列步骤工作区，跳过浮动面板避免双份显示）
    if (uiMode !== 'guided') {
        renderPreflightResults(preflightReport);
    } else {
        // 引导模式不经过 renderPreflightResults，需自行收起"预检进行中"浮动面板
        hidePreflightProgressUI();
    }

    // 集成向导更新
    if (typeof handlePreflightCompletedForWizard === 'function') {
        handlePreflightCompletedForWizard(resultJson);
    }

    // 检查是否有阻断项
    if (preflightReport.summary && preflightReport.summary.block_count > 0) {
        if (!preflightOverrideEnabled) {
            updateStatus(t('预检完成 - 发现阻断项，需修复或启用高级覆盖'));
            showPreflightBlockingDialog(preflightReport);
        } else {
            updateStatus(t('预检完成 - 阻断项已覆盖（高级模式）'));
        }
    } else if (preflightReport.summary && preflightReport.summary.warn_count > 0) {
        updateStatus(t('预检完成 - 发现警告项，建议检查'));
    } else {
        updateStatus(t('预检完成 - 所有检查通过'));
    }

    // 更新向导下一步按钮状态
    const btnNext = document.getElementById('btn-next-step-1');
    if (btnNext) {
        const canProceed = preflightReport.can_proceed;
        const hasBlock = preflightReport.summary?.block_count > 0;
        btnNext.disabled = !(canProceed || (hasBlock && preflightOverrideEnabled));
    }
}

/**
 * 处理预检进度信号
 */
function handlePreflightCheckProgress(progressJson) {
    const progress = parsePayload(progressJson);
    console.log('预检进度:', progress);

    // 更新进度 UI
    updatePreflightProgressUI(progress);
}

/**
 * 处理预检覆盖状态变化
 */
function handlePreflightOverrideChanged(enabled) {
    preflightOverrideEnabled = enabled;
    console.log('预检覆盖状态:', enabled);

    // 更新 UI
    const overrideCheckbox = document.getElementById('preflight-override-checkbox');
    if (overrideCheckbox) {
        overrideCheckbox.checked = enabled;
    }

    // 更新按钮状态
    updatePreflightUIState();
}

/**
 * 运行预检检查（前端触发）
 */
function runPreflightCheck() {
    if (!backend) {
        console.error('后端未连接');
        return;
    }

    if (preflightCheckInProgress) {
        console.log('预检正在进行中');
        return;
    }

    backend.run_preflight_check();
}

/**
 * 设置预检覆盖状态
 */
function setPreflightOverride(enabled) {
    if (!backend) {
        console.error('后端未连接');
        return;
    }

    backend.set_preflight_override(enabled);
}

/**
 * 导出预检报告
 */
function exportPreflightReport() {
    if (!backend) {
        console.error('后端未连接');
        return;
    }

    if (!preflightReport) {
        console.log('没有预检报告可导出');
        return;
    }

    // 请求文件保存路径
    const defaultPath = 'preflight_report_' + new Date().toISOString().slice(0, 10) + '.json';
    backend.select_save_path(defaultPath, 'json');
}

/**
 * 检查是否可以进行测量
 */
function canProceedWithMeasurement() {
    if (!backend) {
        return false;
    }

    // 如果预检未完成，不允许继续
    if (!preflightReport) {
        return false;
    }

    return preflightReport.can_proceed;
}

/**
 * 显示预检进度 UI
 */
function showPreflightProgressUI() {
    // 创建或显示预检进度容器
    let progressContainer = document.getElementById('preflight-progress-container');
    if (!progressContainer) {
        progressContainer = document.createElement('div');
        progressContainer.id = 'preflight-progress-container';
        progressContainer.className = 'preflight-progress';
        progressContainer.innerHTML = `
            <div class="preflight-progress-header">
                <span class="preflight-progress-icon">⏳</span>
                <span class="preflight-progress-title">环境预检进行中...</span>
            </div>
            <div class="preflight-progress-bar">
                <div class="preflight-progress-fill" id="preflight-progress-fill" style="width: 0%"></div>
            </div>
            <div class="preflight-progress-text" id="preflight-progress-text">正在检查...</div>
        `;
        document.body.appendChild(progressContainer);
    }

    progressContainer.style.display = 'block';
}

/**
 * 更新预检进度 UI
 */
function updatePreflightProgressUI(progress) {
    const fill = document.getElementById('preflight-progress-fill');
    const text = document.getElementById('preflight-progress-text');

    if (fill && text && progress) {
        const percent = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;
        fill.style.width = percent + '%';
        text.textContent = t('检查 {progress_current}/{progress_total}: {progress_item}', {progress_current: progress.current, progress_total: progress.total, progress_item: progress.item || '...'});
    }
}

/**
 * 隐藏预检进度 UI
 */
function hidePreflightProgressUI() {
    const progressContainer = document.getElementById('preflight-progress-container');
    if (progressContainer) {
        progressContainer.style.display = 'none';
    }
}

/**
 * 渲染预检结果
 */
function renderPreflightResults(report) {
    hidePreflightProgressUI();

    // 创建或获取预检结果容器
    let resultsContainer = document.getElementById('preflight-results-container');
    if (!resultsContainer) {
        resultsContainer = document.createElement('div');
        resultsContainer.id = 'preflight-results-container';
        resultsContainer.className = 'preflight-results';
        document.body.appendChild(resultsContainer);
    }

    // 构建结果 HTML
    let html = `
        <div class="preflight-results-header">
            <h3>环境预检结果</h3>
            <div class="preflight-summary">
                <span class="pass-count">✓ ${report.summary?.pass_count || 0} 通过</span>
                <span class="warn-count">⚠ ${report.summary?.warn_count || 0} 警告</span>
                <span class="block-count">✗ ${report.summary?.block_count || 0} 阻断</span>
                <span class="skip-count">○ ${report.summary?.skip_count || 0} 跳过</span>
            </div>
            <div class="preflight-actions">
                <button class="btn btn-secondary btn-sm" onclick="exportPreflightReport()">导出报告</button>
                <button class="btn btn-secondary btn-sm" onclick="runPreflightCheck()">重新检查</button>
                <label class="preflight-override-label">
                    <input type="checkbox" id="preflight-override-checkbox"
                           onchange="setPreflightOverride(this.checked)"
                           ${preflightOverrideEnabled ? 'checked' : ''}>
                    <span>高级覆盖（忽略阻断项）</span>
                </label>
            </div>
        </div>
        <div class="preflight-results-list">
    `;

    // 添加每个检查项的结果（检查项名称/消息按界面语言显示；后端输出为英文）
    if (report.results && report.results.length > 0) {
        for (const result of report.results) {
            const statusClass = getStatusClass(result.status);
            const statusIcon = getStatusIcon(result.status);
            const itemName = window.PREFLIGHT_I18N
                ? PREFLIGHT_I18N.translateItemName(result.item_id) : result.item_id;
            const itemMessage = window.PREFLIGHT_I18N
                ? PREFLIGHT_I18N.translateMessage(result.message) : result.message;

            html += `
                <div class="preflight-item ${statusClass}">
                    <span class="preflight-item-status">${statusIcon}</span>
                    <span class="preflight-item-name">${itemName}</span>
                    <span class="preflight-item-message">${itemMessage}</span>
                </div>
            `;
        }
    }

    html += '</div>';

    // 如果有阻断项，显示阻断提示
    if (report.summary?.block_count > 0 && !preflightOverrideEnabled) {
        html += `
            <div class="preflight-blocking-warning">
                <p>存在阻断项，需要修复以下问题才能继续测量：</p>
                <ul>
                    ${report.results.filter(r => r.status === 'BLOCK').map(r => {
                        const n = window.PREFLIGHT_I18N
                            ? PREFLIGHT_I18N.translateItemName(r.item_id) : r.item_id;
                        const m = window.PREFLIGHT_I18N
                            ? PREFLIGHT_I18N.translateMessage(r.message) : r.message;
                        return `<li>${n}: ${m}</li>`;
                    }).join('')}
                </ul>
                <p>或启用"高级覆盖"以忽略阻断项继续测量。</p>
            </div>
        `;
    }

    resultsContainer.innerHTML = html;
    resultsContainer.style.display = 'block';

    // 更新按钮状态
    updatePreflightUIState();
}

/**
 * 显示阻断项对话框
 */
function showPreflightBlockingDialog(report) {
    // 简单的阻断提示（可以用更优雅的 modal 替代）
    const blockingItems = report.results.filter(r => r.status === 'BLOCK');

    if (blockingItems.length > 0) {
        const lines = blockingItems.map(r => {
            const n = window.PREFLIGHT_I18N
                ? PREFLIGHT_I18N.translateItemName(r.item_id) : r.item_id;
            const m = window.PREFLIGHT_I18N
                ? PREFLIGHT_I18N.translateMessage(r.message) : r.message;
            return `• ${n}: ${m}`;
        }).join('\n');
        alert(t('预检发现阻断项:\n\n') + lines + t('\n\n请修复这些问题或启用高级覆盖后继续。'));
    }
}

/**
 * 更新预检 UI 状态
 * 预检在引导/高级两种模式下均为"建议项"：不再门控底部测量按钮
 * （引导模式的强制门控在向导步骤 1 的 validateStep / btn-next-step-1 中）。
 * 原实现引用了不存在的按钮 id（btn-measure-all / btn-start-cycle），实为死代码。
 */
function updatePreflightUIState() {
    // 无需操作：保留函数避免调用点报错
}

/**
 * 获取状态 CSS 类
 */
function getStatusClass(status) {
    switch (status) {
        case 'PASS': return 'status-pass';
        case 'WARN': return 'status-warn';
        case 'BLOCK': return 'status-block';
        case 'SKIP': return 'status-skip';
        case 'ERROR': return 'status-error';
        default: return '';
    }
}

/**
 * 获取状态图标
 */
function getStatusIcon(status) {
    switch (status) {
        case 'PASS': return '✓';
        case 'WARN': return '⚠';
        case 'BLOCK': return '✗';
        case 'SKIP': return '○';
        case 'ERROR': return '⚡';
        default: return '?';
    }
}

/**
 * 在开始测量前检查预检状态
 */
function checkPreflightBeforeMeasurement() {
    if (!preflightReport) {
        // 未预检，提示用户执行预检
        if (confirm(t('尚未执行环境预检。建议在测量前运行预检以确保环境正确。\n\n是否立即执行预检？'))) {
            runPreflightCheck();
            return false;  // 阻止测量，等待预检完成
        }
        // 用户选择不预检，允许继续（但可能不安全）
        return true;
    }

    if (!preflightReport.can_proceed) {
        // 预检未通过
        alert('预检发现阻断项，无法继续测量。\n请修复问题或启用高级覆盖。');
        return false;
    }

    return true;
}

// ==============================================================================
// P6-B 测量过程可视化 UI
// ==============================================================================

// 测量进度状态
const measurementProgressState = {
    isVisible: false,
    currentPatchIndex: 0,
    totalPatches: 0,
    currentPatch: null,
    measuredData: null,
    startTime: null,
    estimatedRemainingTime: null,
    skippedPatches: [],      // 跳过的色块列表
    errorInfo: null,         // 当前错误信息
    repeatabilityData: null, // 重复性数据
    measurementHistory: [],  // 测量历史（用于计算重复性）
    lastProgressUpdate: 0    // 上次进度更新时间
};

/**
 * 显示测量进度面板
 */
function showMeasurementProgressPanel() {
    // 创建或显示进度面板
    let panel = document.getElementById('measurement-progress-panel');
    if (!panel) {
        panel = createMeasurementProgressPanel();
        // 引导模式：内嵌到中列"步骤工作区"；高级/自由模式：浮动在页面上
        const wsContent = (uiMode === 'guided')
            ? document.getElementById('step-workspace-content')
            : null;
        if (wsContent) {
            wsContent.appendChild(panel);
        } else {
            document.body.appendChild(panel);
        }
    }

    measurementProgressState.isVisible = true;
    measurementProgressState.startTime = Date.now();
    panel.classList.add('visible');

    // 初始化面板内容
    updateMeasurementProgressPanel();

    // 步骤 4 的工作区提示此时由进度面板取代
    if (typeof syncStepWorkspace === 'function') {
        syncStepWorkspace(wizardState.currentStep);
    }
}

/**
 * 创建测量进度面板 DOM 元素
 */
function createMeasurementProgressPanel() {
    const panel = document.createElement('div');
    panel.id = 'measurement-progress-panel';
    panel.className = 'measurement-progress-panel';

    panel.innerHTML = `
        <div class="measurement-progress-header">
            <div class="measurement-progress-title">
                <div class="measurement-progress-icon">
                    <span style="font-size: 12px; color: white;">⏳</span>
                </div>
                <span>测量进行中</span>
            </div>
            <button class="measurement-close-btn" onclick="hideMeasurementProgressPanel()" title="关闭面板">×</button>
        </div>

        <!-- 当前色块预览 -->
        <div class="current-patch-preview">
            <div class="patch-preview-box" id="progress-patch-preview" style="background: rgb(0, 0, 0);"></div>
            <div class="patch-preview-info">
                <div class="patch-name-display" id="progress-patch-name">等待测量...</div>
                <div class="patch-rgb-display" id="progress-patch-rgb">RGB(--, --, --)</div>
                <div class="patch-measured-info">
                    <div class="measured-row">
                        <span class="measured-label">实测亮度</span>
                        <span class="measured-value" id="progress-patch-Y">-- cd/m²</span>
                    </div>
                    <div class="measured-row">
                        <span class="measured-label">实测 xy</span>
                        <span class="measured-value" id="progress-patch-xy">--, --</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- 进度条 -->
        <div class="progress-bar-area">
            <div class="progress-bar-header">
                <span class="progress-bar-text" id="progress-bar-text">进度: 0 / 0</span>
                <span class="progress-bar-percent" id="progress-bar-percent">0%</span>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" id="progress-bar-fill" style="width: 0%;"></div>
            </div>
        </div>

        <!-- 引导式测量确认（均匀性逐点确认，等待探头就位时显示） -->
        <div class="guided-confirm-area" id="guided-confirm-area" style="display:none; padding:8px 0; gap:8px;">
            <button class="btn btn-primary" id="btn-guided-confirm" style="flex:1;" onclick="guidedConfirmMeasure()">✓ 测量此点</button>
            <button class="btn btn-secondary" id="btn-guided-skip" style="flex:1;" onclick="guidedSkipMeasure()">跳过此点</button>
        </div>

        <!-- 测量统计 -->
        <div class="measurement-stats-area">
            <div class="stat-item">
                <span class="stat-label">已测量</span>
                <span class="stat-value" id="stats-measured">0</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">已跳过</span>
                <span class="stat-value" id="stats-skipped">0</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">剩余时间</span>
                <span class="stat-value" id="stats-remaining">--</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">平均耗时</span>
                <span class="stat-value" id="stats-avg-time">--</span>
            </div>
        </div>

        <!-- 重复性统计（可选显示） -->
        <div class="repeatability-stats" id="repeatability-stats" style="display: none;">
            <div class="repeatability-header">
                <span class="repeatability-title">重复性统计</span>
                <span class="repeatability-status" id="repeatability-status">--</span>
            </div>
            <div class="repeatability-details">
                <span class="repeatability-item">
                    标准差: <span class="repeatability-value" id="repeatability-std">--</span>
                </span>
                <span class="repeatability-item">
                    最大偏差: <span class="repeatability-value" id="repeatability-max-dev">--</span>
                </span>
            </div>
        </div>

        <!-- 错误提示区域 -->
        <div class="measurement-error-area" id="measurement-error-area" style="display: none;">
            <div class="error-title">
                <span>❌</span>
                <span id="error-title-text">测量失败</span>
            </div>
            <div class="error-message" id="error-message">--</div>
            <div class="error-suggestion" id="error-suggestion">
                <div class="error-suggestion-title">下一步建议</div>
                <ol class="error-suggestion-steps" id="error-suggestion-steps">
                    <li>请检查探头是否正确放置</li>
                    <li>确保屏幕显示正常</li>
                </ol>
            </div>
        </div>

        <!-- 异常处理按钮 -->
        <div class="measurement-actions-area" id="measurement-actions-area">
            <button class="measurement-action-btn remeasure" onclick="remeasureCurrentPatch()">
                <span>🔄</span>
                <span>重测当前点</span>
            </button>
            <button class="measurement-action-btn skip" onclick="skipCurrentPatch()">
                <span>⏭</span>
                <span>跳过并标记</span>
            </button>
            <button class="measurement-action-btn stop-save" onclick="stopAndSaveCheckpoint()">
                <span>⏹</span>
                <span>停止并保存断点</span>
            </button>
        </div>
    `;

    return panel;
}

/**
 * 隐藏测量进度面板
 */
function hideMeasurementProgressPanel() {
    const panel = document.getElementById('measurement-progress-panel');
    if (panel) {
        panel.classList.remove('visible');
    }
    measurementProgressState.isVisible = false;

    // 刷新所有待更新图表数据
    if (typeof flushRealtimeUpdates === 'function') {
        flushRealtimeUpdates();
    }

    // 工作区显隐可能随进度面板关闭而变化
    if (typeof syncStepWorkspace === 'function') {
        syncStepWorkspace(wizardState.currentStep);
    }
}

/**
 * 更新测量进度面板内容
 */
function updateMeasurementProgressPanel() {
    const state = measurementProgressState;

    // 更新当前色块预览
    if (state.currentPatch) {
        const previewBox = document.getElementById('progress-patch-preview');
        const nameDisplay = document.getElementById('progress-patch-name');
        const rgbDisplay = document.getElementById('progress-patch-rgb');

        if (previewBox) {
            const rgb = state.currentPatch.rgb;
            previewBox.style.background = `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
            // 深色色块添加边框
            const brightness = (rgb[0] + rgb[1] + rgb[2]) / 3;
            previewBox.classList.toggle('dark-patch', brightness < 30);
        }
        if (nameDisplay) {
            nameDisplay.textContent = state.currentPatch.name;
        }
        if (rgbDisplay) {
            const rgb = state.currentPatch.rgb;
            rgbDisplay.textContent = `RGB(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
        }
    }

    // 更新测量数据
    if (state.measuredData) {
        const yDisplay = document.getElementById('progress-patch-Y');
        const xyDisplay = document.getElementById('progress-patch-xy');

        if (yDisplay) {
            yDisplay.textContent = state.measuredData.Y.toFixed(2) + ' cd/m²';
            // 根据亮度值设置颜色
            const targetY = getTargetBrightness(state.currentPatch);
            const deviation = Math.abs(state.measuredData.Y - targetY) / targetY;
            yDisplay.classList.toggle('highlight-good', deviation < 0.1);
            yDisplay.classList.toggle('highlight-warning', deviation >= 0.1 && deviation < 0.2);
            yDisplay.classList.toggle('highlight-error', deviation >= 0.2);
        }
        if (xyDisplay) {
            xyDisplay.textContent = `${state.measuredData.x.toFixed(4)}, ${state.measuredData.y.toFixed(4)}`;
        }
    }

    // 更新进度条
    const progressPercent = state.totalPatches > 0 ?
        Math.round((state.currentPatchIndex / state.totalPatches) * 100) : 0;

    const barText = document.getElementById('progress-bar-text');
    const barPercent = document.getElementById('progress-bar-percent');
    const barFill = document.getElementById('progress-bar-fill');

    if (barText) {
        barText.textContent = t('进度: {state_currentPatchIndex} / {state_totalPatches}', {state_currentPatchIndex: state.currentPatchIndex, state_totalPatches: state.totalPatches});
    }
    if (barPercent) {
        barPercent.textContent = progressPercent + '%';
    }
    if (barFill) {
        barFill.style.width = progressPercent + '%';
    }

    // 更新统计信息
    const statsMeasured = document.getElementById('stats-measured');
    const statsSkipped = document.getElementById('stats-skipped');
    const statsRemaining = document.getElementById('stats-remaining');
    const statsAvgTime = document.getElementById('stats-avg-time');

    if (statsMeasured) {
        statsMeasured.textContent = state.currentPatchIndex;
    }
    if (statsSkipped) {
        statsSkipped.textContent = state.skippedPatches.length;
        statsSkipped.classList.toggle('warning', state.skippedPatches.length > 0);
    }

    // 计算剩余时间
    if (state.startTime && state.currentPatchIndex > 0) {
        const elapsed = Date.now() - state.startTime;
        const avgTime = elapsed / state.currentPatchIndex;
        const remaining = avgTime * (state.totalPatches - state.currentPatchIndex);
        const remainingMinutes = Math.ceil(remaining / 60000);

        if (statsRemaining) {
            statsRemaining.textContent = remainingMinutes > 60 ?
                `约 ${Math.floor(remainingMinutes / 60)} 小时 ${remainingMinutes % 60} 分` :
                `约 ${remainingMinutes} 分钟`;
        }
        if (statsAvgTime) {
            statsAvgTime.textContent = (avgTime / 1000).toFixed(1) + t(' 秒');
        }
    }

    // 更新重复性统计
    updateRepeatabilityDisplay();

    // 更新错误信息
    updateErrorDisplay();
}

/**
 * 更新循环测量进度处理（集成测量进度面板）
 */
function handleCycleProgressEnhanced(progressJson) {
    const progress = parsePayload(progressJson);
    if (!progress.current) return;

    // 更新状态
    measurementProgressState.currentPatchIndex = progress.current;
    measurementProgressState.totalPatches = progress.total;

    // 更新当前色块信息
    if (progress.patchName && progress.rgb) {
        measurementProgressState.currentPatch = {
            name: progress.patchName,
            rgb: progress.rgb
        };
    }

    // 更新面板（如果有）
    if (measurementProgressState.isVisible) {
        updateMeasurementProgressPanel();
    }

    // 显示面板（如果未显示）
    if (!measurementProgressState.isVisible && isCycleMeasuring) {
        showMeasurementProgressPanel();
    }

    // 底部色块栏高亮：当前测量中 + 下一块待测（并同步步骤 4 色块预览）
    updatePatchMeasuringHighlight(progress.patchName, progress.current, progress.total, progress.rgb);

    // 原始状态更新
    updateStatus(t('循环测量: {progress_current}/{progress_total} - {progress_patchName}', {progress_current: progress.current, progress_total: progress.total, progress_patchName: progress.patchName}));
}

/**
 * 增强的测量结果处理（集成实时图表更新）
 */
function handleMeasurementResultEnhanced(resultJson) {
    const result = parsePayload(resultJson);
    if (!result.rgb) return;

    // 更新测量数据
    measurementProgressState.measuredData = {
        x: result.x,
        y: result.y,
        Y: result.Y,
        cct: result.cct,
        deltaE: result.deltaE
    };

    // 添加到测量历史（用于重复性计算）
    measurementProgressState.measurementHistory.push({
        patchName: result.patchName,
        Y: result.Y,
        x: result.x,
        y: result.y,
        timestamp: Date.now()
    });

    // 使用实时图表更新（高性能）
    if (typeof addRealtimeChartData === 'function') {
        addRealtimeChartData(result);
    }

    // 更新进度面板
    if (measurementProgressState.isVisible) {
        updateMeasurementProgressPanel();
    }

    // 原始处理逻辑
    updatePatchDataDisplay(result);
    storeMeasurementResult(result);
    updateMeasuredPatches(result);
    updateDisplayBasicData(result);
}

/**
 * 更新已测量色块跟踪
 */
function updateMeasuredPatches(result) {
    const patchName = result.patchName;
    if (patchName) {
        measuredPatches[patchName] = {
            rgb: [result.rgb.r, result.rgb.g, result.rgb.b],
            result: result
        };
        updatePatchButtonMeasuredStyle(patchName);
    }
}

/**
 * 重测当前色块
 */
function remeasureCurrentPatch() {
    if (!backend || !measurementProgressState.currentPatch) return;

    const patch = measurementProgressState.currentPatch;
    const rgb = patch.rgb;

    // 清除该色块的测量历史（重新测量）
    const historyIndex = measurementProgressState.measurementHistory.findIndex(
        h => h.patchName === patch.name
    );
    if (historyIndex >= 0) {
        measurementProgressState.measurementHistory.splice(historyIndex, 1);
    }

    // 清除已测量标记
    if (measuredPatches[patch.name]) {
        delete measuredPatches[patch.name];
    }

    // 显示色块并测量
    backend.show_patch(rgb[0], rgb[1], rgb[2]);
    backend.set_current_patch_name(patch.name);

    // 延迟触发测量
    setTimeout(() => {
        if (backend) {
            backend.measure_single();
        }
    }, 500);

    updateStatus(t('重新测量: {patch_name}', {patch_name: patch.name}));
}

/**
 * 跳过当前色块并标记
 */
function skipCurrentPatch() {
    if (!measurementProgressState.currentPatch) return;

    const patch = measurementProgressState.currentPatch;

    // 添加到跳过列表
    measurementProgressState.skippedPatches.push({
        name: patch.name,
        rgb: patch.rgb,
        reason: '用户跳过',
        timestamp: Date.now()
    });

    // 清除测量数据
    measurementProgressState.measuredData = null;

    updateStatus(t('已跳过: {patch_name} (标记为用户跳过)', {patch_name: patch.name}));
    updateMeasurementProgressPanel();

    // 如果有后端，通知后端跳过
    if (backend) {
        backend.skip_current_patch();
    }
}

/**
 * 停止测量并保存断点
 */
function stopAndSaveCheckpoint() {
    if (!backend) return;

    // 显示确认对话框
    showCheckpointConfirmDialog();
}

/**
 * 显示断点保存确认对话框
 */
function showCheckpointConfirmDialog() {
    const state = measurementProgressState;

    // 创建对话框
    const dialog = document.createElement('div');
    dialog.className = 'modal-overlay show';
    dialog.id = 'checkpoint-dialog';

    dialog.innerHTML = `
        <div class="modal-dialog" style="max-width: 400px;">
            <div class="modal-header">
                <h3>停止并保存断点</h3>
                <button class="modal-close-btn" onclick="closeCheckpointDialog()">×</button>
            </div>
            <div class="modal-body">
                <div class="checkpoint-confirm-dialog">
                    <div class="checkpoint-confirm-title">确认停止测量</div>
                    <div class="checkpoint-confirm-content">
                        当前已测量 ${state.currentPatchIndex} / ${state.totalPatches} 个色块。
                        停止后可以保存当前进度，下次可从断点继续测量。
                    </div>
                    <div class="checkpoint-confirm-info">
                        已跳过: ${state.skippedPatches.length} 个色块<br>
                        跳过的色块: ${state.skippedPatches.map(p => p.name).join(', ') || '无'}
                    </div>
                    <div class="checkpoint-confirm-actions">
                        <button class="btn btn-secondary" onclick="closeCheckpointDialog()">取消</button>
                        <button class="btn btn-primary" onclick="confirmStopAndSave()">保存断点并停止</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(dialog);
}

/**
 * 关闭断点确认对话框
 */
function closeCheckpointDialog() {
    const dialog = document.getElementById('checkpoint-dialog');
    if (dialog) {
        dialog.remove();
    }
}

/**
 * 确认停止并保存断点
 */
function confirmStopAndSave() {
    closeCheckpointDialog();

    // 停止测量
    if (backend) {
        backend.stop_cycle();
    }

    // 保存当前数据
    saveCurrentData();

    // 隐藏进度面板
    hideMeasurementProgressPanel();

    // 重置状态
    isCycleMeasuring = false;
    setCycleButtonsState(false);

    updateStatus(t('测量已停止，断点已保存。下次可从第 {measurementProgressState_currentPatchIndex___1} 个色块继续', {measurementProgressState_currentPatchIndex___1: measurementProgressState.currentPatchIndex + 1}));
}

/**
 * 更新重复性统计显示
 */
function updateRepeatabilityDisplay() {
    const state = measurementProgressState;
    const container = document.getElementById('repeatability-stats');

    // 计算重复性统计（需要多次测量同一点）
    const history = state.measurementHistory;

    // 如果有足够的数据，计算统计值
    if (history.length >= 3) {
        // 计算最近的测量数据的标准差
        const recentData = history.slice(-5);
        const yValues = recentData.map(h => h.Y);
        const avgY = yValues.reduce((a, b) => a + b, 0) / yValues.length;

        // 计算标准差
        const variance = yValues.reduce((sum, y) => sum + Math.pow(y - avgY, 2), 0) / yValues.length;
        const stdDev = Math.sqrt(variance);

        // 计算最大偏差
        const maxDev = Math.max(...yValues.map(y => Math.abs(y - avgY)));

        // 显示重复性统计
        if (container) {
            container.style.display = 'block';

            const stdDisplay = document.getElementById('repeatability-std');
            const maxDevDisplay = document.getElementById('repeatability-max-dev');
            const statusDisplay = document.getElementById('repeatability-status');

            if (stdDisplay) {
                stdDisplay.textContent = stdDev.toFixed(3) + ' cd/m²';
            }
            if (maxDevDisplay) {
                maxDevDisplay.textContent = maxDev.toFixed(3) + ' cd/m²';
            }
            if (statusDisplay) {
                // 根据相对标准差评估重复性
                const relativeStdDev = avgY > 0 ? (stdDev / avgY) * 100 : 0;

                if (relativeStdDev < 1) {
                    statusDisplay.textContent = t('优秀');
                    statusDisplay.className = 'repeatability-status good';
                } else if (relativeStdDev < 3) {
                    statusDisplay.textContent = t('良好');
                    statusDisplay.className = 'repeatability-status acceptable';
                } else {
                    statusDisplay.textContent = t('较差');
                    statusDisplay.className = 'repeatability-status poor';
                }
            }
        }
    }
}

/**
 * 更新错误显示
 */
function updateErrorDisplay() {
    const state = measurementProgressState;
    const container = document.getElementById('measurement-error-area');

    if (!state.errorInfo || !container) {
        if (container) {
            container.style.display = 'none';
        }
        return;
    }

    // 显示错误信息
    container.style.display = 'block';

    const titleText = document.getElementById('error-title-text');
    const messageText = document.getElementById('error-message');
    const suggestionSteps = document.getElementById('error-suggestion-steps');

    if (titleText) {
        titleText.textContent = state.errorInfo.title || t('测量异常');
    }
    if (messageText) {
        messageText.textContent = state.errorInfo.message || '--';
    }
    if (suggestionSteps && state.errorInfo.suggestions) {
        suggestionSteps.innerHTML = state.errorInfo.suggestions.map(s => `<li>${s}</li>`).join('');
    }
}

/**
 * 设置测量错误信息
 */
function setMeasurementError(errorType, errorData) {
    const errorInfo = {
        title: '',
        message: '',
        suggestions: []
    };

    // 根据错误类型设置信息
    switch (errorType) {
        case 'instrument_disconnected':
            errorInfo.title = t('探头连接断开');
            errorInfo.message = '测量仪器已断开连接，无法继续测量。';
            errorInfo.suggestions = [
                '请检查 USB 连接是否稳固',
                '确认仪器电源是否正常',
                '尝试重新连接探头后继续'
            ];
            break;

        case 'measurement_timeout':
            errorInfo.title = t('测量超时');
            errorInfo.message = '等待测量结果超时，可能是仪器响应缓慢。';
            errorInfo.suggestions = [
                '检查探头是否正确放置在屏幕上',
                '确认屏幕是否显示正确的色块',
                '尝试增加测量延迟时间'
            ];
            break;

        case 'invalid_result':
            errorInfo.title = t('测量结果异常');
            errorInfo.message = `收到无效的测量数据: ${errorData?.detail || '未知'}`;
            errorInfo.suggestions = [
                '检查测量环境是否稳定',
                '确认屏幕亮度设置正确',
                '重测当前色块'
            ];
            break;

        case 'argyll_error':
            errorInfo.title = t('ArgyllCMS 错误');
            errorInfo.message = errorData?.message || 'ArgyllCMS 工具执行失败';
            errorInfo.suggestions = [
                '检查 ArgyllCMS 是否正确安装',
                '确认探头驱动是否已配置',
                '查看控制台日志获取详细信息'
            ];
            break;

        default:
            errorInfo.title = t('未知错误');
            errorInfo.message = errorData?.message || '测量过程中发生未知错误';
            errorInfo.suggestions = [
                '请尝试重新测量',
                '检查设备和环境配置',
                '联系技术支持获取帮助'
            ];
    }

    measurementProgressState.errorInfo = errorInfo;
    updateErrorDisplay();
}

/**
 * 清除测量错误信息
 */
function clearMeasurementError() {
    measurementProgressState.errorInfo = null;
    updateErrorDisplay();
}

/**
 * 获取色块的目标亮度（用于判断偏差）
 */
function getTargetBrightness(patch) {
    if (!patch || !patch.rgb) return 100;

    const rgb = patch.rgb;
    const brightness = (rgb[0] + rgb[1] + rgb[2]) / 3 / 255 * 100;

    // 如果是灰阶，返回对应的亮度
    if (patch.name && patch.name.includes('%')) {
        const level = parseFloat(patch.name.replace('%', ''));
        return level;
    }

    // 白色返回峰值亮度估计
    if (rgb[0] === 255 && rgb[1] === 255 && rgb[2] === 255) {
        return 100;
    }

    // 黑色返回黑场亮度估计
    if (rgb[0] === 0 && rgb[1] === 0 && rgb[2] === 0) {
        return 0.1;
    }

    return brightness;
}

/**
 * 重置测量进度状态
 */
function resetMeasurementProgressState() {
    measurementProgressState.isVisible = false;
    measurementProgressState.currentPatchIndex = 0;
    measurementProgressState.totalPatches = 0;
    measurementProgressState.currentPatch = null;
    measurementProgressState.measuredData = null;
    measurementProgressState.startTime = null;
    measurementProgressState.estimatedRemainingTime = null;
    measurementProgressState.skippedPatches = [];
    measurementProgressState.errorInfo = null;
    measurementProgressState.repeatabilityData = null;
    measurementProgressState.measurementHistory = [];
    measurementProgressState.lastProgressUpdate = 0;

    // 重置图表更新状态
    if (typeof resetRealtimeUpdateState === 'function') {
        resetRealtimeUpdateState();
    }
}

/**
 * 显示测量完成动画
 */
function showMeasurementCompleteAnimation() {
    const animation = document.createElement('div');
    animation.className = 'measurement-complete-animation';
    animation.innerHTML = `
        <div class="complete-icon">✓</div>
    `;

    document.body.appendChild(animation);

    // 6秒后自动消失
    setTimeout(() => {
        animation.remove();
    }, 600);
}

// ==============================================================================
// P6-A 专业工作流向导状态管理和步骤切换逻辑
// ==============================================================================

// 向导状态
const wizardState = {
    currentWorkflow: 'gamut',       // 当前工作流: gamut, icc, lut, ccmx, validation, history
    currentStep: 1,                 // 当前步骤 (1-7)
    completedSteps: [],             // 已完成的步骤列表
    isWorkflowRunning: false,       // 工作流是否正在运行

    // 工作流配置
    workflows: {
        gamut: { name: '显示器检测', desc: 'sRGB/DCI-P3/Rec.2020 色域分析', steps: [1,2,3,4,7] },
        icc: { name: 'ICC 校准', desc: '显示器 ICC Profile 制作', steps: [1,2,3,4,5,6,7] },
        lut: { name: '3D LUT', desc: 'Resolve/madVR LUT 制作', steps: [1,2,3,4,5,6,7] },
        ccmx: { name: 'CCMX 矩阵', desc: '色度计光谱校正制作', steps: [1,2,3,4,7] },
        validation: { name: '验证', desc: '校准效果验证报告', steps: [1,3,4,6,7] },
        history: { name: '历史报告', desc: '测量历史数据管理', steps: [7] }
    },

    // 步骤名称映射
    stepNames: {
        1: '预检',
        2: '目标设置',
        3: '探头/修正',
        4: '测量',
        5: '生成',
        6: '验证',
        7: '报告'
    },

    // 目标参数
    targetSettings: {
        gamut: 'sRGB',
        whitePoint: 'D65',
        gamma: '2.2',
        graySteps: '21',
        patchCount: 'auto',
        sampleStrategy: 'balanced'
    },

    // 探头参数
    probeSettings: {
        probeType: 'i1d3',
        displayType: 'l',
        measureDelay: 500,
        refreshRate: 'auto',
        oledMode: false,
        darkMultisample: false,
        correctionFile: ''
    },

    // 新用户引导状态
    newUserGuide: {
        isActive: false,
        currentTip: null,
        tipsShown: []
    }
};

// ==============================================================================
// 双模式 UI 管理（引导模式 guided / 专业自由模式 advanced）
// ==============================================================================

/**
 * 当前是否有测量/校准流程正在进行（期间禁止切换 UI 模式）
 */
function isWorkflowBusy() {
    return isCycleMeasuring || wizardState.isWorkflowRunning || isCalibrating;
}

/**
 * 应用 UI 模式
 * @param {string} mode 'guided' | 'advanced'
 * @returns {boolean} 是否切换成功
 */
function applyUiMode(mode) {
    if (mode !== 'guided' && mode !== 'advanced') {
        mode = 'guided';
    }
    if (mode !== uiMode && isWorkflowBusy()) {
        updateStatus(t('测量/校准进行中，无法切换 UI 模式，请先停止'));
        return false;
    }
    uiMode = mode;
    try {
        localStorage.setItem(UI_MODE_STORAGE_KEY, mode);
    } catch (e) { /* localStorage 不可用时忽略 */ }

    const advanced = (mode === 'advanced');
    document.body.classList.toggle('mode-guided', !advanced);
    document.body.classList.toggle('mode-advanced', advanced);

    const show = (id, visible) => {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('hidden', !visible);
    };

    // 引导模式：工作流卡片 + 向导导航 + CTA + 步骤工作区 + 测量结果；隐藏 自由测量按钮/测量模式面板/高级设置面板/历史数据
    // 高级模式：相反（历史数据的加载/对比属于进阶操作，仅高级模式显示）
    show('workflow-selector-panel', !advanced);
    show('wizard-nav-panel', !advanced);
    show('wizard-cta-area', !advanced);
    show('step-workspace-section', !advanced);
    show('history-section', advanced);
    show('resize-handle-history', advanced);
    show('measure-group-free', advanced);
    show('measure-mode-panel', advanced);
    show('legacy-settings-panel', advanced);

    if (advanced) {
        // 隐藏所有向导步骤内容（侧栏设置步骤 + 工作区结果步骤）
        document.querySelectorAll('.wizard-step-content').forEach(c => c.classList.add('hidden'));
        // 内嵌在工作区的进度面板移回 body 浮动显示
        const progressPanel = document.getElementById('measurement-progress-panel');
        if (progressPanel && progressPanel.parentElement !== document.body) {
            document.body.appendChild(progressPanel);
        }
    } else {
        // 引导模式：按当前步骤重新计算 CTA / 工作区显隐
        goToStep(wizardState.currentStep);
    }

    updateAdvancedModeControls();
    triggerChartResize();
    return true;
}

/**
 * 切换引导/高级模式（两个入口共用）
 */
function toggleAdvancedMode() {
    const next = (uiMode === 'guided') ? 'advanced' : 'guided';
    if (applyUiMode(next)) {
        updateStatus(next === 'advanced'
            ? '已切换到专业自由模式：请自行连接探头后使用底部测量按钮'
            : '已切换到引导模式：按步骤完成校准流程');
        return true;
    }
    return false;
}

/**
 * 启动时恢复上次使用的 UI 模式（默认引导模式）
 */
function initUiMode() {
    let saved = 'guided';
    try {
        saved = localStorage.getItem(UI_MODE_STORAGE_KEY) || 'guided';
    } catch (e) { /* ignore */ }
    applyUiMode(saved);
}

/**
 * 同步模式切换入口的选中态（设置菜单勾选 + 顶栏开关 + 工作流面板按钮文案）
 */
function updateAdvancedModeControls() {
    const check = document.getElementById('advanced-mode-check');
    if (check) {
        check.textContent = (uiMode === 'advanced') ? '✓' : '';
    }
    const btn = document.getElementById('btn-toggle-advanced-mode');
    if (btn) {
        btn.textContent = (uiMode === 'advanced') ? t('引导模式') : t('高级模式');
        btn.title = (uiMode === 'advanced')
            ? '切换回引导模式（向导步骤流程）'
            : '切换到专业自由模式（隐藏向导引导）';
    }
    const toggleBtn = document.getElementById('btn-mode-toggle');
    if (toggleBtn) {
        toggleBtn.classList.toggle('active', uiMode === 'advanced');
        toggleBtn.title = (uiMode === 'advanced')
            ? '切换回引导模式（向导步骤流程）'
            : '切换到专业自由模式（隐藏向导引导）';
    }
    const switchEl = document.getElementById('mode-switch');
    if (switchEl) {
        switchEl.classList.toggle('on', uiMode === 'advanced');
    }
}

/**
 * 绑定模式切换入口（设置菜单 + 顶栏开关 + 工作流面板按钮）
 */
function initUiModeControls() {
    document.getElementById('menu-advanced-mode')?.addEventListener('click', toggleAdvancedMode);
    document.getElementById('btn-mode-toggle')?.addEventListener('click', toggleAdvancedMode);
    document.getElementById('btn-toggle-advanced-mode')?.addEventListener('click', toggleAdvancedMode);
}

/**
 * 同步侧栏设置类步骤面板（2 目标设置 / 3 探头修正 / 4 测量）的可用状态：
 * 前置步骤未完成时灰显禁用（如预检未通过时目标设置不可点），
 * 已到达的步骤可正常交互，保持侧栏无空白区域。
 */
function syncSidebarStepPanels(currentStep) {
    const SIDEBAR_STEPS = [2, 3, 4];
    document.querySelectorAll('.wizard-step-content').forEach(content => {
        const num = parseInt(content.dataset.step);
        if (!SIDEBAR_STEPS.includes(num)) return;
        const enabled = canGoToStep(num);
        content.classList.toggle('step-panel-disabled', !enabled);
    });
}

/**
 * 同步底部向导 CTA 区：只显示当前步骤的按钮，"下一步"文案跟随工作流实际下一步
 */
function syncWizardCta(stepNum) {
    const ctaArea = document.getElementById('wizard-cta-area');
    if (!ctaArea) return;

    const workflowConfig = wizardState.workflows[wizardState.currentWorkflow];
    const nextStep = getNextStep();
    const hasNext = nextStep !== null;

    ctaArea.querySelectorAll('.wizard-cta-btn').forEach(btn => {
        const forStep = parseInt(btn.dataset.step);
        let visible = (forStep === stepNum);
        // "下一步"按钮：当前步骤已是工作流最后一步时隐藏（由"完成工作流"接管）
        if (visible && btn.classList.contains('btn-next-step') && !hasNext) {
            visible = false;
        }
        // 动态状态按钮（如"停止测量"）的显隐由测量逻辑自己管理，这里跳过
        if (btn.classList.contains('wizard-cta-dynamic')) {
            return;
        }
        btn.classList.toggle('hidden', !visible);
    });

    // 动态更新"下一步"文案（validation 工作流跳过步骤 2 等场景）
    const nextBtn = ctaArea.querySelector(`.wizard-cta-btn[data-step="${stepNum}"].btn-next-step`);
    if (nextBtn && hasNext) {
        nextBtn.textContent = t('下一步：{wizardState_stepNames_nextStep} →', {
            wizardState_stepNames_nextStep: t(wizardState.stepNames[nextStep] || '')
        });
    }

    const status = document.getElementById('wizard-cta-status');
    if (status) {
        const pos = workflowConfig.steps.indexOf(stepNum) + 1;
        status.textContent = t('步骤 {pos}/{workflowConfig_steps_length} · {wizardState_stepNames_stepNum}', {
            pos: pos,
            workflowConfig_steps_length: workflowConfig.steps.length,
            wizardState_stepNames_stepNum: t(wizardState.stepNames[stepNum] || '')
        });
    }
}

/**
 * 同步中列"步骤工作区"显隐与提示文案
 * 步骤 1/5/6/7 的面板物理位于工作区内（由 goToStep 常规显隐逻辑处理）；
 * 步骤 2/3/4 显示简短引导文案；测量进行中时工作区容纳内嵌进度面板。
 */
function syncStepWorkspace(stepNum) {
    const section = document.getElementById('step-workspace-section');
    if (!section) return;
    if (uiMode === 'advanced') {
        section.classList.add('hidden');
        return;
    }

    const hints = {
        2: '在左侧「目标设置」面板中选择目标色域、白点和 Gamma，然后点击下方"下一步"。',
        3: '在左侧「探头与修正」面板中连接探头、按需选择光谱校正文件，然后点击下方"下一步"。',
        4: '点击下方"开始测量"后，屏幕将依次显示色块；测量进度与统计信息会实时显示在这里。'
    };

    const hasPanel = !!document.querySelector('#step-workspace-content .wizard-step-content:not(.hidden)');
    // 测量进行中：无论当前在哪一步都保持工作区可见（内嵌进度面板不能凭空消失）
    const measuring = measurementProgressState.isVisible;
    const showSection = hasPanel || measuring || !!hints[stepNum];
    section.classList.toggle('hidden', !showSection);

    const hint = document.getElementById('workspace-hint');
    if (hint) {
        hint.textContent = hints[stepNum] || '';
        hint.classList.toggle('hidden', !hints[stepNum]);
    }

    const title = document.getElementById('step-workspace-title');
    if (title) {
        title.textContent = t('步骤详情 · {wizardState_stepNames_stepNum}', {wizardState_stepNames_stepNum: wizardState.stepNames[stepNum] || ''});
    }

    // 面板自带标题（如"环境预检"），面板可见时隐藏外层标题行，避免同名头部叠两层
    const sectionHeader = section.querySelector('.section-header');
    if (sectionHeader) {
        sectionHeader.classList.toggle('hidden', hasPanel && !measuring);
    }
}

/**
 * 初始化向导 UI
 */
function initWizardUI() {
    // 工作流卡片点击事件
    const workflowCards = document.querySelectorAll('.workflow-card');
    workflowCards.forEach(card => {
        card.addEventListener('click', () => {
            const workflow = card.dataset.workflow;
            selectWorkflow(workflow);
        });
    });

    // 步骤点击事件（允许跳转到已完成的步骤）
    const wizardSteps = document.querySelectorAll('.wizard-step');
    wizardSteps.forEach(step => {
        step.addEventListener('click', () => {
            const stepNum = parseInt(step.dataset.step);
            if (wizardState.completedSteps.includes(stepNum) || stepNum === wizardState.currentStep) {
                goToStep(stepNum);
            }
        });
    });

    // 预检按钮事件
    const btnRunPreflight = document.getElementById('btn-run-preflight');
    if (btnRunPreflight) {
        btnRunPreflight.addEventListener('click', () => {
            runPreflightCheck();
        });
    }

    // 预检覆盖复选框事件
    const preflightOverrideCheckbox = document.getElementById('preflight-override-checkbox');
    if (preflightOverrideCheckbox) {
        preflightOverrideCheckbox.addEventListener('change', (e) => {
            setPreflightOverride(e.target.checked);
            updateOverrideWarningDisplay(e.target.checked);
        });
    }

    // 预设按钮事件
    const presetButtons = document.querySelectorAll('.preset-btn');
    presetButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const preset = btn.dataset.preset;
            applyTargetPreset(preset);
        });
    });

    // 高级参数展开按钮
    setupAdvancedToggle('btn-advanced-target', 'advanced-target-params');
    setupAdvancedToggle('btn-advanced-probe', 'advanced-probe-params');

    // 步骤导航按钮
    setupStepNavigation();

    // 向导测量按钮绑定（只绑一次；原先在 initializeMeasureStep 中每次进入步骤 4 都会重复绑定）
    document.getElementById('wizard-btn-start-measure')?.addEventListener('click', () => startWizardMeasurement());
    document.getElementById('wizard-btn-stop-measure')?.addEventListener('click', () => stopWizardMeasurement());

    // 新用户引导：恢复已展示过的提示记录（localStorage 持久化）
    try {
        const savedTips = JSON.parse(localStorage.getItem(NEW_USER_TIPS_STORAGE_KEY) || '[]');
        if (Array.isArray(savedTips)) {
            wizardState.newUserGuide.tipsShown.push(...savedTips.filter(t => typeof t === 'string'));
        }
    } catch (e) { /* ignore */ }

    // 初始化显示
    selectWorkflow('gamut');
    updateWizardProgress();
}

/**
 * 选择工作流
 */
function selectWorkflow(workflow) {
    // 更新状态
    wizardState.currentWorkflow = workflow;
    wizardState.currentStep = 1;
    wizardState.completedSteps = [];

    // 更新工作流卡片选中状态
    const workflowCards = document.querySelectorAll('.workflow-card');
    workflowCards.forEach(card => {
        card.classList.toggle('selected', card.dataset.workflow === workflow);
    });

    // 更新步骤导航（隐藏不需要的步骤）
    const workflowConfig = wizardState.workflows[workflow];
    const wizardSteps = document.querySelectorAll('.wizard-step');
    wizardSteps.forEach(step => {
        const stepNum = parseInt(step.dataset.step);
        const isRequired = workflowConfig.steps.includes(stepNum);
        step.style.display = isRequired ? 'flex' : 'none';
    });

    // 显示第一步内容
    goToStep(1);

    // 更新进度条
    updateWizardProgress();

    // 设置测量模式
    if (backend) {
        backend.set_measure_mode(workflow);
    }

    // 新用户引导：首次选择工作流时显示提示
    if (uiMode === 'guided') {
        wizardState.newUserGuide.isActive = true;
    }
    if (!wizardState.newUserGuide.tipsShown.includes('workflow-selected')) {
        showNewUserTip('workflow-selected', `已选择 "${workflowConfig.name}" 工作流。\n请按步骤完成校准流程。`);
    }

    // 更新生成步骤内容（根据工作流类型）
    updateGenerateStepContent(workflow);

    updateStatus(t('已选择工作流: {workflowConfig_name}', {workflowConfig_name: workflowConfig.name}));
}

/**
 * 切换到指定步骤
 */
function goToStep(stepNum) {
    // 验证是否可以切换
    if (!canGoToStep(stepNum)) {
        showStepBlockedDialog(stepNum);
        return;
    }

    // 更新当前步骤
    wizardState.currentStep = stepNum;

    // 更新步骤导航样式
    const wizardSteps = document.querySelectorAll('.wizard-step');
    wizardSteps.forEach(step => {
        const num = parseInt(step.dataset.step);
        step.classList.remove('active');
        step.classList.toggle('completed', wizardState.completedSteps.includes(num));
        if (num === stepNum) {
            step.classList.add('active');
        }
    });

    // 显示对应步骤内容：
    // - 结果类步骤（1/5/6/7，位于中列工作区）按当前步骤切换显隐
    // - 设置类步骤（2/3/4，位于侧栏）引导模式下常驻显示，未到达时灰显禁用（消除侧栏空白）
    const SIDEBAR_STEPS = [2, 3, 4];
    const stepContents = document.querySelectorAll('.wizard-step-content');
    stepContents.forEach(content => {
        const num = parseInt(content.dataset.step);
        if (uiMode === 'advanced') {
            return; // 高级模式由 applyUiMode 统一隐藏
        }
        if (SIDEBAR_STEPS.includes(num)) {
            content.classList.remove('hidden');
        } else {
            content.classList.toggle('hidden', num !== stepNum);
        }
    });
    syncSidebarStepPanels(stepNum);

    // 同步底部向导 CTA 区与中列步骤工作区（引导模式）
    syncWizardCta(stepNum);
    syncStepWorkspace(stepNum);

    // 更新进度条
    updateWizardProgress();

    // 步骤特定初始化
    initializeStepContent(stepNum);
}

/**
 * 检查是否可以切换到指定步骤
 */
function canGoToStep(stepNum) {
    const workflowConfig = wizardState.workflows[wizardState.currentWorkflow];

    // 检查步骤是否在工作流中
    if (!workflowConfig.steps.includes(stepNum)) {
        return false;
    }

    // 检查是否已完成前置步骤
    const requiredSteps = workflowConfig.steps.filter(s => s < stepNum);
    for (const reqStep of requiredSteps) {
        if (!wizardState.completedSteps.includes(reqStep)) {
            return false;
        }
    }

    return true;
}

/**
 * 显示步骤被阻止的对话框
 */
function showStepBlockedDialog(stepNum) {
    const workflowConfig = wizardState.workflows[wizardState.currentWorkflow];
    const requiredSteps = workflowConfig.steps.filter(s => s < stepNum);
    const missingSteps = requiredSteps.filter(s => !wizardState.completedSteps.includes(s));

    const missingStepNames = missingSteps.map(s => wizardState.stepNames[s]).join('、');

    const dialog = createAlertDialog(
        '无法跳转',
        `请先完成以下步骤: ${missingStepNames}`,
        'info'
    );
    document.body.appendChild(dialog);
}

/**
 * 创建提示对话框
 */
function createAlertDialog(title, message, type = 'info') {
    const dialog = document.createElement('div');
    dialog.className = 'modal-overlay show';
    dialog.id = 'alert-dialog';

    const icon = type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️';

    dialog.innerHTML = `
        <div class="modal-dialog" style="max-width: 360px;">
            <div class="modal-header">
                <h3>${icon} ${title}</h3>
                <button class="modal-close-btn" onclick="closeAlertDialog()">×</button>
            </div>
            <div class="modal-body">
                <div class="alert-content">${message}</div>
                <div class="alert-actions">
                    <button class="btn btn-primary" onclick="closeAlertDialog()">确定</button>
                </div>
            </div>
        </div>
    `;

    return dialog;
}

/**
 * 关闭提示对话框
 */
function closeAlertDialog() {
    const dialog = document.getElementById('alert-dialog');
    if (dialog) {
        dialog.remove();
    }
}

/**
 * 更新向导进度条
 */
function updateWizardProgress() {
    const workflowConfig = wizardState.workflows[wizardState.currentWorkflow];
    const totalSteps = workflowConfig.steps.length;
    const completedCount = wizardState.completedSteps.filter(s => workflowConfig.steps.includes(s)).length;

    const progressPercent = totalSteps > 0 ? Math.round((completedCount / totalSteps) * 100) : 0;

    const progressFill = document.getElementById('wizard-progress-fill');
    if (progressFill) {
        progressFill.style.width = progressPercent + '%';
    }
}

/**
 * 初始化步骤内容
 */
function initializeStepContent(stepNum) {
    switch (stepNum) {
        case 1:
            initializePreflightStep();
            break;
        case 2:
            initializeTargetSettingsStep();
            break;
        case 3:
            initializeProbeSettingsStep();
            break;
        case 4:
            initializeMeasureStep();
            break;
        case 5:
            initializeGenerateStep();
            break;
        case 6:
            initializeValidateStep();
            break;
        case 7:
            initializeReportStep();
            break;
    }
}

/**
 * 初始化预检步骤
 */
function initializePreflightStep() {
    // 如果已有预检报告，显示结果
    if (preflightReport) {
        renderWizardPreflightResults(preflightReport);
    }

    // 更新按钮状态
    updatePreflightStepButtons();
}

/**
 * 渲染向导内的预检结果（扁平单行：图标 + 名称 + 消息，超长截断、悬停显示全文）
 */
function renderWizardPreflightResults(report) {
    const resultsDiv = document.getElementById('preflight-results');
    if (!resultsDiv) return;

    resultsDiv.innerHTML = '';

    if (report.results && report.results.length > 0) {
        const frag = document.createDocumentFragment();
        report.results.forEach(item => {
            const row = document.createElement('div');
            const itemName = window.PREFLIGHT_I18N
                ? PREFLIGHT_I18N.translateItemName(item.item_id) : item.item_id;
            const itemMessage = window.PREFLIGHT_I18N
                ? PREFLIGHT_I18N.translateMessage(item.message) : (item.message || '');
            row.className = `preflight-item ${getStatusClass(item.status)}`;
            row.title = `${itemName}: ${itemMessage}`;
            row.innerHTML = `
                <span class="preflight-item-status">${getStatusIcon(item.status)}</span>
                <span class="preflight-item-name">${itemName}</span>
                <span class="preflight-item-message">${itemMessage}</span>
            `;
            frag.appendChild(row);
        });
        resultsDiv.appendChild(frag);
    }

    // 显示覆盖面板（如果有阻断项）
    if (report.summary && report.summary.block_count > 0) {
        const overridePanel = document.getElementById('preflight-override-panel');
        if (overridePanel) {
            overridePanel.classList.remove('hidden');
        }
    }

    // 更新摘要
    const summarySpan = document.getElementById('preflight-summary');
    if (summarySpan && report.summary) {
        summarySpan.textContent = t('通过 {report_summary_pass_count____0} | 警告 {report_summary_warn_count____0} | 阻断 {report_summary_block_count____0}', {report_summary_pass_count____0: report.summary.pass_count || 0, report_summary_warn_count____0: report.summary.warn_count || 0, report_summary_block_count____0: report.summary.block_count || 0});
        summarySpan.className = 'preflight-summary';
        if (report.summary.block_count > 0) {
            summarySpan.classList.add('block');
        } else if (report.summary.warn_count > 0) {
            summarySpan.classList.add('warn');
        } else {
            summarySpan.classList.add('pass');
        }
    }
}

/**
 * 更新预检步骤按钮状态
 */
function updatePreflightStepButtons() {
    const btnNext = document.getElementById('btn-next-step-1');
    if (!btnNext) return;

    // 检查预检是否通过
    const canProceed = preflightReport && preflightReport.can_proceed;

    // 如果有阻断项但启用了覆盖，也允许继续
    const hasBlock = preflightReport && preflightReport.summary && preflightReport.summary.block_count > 0;
    const overrideEnabled = preflightOverrideEnabled;

    btnNext.disabled = !(canProceed || (hasBlock && overrideEnabled));

    if (btnNext.disabled) {
        btnNext.title = t('请先完成预检');
    } else {
        btnNext.title = '';
    }
}

/**
 * 初始化目标设置步骤
 */
function initializeTargetSettingsStep() {
    // 应用当前目标设置到 UI
    const gamutSelect = document.getElementById('wizard-target-gamut');
    const whiteSelect = document.getElementById('wizard-target-white');
    const gammaSelect = document.getElementById('wizard-target-gamma');

    if (gamutSelect) gamutSelect.value = wizardState.targetSettings.gamut;
    if (whiteSelect) whiteSelect.value = wizardState.targetSettings.whitePoint;
    if (gammaSelect) gammaSelect.value = wizardState.targetSettings.gamma;

    // 监听变化
    if (gamutSelect) {
        gamutSelect.addEventListener('change', (e) => {
            wizardState.targetSettings.gamut = e.target.value;
            updateTargetPresetState();
        });
    }
    if (whiteSelect) {
        whiteSelect.addEventListener('change', (e) => {
            wizardState.targetSettings.whitePoint = e.target.value;
            updateTargetPresetState();
        });
    }
    if (gammaSelect) {
        gammaSelect.addEventListener('change', (e) => {
            wizardState.targetSettings.gamma = e.target.value;
            updateTargetPresetState();
        });
    }
}

/**
 * 应用目标预设
 */
function applyTargetPreset(preset) {
    const presetButtons = document.querySelectorAll('.preset-btn');
    presetButtons.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.preset === preset);
    });

    // 预设参数
    const presets = {
        'srgb': { gamut: 'sRGB', whitePoint: 'D65', gamma: '2.2' },
        'rec709': { gamut: 'Rec709', whitePoint: 'D65', gamma: '2.4' },
        'dci-p3': { gamut: 'DCI_P3', whitePoint: 'D63', gamma: '2.6' },
        'custom': {}  // 自定义不改变当前值
    };

    if (presets[preset]) {
        Object.assign(wizardState.targetSettings, presets[preset]);

        // 更新 UI
        const gamutSelect = document.getElementById('wizard-target-gamut');
        const whiteSelect = document.getElementById('wizard-target-white');
        const gammaSelect = document.getElementById('wizard-target-gamma');

        if (gamutSelect) gamutSelect.value = wizardState.targetSettings.gamut;
        if (whiteSelect) whiteSelect.value = wizardState.targetSettings.whitePoint;
        if (gammaSelect) gammaSelect.value = wizardState.targetSettings.gamma;
    }

    updateStatus(t('应用预设: {preset}', {preset: preset}));
}

/**
 * 更新目标预设按钮状态（根据当前参数判断匹配哪个预设）
 */
function updateTargetPresetState() {
    const current = wizardState.targetSettings;

    // 检查是否匹配某个预设
    const presets = {
        'srgb': current.gamut === 'sRGB' && current.whitePoint === 'D65' && current.gamma === '2.2',
        'rec709': current.gamut === 'Rec709' && current.whitePoint === 'D65' && current.gamma === '2.4',
        'dci-p3': current.gamut === 'DCI_P3' && current.whitePoint === 'D63' && current.gamma === '2.6'
    };

    let matchedPreset = 'custom';
    for (const [preset, match] of Object.entries(presets)) {
        if (match) {
            matchedPreset = preset;
            break;
        }
    }

    // 更新按钮状态
    const presetButtons = document.querySelectorAll('.preset-btn');
    presetButtons.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.preset === matchedPreset);
    });
}

/**
 * 初始化探头设置步骤
 */
function initializeProbeSettingsStep() {
    // 同步探头状态（含"探头已连接，无需切换"提示条）
    updateWizardProbeStatus();

    // 刷新多探头列表（>1 台时显示切换选择器；
    // 列表有缓存则立即返回，后台枚举完成后经信号刷新）
    if (backend && backend.get_instrument_list) {
        const cached = parsePayload(backend.get_instrument_list(), []);
        populateWizardInstrumentList(cached);
    }

    // 应用当前探头设置到 UI
    const probeTypeSelect = document.getElementById('wizard-probe-type');
    const displayTypeSelect = document.getElementById('wizard-display-type');
    const measureDelayInput = document.getElementById('wizard-measure-delay');

    if (probeTypeSelect) probeTypeSelect.value = wizardState.probeSettings.probeType;
    if (displayTypeSelect) displayTypeSelect.value = wizardState.probeSettings.displayType;
    if (measureDelayInput) measureDelayInput.value = wizardState.probeSettings.measureDelay;

    // 监听变化并同步到后端
    if (probeTypeSelect) {
        probeTypeSelect.addEventListener('change', (e) => {
            wizardState.probeSettings.probeType = e.target.value;
            if (backend) backend.set_probe_type(e.target.value);
        });
    }
    if (displayTypeSelect) {
        displayTypeSelect.addEventListener('change', (e) => {
            wizardState.probeSettings.displayType = e.target.value;
            if (backend) backend.set_display_type(e.target.value);
        });
    }
    if (measureDelayInput) {
        measureDelayInput.addEventListener('change', (e) => {
            wizardState.probeSettings.measureDelay = parseInt(e.target.value) || 500;
            if (backend) backend.set_measure_delay(wizardState.probeSettings.measureDelay);
        });
    }

    // 连接按钮（切换逻辑：未连接→连接 / 已连接→断开 / 连接中→忽略点击）
    const btnConnect = document.getElementById('wizard-btn-connect');
    const btnCalibrate = document.getElementById('wizard-btn-calibrate');
    if (btnConnect) {
        btnConnect.addEventListener('click', () => {
            if (!backend || probeConnecting) return;
            if (probeConnected) {
                backend.disconnect_probe();
            } else {
                backend.connect_probe();
            }
        });
    }
    if (btnCalibrate) {
        btnCalibrate.addEventListener('click', () => {
            if (backend && probeConnected) backend.calibrate_probe();
        });
    }

    // 多探头切换选择器（检测到 >1 台校色仪时显示）
    const instrumentSelect = document.getElementById('wizard-instrument-select');
    if (instrumentSelect) {
        instrumentSelect.addEventListener('change', function() {
            const idx = parseInt(this.value, 10);
            if (Number.isFinite(idx) && backend && backend.select_and_connect_instrument) {
                backend.select_and_connect_instrument(idx);
            }
        });
        // 列表刷新完成信号（后台枚举 20+ 秒，完成后推送）
        if (backend.instrumentListUpdated) {
            backend.instrumentListUpdated.connect(function(listJson) {
                populateWizardInstrumentList(parsePayload(listJson, []));
            });
        }
    }

    // 加载修正文件列表
    loadWizardCorrectionFiles();

    // 导出报告按钮
    const btnExportPdf = document.getElementById('wizard-btn-export-pdf');
    const btnExportHtml = document.getElementById('wizard-btn-export-html');
    const btnExportJson = document.getElementById('wizard-btn-export-json');

    if (btnExportPdf) {
        btnExportPdf.addEventListener('click', () => {
            if (backend) backend.export_wizard_report_pdf();
        });
    }
    if (btnExportHtml) {
        btnExportHtml.addEventListener('click', () => {
            if (backend) backend.export_wizard_report_html();
        });
    }
    if (btnExportJson) {
        btnExportJson.addEventListener('click', () => {
            if (backend) backend.export_wizard_report_json();
        });
    }
}

/**
 * 更新向导内的探头状态
 */
function updateWizardProbeStatus() {
    const indicator = document.getElementById('wizard-probe-indicator');
    const statusText = document.getElementById('wizard-probe-status-text');
    const btnCalibrate = document.getElementById('wizard-btn-calibrate');
    const btnConnect = document.getElementById('wizard-btn-connect');
    const btnNext = document.getElementById('btn-next-step-3');
    const banner = document.getElementById('wizard-probe-connected-banner');

    if (!indicator) return;

    indicator.classList.remove('connected', 'error');

    if (probeConnected) {
        // 探头已连接（通常由启动时后台自动连接完成）
        indicator.classList.add('connected');
        const typeName = probeLastType === 'i1d3' ? 'i1 Display Pro' : probeLastType;
        if (statusText) statusText.textContent = t('已连接') + (typeName ? ` (${typeName})` : '');
        if (btnCalibrate) btnCalibrate.disabled = false;
        if (btnConnect) btnConnect.textContent = t('断开探头');
        // 提示用户无需重复操作，可直接进入下一步
        if (banner) {
            const bannerText = banner.querySelector('span:last-child') || banner;
            bannerText.textContent = t('探头已连接，无需切换，可直接点击"下一步"');
            banner.classList.remove('hidden');
        }
    } else if (probeConnecting) {
        // 连接进行中（首次枚举+握手实测约 30-60 秒，此期间显示"未连接"会误导用户）
        if (statusText) statusText.textContent = t('连接中...（首次连接约需 30-60 秒，请耐心等待）');
        if (btnCalibrate) btnCalibrate.disabled = true;
        if (btnConnect) {
            btnConnect.textContent = t('连接中...');
            btnConnect.disabled = true;
        }
        if (banner) banner.classList.add('hidden');
    } else {
        if (statusText) statusText.textContent = t('未连接');
        if (btnCalibrate) btnCalibrate.disabled = true;
        if (btnConnect) {
            btnConnect.textContent = t('连接探头');
            btnConnect.disabled = false;
        }
        if (banner) banner.classList.add('hidden');
    }

    // 更新下一步按钮状态（探头连接是可选的，修正文件也是可选的）
    if (btnNext) {
        // 对于显示器检测工作流，探头连接后才能测量
        // 但允许用户先设置参数，稍后连接探头
        btnNext.disabled = false;
    }
}

/**
 * 填充多探头切换选择器（仅当检测到 >1 台校色仪时显示）
 */
function populateWizardInstrumentList(devices) {
    const row = document.getElementById('wizard-instrument-row');
    const select = document.getElementById('wizard-instrument-select');
    if (!row || !select) return;

    if (!devices || devices.length <= 1) {
        // 单探头（或无探头）无需切换
        row.classList.add('hidden');
        return;
    }

    row.classList.remove('hidden');
    const prev = select.value;
    select.innerHTML = '';
    devices.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.index;
        opt.textContent = `[${d.index}] ${d.name || t('未知设备')}`;
        select.appendChild(opt);
    });
    if (prev && devices.some(d => String(d.index) === prev)) {
        select.value = prev;
    }
}

/**
 * 加载向导修正文件列表
 */
function loadWizardCorrectionFiles() {
    const select = document.getElementById('wizard-correction-select');
    if (!select || !backend) return;

    backend.get_correction_files().then(function(filesJson) {
        const files = parsePayload(filesJson, []);
        select.innerHTML = '<option value="" selected>无 (不启用)</option>';

        appendCorrectionOptionsGrouped(select, files, function(file) {
            return `${file.name} (${file.instrument || '未知'})`;
        });
    }).catch(function(e) {
        console.error('加载向导校正文件列表失败:', e);
    });
}

/**
 * 初始化测量步骤
 */
function initializeMeasureStep() {
    // 更新测量摘要
    updateMeasureSummary();

    // 自动打开测量窗口（浮动模式，可拖动）：
    // 让用户在点击"开始测量"前，从容地把窗口摆到探头贴合的位置。
    // 多屏时窗口出现在副屏（启动时已定位），单屏时出现在主屏。
    if (backend && backend.open_floating_window) {
        backend.open_floating_window();
    }

    // 显示摆放引导提示（点击"开始测量"后隐藏）
    const hint = document.getElementById('wizard-probe-placement-hint');
    if (hint && !isCycleMeasuring) hint.classList.remove('hidden');

    // 开始/停止测量按钮绑定已移至 initWizardUI（只绑一次，避免每次进入步骤 4 重复绑定）
}

/**
 * 更新测量摘要显示
 */
function updateMeasureSummary() {
    const workflow = wizardState.currentWorkflow;
    const target = wizardState.targetSettings;
    const probe = wizardState.probeSettings;

    // 更新摘要值
    const summaryGamut = document.getElementById('summary-gamut');
    const summaryWhite = document.getElementById('summary-white');
    const summaryGamma = document.getElementById('summary-gamma');
    const summaryPatches = document.getElementById('summary-patches');

    if (summaryGamut) summaryGamut.textContent = target.gamut || 'sRGB';
    if (summaryWhite) summaryWhite.textContent = target.whitePoint || 'D65';
    if (summaryGamma) summaryGamma.textContent = target.gamma || '2.2';
    if (summaryPatches) summaryPatches.textContent = target.patchCount === 'auto' ? t('自动') : target.patchCount;
}

/**
 * 开始向导测量
 */
function startWizardMeasurement() {
    // 并发保护：自由模式测量/校准进行中时不允许向导测量
    if (isCycleMeasuring || isCalibrating) {
        updateStatus(t('已有测量/校准进行中，请先停止后再开始向导测量'));
        return;
    }

    // 检查探头连接
    if (!probeConnected) {
        const dialog = createAlertDialog(
            '探头未连接',
            '请先连接探头后再开始测量。\n\n点击"连接探头"按钮进行连接。',
            'warning'
        );
        document.body.appendChild(dialog);
        return;
    }

    // 预检检查（如果未预检）
    if (!preflightReport) {
        if (confirm(t('尚未执行环境预检。建议在测量前运行预检。\n\n是否立即执行预检？'))) {
            runPreflightCheck();
            return;
        }
    }

    // 同步设置到后端
    syncWizardSettingsToBackend();

    // 隐藏"摆放探头"引导提示（测量即将开始，窗口即将全屏）
    document.getElementById('wizard-probe-placement-hint')?.classList.add('hidden');

    // 标记测量来源为向导（完成回调只驱动向导流程）
    measurementSource = 'wizard';

    // 测量前自动全屏显示色块窗口（多屏幕在副屏全屏；单屏幕保持浮动）
    if (backend) {
        backend.auto_fullscreen_for_measurement?.();
        dispatchCycleStart();
    }

    // 更新 UI
    const btnStart = document.getElementById('wizard-btn-start-measure');
    const btnStop = document.getElementById('wizard-btn-stop-measure');
    if (btnStart) btnStart.classList.add('hidden');
    if (btnStop) btnStop.classList.remove('hidden');

    wizardState.isWorkflowRunning = true;

    // 显示测量进度面板
    showMeasurementProgressPanel();
}

/**
 * 停止向导测量
 */
function stopWizardMeasurement() {
    if (backend) {
        backend.stop_cycle();
    }

    // 更新 UI
    const btnStart = document.getElementById('wizard-btn-start-measure');
    const btnStop = document.getElementById('wizard-btn-stop-measure');
    if (btnStart) btnStart.classList.remove('hidden');
    if (btnStop) btnStop.classList.add('hidden');

    wizardState.isWorkflowRunning = false;
    measurementSource = 'free';
    clearPatchMeasuringHighlight();
    hideMeasurementProgressPanel();
    backend?.exit_patch_window_fullscreen?.();

    // 窗口已恢复浮动：重新显示摆放引导，方便调整探头位置后重测
    if (!isCycleMeasuring) {
        document.getElementById('wizard-probe-placement-hint')?.classList.remove('hidden');
    }

    updateStatus(t('测量已停止'));
}

/**
 * 同步向导设置到后端
 */
function syncWizardSettingsToBackend() {
    if (!backend) return;

    // 目标设置
    const target = wizardState.targetSettings;
    backend.set_target_white(target.whitePoint);
    backend.set_target_gamma(target.gamma);

    // 灰阶级数 / 色块数量 / 采样策略（高级参数面板；此前未同步，
    // 导致向导里选择不生效，后端一直用默认值 21 级 / 99 色块）
    const graySteps = parseInt(document.getElementById('wizard-gray-steps')?.value, 10);
    backend.set_gray_steps(Number.isFinite(graySteps) ? graySteps : 21);

    const patchRaw = document.getElementById('wizard-patch-count')?.value || 'auto';
    const patchCount = resolveWizardPatchCount(patchRaw);
    backend.set_lut_patch_count(patchCount);

    const strategy = document.getElementById('wizard-sample-strategy')?.value || 'balanced';
    backend.set_lut_sample_strategy(strategy);
}

/**
 * 解析向导色块数量选择："自动推荐"按工作流/目标色域给出推荐值，其余原样返回
 */
function resolveWizardPatchCount(selectedValue) {
    const count = parseInt(selectedValue, 10);
    if (Number.isFinite(count)) return count;

    // 自动推荐：广色域目标需要更密的采样；ICC 快速校准用较少色块
    const workflow = wizardState.currentWorkflow;
    const gamut = (wizardState.targetSettings.gamut || '').toLowerCase();
    const wideGamut = gamut.includes('p3') || gamut.includes('2020') || gamut.includes('rec2020');

    if (workflow === 'icc') return wideGamut ? 512 : 288;
    if (workflow === 'validation') return 288;
    // LUT / 默认：标准 sRGB 用 512，广色域用 1024
    return wideGamut ? 1024 : 512;
}

// ========== 向导高级参数：灰阶级数 / 色块数量 / 采样策略 ==========
// 此前这三个下拉框未绑定任何事件（死 UI），选择不生效
document.getElementById('wizard-gray-steps')?.addEventListener('change', function() {
    const steps = parseInt(this.value, 10) || 21;
    wizardState.targetSettings.graySteps = String(steps);
    if (backend) backend.set_gray_steps(steps);
    updateStatus(t('灰阶级数: {steps} 级', {steps: steps}));
});

document.getElementById('wizard-patch-count')?.addEventListener('change', function() {
    const raw = this.value;
    const count = resolveWizardPatchCount(raw);
    wizardState.targetSettings.patchCount = raw;
    if (backend) backend.set_lut_patch_count(count);
    const strategy = document.getElementById('wizard-sample-strategy')?.value || 'balanced';
    updateStatus(t('LUT 测试色块: {count} 个, 采样策略: {strategy}', {
        count: count,
        strategy: raw === 'auto' ? strategy + ' (自动推荐)' : strategy
    }));
});

document.getElementById('wizard-sample-strategy')?.addEventListener('change', function() {
    const strategy = this.value || 'balanced';
    wizardState.targetSettings.sampleStrategy = strategy;
    if (backend) backend.set_lut_sample_strategy(strategy);
    updateStatus(t('LUT 采样策略: {strategy}', {strategy: strategy}));
});

/**
 * 初始化生成步骤
 */
function initializeGenerateStep() {
    updateGenerateStepContent(wizardState.currentWorkflow);
}

/**
 * 更新生成步骤内容（根据工作流类型）
 */
function updateGenerateStepContent(workflow) {
    const optionsDiv = document.getElementById('wizard-generate-options');
    if (!optionsDiv) return;

    let content = '';

    switch (workflow) {
        case 'icc':
            content = `
                <div class="generate-section">
                    <div class="generate-title">ICC Profile 设置</div>
                    <div class="form-row">
                        <label>Profile 类型:</label>
                        <select id="wizard-icc-type">
                            <option value="lut" selected>LUT 型 (推荐)</option>
                            <option value="matrix">矩阵型</option>
                        </select>
                    </div>
                    <div class="form-row">
                        <label>质量级别:</label>
                        <select id="wizard-icc-quality">
                            <option value="h" selected>High (高)</option>
                            <option value="m">Medium (中)</option>
                            <option value="u">Ultra (超高)</option>
                        </select>
                    </div>
                    <div class="form-row">
                        <label>保存路径:</label>
                        <input type="text" id="wizard-icc-path" placeholder="留空 = measurements 目录（可选完整 .icc 路径）">
                    </div>
                    <div class="generate-actions">
                        <button class="btn btn-primary btn-full" onclick="generateICCProfile()">生成 ICC Profile</button>
                    </div>
                </div>
            `;
            break;

        case 'lut':
            content = `
                <div class="generate-section">
                    <div class="generate-title">3D LUT 设置</div>
                    <div class="form-row">
                        <label>源色域:</label>
                        <select id="wizard-lut-source">
                            <option value="rec709" selected>Rec.709</option>
                            <option value="srgb">sRGB</option>
                            <option value="displayp3">Display P3</option>
                            <option value="dcip3">DCI-P3</option>
                            <option value="rec2020">Rec.2020</option>
                        </select>
                    </div>
                    <div class="form-row">
                        <label>LUT 尺寸:</label>
                        <select id="wizard-lut-size">
                            <option value="33" selected>33³ (标准)</option>
                            <option value="65">65³ (高精度)</option>
                        </select>
                    </div>
                    <div class="form-row">
                        <label>输出格式:</label>
                        <select id="wizard-lut-format">
                            <option value="cube" selected>.cube (Resolve/达芬奇)</option>
                            <option value="3dl">.3dl (10bit 整数)</option>
                            <option value="mga">.mga</option>
                            <option value="clf">.clf (Common LUT XML)</option>
                        </select>
                    </div>
                    <div class="form-row">
                        <label>保存路径:</label>
                        <input type="text" id="wizard-lut-path" placeholder="留空 = measurements 目录（可选完整 .cube 路径）">
                    </div>
                    <div class="generate-actions">
                        <button class="btn btn-primary btn-full" onclick="generate3DLUT()">生成 3D LUT</button>
                    </div>
                </div>
            `;
            break;

        case 'ccmx':
            content = `
                <div class="generate-section">
                    <div class="generate-title">CCMX 矩阵设置</div>
                    <div class="generate-info" style="margin-bottom: 8px; color: var(--text-secondary); font-size: 12px;">
                        需要两份已保存的测量数据：分光仪（基准）与色度计（目标）。
                        请先用两台探头分别完成循环测量并点击"保存数据"。
                    </div>
                    <div class="form-row">
                        <label>基准测量:</label>
                        <select id="wizard-ccmx-ref">
                            <option value="">选择分光仪测量数据</option>
                        </select>
                    </div>
                    <div class="form-row">
                        <label>目标测量:</label>
                        <select id="wizard-ccmx-target">
                            <option value="">选择色度计测量数据</option>
                        </select>
                    </div>
                    <div class="form-row">
                        <label>描述:</label>
                        <input type="text" id="wizard-ccmx-desc" placeholder="例如: i1d3 for LG OLED">
                    </div>
                    <div class="generate-actions">
                        <button class="btn btn-primary btn-full" onclick="generateCCMX()">生成 CCMX 矩阵</button>
                    </div>
                </div>
            `;
            break;

        default:
            content = `
                <div class="generate-section">
                    <div class="generate-title">测量数据已收集</div>
                    <div class="generate-info">
                        当前工作流不需要生成额外文件。\n测量数据已自动保存。
                    </div>
                </div>
            `;
    }

    optionsDiv.innerHTML = content;

    // CCMX：用已保存的测量历史填充基准/目标下拉框
    if (workflow === 'ccmx') {
        populateCcmxMeasurementSelects();
    }
}

/**
 * 填充 CCMX 生成的基准/目标测量数据下拉框（复用历史测量列表）
 */
function populateCcmxMeasurementSelects() {
    const refSelect = document.getElementById('wizard-ccmx-ref');
    const targetSelect = document.getElementById('wizard-ccmx-target');
    if (!refSelect || !targetSelect) return;

    const list = Array.isArray(historyMeasurements) ? historyMeasurements : [];
    for (const select of [refSelect, targetSelect]) {
        // 保留第一个占位 option
        while (select.options.length > 1) {
            select.remove(1);
        }
        list.forEach(item => {
            const option = document.createElement('option');
            option.value = item.id || '';
            // 与历史数据下拉一致的显示格式
            let label = (item.display_name && item.display_name.trim())
                ? item.display_name
                : `${formatTimestamp(item.timestamp)} - ${item.probe || ''}`;
            if (item.measure_mode) {
                label += ` [${item.measure_mode}]`;
            }
            option.textContent = label;
            select.appendChild(option);
        });
    }
}

// ==============================================================================
// 向导步骤 5：生成（ICC / 3D LUT / CCMX）—— 调用后端真实生成能力
// ==============================================================================

/**
 * 生成中的按钮禁用状态（生成按钮 + 底部 CTA 的"下一步"）
 */
function setWizardGenerateButtonsDisabled(disabled) {
    document.querySelectorAll('#wizard-generate-actions-btn, #wizard-generate-options .generate-actions .btn')
        .forEach(btn => { btn.disabled = disabled; });
}

/**
 * 生成成功的统一入口：记录产物、启用步骤 5 的"下一步"、引导模式自动进入验证步骤
 * 由 handleFileCreated（ICC/LUT）与 handleLogMessage（CCMX）触发
 */
function maybeCompleteWizardGenerateStep(result) {
    window.lastGeneratedFile = {
        path: result.filepath || '',
        format: result.format || ''
    };
    setWizardGenerateButtonsDisabled(false);
    markStepCompleted(5);
    const btnNext5 = document.getElementById('btn-next-step-5');
    if (btnNext5) {
        btnNext5.disabled = false;
    }
    updateWizardProgress();

    if (result.filepath) {
        updateStatus(t('生成完成: {result_filepath}', {result_filepath: result.filepath}));
    }

    // 引导模式：自动进入验证步骤并显示摘要
    if (uiMode === 'guided') {
        goToStep(6);
        renderValidationSummary(result);
    }
}

/**
 * 生成失败：恢复按钮状态（错误详情已由 handleFileCreated/日志显示）
 */
function maybeFailWizardGenerateStep() {
    setWizardGenerateButtonsDisabled(false);
    window._ccmxGeneratePending = false;
}

/**
 * 从时间戳生成默认文件名
 */
function wizardDefaultFileName(prefix, ext) {
    const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '');
    return `${prefix}_${ts}${ext}`;
}

/**
 * 把用户输入的保存路径规整为完整文件路径
 * @returns {string} 完整路径；空字符串表示使用后端默认目录
 */
function resolveWizardOutputPath(pathInput, defaultName) {
    const trimmed = (pathInput || '').trim();
    if (!trimmed) return '';
    if (/\/$/.test(trimmed)) {
        return trimmed + defaultName;  // 目录 → 拼默认文件名
    }
    return trimmed;  // 视为完整文件路径
}

/**
 * 生成 ICC Profile（调用后端 colprof：TI3 → ICC）
 */
function generateICCProfile() {
    if (!backend) return;
    if (!measurementData.gamut.white) {
        showAlertDialog('没有测量数据', '请先完成步骤 4 的色块测量，再生成 ICC Profile。', 'warning');
        return;
    }

    const type = document.getElementById('wizard-icc-type')?.value || 'lut';
    const quality = document.getElementById('wizard-icc-quality')?.value || 'h';
    const fileName = wizardDefaultFileName('topos_profile', '.icc');
    const filePath = resolveWizardOutputPath(
        document.getElementById('wizard-icc-path')?.value, fileName);

    setWizardGenerateButtonsDisabled(true);
    updateStatus(t('正在生成 ICC Profile（TI3 → colprof → ICC）…'));
    backend.create_icc_file(JSON.stringify({
        format: 'icc',
        file_path: filePath,
        file_name: fileName,
        profile_type: type,     // lut / matrix（后端映射为 colprof -al / -am）
        quality: quality,       // h / m / u（colprof -q）
        apply_profile: false
    }));
}

/**
 * 生成 3D LUT（调用后端 collink：TI3 → ICC → 3D LUT）
 */
function generate3DLUT() {
    if (!backend) return;
    if (!measurementData.gamut.white) {
        showAlertDialog('没有测量数据', '请先完成步骤 4 的色块测量，再生成 3D LUT。', 'warning');
        return;
    }

    const sourceRaw = document.getElementById('wizard-lut-source')?.value || 'rec709';
    const sourceMap = { rec709: 'Rec709', srgb: 'sRGB', displayp3: 'P3', dcip3: 'P3', rec2020: 'Rec2020' };
    const formatRaw = document.getElementById('wizard-lut-format')?.value || 'cube';
    const formatExtMap = { cube: '.cube', '3dl': '.3dl', mga: '.mga', clf: '.clf' };
    const fileName = wizardDefaultFileName('topos_lut', formatExtMap[formatRaw] || '.cube');
    const filePath = resolveWizardOutputPath(
        document.getElementById('wizard-lut-path')?.value, fileName);

    setWizardGenerateButtonsDisabled(true);
    updateStatus(t('正在生成 3D LUT（TI3 → ICC → collink）…'));
    backend.create_lut_file(JSON.stringify({
        format: formatRaw,
        file_path: filePath,
        file_name: fileName,
        source_gamut: sourceMap[sourceRaw] || 'Rec709',
        rendering_intent: 'r',
        lut_size: parseInt(document.getElementById('wizard-lut-size')?.value) || 33,
        target_gamma: wizardState.targetSettings.gamma || '2.2'
    }));
}

/**
 * 生成 CCMX 矩阵（调用后端 ccxxmake，结果通过日志信号回传）
 */
function generateCCMX() {
    if (!backend) return;
    const refId = document.getElementById('wizard-ccmx-ref')?.value;
    const targetId = document.getElementById('wizard-ccmx-target')?.value;
    if (!refId || !targetId) {
        showAlertDialog('缺少测量数据',
            '请先选择基准（分光仪）与目标（色度计）测量数据。\n\n两份数据需已通过"保存数据"保存到历史记录。',
            'warning');
        return;
    }
    if (refId === targetId) {
        showAlertDialog('数据重复', '基准与目标不能选择同一份测量数据。', 'warning');
        return;
    }

    window._ccmxGeneratePending = true;
    setWizardGenerateButtonsDisabled(true);
    updateStatus(t('正在生成 CCMX 矩阵（ccxxmake）…'));
    backend.generate_ccmx_from_measurements(refId, targetId);
}

/**
 * 渲染验证步骤摘要（生成完成后自动调用）
 */
function renderValidationSummary(result) {
    const resultsDiv = document.getElementById('wizard-validate-results');
    if (!resultsDiv) return;

    const formatName = { ICC: 'ICC Profile', CUBE: '3D LUT (.cube)', '3DL': '3D LUT (.3dl)', CCMX: 'CCMX 校正矩阵' }[result.format] || result.format || '文件';
    const target = wizardState.targetSettings;
    const white = measurementData.gamut.white;

    resultsDiv.innerHTML = `
        <div class="validate-summary">
            <div class="report-row">
                <span class="report-label">生成产物:</span>
                <span class="report-value">${formatName}</span>
            </div>
            <div class="report-row">
                <span class="report-label">文件路径:</span>
                <span class="report-value">${result.filepath || 'corrections 目录（详见日志）'}</span>
            </div>
            <div class="report-row">
                <span class="report-label">目标色域:</span>
                <span class="report-value">${target.gamut}</span>
            </div>
            <div class="report-row">
                <span class="report-label">目标白点 / Gamma:</span>
                <span class="report-value">${target.whitePoint} / ${target.gamma}</span>
            </div>
            ${white ? `
            <div class="report-row">
                <span class="report-label">实测白点:</span>
                <span class="report-value">x=${white.x?.toFixed(4) ?? '--'}, y=${white.y?.toFixed(4) ?? '--'}, Y=${white.Y?.toFixed(2) ?? '--'} cd/m²</span>
            </div>` : ''}
            <div class="validate-hint" style="margin-top: 8px; color: var(--text-secondary); font-size: 12px;">
                💡 可安装生成的 ICC 后运行"验证"工作流，对比校准前后的色域与白点偏差。
            </div>
        </div>
    `;
}

/**
 * 初始化验证步骤
 */
function initializeValidateStep() {
    const resultsDiv = document.getElementById('wizard-validate-results');
    if (!resultsDiv) return;

    resultsDiv.innerHTML = `
        <div class="validate-placeholder">
            <div class="validate-icon">📊</div>
            <div class="validate-text">验证测量将在生成完成后自动进行</div>
            <div class="validate-hint">请先完成上一步的生成操作</div>
        </div>
    `;
}

/**
 * 初始化报告步骤
 */
function initializeReportStep() {
    const summaryDiv = document.getElementById('wizard-report-summary');
    if (!summaryDiv) return;

    // 根据工作流生成报告摘要
    const workflow = wizardState.currentWorkflow;
    const target = wizardState.targetSettings;

    summaryDiv.innerHTML = `
        <div class="report-header">
            <h4>${wizardState.workflows[workflow].name} - 完成报告</h4>
        </div>
        <div class="report-details">
            <div class="report-row">
                <span class="report-label">目标色域:</span>
                <span class="report-value">${target.gamut}</span>
            </div>
            <div class="report-row">
                <span class="report-label">目标白点:</span>
                <span class="report-value">${target.whitePoint}</span>
            </div>
            <div class="report-row">
                <span class="report-label">目标 Gamma:</span>
                <span class="report-value">${target.gamma}</span>
            </div>
            <div class="report-row">
                <span class="report-label">测量时间:</span>
                <span class="report-value">${new Date().toLocaleString()}</span>
            </div>
        </div>
    `;
}

/**
 * 设置高级参数展开按钮
 */
function setupAdvancedToggle(buttonId, paramsId) {
    const button = document.getElementById(buttonId);
    const params = document.getElementById(paramsId);

    if (!button || !params) return;

    button.addEventListener('click', () => {
        const isExpanded = !params.classList.contains('hidden');
        params.classList.toggle('hidden');
        button.classList.toggle('expanded');

        const toggleIcon = button.querySelector('.toggle-icon');
        if (toggleIcon) {
            toggleIcon.textContent = isExpanded ? '▶' : '▼';
        }
    });
}

/**
 * 设置步骤导航按钮
 */
function setupStepNavigation() {
    // 各步骤的下一步按钮
    for (let i = 1; i <= 7; i++) {
        const btnNext = document.getElementById(`btn-next-step-${i}`);
        const btnPrev = document.getElementById(`btn-prev-step-${i}`);

        if (btnNext) {
            btnNext.addEventListener('click', () => {
                if (validateStep(i)) {
                    markStepCompleted(i);
                    goToNextStep();
                }
            });
        }

        if (btnPrev) {
            btnPrev.addEventListener('click', () => {
                goToPreviousStep();
            });
        }
    }

    // 完成和新工作流按钮
    const btnComplete = document.getElementById('wizard-btn-complete');
    const btnNewWorkflow = document.getElementById('wizard-btn-new-workflow');
    if (btnComplete) {
        btnComplete.addEventListener('click', () => {
            completeWorkflow();
        });
    }
    if (btnNewWorkflow) {
        btnNewWorkflow.addEventListener('click', () => {
            resetWizard();
        });
    }
}

/**
 * 验证步骤是否完成
 */
function validateStep(stepNum) {
    switch (stepNum) {
        case 1: // 预检
            if (!preflightReport) {
                showAlertDialog('请先运行预检', '点击"开始预检"按钮检查环境配置。');
                return false;
            }
            if (!preflightReport.can_proceed && !preflightOverrideEnabled) {
                showAlertDialog('预检未通过', '请修复阻断项或启用高级覆盖。');
                return false;
            }
            return true;

        case 2: // 目标设置
            // 目标设置总有值，无需特殊验证
            return true;

        case 3: // 探头/修正
            // 探头连接在开始测量时检查
            return true;

        case 4: // 测量
            if (!measurementData.gamut.white && currentMeasureMode !== 'validation') {
                showAlertDialog('请先完成测量', '点击"开始测量"按钮进行色块测量。');
                return false;
            }
            return true;

        case 5: // 生成
            // 生成型工作流必须有产物（按钮默认禁用，此处兜底）
            if ((wizardState.currentWorkflow === 'icc' || wizardState.currentWorkflow === 'lut')
                && !window.lastGeneratedFile) {
                showAlertDialog('请先生成文件', '请设置参数并点击"生成"按钮，成功后再进入验证步骤。');
                return false;
            }
            return true;

        case 6: // 验证
            return true;

        default:
            return true;
    }
}

/**
 * 标记步骤已完成
 */
function markStepCompleted(stepNum) {
    if (!wizardState.completedSteps.includes(stepNum)) {
        wizardState.completedSteps.push(stepNum);
    }
}

/**
 * 获取下一个步骤
 */
function getNextStep() {
    const workflowConfig = wizardState.workflows[wizardState.currentWorkflow];
    const currentIdx = workflowConfig.steps.indexOf(wizardState.currentStep);
    if (currentIdx < workflowConfig.steps.length - 1) {
        return workflowConfig.steps[currentIdx + 1];
    }
    return null;
}

/**
 * 切换到下一步
 */
function goToNextStep() {
    const nextStep = getNextStep();
    if (nextStep) {
        goToStep(nextStep);
    }
}

/**
 * 切换到上一步
 */
function goToPreviousStep() {
    const workflowConfig = wizardState.workflows[wizardState.currentWorkflow];
    const currentIdx = workflowConfig.steps.indexOf(wizardState.currentStep);
    if (currentIdx > 0) {
        goToStep(workflowConfig.steps[currentIdx - 1]);
    }
}

/**
 * 完成工作流
 */
function completeWorkflow() {
    // 保存数据
    if (backend) {
        backend.save_current_data();
    }

    // 显示完成动画
    showMeasurementCompleteAnimation();

    // 更新状态
    wizardState.isWorkflowRunning = false;

    // 新用户引导完成提示
    if (wizardState.newUserGuide.isActive) {
        showNewUserTip('workflow-complete', '恭喜！您已完成首个工作流。\n可以导出报告或开始新的校准任务。');
        wizardState.newUserGuide.isActive = false;
    }

    updateStatus(t('工作流已完成！'));
}

/**
 * 重置向导
 */
function resetWizard() {
    wizardState.currentStep = 1;
    wizardState.completedSteps = [];
    wizardState.isWorkflowRunning = false;

    // 重置生成产物记录与生成按钮状态
    window.lastGeneratedFile = null;
    window._ccmxGeneratePending = false;
    setWizardGenerateButtonsDisabled(false);

    // 重置测量数据
    resetMeasurementProgressState();

    // 选择第一个工作流
    selectWorkflow('gamut');
}

/**
 * 显示新用户引导提示
 */
function showNewUserTip(tipId, message) {
    // 记录并持久化已展示的提示（跨会话只提示一次）
    if (!wizardState.newUserGuide.tipsShown.includes(tipId)) {
        wizardState.newUserGuide.tipsShown.push(tipId);
    }
    try {
        localStorage.setItem(NEW_USER_TIPS_STORAGE_KEY, JSON.stringify(wizardState.newUserGuide.tipsShown));
    } catch (e) { /* ignore */ }

    if (!wizardState.newUserGuide.isActive) {
        return; // 引导未激活（如高级模式）时不弹提示
    }

    const tipDiv = document.createElement('div');
    tipDiv.className = 'new-user-tip';
    tipDiv.id = `tip-${tipId}`;
    tipDiv.innerHTML = `
        <div class="tip-content">
            <div class="tip-icon">💡</div>
            <div class="tip-message">${message}</div>
            <button class="tip-close-btn" onclick="closeNewUserTip('${tipId}')">×</button>
        </div>
    `;

    document.body.appendChild(tipDiv);

    // 5秒后自动消失
    setTimeout(() => {
        closeNewUserTip(tipId);
    }, 5000);
}

/**
 * 关闭新用户引导提示
 */
function closeNewUserTip(tipId) {
    const tipDiv = document.getElementById(`tip-${tipId}`);
    if (tipDiv) {
        tipDiv.remove();
    }
}

/**
 * 更新覆盖警告显示
 */
function updateOverrideWarningDisplay(enabled) {
    const warningDiv = document.getElementById('preflight-override-warning');
    if (warningDiv) {
        warningDiv.classList.toggle('hidden', !enabled);
    }
}

/**
 * 处理预检完成后的向导更新
 */
function handlePreflightCompletedForWizard(resultJson) {
    const report = parsePayload(resultJson);
    preflightReport = report;

    // 渲染结果到向导内
    renderWizardPreflightResults(report);

    // 更新按钮状态
    updatePreflightStepButtons();
}

/**
 * 处理测量完成后的向导更新
 */
function handleMeasurementCompletedForWizard() {
    // 标记测量步骤完成
    markStepCompleted(4);

    // 更新进度
    updateWizardProgress();

    // 显示下一步按钮
    const btnNext4 = document.getElementById('btn-next-step-4');
    if (btnNext4) {
        btnNext4.disabled = false;
    }

    // 根据工作流自动进入下一步骤
    const workflow = wizardState.currentWorkflow;
    if (workflow === 'icc' || workflow === 'lut') {
        // ICC/LUT 工作流：测量完成后进入生成步骤
        goToStep(5);
    } else if (workflow === 'gamut' || workflow === 'ccmx') {
        // 域检测/CCMX：直接进入报告步骤
        goToStep(7);
    }
}

// 导出测量进度相关函数（供全局调用）
window.showMeasurementProgressPanel = showMeasurementProgressPanel;
window.hideMeasurementProgressPanel = hideMeasurementProgressPanel;
window.updateMeasurementProgressPanel = updateMeasurementProgressPanel;
window.handleCycleProgressEnhanced = handleCycleProgressEnhanced;
window.handleMeasurementResultEnhanced = handleMeasurementResultEnhanced;
window.remeasureCurrentPatch = remeasureCurrentPatch;
window.skipCurrentPatch = skipCurrentPatch;
window.stopAndSaveCheckpoint = stopAndSaveCheckpoint;
window.closeCheckpointDialog = closeCheckpointDialog;
window.confirmStopAndSave = confirmStopAndSave;
window.setMeasurementError = setMeasurementError;
window.clearMeasurementError = clearMeasurementError;
window.resetMeasurementProgressState = resetMeasurementProgressState;
window.showMeasurementCompleteAnimation = showMeasurementCompleteAnimation;

// 导出向导相关函数（供全局调用）
window.initWizardUI = initWizardUI;
window.selectWorkflow = selectWorkflow;
window.goToStep = goToStep;
window.applyTargetPreset = applyTargetPreset;
window.startWizardMeasurement = startWizardMeasurement;
window.stopWizardMeasurement = stopWizardMeasurement;
window.closeAlertDialog = closeAlertDialog;
window.closeNewUserTip = closeNewUserTip;
window.showNewUserTip = showNewUserTip;
window.completeWorkflow = completeWorkflow;
window.resetWizard = resetWizard;
window.handlePreflightCompletedForWizard = handlePreflightCompletedForWizard;
window.handleMeasurementCompletedForWizard = handleMeasurementCompletedForWizard;

// 导出双模式与生成相关函数（inline onclick / 调试用）
window.toggleAdvancedMode = toggleAdvancedMode;
window.applyUiMode = applyUiMode;
window.generateICCProfile = generateICCProfile;
window.generate3DLUT = generate3DLUT;
window.generateCCMX = generateCCMX;

// ========== ICC Workflow 信号处理函数 (P4-B 集成) ==========

/**
 * ICC Workflow 状态变化处理
 */
function handleICCWorkflowStateChanged(stateJson) {
    const data = parsePayload(stateJson);
    console.log('ICC Workflow 状态变化:', data.state, '(前状态:', data.previous, ')');

    // 更新向导步骤状态
    const stateToStepMap = {
        'preflight': 1,
        'calibrating': 2,
        'generating_patches': 2,
        'measuring': 4,
        'generating_profile': 5,
        'verifying': 6,
        'completed': 7,
        'failed': -1,
        'suspended': -2,
    };

    const targetStep = stateToStepMap[data.state] || -1;
    if (targetStep > 0 && wizardState.currentWorkflow === 'icc') {
        goToStep(targetStep);
    }

    // 失败或暂停时显示提示
    if (data.state === 'failed') {
        showAlertDialog('ICC Profile 生成失败', '请检查错误信息并重试', 'error');
    } else if (data.state === 'suspended') {
        showAlertDialog('ICC Profile 工作流已暂停', '可以从断点恢复继续工作流', 'warning');
    }
}

/**
 * ICC Workflow 进度更新处理
 */
function handleICCWorkflowProgress(progressJson) {
    const data = parsePayload(progressJson);
    console.log('ICC Workflow 进度:', data.percent, '% -', data.step);

    // 更新进度显示
    if (wizardState.currentWorkflow === 'icc') {
        updateMeasurementProgressPanel(data.percent, data.step);
    }

    // 更新状态栏
    updateStatus(`ICC Profile: ${data.step} (${data.percent}%)`);
}

/**
 * ICC Workflow 完成处理
 */
function handleICCWorkflowCompleted(resultJson) {
    const data = parsePayload(resultJson);
    console.log('ICC Workflow 完成:', data);

    // 显示完成消息
    updateStatus(t('ICC Profile 生成完成'));

    // 更新向导状态
    if (wizardState.currentWorkflow === 'icc') {
        markStepCompleted(7);
        updateWizardProgress();

        // 显示生成的 artifacts
        const resultsDiv = document.getElementById('wizard-report-summary');
        if (resultsDiv) {
            let artifactsHtml = '<div class="artifact-list">';
            if (data.artifacts && data.artifacts.length > 0) {
                data.artifacts.forEach(artifact => {
                    artifactsHtml += `<div class="artifact-item">
                        <span class="artifact-type">${artifact.type}</span>
                        <span class="artifact-path">${artifact.path}</span>
                        ${artifact.size ? `<span class="artifact-size">(${Math.round(artifact.size / 1024)} KB)</span>` : ''}
                    </div>`;
                });
            }
            artifactsHtml += '</div>';
            resultsDiv.innerHTML = artifactsHtml;
        }
    }

    // 隐藏进度面板
    hideMeasurementProgressPanel();
}

/**
 * 报告导出完成处理
 */
function handleReportExportCompleted(resultJson) {
    const data = parsePayload(resultJson);
    console.log('报告导出完成:', data);

    if (data.success) {
        updateStatus(t('{data_format_toUpperCase} 报告已导出: {data_path}', {data_format_toUpperCase: data.format.toUpperCase(), data_path: data.path}));
        // 显示成功提示
        showAlertDialog('导出成功', `报告已成功导出到:\n${data.path}\n\n格式: ${data.format.toUpperCase()}`);
    } else {
        updateStatus(t('导出失败: {data_error}', {data_error: data.error}));
        // 显示错误提示
        let errorMessage = data.error;
        if (data.suggestion) {
            errorMessage += `\n\n建议: ${data.suggestion}`;
        }
        showAlertDialog('导出失败', errorMessage);
    }
}

/**
 * ICC Workflow 失败处理
 */
function handleICCWorkflowFailed(errorJson) {
    const data = parsePayload(errorJson);
    console.error('ICC Workflow 失败:', data.error, '(', data.error_code, ')');

    // 显示错误
    showAlertDialog('ICC Profile 生成失败', data.error + (data.suggestion ? '\n建议: ' + data.suggestion : ''), 'error');

    // 更新状态栏
    updateStatus(t('ICC Profile 失败: {data_error}', {data_error: data.error}));

    // 如果可恢复，显示恢复选项
    if (data.recoverable) {
        const resumeBtn = document.createElement('button');
        resumeBtn.className = 'btn btn-primary';
        resumeBtn.textContent = t('从断点恢复');
        resumeBtn.onclick = () => {
            if (backend && data.session_dir) {
                backend.resume_icc_workflow(data.session_dir);
            }
        };
        // 添加到对话框
    }

    // 隐藏进度面板
    hideMeasurementProgressPanel();
}

/**
 * ICC Workflow 会话信息处理
 */
function handleICCWorkflowSessionInfo(infoJson) {
    const data = parsePayload(infoJson);
    console.log('ICC Workflow 会话信息:', data);

    // 存储会话信息
    window.iccWorkflowSession = data;
}

/**
 * 启动 ICC Workflow
 */
function startICCWorkflow() {
    if (!backend) {
        console.error('Backend 未初始化');
        return;
    }

    // 从 UI 收集配置
    const config = {
        preset: document.getElementById('icc-preset')?.value || 'general',
        white_point: document.getElementById('icc-white-point')?.value || 'D65',
        gamma: document.getElementById('icc-gamma')?.value || '2.2',
        brightness: document.getElementById('icc-brightness')?.value || null,
        patch_set: document.getElementById('icc-patch-set')?.value || 'standard',
        profile_name: document.getElementById('icc-profile-name')?.value || 'Topos Display Profile',
        use_dispcal: document.getElementById('icc-use-dispcal')?.checked ?? true,
        display_index: parseInt(document.getElementById('display-index')?.value) || 1,
        instrument_port: parseInt(document.getElementById('instrument-port')?.value) || 1,
        correction_file: document.getElementById('correction-file-select')?.value || null,
    };

    // 处理自定义白点
    if (config.white_point === 'custom') {
        const x = parseFloat(document.getElementById('icc-white-point-x')?.value) || 0.3127;
        const y = parseFloat(document.getElementById('icc-white-point-y')?.value) || 0.329;
        config.white_point_xy = [x, y];
    }

    const configJson = JSON.stringify(config);
    backend.start_icc_workflow(configJson).then(function(resultJson) {
        const result = parsePayload(resultJson);
        if (result.success) {
            updateStatus(t('ICC Profile 工作流已启动'));
            showMeasurementProgressPanel(0, '正在初始化...');
        } else {
            showAlertDialog('启动失败', result.error, 'error');
        }
    }).catch(function(e) {
        console.error('启动 ICC Workflow 失败:', e);
        showAlertDialog('启动失败', e.toString(), 'error');
    });
}

/**
 * 暂停 ICC Workflow
 */
function pauseICCWorkflow() {
    if (!backend) return;

    backend.pause_icc_workflow().then(function(success) {
        if (success) {
            updateStatus(t('ICC Profile 工作流已暂停'));
            showAlertDialog('工作流已暂停', '可以从断点恢复继续', 'warning');
        }
    });
}

/**
 * 恢复 ICC Workflow
 */
function resumeICCWorkflow(sessionDir) {
    if (!backend) return;

    backend.resume_icc_workflow(sessionDir).then(function(resultJson) {
        const result = parsePayload(resultJson);
        if (result.success) {
            updateStatus(t('ICC Profile 工作流已恢复'));
        } else {
            showAlertDialog('恢复失败', result.error, 'error');
        }
    });
}

/**
 * 取消 ICC Workflow
 */
function cancelICCWorkflow() {
    if (!backend) return;

    backend.cancel_icc_workflow().then(function(success) {
        if (success) {
            updateStatus(t('ICC Profile 工作流已取消'));
            hideMeasurementProgressPanel();
            resetWizard();
        }
    });
}

/**
 * 获取 ICC Workflow 预设列表
 */
function loadICCPresets() {
    if (!backend) return;

    backend.get_icc_workflow_presets().then(function(presetsJson) {
        const data = parsePayload(presetsJson);
        const select = document.getElementById('icc-preset');
        if (select && data.presets) {
            select.innerHTML = '';
            Object.entries(data.presets).forEach(([key, preset]) => {
                const option = document.createElement('option');
                option.value = key;
                option.textContent = preset.description || key;
                select.appendChild(option);
            });
        }
    });
}

/**
 * 获取可恢复的 ICC Workflow 会话列表
 */
function loadRecoverableICCSessions() {
    if (!backend) return;

    backend.list_icc_recoverable_sessions().then(function(sessionsJson) {
        const data = parsePayload(sessionsJson);
        const listDiv = document.getElementById('icc-recoverable-sessions');
        if (listDiv && data.sessions) {
            listDiv.innerHTML = '';
            data.sessions.forEach(session => {
                const item = document.createElement('div');
                item.className = 'session-item';
                item.innerHTML = `
                    <span class="session-id">${session.session_id}</span>
                    <span class="session-state">${session.state}</span>
                    <span class="session-date">${session.created_at}</span>
                    <button class="btn btn-sm btn-primary" onclick="resumeICCWorkflow('${session.session_dir}')">恢复</button>
                `;
                listDiv.appendChild(item);
            });
        }
    });
}

// 导出 ICC Workflow 函数（供全局调用）
window.handleICCWorkflowStateChanged = handleICCWorkflowStateChanged;
window.handleICCWorkflowProgress = handleICCWorkflowProgress;
window.handleICCWorkflowCompleted = handleICCWorkflowCompleted;
window.handleICCWorkflowFailed = handleICCWorkflowFailed;
window.handleICCWorkflowSessionInfo = handleICCWorkflowSessionInfo;
window.startICCWorkflow = startICCWorkflow;
window.pauseICCWorkflow = pauseICCWorkflow;
window.resumeICCWorkflow = resumeICCWorkflow;
window.cancelICCWorkflow = cancelICCWorkflow;
window.loadICCPresets = loadICCPresets;
window.loadRecoverableICCSessions = loadRecoverableICCSessions;
// ==============================================================================
// AutoCal 自动校准闭环 (P1 集成)
// ==============================================================================

// 状态变量（顶层作用域，供 DOMContentLoaded 内的按钮监听与本区处理函数共享）
let ddcConnected = false;
let autocalRunning = false;

function updateAutoCalButtons() {
    const startBtn = document.getElementById('btn-autocal-start');
    const stopBtn = document.getElementById('btn-autocal-stop');
    const snapshotBtn = document.getElementById('btn-ddc-snapshot');
    const rollbackBtn = document.getElementById('btn-ddc-rollback');
    if (startBtn) startBtn.disabled = !ddcConnected || autocalRunning;
    if (stopBtn) stopBtn.disabled = !autocalRunning;
    if (snapshotBtn) snapshotBtn.disabled = !ddcConnected || autocalRunning;
    if (rollbackBtn) rollbackBtn.disabled = !ddcConnected || autocalRunning;
}

const AUTOCAL_STATE_LABELS = {
    'idle': '就绪',
    'preflight': '预检',
    'baseline': '基线测量',
    'solving': '计算调整方案',
    'applying': '写入显示器参数',
    'verifying': '验证调整效果',
    'iterating': '迭代调整',
    'completed': '校准完成',
    'failed': '校准失败',
    'rollback': '已回滚',
    'cancelled': '已取消'
};

function handleAutoCalStateChanged(stateJson) {
    const data = parsePayload(stateJson);
    const label = AUTOCAL_STATE_LABELS[data.state] || data.state;
    updateStatus(`AutoCal: ${label}`);
    const textEl = document.getElementById('autocal-progress-text');
    if (textEl) textEl.textContent = t('阶段: {label}', {label: label});

    if (data.state === 'baseline' || data.state === 'verifying' || data.state === 'preflight') {
        // 运行中状态（由 progress 驱动按钮，这里兜底）
        if (typeof autocalSetRunning === 'function') autocalSetRunning(true);
    }
}

function handleAutoCalProgress(progressJson) {
    const data = parsePayload(progressJson);
    const fill = document.getElementById('autocal-progress-fill');
    const textEl = document.getElementById('autocal-progress-text');
    if (fill && typeof data.percent === 'number' && data.percent >= 0) {
        fill.style.width = `${Math.min(100, Math.max(0, data.percent))}%`;
    }
    if (textEl && data.message) textEl.textContent = data.message;
}

function handleAutoCalFinished(resultJson) {
    const data = parsePayload(resultJson);
    if (typeof autocalSetRunning === 'function') autocalSetRunning(false);

    const fill = document.getElementById('autocal-progress-fill');
    const textEl = document.getElementById('autocal-progress-text');
    const session = data.session || {};
    const state = data.state || (session.state || '');
    const stateLabel = AUTOCAL_STATE_LABELS[state] || state;

    if (data.success) {
        if (fill) fill.style.width = '100%';
        const iterations = (session.iterations || []).length;
        const final = session.final_result || {};
        const summary = final.summary || '';
        let msg = `自动校准完成（${iterations} 轮迭代）`;
        if (final.delta_e_avg !== undefined) msg += `，平均 ΔE ${Number(final.delta_e_avg).toFixed(2)}`;
        if (textEl) textEl.textContent = msg;
        updateStatus(msg);
        showAlertDialog('自动校准完成', msg + (summary ? `\n${summary}` : ''), 'success');
    } else {
        if (fill) fill.style.width = '0%';
        const errMsg = data.error || session.error_message || '未知错误';
        if (textEl) textEl.textContent = `${stateLabel}: ${errMsg}`;
        updateStatus(`AutoCal ${stateLabel}: ${errMsg}`);
        showAlertDialog('自动校准未完成', errMsg +
            (session.manual_guide ? '\n可按手动调整指导操作显示器 OSD' : ''), 'error');
    }

    // 控制项最终值（便于核对）
    if (session.iterations && session.iterations.length > 0) {
        const lastIter = session.iterations[session.iterations.length - 1];
        if (lastIter.snapshot && lastIter.snapshot.values) {
            const vals = Object.entries(lastIter.snapshot.values)
                .map(([k, v]) => `${k}=${v}`).join(', ');
            console.log('AutoCal 最终控制值:', vals);
        }
    }
}

function handleDisplayControlUpdated(resultJson) {
    const data = parsePayload(resultJson);
    const statusEl = document.getElementById('ddc-status');

    switch (data.type) {
        case 'connect': {
            if (data.success) {
                ddcConnected = true;
                const caps = data.capabilities;
                const writable = caps ? (caps.capabilities || []).filter(c => c.writable) : [];
                let label = `已连接（${writable.length} 个可控项）`;
                if (data.is_fake) label = '模拟模式（DDC 不可用，仅演练）';
                if (statusEl) statusEl.textContent = label;
                updateStatus(`DDC/CI ${label}`);
            } else {
                ddcConnected = false;
                if (statusEl) statusEl.textContent = t('连接失败: {data_error}', {data_error: data.error || t('未知错误')});
                updateStatus(t('DDC/CI 连接失败: {data_error}', {data_error: data.error || ''}));
            }
            updateAutoCalButtons();
            break;
        }
        case 'capabilities': {
            ddcConnected = !!data.connected;
            if (statusEl) {
                const caps = data.capabilities;
                if (data.connected && caps) {
                    const writable = (caps.capabilities || []).filter(c => c.writable);
                    statusEl.textContent = t('已连接（{writable_length} 个可控项）', {writable_length: writable.length});
                } else {
                    statusEl.textContent = t('未连接');
                }
            }
            updateAutoCalButtons();
            break;
        }
        case 'write': {
            updateStatus(data.success ? t('已写入 {data_name} = {data_value}', {data_name: data.name, data_value: data.value}) : t('写入失败: {data_error}', {data_error: data.error}));
            break;
        }
        case 'read': {
            updateStatus(data.success ? t('{data_name} 当前值: {data_value}', {data_name: data.name, data_value: data.value}) : t('读取失败: {data_error}', {data_error: data.error}));
            break;
        }
        case 'snapshot': {
            updateStatus(data.success ? t('已保存显示器参数快照') : t('快照失败: {data_error}', {data_error: data.error}));
            break;
        }
        case 'rollback': {
            updateStatus(data.success ? t('已回滚到快照') : t('回滚失败: {data_error}', {data_error: data.error}));
            break;
        }
        case 'autocal_status': {
            if (data.running) autocalSetRunning(true);
            break;
        }
    }
}

function autocalSetRunning(running) {
    autocalRunning = running;
    updateAutoCalButtons();
}

// 导出 AutoCal 函数（供全局调用）
window.handleAutoCalStateChanged = handleAutoCalStateChanged;
window.handleAutoCalProgress = handleAutoCalProgress;
window.handleAutoCalFinished = handleAutoCalFinished;
window.handleDisplayControlUpdated = handleDisplayControlUpdated;

// ==============================================================================
// HDR EOTF 追踪报告 (P3 集成)
// ==============================================================================

/**
 * 渲染 HDR EOTF 追踪报告（backend.analyze_hdr_eotf 的返回）
 */
function renderHdrEotfReport(resultJson) {
    let data;
    try {
        data = parsePayload(resultJson);
    } catch (e) {
        updateStatus(t('报告解析失败: ') + e);
        return;
    }

    const reportDiv = document.getElementById('hdr-report');
    if (!reportDiv) return;

    if (!data.success) {
        reportDiv.style.display = 'block';
        reportDiv.innerHTML = `<div style="color:#e74c3c;">分析失败: ${data.error || '未知错误'}</div>`;
        return;
    }

    const s = data.summary || {};
    if (!s.point_count) {
        reportDiv.style.display = 'block';
        reportDiv.innerHTML = '<div style="color:#f39c12;">没有可分析的 HDR 测量点</div>';
        return;
    }

    reportDiv.style.display = 'block';

    // 摘要
    let html = `
        <div style="border:1px solid var(--border-color); border-radius:6px; padding:8px; margin-bottom:8px;">
            <strong>${data.eotf} 追踪摘要（目标峰值 ${data.peak_nits} nits）</strong><br>
            实测峰值: <strong>${s.peak_measured_nits} nits</strong> |
            平均亮度误差: ${s.mean_abs_error_nits} nits |
            最大误差: ${s.max_abs_error_nits} nits @码值${s.max_abs_error_point} |
            平均 ΔE ITP: ${s.mean_delta_e_itp} | 最大 ΔE ITP: ${s.max_delta_e_itp}
        </div>`;

    // 逐点表
    html += `
        <table style="width:100%; border-collapse:collapse; font-size:11px;">
            <thead>
                <tr style="border-bottom:1px solid var(--border-color); text-align:left;">
                    <th style="padding:3px 6px;">码值</th>
                    <th style="padding:3px 6px;">目标 nits</th>
                    <th style="padding:3px 6px;">实测 nits</th>
                    <th style="padding:3px 6px;">误差</th>
                    <th style="padding:3px 6px;">误差 %</th>
                    <th style="padding:3px 6px;">ΔE ITP</th>
                </tr>
            </thead>
            <tbody>`;

    (data.points || []).forEach(p => {
        const errColor = Math.abs(p.error_pct) <= 10 ? '#2ecc71' : (Math.abs(p.error_pct) <= 25 ? '#f39c12' : '#e74c3c');
        const itpColor = p.delta_e_itp <= 3 ? '#2ecc71' : (p.delta_e_itp <= 10 ? '#f39c12' : '#e74c3c');
        html += `
            <tr style="border-bottom:1px solid var(--border-color);">
                <td style="padding:2px 6px;">${p.code}</td>
                <td style="padding:2px 6px;">${p.target_nits}</td>
                <td style="padding:2px 6px;">${p.measured_nits}</td>
                <td style="padding:2px 6px; color:${errColor};">${p.error_nits > 0 ? '+' : ''}${p.error_nits}</td>
                <td style="padding:2px 6px; color:${errColor};">${p.error_pct > 0 ? '+' : ''}${p.error_pct}%</td>
                <td style="padding:2px 6px; color:${itpColor};">${p.delta_e_itp}</td>
            </tr>`;
    });

    html += '</tbody></table>';
    reportDiv.innerHTML = html;
    updateStatus(t('HDR {data_eotf} 追踪报告已生成（{s_point_count} 点，平均 ΔE ITP {s_mean_delta_e_itp}）', {data_eotf: data.eotf, s_point_count: s.point_count, s_mean_delta_e_itp: s.mean_delta_e_itp}));
}

window.renderHdrEotfReport = renderHdrEotfReport;

// ========== 引导式测量确认（均匀性逐点确认） ==========

function guidedConfirmMeasure() {
    if (!backend) return;
    const area = document.getElementById('guided-confirm-area');
    if (area) area.style.display = 'none';
    backend.confirm_cycle_measurement();
    updateStatus(t('已确认，正在测量当前区域…'));
}

function guidedSkipMeasure() {
    if (!backend) return;
    const area = document.getElementById('guided-confirm-area');
    if (area) area.style.display = 'none';
    backend.skip_cycle_measurement();
    updateStatus(t('已跳过当前测点'));
}

// ========== 均匀性检测（对标 Calman uniformity） ==========

/**
 * 累积一个均匀性测点结果（patchName 形如 "U-r{row}c{col}"）
 */
function addUniformityMeasurement(result) {
    if (!window.uniformityData) window.uniformityData = [];
    const m = /^U-r(\d+)c(\d+)$/.exec(result.patchName || '');
    if (!m) return;
    window.uniformityData = window.uniformityData.filter(d => d.patchName !== result.patchName);
    window.uniformityData.push({
        patchName: result.patchName,
        row: parseInt(m[1]),
        col: parseInt(m[2]),
        x: result.x, y: result.y, Y: result.Y,
        cct: result.cct
    });
}

/** xy 色度 → CIE 1976 u'v' */
function xyToUpVp(x, y) {
    const denom = -2 * x + 12 * y + 3;
    if (denom === 0) return { up: 0, vp: 0 };
    return { up: 4 * x / denom, vp: 9 * y / denom };
}

/**
 * 渲染均匀性热力图报告（亮度均匀性 + 色度偏差）
 *
 * 指标：
 * - 各测点相对中心测点的亮度偏差 %（热力图主体）
 * - 亮度均匀性 = (1 - (Ymax-Ymin)/Ymax) × 100%
 * - 各测点相对中心的 Δu'v' 色度偏差
 */
function renderUniformityReport() {
    const data = window.uniformityData || [];
    const section = document.getElementById('uniformity-section');
    const summaryEl = document.getElementById('uniformity-summary');
    const heatmapEl = document.getElementById('uniformity-heatmap');
    if (!section || !summaryEl || !heatmapEl || data.length === 0) return;

    const grid = Math.max(...data.map(d => Math.max(d.row, d.col))) + 1;
    const centerIdx = Math.floor(grid / 2);
    const center = data.find(d => d.row === centerIdx && d.col === centerIdx)
        || data.find(d => d.row === centerIdx) || data[0];

    const Ys = data.map(d => d.Y);
    const Ymax = Math.max(...Ys), Ymin = Math.min(...Ys);
    const uniformity = Ymax > 0 ? (1 - (Ymax - Ymin) / Ymax) * 100 : 0;
    const cUpVp = xyToUpVp(center.x, center.y);

    // CCT 统计
    const ccts = data.filter(d => d.cct && isFinite(d.cct)).map(d => d.cct);
    const cctMin = ccts.length ? Math.min(...ccts) : null;
    const cctMax = ccts.length ? Math.max(...ccts) : null;

    // 最大偏差测点
    let worst = data[0], worstDev = 0, worstDuv = 0;
    data.forEach(d => {
        const dev = center.Y > 0 ? Math.abs((d.Y - center.Y) / center.Y * 100) : 0;
        const uv = xyToUpVp(d.x, d.y);
        const duv = Math.sqrt((uv.up - cUpVp.up) ** 2 + (uv.vp - cUpVp.vp) ** 2);
        if (dev > worstDev) { worstDev = dev; worst = d; }
        if (duv > worstDuv) worstDuv = duv;
    });

    function devColor(dev) {
        const a = Math.abs(dev);
        if (a <= 3) return '#10b981';
        if (a <= 5) return '#84cc16';
        if (a <= 10) return '#f59e0b';
        return '#ef4444';
    }

    summaryEl.innerHTML = `
        <span class="uni-stat">亮度均匀性<b>${uniformity.toFixed(1)}%</b></span>
        <span class="uni-stat">中心亮度<b>${center.Y.toFixed(1)} cd/m²</b></span>
        <span class="uni-stat">最大亮度偏差<b>${worstDev.toFixed(1)}%</b>（${worst.patchName.replace('U-', '')}）</span>
        <span class="uni-stat">最大 Δu'v'<b>${worstDuv.toFixed(4)}</b></span>
        ${cctMin !== null ? `<span class="uni-stat">CCT 范围<b>${Math.round(cctMin)} ~ ${Math.round(cctMax)} K</b></span>` : ''}
        <span class="uni-stat">测点数<b>${data.length}</b>（${grid}×${grid}）</span>`;

    heatmapEl.style.gridTemplateColumns = `repeat(${grid}, 1fr)`;
    heatmapEl.style.gridTemplateRows = `repeat(${grid}, 1fr)`;
    let html = '';
    for (let r = 0; r < grid; r++) {
        for (let c = 0; c < grid; c++) {
            const d = data.find(v => v.row === r && v.col === c);
            if (!d) {
                html += '<div class="uni-cell" style="background:#1a1a2a;">--</div>';
                continue;
            }
            const dev = center.Y > 0 ? (d.Y - center.Y) / center.Y * 100 : 0;
            const uv = xyToUpVp(d.x, d.y);
            const duv = Math.sqrt((uv.up - cUpVp.up) ** 2 + (uv.vp - cUpVp.vp) ** 2);
            const isCenter = (r === center.row && c === center.col);
            const cctTxt = d.cct && isFinite(d.cct) ? `${Math.round(d.cct)}K` : '--';
            html += `
                <div class="uni-cell${isCenter ? ' center' : ''}" style="background:${devColor(dev)};"
                     title="位置 r${r}c${c}（第${r + 1}行 第${c + 1}列）&#10;亮度: ${d.Y.toFixed(2)} cd/m²&#10;偏差: ${dev > 0 ? '+' : ''}${dev.toFixed(1)}%&#10;CCT: ${cctTxt}&#10;Δu'v' vs 中心: ${duv.toFixed(4)}">
                    <span class="uni-val">${dev > 0 ? '+' : ''}${dev.toFixed(1)}%</span>
                    <span class="uni-sub">${d.Y.toFixed(1)} nit · ${cctTxt}</span>
                </div>`;
        }
    }
    heatmapEl.innerHTML = html;
    section.classList.remove('hidden');
    updateStatus(t('均匀性报告已生成：亮度均匀性 {uniformity_toFixed_1}%，最大偏差 {worstDev_toFixed_1}%（相对中心 r{center_row}c{center_col}）', {uniformity_toFixed_1: uniformity.toFixed(1), worstDev_toFixed_1: worstDev.toFixed(1), center_row: center.row, center_col: center.col}));
}
