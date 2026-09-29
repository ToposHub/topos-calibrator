/*
 * Topos Calibrator - 使用文档内容（中英双语）
 *
 * 设计说明：
 * 1. 文档正文按语言整体编写（zh-CN / en 各一份），不经过 i18n.js 的 DOM 翻译器
 *    （正文渲染时英文模式下不含中文文本节点，中文模式下 t() 原样返回，互不干扰）。
 * 2. 两种语言的 chapters 必须保持 id 一一对应（tests/test_workflows/test_docs_content.py 校验），
 *    渲染器按 id 记忆当前阅读章节，语言切换时停留在原章节。
 * 3. 章节正文支持 HTML：h4 / p / ul / ol / table / code，以及
 *    <div class="doc-tip">（提示）/ <div class="doc-warn">（注意）两类标注块。
 */
(function (global) {
    'use strict';

    var DOCS_CONTENT = {

        /* ============================== 中文 ============================== */
        'zh-CN': {
            chapters: [

                {
                    id: 'quick-start',
                    icon: '🚀',
                    title: '快速入门',
                    html: `
<h4>Topos Calibrator 是什么？</h4>
<p>Topos Calibrator 是一款基于 ArgyllCMS 的显示器校正与测量软件，配合校色仪（探头）可以完成：</p>
<ul>
    <li><strong>显示器检测</strong>——测量色域覆盖率、亮度、对比度、Gamma、白点等基础指标；</li>
    <li><strong>ICC 校准</strong>——生成显示器 ICC Profile，实现软件级色彩校准；</li>
    <li><strong>3D LUT 制作</strong>——为 DaVinci Resolve、madVR 等视频后期软件生成校准 LUT；</li>
    <li><strong>CCMX 矩阵</strong>——用分光仪为色度计制作光谱校正，提升测量精度；</li>
    <li><strong>校准验证</strong>——对照 sRGB / DCI-P3 等标准出验收报告。</li>
</ul>

<h4>测量前需要准备什么？</h4>
<ol>
    <li><strong>探头</strong>：通过 USB 连接校色仪（如 i1 Display Pro、SpyderX）。</li>
    <li><strong>显示器预热</strong>：开机预热 30 分钟以上再测量，结果更稳定。</li>
    <li><strong>环境光线</strong>：尽量在可控制光线的暗房环境中测量，避免灯光直射屏幕。</li>
    <li><strong>关闭干扰</strong>：关闭 Night Shift / True Tone、f.lux 等色温调节软件，并将显示器恢复出厂设置或默认色温。</li>
</ol>
<div class="doc-warn">⚠️ macOS 首次使用需在「系统设置 → 隐私与安全性」中授予应用<strong>USB 设备访问</strong>等权限，否则探头无法连接。预检步骤会自动检测这些权限。</div>

<h4>第一次测量（5 步）</h4>
<ol>
    <li>在左侧<strong>工作流选择</strong>面板点击「显示器检测」卡片；</li>
    <li>按向导点击「开始预检」，确认环境检查通过（警告项可酌情忽略）；</li>
    <li>在「探头/修正」步骤点击「连接探头」，等待状态变为已连接；</li>
    <li>在「目标设置」步骤选择预设（默认 sRGB / D65 / 2.2 即可），点击「下一步」直至「开始测量」；</li>
    <li>测量完成后进入「报告」步骤，可导出 PDF / HTML / JSON 报告。</li>
</ol>
<div class="doc-tip">💡 软件默认处于<strong>引导模式</strong>，向导会按步骤带你完成整个流程。熟练后可点击右上角「高级模式」开关切换到专业自由模式。</div>
`
                },

                {
                    id: 'interface',
                    icon: '🖥️',
                    title: '界面导览',
                    html: `
<h4>主窗口布局</h4>
<p>主窗口分为<strong>顶部菜单栏</strong>、<strong>左右双栏 + 中央图表区</strong>、<strong>底部状态栏</strong>：</p>
<ul>
    <li><strong>左侧面板</strong>——引导模式下为「工作流选择」卡片与向导步骤面板（目标设置 / 探头与修正 / 测量）；高级模式下为「高级设置面板」（探头、显示器类型、测量延迟等）与「测量模式」面板。</li>
    <li><strong>中间区域</strong>——向导步骤详情工作区（预检结果、测量进度、生成与报告等），以及显示器基础数据、当前色块数据。</li>
    <li><strong>右侧面板</strong>——CIE 1931 色度图、Gamma 曲线、饱和度追踪、色温追踪、均匀性分析等图表。</li>
    <li><strong>状态栏</strong>——左侧显示当前操作提示，右侧为滚动日志输出，测量失败原因会在这里详细打印。</li>
</ul>

<h4>菜单栏</h4>
<table>
    <tr><th>菜单</th><th>功能</th></tr>
    <tr><td>文件</td><td>导出 CSV / 导出报告（部分配置项功能开发中）、退出</td></tr>
    <tr><td>测量</td><td>连接探头（⌘K）、校准探头、循环测量（⌘M）、停止测量（Esc）</td></tr>
    <tr><td>视图</td><td>显示/隐藏 各面板、打开测量窗口、Web测量服务器开关、数据对比</td></tr>
    <tr><td>设置</td><td>高级模式开关、界面语言（简体中文 / English）、偏好设置、探头配置（开发中）</td></tr>
    <tr><td>帮助</td><td>使用文档（本窗口）、关于 Topos Calibrator</td></tr>
</table>

<h4>引导模式 vs 高级模式</h4>
<ul>
    <li><strong>引导模式（默认）</strong>：选择一个工作流后，界面按「预检 → 目标设置 → 探头/修正 → 测量 → 生成 → 验证 → 报告」的步骤导航，逐步引导完成，适合新用户。</li>
    <li><strong>高级模式</strong>：隐藏向导，由你自由连接探头、选择测量模式（色域 / ICC / LUT / 均匀性 / HDR 等）与参数，用底部按钮直接「单次测量 / 循环测量 / 停止」，并开放历史数据加载与对比等进阶操作。</li>
</ul>
<p>三种切换方式（效果相同）：顶部菜单「设置 → 高级模式」、右上角「高级模式」开关、左侧面板「高级模式」按钮。测量进行中无法切换模式。</p>
<div class="doc-tip">💡 模式选择会自动记忆，下次启动保持上次使用的模式。</div>
`
                },

                {
                    id: 'probe',
                    icon: '🔌',
                    title: '探头连接与校准',
                    html: `
<h4>连接探头</h4>
<ol>
    <li>用 USB 将校色仪连接到电脑（部分探头需先取下镜头盖）；</li>
    <li>点击菜单「测量 → 连接探头」（快捷键 ⌘K）或左侧面板「连接探头」按钮；</li>
    <li>首次连接设备枚举可能需要 10–20 秒，请留意状态栏与日志提示，成功后按钮变为「断开探头」。</li>
</ol>
<div class="doc-tip">💡 软件支持 30 余款仪器：X-Rite i1 Display Pro / i1 Pro 2 / i1 Pro 3、ColorMunki、Datacolor Spyder 全系列、Klein K10-A、JETI 分光仪、ColorHug、HCFR 等。连接成功后如果设备与所选探头类型不符，软件会自动切换探头类型。</div>
<div class="doc-warn">⚠️ macOS 需授予「USB 设备访问」权限；Windows 需安装仪器驱动；Linux 需配置 udev 规则。预检步骤会给出具体提示。</div>

<h4>校准探头</h4>
<p>测量类探头（如 i1 Display）依赖环境光校准来消除零点漂移：<strong>连接探头后</strong>，点击「校准探头」，将探头放在校色仪自带的白色校准板上（或扣上镜头盖，按仪器说明操作），等待提示「探头校准成功」。建议每次测量开始前、环境亮度变化后重新校准。</p>

<h4>光谱修正（提升色度计精度的关键）</h4>
<p>色度计（如 i1 Display Pro）测量不同背光技术的显示器时存在光谱偏差，需要加载<strong>光谱修正文件</strong>：</p>
<ul>
    <li><strong>内置修正库</strong>：软件内置了常见显示器与探头组合的 CCMX/CCSS 修正文件，在「光谱修正」下拉中按探头分组选择即可，选中后可查看修正类型、目标显示技术、创建日期等元数据；</li>
    <li><strong>导入 EDR</strong>：若你在 i1Profiler 中有官方 .edr 校正文件，点击「导入 EDR…」自动转换为 CCSS 并加入修正库；</li>
    <li><strong>自制 CCMX</strong>：使用「CCMX 矩阵」工作流，用分光仪与色度计同时测量生成专属修正矩阵（见「CCMX 矩阵」章节）。</li>
</ul>
<div class="doc-tip">💡 「显示器类型」下拉（LCD 通用 / LCD White LED / OLED / WOLED 等）会影响 ArgyllCMS 的测量稳定策略与修正匹配，请按实际显示器选择。</div>
`
                },

                {
                    id: 'workflow-gamut',
                    icon: '🔍',
                    title: '工作流：显示器检测',
                    html: `
<h4>用途</h4>
<p>测量显示器的色彩表现，生成色域覆盖率、亮度、Gamma、白点等基础指标报告，是最常用的工作流。</p>

<h4>向导步骤</h4>
<ol>
    <li><strong>预检</strong>——自动执行 20 余项环境检查（ArgyllCMS 工具、探头连接、系统色温干扰、系统休眠、USB 权限等）。所有检查项均可单独覆盖忽略，但勾选「高级覆盖」可能影响测量准确性；可导出 JSON 预检报告。</li>
    <li><strong>目标设置</strong>——选择目标标准（见下表）。</li>
    <li><strong>探头/修正</strong>——连接并校准探头，选择光谱修正文件。</li>
    <li><strong>测量</strong>——确认测量设置摘要后点击「开始测量」。测量期间请勿移动探头；色块预览与进度、剩余时间、重复性统计会实时显示。</li>
    <li><strong>报告</strong>——导出 PDF / HTML / JSON。</li>
</ol>

<h4>目标设置参考</h4>
<table>
    <tr><th>预设</th><th>目标色域</th><th>白点</th><th>Gamma</th><th>适用场景</th></tr>
    <tr><td>sRGB（默认）</td><td>sRGB</td><td>D65 (6500K)</td><td>2.2</td><td>日常办公、网页、Windows/Mac 通用</td></tr>
    <tr><td>Rec.709</td><td>Rec.709</td><td>D65</td><td>2.4 (BT.1886)</td><td>高清视频制作</td></tr>
    <tr><td>DCI-P3</td><td>DCI-P3</td><td>D63</td><td>2.6</td><td>数字影院、HDR 片源调色参考</td></tr>
    <tr><td>自定义</td><td>可选 Display P3 / Adobe RGB / Rec.2020 等</td><td>D50/D65/D75/原生</td><td>2.2/2.4/2.6</td><td>按需手动组合</td></tr>
</table>
<p>「展开高级参数」可选择灰阶级数（10 级快速 / 21 级标准 / 256 级精细）、色块数量（自动推荐 / 99–1500）与采样策略（均衡覆盖 / 暗部优先 / 灰阶优先）。</p>
<div class="doc-tip">💡 测量完成后右侧图表会叠加显示实测色域与所选参考色域的对比；「显示器基础数据」中的色域覆盖率始终按 sRGB / DCI-P3 / AdobeRGB / Rec.2020 四个标准同时给出。</div>
`
                },

                {
                    id: 'workflow-icc',
                    icon: '📄',
                    title: '工作流：ICC 校准',
                    html: `
<h4>用途</h4>
<p>测量显示器并生成 ICC Profile，由操作系统色彩管理在支持色彩管理的应用（Photoshop、Safari 等）中实现准确显色。</p>

<h4>向导步骤</h4>
<p>完整流程为「预检 → 目标设置 → 探头/修正 → 测量 → 生成 → 验证 → 报告」7 步，比显示器检测多出「生成」与「验证」两步：</p>
<ol>
    <li>按向导完成预检、目标设置、探头连接与测量（与显示器检测相同）；</li>
    <li><strong>生成</strong>——在「ICC Profile 设置」中选择：
        <ul>
            <li><strong>Profile 类型</strong>：LUT 型（推荐，精度更高）或矩阵型（兼容性好、体积小）；</li>
            <li><strong>质量级别</strong>：Medium / High（默认）/ Ultra，质量越高生成越慢；</li>
            <li><strong>保存路径</strong>：留空则保存到默认 measurements 目录。</li>
        </ul>
        点击「生成 ICC Profile」，完成后显示生成摘要（文件路径、目标/实测白点等）。</li>
    <li><strong>验证</strong>——生成后软件自动用 64 个验证色块复测，评估 Profile 效果；</li>
    <li><strong>报告</strong>——导出校准报告。</li>
</ol>

<h4>安装与启用 Profile</h4>
<ul>
    <li>在「导出报告」/ 导出弹窗的 ICC 页签勾选「应用ICC色彩描述文件」，软件会把 Profile 安装到系统并立即生效；</li>
    <li>也可在系统显示设置中手动选择生成的 Profile。</li>
</ul>
<div class="doc-warn">⚠️ ICC 校准属于<strong>软件校准</strong>，只对支持系统色彩管理的应用生效。若需要让播放器、游戏等所有画面统一校正，请使用「3D LUT」工作流（配合 madVR / Resolve 等支持 LUT 的加载器）。</div>
<div class="doc-tip">💡 生成后可切换到「验证」工作流，对比校准前后的色域与白点偏差，量化校准收益。</div>
`
                },

                {
                    id: 'workflow-lut',
                    icon: '🎬',
                    title: '工作流：3D LUT',
                    html: `
<h4>用途</h4>
<p>测量显示器并生成 3D LUT 文件，用于 DaVinci Resolve、madVR、Premiere（Lumetri）等视频后期/播放软件的显示器校准，实现全画面统一色彩。</p>

<h4>向导步骤</h4>
<p>流程同 ICC 校准（7 步），仅在「生成」步骤改为「3D LUT 设置」：</p>
<ul>
    <li><strong>源色域</strong>：显示器当前所处色彩空间（Rec.709 / sRGB / Display P3 / DCI-P3 / Rec.2020）；</li>
    <li><strong>LUT 尺寸</strong>：33³（标准，推荐）或 65³（高精度，文件更大、生成更慢）；</li>
    <li><strong>输出格式</strong>：<code>.cube</code>（Resolve/达芬奇等通用，默认）、<code>.3dl</code>（10bit 整数）、<code>.mga</code>、<code>.clf</code>（Common LUT XML）。</li>
</ul>
<p>点击「生成 3D LUT」，完成后同样进入自动验证与报告步骤。</p>

<h4>导入到后期软件</h4>
<ul>
    <li><strong>DaVinci Resolve</strong>：项目设置 → 色彩管理 →「3D LUT / 输出查找表」加载 .cube 文件，或放入 LUT 文件夹后在时间线中使用；</li>
    <li><strong>madVR</strong>：渲染器设置 → colour management →「install the 3D LUT」加载 .3dl/.cube；</li>
    <li><strong>其他</strong>：支持加载 .cube 的监视器/播放器（如 OS X 的 videoLAN + LUT 插件方案）同理。</li>
</ul>
<div class="doc-tip">💡 视频工作流建议目标设为 Rec.709 / D65 / Gamma 2.4 (BT.1886)。LUT 校准不做显示器端硬件调整，只保证「经 LUT 加载器输出」的画面准确。</div>
`
                },

                {
                    id: 'workflow-ccmx',
                    icon: '🔧',
                    title: '工作流：CCMX 矩阵',
                    html: `
<h4>用途</h4>
<p>色度计（如 i1 Display Pro）对特定显示器存在系统性光谱偏差。用手头<strong>分光仪</strong>（i1 Pro 等，精度高）作为基准，与<strong>色度计</strong>同时测量同一组色块，即可生成该「探头 × 显示器」组合的 CCMX 修正矩阵，让色度计达到接近分光仪的精度。</p>

<h4>向导步骤</h4>
<ol>
    <li>预检、目标设置、探头/修正（先将分光仪设为当前探头）；</li>
    <li><strong>测量</strong>——用分光仪完成循环测量，点击「保存数据」；</li>
    <li>更换为色度计（同一位置、同一显示器状态），再次完成循环测量并「保存数据」；</li>
    <li><strong>生成</strong>——在「CCMX 矩阵设置」中：
        <ul>
            <li><strong>基准测量</strong>：选择分光仪的那份数据；</li>
            <li><strong>目标测量</strong>：选择色度计的那份数据；</li>
            <li><strong>描述</strong>：填写便于识别的名称（例如：i1d3 for LG OLED）；</li>
        </ul>
        点击「生成 CCMX 矩阵」，生成的 .ccmx 会自动加入内置修正库，之后在「光谱修正」下拉即可选用。</li>
</ol>
<div class="doc-warn">⚠️ 两次测量必须使用<strong>相同的色块序列</strong>（白、红、绿、蓝），并且显示器状态（亮度、色温、模式）保持不变，探头位置也应尽量一致，否则矩阵会引入误差。</div>
<div class="doc-tip">💡 若没有分光仪，可先尝试「光谱修正」下拉中的内置修正库，或从 i1Profiler 导入官方 EDR 文件。</div>
`
                },

                {
                    id: 'workflow-validation',
                    icon: '✅',
                    title: '工作流：验证',
                    html: `
<h4>用途</h4>
<p>在安装 ICC 或加载 3D LUT <strong>之后</strong>复测显示器，对照行业标准阈值出具验收结论（通过 / 警告 / 不合格），量化校准效果。</p>

<h4>操作流程</h4>
<ol>
    <li>先确保被测状态已生效（ICC 已安装并启用，或 LUT 已在加载器中激活）；</li>
    <li>选择「验证」工作流，完成预检、探头连接；</li>
    <li>目标设置中选择验收标准（sRGB / Rec.709 / DCI-P3 / Rec.2020 / AdobeRGB）；</li>
    <li>开始测量（默认 64 个验证色块），完成后在报告步骤导出验证报告。</li>
</ol>

<h4>标准阈值参考</h4>
<table>
    <tr><th>标准</th><th>ΔE 平均</th><th>ΔE 最大</th><th>白点容差</th><th>Gamma 容差</th><th>覆盖率要求</th></tr>
    <tr><td>sRGB / Rec.709</td><td>≤ 2.0</td><td>≤ 6.0</td><td>±200K / Δuv ≤ 0.005</td><td>±0.05</td><td>≥ 95%</td></tr>
    <tr><td>DCI-P3</td><td>≤ 3.0</td><td>≤ 8.0</td><td>±300K / Δuv ≤ 0.007</td><td>±0.05</td><td>≥ 90%</td></tr>
    <tr><td>Rec.2020</td><td>≤ 3.0</td><td>≤ 8.0</td><td>±200K / Δuv ≤ 0.005</td><td>±0.05</td><td>≥ 80%</td></tr>
    <tr><td>AdobeRGB</td><td>≤ 2.5</td><td>≤ 7.0</td><td>±200K / Δuv ≤ 0.005</td><td>±0.05</td><td>≥ 90%</td></tr>
</table>
<div class="doc-tip">💡 经验判断：ΔE 平均 &lt; 1 人眼几乎无法分辨；1–2 为优秀；2–3.5 可接受；&gt; 3.5 建议重新校准。</div>
`
                },

                {
                    id: 'measurement-settings',
                    icon: '⚙️',
                    title: '测量设置详解',
                    html: `
<p>以下参数位于<strong>高级模式的「高级设置面板」</strong>，或向导第 3 步「探头/修正」：</p>

<h4>探头相关</h4>
<ul>
    <li><strong>探头类型</strong>：必须与实际连接的仪器一致（连接后软件会自动识别切换）；</li>
    <li><strong>光谱修正</strong>：选择 CCMX/CCSS 修正文件，详见「探头连接与校准」章节；</li>
    <li><strong>校准探头</strong>：测量前对探头做零点校准。</li>
</ul>

<h4>显示器相关</h4>
<ul>
    <li><strong>显示器类型</strong>：LCD 通用 / LCD White LED / LCD RGB LED（广色域）/ OLED / WOLED / CRT / 投影仪等。该选项影响色块切换后的稳定等待策略（OLED 响应快可短等，部分 LCD 需更长）；</li>
    <li><strong>刷新率</strong>：自动检测（默认），特殊情况下可手动指定 60/120/144/240 Hz；</li>
    <li><strong>测量延迟</strong>：切出色块后等待读数稳定的时间，默认 500 ms。OLED 可设 100–200 ms 加速测量；响应慢的显示器可增至 1000 ms 以上提高稳定性。</li>
</ul>

<h4>测量质量</h4>
<ul>
    <li><strong>平均次数</strong>：每个色块多次读数取平均以降噪（1 = 关闭；建议 2–4，速度按倍数变慢）；</li>
    <li><strong>暗部采样</strong>：低亮度（默认阈值 0.2 cd/m²）读数波动大时自动多重采样，最多重测 3 次。测量显示器黑场与暗部 accuracy 的关键，保持默认开启；</li>
    <li><strong>重复性统计</strong>：测量过程中实时显示读数标准差与最大偏差，用于判断测量稳定性。</li>
</ul>

<h4>测量中断与恢复</h4>
<p>测量中若探头意外掉线，软件会自动尝试重连（最多 3 次）并继续；也可主动「停止并保存断点」，之后从恢复提示中继续测量而无需从头开始。</p>
<div class="doc-tip">💡 测量时务必让探头完全贴住屏幕（遮光），悬空或漏光会让暗部读数显著偏高。i1 Display 类探头建议使用配重袋悬挂贴合。</div>
`
                },

                {
                    id: 'advanced-mode',
                    icon: '🧰',
                    title: '高级模式与测量模式',
                    html: `
<p>切换到高级模式后，左侧出现「测量模式」下拉，提供 9 种模式：</p>
<table>
    <tr><th>模式</th><th>用途</th></tr>
    <tr><td>屏幕检测（色彩空间）</td><td>同「显示器检测」工作流：色域 / Gamma / 白点测量</td></tr>
    <tr><td>屏幕校正（ICC 制作）</td><td>含 dispcal 显示器校准 + colprof 生成 ICC 的完整流程，可选校准白点 / Gamma / 质量与测试色块数</td></tr>
    <tr><td>硬件校准（3D LUT 制作）</td><td>测量后生成 3D LUT（17³/33³/65³），可选渲染意图与黑场补偿（BPC）</td></tr>
    <tr><td>自定义颜色</td><td>手工编辑 RGB 色块列表（添加 / 重命名 / 删除 / 保存为色块组），自由测量任意颜色</td></tr>
    <tr><td>CCMX 矩阵制作</td><td>选择分光仪与色度计两份数据直接生成矩阵（同 CCMX 工作流）</td></tr>
    <tr><td>饱和度/色相扫描</td><td>六色 × 4 级饱和度 + 12 步色相 + 中性灰共 40 块（约 3–5 分钟），生成「饱和度追踪」图表；可选自动切图</td></tr>
    <tr><td>HDR EOTF 追踪</td><td>PQ (ST 2084) / HLG 标准，可选目标峰值亮度（400–4000 nits），生成约 21 级对数灰阶的 EOTF 追踪报告（ΔE ITP）</td></tr>
    <tr><td>均匀性检测</td><td>3×3 / 5×5 测点网格，在 100% 白 / 50% 灰 / 30% 灰电平测量屏幕各区域亮度与色度均匀性，生成热力图</td></tr>
    <tr><td>自动校准（AutoCal 闭环）</td><td>通过 DDC/CI 直连显示器 OSD：基线测量 → 计算调整方案 → 写入显示器 → 复测验证，可设迭代轮数 / ΔE 合格线 / 稳定等待，支持演练模式与快照回滚</td></tr>
</table>

<h4>均匀性检测的引导模式</h4>
<p>勾选「引导模式（逐点确认）」后，测量窗口会依次把色块定位到每个测点区域并暂停；将探头对准该区域后按<strong>空格</strong>或点击「✓ 测量此点」确认，全部测点完成后自动生成亮度/色度均匀性热力图。</p>

<h4>AutoCal 注意事项</h4>
<ul>
    <li>点击「连接 DDC/CI」建立与显示器 OSD 通道的通信（需要显示器支持 DDC/CI 且系统授予辅助功能/权限）；</li>
    <li>首次使用建议勾选<strong>演练模式</strong>（只计算方案不写入显示器）；</li>
    <li>写入前自动创建快照，异常时可「回滚」到调整前状态。</li>
</ul>
`
                },

                {
                    id: 'results',
                    icon: '📊',
                    title: '测量结果解读',
                    html: `
<h4>显示器基础数据</h4>
<ul>
    <li><strong>峰值亮度</strong>：100% 白场亮度（cd/m²）。sRGB 办公推荐 120–150；观影环境可更低；</li>
    <li><strong>黑场亮度</strong>：0% 黑场亮度，越低越好；<strong>对比度</strong> = 峰值 / 黑场；</li>
    <li><strong>Gamma</strong>：实测灰阶 Gamma（高亮段），与目标值（如 2.2）偏差越小越好；</li>
    <li><strong>白点色温 / x / y / 偏差 ΔE</strong>：实测白点坐标与目标白点的色差，ΔE ≤ 2 为佳。</li>
</ul>

<h4>当前色块数据</h4>
<p>显示最近一个测量色块的 x, y 色度坐标、亮度 Y（cd/m²）、色温（K）、ΔE 与 u' v'，用于测量过程中的即时监控。</p>

<h4>右侧图表</h4>
<ul>
    <li><strong>CIE 1931 色度图</strong>：实测 RGBW 角点与色域三角形，可叠加 sRGB / DCI-P3 / AdobeRGB / Rec.2020 / ProPhoto / ACES 等十余种参考色域；</li>
    <li><strong>Gamma 曲线</strong>：实测灰阶响应与参考曲线（2.2 / 2.4 BT.1886 / sRGB / PQ / HLG / Log 曲线等）对比；</li>
    <li><strong>饱和度追踪</strong>：饱和度/色相扫描后显示各饱和度档位的目标 vs 实测偏差；</li>
    <li><strong>色温 (CCT) 追踪</strong>：灰阶测量后显示各灰阶的色温与 Δuv 走势，判断白平衡一致性；</li>
    <li><strong>均匀性分析</strong>：均匀性检测后显示热力图，绿色 &lt; 3% 偏差、红色 &gt; 10% 偏差，悬停查看各测点详情。</li>
</ul>

<h4>测量进度面板</h4>
<p>测量过程中显示当前色块预览（名称/RGB/Y）、进度与剩余时间、平均耗时和重复性统计。单点失败时可选择「🔄 重测当前点」「⏭ 跳过并标记」或「⏹ 停止并保存断点」，错误区会给出下一步建议。</p>
<div class="doc-tip">💡 报告中的<strong>测量可信度</strong>（置信度评分、拒绝读数比例、warm-up 稳定性）可用于判断本次测量的整体质量；置信度低时建议重新校准探头并检查探头贴合。</div>
`
                },

                {
                    id: 'patch-window',
                    icon: '🪟',
                    title: '测量窗口',
                    html: `
<h4>用途</h4>
<p>「测量窗口」是一个独立的纯色色块窗口，测量时在屏幕上显示当前色块供探头读取。菜单「视图 → 测量窗口」或主界面按钮即可打开。</p>

<h4>窗口操作</h4>
<ul>
    <li><strong>＋ / −</strong>：放大 / 缩小窗口；右下角可拖拽调整大小；</li>
    <li><strong>⤢ 全屏测量</strong>：整个屏幕显示为纯色色块（避免窗口边框/任务栏干扰测量），按 <strong>Esc</strong> 退出；</li>
    <li><strong>✕</strong>：关闭窗口；底部标签实时显示当前 RGB 值。</li>
</ul>

<h4>多显示器场景</h4>
<p>检测到多个显示器时，测量窗口会自动移动到副屏并在测量时自动全屏，主屏保持可操作，方便边操作软件边测量副屏。</p>

<h4>引导式确认</h4>
<p>均匀性等引导测量中，全屏色块下方出现悬浮条：<strong>空格 / 回车</strong>确认「✓ 测量此点」，或点击「⏹ 停止测量」。请先把探头物理对准显示的区域再确认。</p>
<div class="doc-tip">💡 测量窗口由 Qt 直接绘制，绕过系统 ICC 色彩管理，保证探头读到的是显卡实际输出的颜色。若使用浏览器测量则不具备此特性（见 Web 测量服务器章节的说明）。</div>
`
                },

                {
                    id: 'web-server',
                    icon: '🌐',
                    title: 'Web 测量服务器',
                    html: `
<h4>用途</h4>
<p>启动后，同一局域网内的手机 / 平板 / 另一台电脑可以用浏览器打开服务地址，作为<strong>被测色的显示端</strong>（全屏色块页）。适合测量第二台设备的屏幕，或无法安装本软件的设备。</p>

<h4>开启方式</h4>
<ul>
    <li>菜单「视图 → Web测量服务器」点击即启动 / 停止；</li>
    <li>或「设置 → 偏好设置 → 🌐 Web测量服务器」勾选「启用 Web 测量服务」。</li>
</ul>
<p>启动后偏好设置中会显示运行状态徽标（运行中 / 未启动）、<strong>服务地址</strong>（如 <code>http://192.168.1.100:8080</code>）与<strong>复制</strong>按钮，点击复制后直接粘贴到浏览器地址栏即可打开。修改端口（1024–65535）后服务会自动以新端口重启。</p>

<h4>浏览器端</h4>
<p>打开地址后页面自动全屏显示当前色块，左上角显示当前 RGB 值，每 100ms 与软件同步。配合本软件的「循环测量」即可像普通测量窗口一样完成测量。</p>

<h4>色彩管理注意</h4>
<div class="doc-warn">⚠️ 浏览器渲染<strong>会经过系统 ICC 色彩管理</strong>，与 Qt 测量窗口（绕过 ICC）不同。为保证浏览器输出原生颜色，请在偏好设置中开启「自动清除系统 ICC」（清除显卡 VCGT/LUT），并按需勾选「使用 Null Profile 方案」（挂载线性 ICC，让浏览器绕过系统配色方案）。</div>
<div class="doc-tip">💡 手机/平板无法访问时，请确认设备与电脑在同一 Wi-Fi、防火墙未拦截该端口，且地址栏使用偏好设置中显示的完整地址（含端口）。</div>
`
                },

                {
                    id: 'data-comparison',
                    icon: '🗂️',
                    title: '数据管理与对比',
                    html: `
<h4>保存测量数据</h4>
<ul>
    <li><strong>手动保存</strong>：点击顶部「保存数据」按钮，测量数据以 JSON 存入 <code>measurements/</code> 目录，文件名含时间戳与测量 ID；</li>
    <li><strong>自动保存</strong>：默认开启（偏好设置可改），完成后自动存入 <code>measurements/auto_save/日期/时间_模式.json + .ti3</code>；</li>
    <li>.ti3 为 ArgyllCMS 标准测量数据，可被 dispcal/colprof 等工具直接使用。</li>
</ul>

<h4>数据对比窗口</h4>
<p>菜单「视图 → 数据对比」打开独立窗口：</p>
<ol>
    <li><strong>选择数据</strong>——左栏勾选两次或多次历史测量（可按显示器 / 目标标准 / 工作流 / 日期分组，支持全选与刷新）；</li>
    <li><strong>概览</strong>——CIE 色域与 Gamma 曲线叠加对比，「关键参数汇总」表自动以绿色标出每项最优值（亮度、对比度、白点、ΔE、覆盖率等）；</li>
    <li><strong>详细色块</strong>——逐色块的 RGB / xyY / CCT / ΔE 多测量横向对比表；</li>
    <li><strong>历史趋势</strong>——选定分组后查看历次测量的白点亮度 / CCT / 平均 Gamma / Δu'v' 走势，追踪显示器漂移与校准衰减。</li>
</ol>
<p>点击「导出」可将对比报告保存为 HTML 文件。</p>

<h4>Golden Baseline（黄金基线）</h4>
<p>在测量列表中右键可将某次测量<strong>标记为 Golden Baseline</strong>（按显示器 + 目标标准保存的基准）。之后任意测量都可「与 Golden Baseline 对比」，快速判断当前状态是否偏离基准，适合显示器定期复检。</p>
<div class="doc-tip">💡 建议每次校准完成后立即保存一份数据并标记为 Golden Baseline，作为该显示器该标准下的"出厂基准"。</div>
`
                },

                {
                    id: 'export',
                    icon: '📤',
                    title: '导出与报告',
                    html: `
<h4>统一导出弹窗</h4>
<p>菜单「文件 → 导出 CSV...」或顶部「导出」按钮打开「📦 导出文件」弹窗，含五个页签：</p>
<table>
    <tr><th>页签</th><th>格式</th><th>说明</th></tr>
    <tr><td>色彩空间</td><td>TI3 / CSV / JSON</td><td>原始测量数据（色域 + 灰阶，可勾选）</td></tr>
    <tr><td>ICC 校正</td><td>ICC Profile / TI3</td><td>由历史或当前测量生成 Profile，可选类型 / 质量 / 目标白点 / Gamma / BPC，支持「应用ICC色彩描述文件」一键安装生效</td></tr>
    <tr><td>LUT 校正</td><td>CUBE / 3DL / MGA / CLF</td><td>快速（仅 Gamma）或高级（ICC + Collink）两种方式，可选尺寸 17³–129³、渲染意图、输入范围 Full/Video</td></tr>
    <tr><td>自定义</td><td>CSV / JSON / TI3</td><td>自定义色块组数据导出</td></tr>
    <tr><td>CCMX</td><td>CCMX / CSV</td><td>校正矩阵或测量数据表</td></tr>
</table>

<h4>快速生成</h4>
<p>测量完成后，使用「⚡ 快速生成 ICC」/「⚡ 快速生成 LUT」按钮可用实测白点与默认参数一步生成文件，适合快速出件；需要精细控制时再用完整导出弹窗。</p>

<h4>报告</h4>
<ul>
    <li><strong>PDF 报告</strong>：向导第 7 步「导出 PDF」，内含目标参数、探头与显示器信息、白点 / Gamma / 色域覆盖率、ΔE 统计与分布直方图、测量可信度、验证结论（通过/警告/不合格）与 Gamma / CIE / ΔE 图表；</li>
    <li><strong>HTML / JSON</strong>：同一份数据的网页版与机器可读版；</li>
    <li><strong>预检报告</strong>：预检结果可导出 JSON 存档。</li>
</ul>
<div class="doc-tip">💡 CSV 包含两张表：色域段（Color, RGB, XYZ, xy, Y）与灰阶段（RGB, XYZ, xy, Y），可直接用 Excel / Numbers 打开做二次分析。</div>
`
                },

                {
                    id: 'preferences',
                    icon: '🎛️',
                    title: '偏好设置',
                    html: `
<p>菜单「设置 → 偏好设置...」打开，共四组：</p>

<h4>🌗 界面外观</h4>
<ul>
    <li><strong>暗房模式</strong>：进一步压暗界面背景、文字亮度与主色饱和度，适合暗房校色环境，减少 UI 亮光对色觉适应的干扰；</li>
    <li><strong>字体大小</strong>：标准 / 大 (115%) / 特大 (130%)。</li>
</ul>

<h4>💾 自动保存</h4>
<ul>
    <li><strong>测量完成后自动保存</strong>：默认开启；</li>
    <li><strong>保存目录</strong>：默认 <code>measurements/auto_save</code>，可浏览更改；格式为 <code>日期/时间_模式.json + .ti3</code>。</li>
</ul>

<h4>🌐 Web测量服务器</h4>
<ul>
    <li><strong>启用 Web 测量服务</strong>：开关服务并显示运行状态；</li>
    <li><strong>端口</strong>：默认 8080（1024–65535），修改后自动重启服务；</li>
    <li><strong>服务地址 + 复制</strong>：一键复制完整地址，粘贴到浏览器即开。详见「Web 测量服务器」章节。</li>
</ul>

<h4>🎨 色彩管理高级选项</h4>
<ul>
    <li><strong>自动清除系统 ICC</strong>（默认开）：测量前清除显卡 LUT（VCGT），确保测到显示器原生状态；</li>
    <li><strong>使用 Null Profile 方案</strong>：挂载线性 ICC 让浏览器等应用绕过系统 ICC，仅在通过 Web 测量服务器测量时需要（Qt 测量窗口本身绕过 ICC，无需勾选）；依赖上一项开启。</li>
</ul>
<div class="doc-tip">💡 界面语言不在偏好设置中——使用菜单「设置 → 简体中文 / English」切换，本使用文档会跟随界面语言同步切换。</div>
`
                },

                {
                    id: 'shortcuts',
                    icon: '⌨️',
                    title: '快捷键',
                    html: `
<table>
    <tr><th>快捷键</th><th>作用范围</th><th>功能</th></tr>
    <tr><td><code>⌘K</code></td><td>主窗口</td><td>连接 / 断开探头</td></tr>
    <tr><td><code>⌘M</code></td><td>主窗口</td><td>开始循环测量</td></tr>
    <tr><td><code>Esc</code></td><td>主窗口</td><td>停止测量</td></tr>
    <tr><td><code>Esc</code></td><td>测量窗口全屏</td><td>退出全屏</td></tr>
    <tr><td><code>空格</code> / <code>回车</code></td><td>引导式测量 / 全屏测量</td><td>确认「✓ 测量此点」</td></tr>
</table>
<div class="doc-tip">💡 全部菜单动作也可以直接点击菜单栏执行；快捷键标注见「测量」菜单。</div>
`
                },

                {
                    id: 'faq',
                    icon: '❓',
                    title: '常见问题',
                    html: `
<h4>探头连接不上？</h4>
<ul>
    <li>macOS：检查「系统设置 → 隐私与安全性 → USB 设备访问」是否已授权本应用；</li>
    <li>首次枚举可能需要 10–20 秒，请看日志输出；可拔插 USB 后重试；</li>
    <li>确认探头类型选择与实际设备一致（连接成功后软件会自动纠正）；</li>
    <li>Windows 用户确认仪器驱动已安装；Linux 用户需配置 udev 规则（预检会提示）。</li>
</ul>

<h4>预检出现阻断项怎么办？</h4>
<p>阻断项（如 ArgyllCMS 工具缺失、探头未连接、USB 权限缺失）会直接阻止测量开始。请按预检面板给出的建议逐项处理。确有经验者可勾选「高级覆盖」忽略阻断项强行继续，但<strong>可能影响测量准确性</strong>。</p>

<h4>测量中途失败 / 探头掉线？</h4>
<p>软件会自动重连（最多 3 次）并继续测量；若仍未恢复，可「停止并保存断点」，排查后从断点继续，无需重头测量。单点失败也可用「重测当前点」或「跳过并标记」。</p>

<h4>暗部测量特别慢？</h4>
<p>「暗部采样」开启时，低亮度色块会自动多重采样以提高精度，属于正常现象。若不需要极高暗部精度，可关闭或提高阈值。</p>

<h4>测量结果偏差大？</h4>
<ul>
    <li>确认已选择与显示器匹配的<strong>光谱修正文件</strong>（内置库 / EDR / 自制 CCMX）；</li>
    <li>显示器未预热（建议 30 分钟以上）或环境光直射屏幕；</li>
    <li>Night Shift / True Tone / f.lux 等仍在运行；</li>
    <li>探头未贴合屏幕（漏光）或测量中移位；</li>
    <li>「自动清除系统 ICC」被关闭，显卡 VCGT/LUT 仍在起作用。</li>
</ul>

<h4>浏览器打不开 Web 测量地址？</h4>
<p>确认手机/电脑与主机在同一局域网、偏好设置中状态为「运行中」、地址包含端口号（如 <code>http://192.168.x.x:8080</code>）；macOS 首次启动服务时若系统弹出防火墙提示请选择「允许」。</p>

<h4>如何切换界面语言？</h4>
<p>菜单「设置 → 简体中文 / English」，切换后整个界面（含本使用文档）立即生效并自动记忆。</p>

<h4>部分菜单项显示"开发中"？</h4>
<p>「文件 → 新建/打开/保存配置」「探头配置」等功能仍在开发中，其余功能均已可用。欢迎通过「关于 Topos Calibrator」查看版本信息。</p>
`
                }

            ]
        },

        /* ============================== English ============================== */
        'en': {
            chapters: [

                {
                    id: 'quick-start',
                    icon: '🚀',
                    title: 'Quick Start',
                    html: `
<h4>What is Topos Calibrator?</h4>
<p>Topos Calibrator is an ArgyllCMS-based display calibration and measurement tool. With a colorimeter (probe), it can:</p>
<ul>
    <li><strong>Analyze displays</strong> — measure gamut coverage, luminance, contrast, gamma and white point;</li>
    <li><strong>Create ICC profiles</strong> — software-level color calibration for your display;</li>
    <li><strong>Build 3D LUTs</strong> — calibration LUTs for DaVinci Resolve, madVR and other video tools;</li>
    <li><strong>Create CCMX matrices</strong> — spectro-correct a colorimeter using a reference spectrophotometer;</li>
    <li><strong>Validate calibrations</strong> — acceptance reports against sRGB / DCI-P3 and other standards.</li>
</ul>

<h4>Before you measure</h4>
<ol>
    <li><strong>Probe</strong>: connect your colorimeter via USB (e.g. i1 Display Pro, SpyderX).</li>
    <li><strong>Warm-up</strong>: let the display run for 30+ minutes for stable results.</li>
    <li><strong>Ambient light</strong>: measure in a controlled/darkened room; avoid light falling directly on the screen.</li>
    <li><strong>Remove interference</strong>: disable Night Shift / True Tone, f.lux and similar; reset the display to factory or default color temperature.</li>
</ol>
<div class="doc-warn">⚠️ On macOS, first-time use requires granting <strong>USB device access</strong> (and related permissions) in System Settings → Privacy &amp; Security, otherwise the probe cannot connect. The preflight step checks these automatically.</div>

<h4>Your first measurement (5 steps)</h4>
<ol>
    <li>Click the "Display Analysis" card in the <strong>Workflow</strong> panel on the left;</li>
    <li>Click "Start Preflight" and make sure checks pass (warnings may be acceptable);</li>
    <li>In the "Probe / Correction" step, click "Connect Probe" and wait for the connected state;</li>
    <li>In "Target Settings", pick a preset (the default sRGB / D65 / 2.2 works for most), then step through to "Start Measurement";</li>
    <li>When finished, go to the "Report" step and export a PDF / HTML / JSON report.</li>
</ol>
<div class="doc-tip">💡 The app starts in <strong>Guided mode</strong>: a wizard walks you through every step. Once familiar, flip the "Advanced Mode" switch (top-right) for the professional free-form workspace.</div>
`
                },

                {
                    id: 'interface',
                    icon: '🖥️',
                    title: 'Interface Tour',
                    html: `
<h4>Main window layout</h4>
<p>The window consists of a <strong>menu bar</strong>, a <strong>left / center / right layout</strong>, and a <strong>status bar</strong>:</p>
<ul>
    <li><strong>Left panel</strong> — Guided mode shows the workflow cards and wizard steps (Targets / Probe &amp; Correction / Measurement); Advanced mode shows the Advanced Settings panel (probe, display type, measurement delay…) and the Measurement Mode panel.</li>
    <li><strong>Center area</strong> — the wizard step workspace (preflight results, measurement progress, generation &amp; report) plus the Basic Display Data and Current Patch Data panels.</li>
    <li><strong>Right panel</strong> — charts: CIE 1931 chromaticity diagram, gamma curve, saturation tracking, CCT tracking and uniformity analysis.</li>
    <li><strong>Status bar</strong> — operation hints on the left, a scrolling log on the right; failure reasons are printed here in detail.</li>
</ul>

<h4>Menu bar</h4>
<table>
    <tr><th>Menu</th><th>Items</th></tr>
    <tr><td>File</td><td>Export CSV / Export report (some configuration items are under development), Quit</td></tr>
    <tr><td>Measure</td><td>Connect Probe (⌘K), Calibrate Probe, Loop Measurement (⌘M), Stop Measurement (Esc)</td></tr>
    <tr><td>View</td><td>Show/hide panels, Measurement Window, Web Measurement Server toggle, Data Comparison</td></tr>
    <tr><td>Settings</td><td>Advanced Mode, language (简体中文 / English), Preferences, Probe Config (in development)</td></tr>
    <tr><td>Help</td><td>Documentation (this window), About Topos Calibrator</td></tr>
</table>

<h4>Guided mode vs Advanced mode</h4>
<ul>
    <li><strong>Guided (default)</strong>: pick a workflow and the UI navigates you through Preflight → Targets → Probe/Correction → Measurement → Generation → Validation → Report. Best for new users.</li>
    <li><strong>Advanced</strong>: the wizard is hidden — connect the probe, choose a measurement mode (gamut / ICC / LUT / uniformity / HDR…) and parameters yourself, and drive measurement with the Single / Loop / Stop buttons. History loading and comparison are also unlocked here.</li>
</ul>
<p>Three equivalent switches: menu "Settings → Advanced Mode", the top-right "Advanced Mode" toggle, or the button in the workflow panel. Switching is blocked while a measurement is running.</p>
<div class="doc-tip">💡 The mode is remembered across launches.</div>
`
                },

                {
                    id: 'probe',
                    icon: '🔌',
                    title: 'Probe Connection & Calibration',
                    html: `
<h4>Connecting a probe</h4>
<ol>
    <li>Connect the colorimeter via USB (remove the lens cap if required);</li>
    <li>Click menu "Measure → Connect Probe" (⌘K) or the "Connect Probe" button;</li>
    <li>First-time device enumeration can take 10–20 seconds — watch the status bar and log. When connected, the button becomes "Disconnect Probe".</li>
</ol>
<div class="doc-tip">💡 30+ instruments are supported: X-Rite i1 Display Pro / i1 Pro 2 / i1 Pro 3, ColorMunki, the Datacolor Spyder family, Klein K10-A, JETI spectrophotometers, ColorHug, HCFR and more. If the detected device differs from the selected probe type, the software switches the type automatically.</div>
<div class="doc-warn">⚠️ macOS requires the "USB device access" permission; Windows needs the instrument driver; Linux needs udev rules. Preflight gives specific guidance.</div>

<h4>Calibrating the probe</h4>
<p>Colorimeters rely on a dark/ambient offset calibration: after connecting, click "Calibrate Probe", place the probe on its white calibration reference (or cap it, per the instrument manual) and wait for "Probe calibrated". Recalibrate before every session and whenever ambient light changes.</p>

<h4>Spectral correction (key to colorimeter accuracy)</h4>
<p>Colorimeters (e.g. i1 Display Pro) show spectral bias on certain backlight technologies. Load a <strong>correction file</strong> to compensate:</p>
<ul>
    <li><strong>Built-in library</strong>: common display × probe corrections (CCMX/CCSS) ship with the app; pick one from the "Spectral Correction" dropdown grouped by probe. Metadata (type, target display tech, date, reference instrument) is shown on selection;</li>
    <li><strong>Import EDR</strong>: official X-Rite .edr files from i1Profiler can be imported via "Import EDR…" — they are converted to CCSS automatically;</li>
    <li><strong>Custom CCMX</strong>: create your own matrix with the CCMX workflow using a spectrophotometer as reference (see the CCMX chapter).</li>
</ul>
<div class="doc-tip">💡 The "Display Type" selection (LCD Generic / LCD White LED / OLED / WOLED…) drives ArgyllCMS settling behavior and correction matching — choose the one matching your panel.</div>
`
                },

                {
                    id: 'workflow-gamut',
                    icon: '🔍',
                    title: 'Workflow: Display Analysis',
                    html: `
<h4>Purpose</h4>
<p>Measure the display's color performance and produce a report of gamut coverage, luminance, gamma and white point — the most commonly used workflow.</p>

<h4>Wizard steps</h4>
<ol>
    <li><strong>Preflight</strong> — 20+ automatic checks (ArgyllCMS tools, probe connection, system color-temperature interference, sleep settings, USB permissions…). Individual checks can be overridden, but enabling "Advanced override" may compromise accuracy; the preflight report can be exported as JSON.</li>
    <li><strong>Target Settings</strong> — choose the reference standard (table below).</li>
    <li><strong>Probe / Correction</strong> — connect &amp; calibrate the probe, select a spectral correction.</li>
    <li><strong>Measurement</strong> — review the settings summary and click "Start Measurement". Do not move the probe; patch preview, progress, ETA and repeatability stats update live.</li>
    <li><strong>Report</strong> — export PDF / HTML / JSON.</li>
</ol>

<h4>Target presets</h4>
<table>
    <tr><th>Preset</th><th>Gamut</th><th>White point</th><th>Gamma</th><th>Use case</th></tr>
    <tr><td>sRGB (default)</td><td>sRGB</td><td>D65 (6500K)</td><td>2.2</td><td>Office, web, general use</td></tr>
    <tr><td>Rec.709</td><td>Rec.709</td><td>D65</td><td>2.4 (BT.1886)</td><td>HD video production</td></tr>
    <tr><td>DCI-P3</td><td>DCI-P3</td><td>D63</td><td>2.6</td><td>Digital cinema, HDR reference</td></tr>
    <tr><td>Custom</td><td>Display P3 / Adobe RGB / Rec.2020…</td><td>D50/D65/D75/native</td><td>2.2/2.4/2.6</td><td>Manual combinations</td></tr>
</table>
<p>"Advanced parameters" expose gray-level count (10 fast / 21 standard / 256 fine), patch count (auto / 99–1500) and sampling strategy (balanced / shadow-priority / grayscale-priority).</p>
<div class="doc-tip">💡 After measuring, the CIE chart overlays your measured gamut on the selected reference. Gamut coverage is always reported for sRGB / DCI-P3 / AdobeRGB / Rec.2020 simultaneously.</div>
`
                },

                {
                    id: 'workflow-icc',
                    icon: '📄',
                    title: 'Workflow: ICC Profiling',
                    html: `
<h4>Purpose</h4>
<p>Measure the display and build an ICC profile used by OS color management in color-managed apps (Photoshop, Safari, …).</p>

<h4>Wizard steps</h4>
<p>The full 7-step flow (Preflight → Targets → Probe/Correction → Measurement → Generation → Validation → Report) adds two steps over Display Analysis:</p>
<ol>
    <li>Complete preflight, targets, probe and measurement as usual;</li>
    <li><strong>Generation</strong> — in "ICC Profile Settings" choose:
        <ul>
            <li><strong>Profile type</strong>: LUT type (recommended, higher accuracy) or matrix type (better compatibility, smaller);</li>
            <li><strong>Quality</strong>: Medium / High (default) / Ultra — higher quality takes longer;</li>
            <li><strong>Save path</strong>: leave empty to use the default measurements folder.</li>
        </ul>
        Click "Generate ICC Profile"; a summary (file path, target vs measured white point) appears when done.</li>
    <li><strong>Validation</strong> — 64 verification patches are re-measured automatically to grade the profile;</li>
    <li><strong>Report</strong> — export the calibration report.</li>
</ol>

<h4>Installing the profile</h4>
<ul>
    <li>Tick "Apply ICC color profile" in the ICC tab of the export dialog — the app installs it into the system and activates it immediately;</li>
    <li>Or select it manually in your OS display settings.</li>
</ul>
<div class="doc-warn">⚠️ ICC calibration is <strong>software-only</strong>: it affects color-managed applications. For uniform correction across players and games, use the 3D LUT workflow with a LUT loader (madVR, Resolve, …).</div>
<div class="doc-tip">💡 Afterwards, run the Validation workflow to compare before/after gamut and white point and quantify the gain.</div>
`
                },

                {
                    id: 'workflow-lut',
                    icon: '🎬',
                    title: 'Workflow: 3D LUT',
                    html: `
<h4>Purpose</h4>
<p>Measure the display and generate a 3D LUT for DaVinci Resolve, madVR, Premiere (Lumetri) and other video tools, achieving uniform color across the whole pipeline.</p>

<h4>Wizard steps</h4>
<p>Same 7-step flow as ICC; the Generation step becomes "3D LUT Settings":</p>
<ul>
    <li><strong>Source gamut</strong>: the space the display currently operates in (Rec.709 / sRGB / Display P3 / DCI-P3 / Rec.2020);</li>
    <li><strong>LUT size</strong>: 33³ (standard, recommended) or 65³ (high precision — larger and slower);</li>
    <li><strong>Output format</strong>: <code>.cube</code> (Resolve &amp; most tools, default), <code>.3dl</code> (10-bit integer), <code>.mga</code>, <code>.clf</code> (Common LUT Format).</li>
</ul>
<p>Click "Generate 3D LUT"; auto validation and report steps follow as usual.</p>

<h4>Loading the LUT</h4>
<ul>
    <li><strong>DaVinci Resolve</strong>: Project Settings → Color Management → load the .cube as 3D LUT / output LUT, or place it in the LUT folder;</li>
    <li><strong>madVR</strong>: renderer settings → colour management → "install the 3D LUT" (.3dl/.cube);</li>
    <li><strong>Others</strong>: any player/monitor pipeline that accepts .cube works the same way.</li>
</ul>
<div class="doc-tip">💡 For video work target Rec.709 / D65 / Gamma 2.4 (BT.1886). A LUT does not adjust the panel itself — it corrects the signal after the LUT loader.</div>
`
                },

                {
                    id: 'workflow-ccmx',
                    icon: '🔧',
                    title: 'Workflow: CCMX Matrix',
                    html: `
<h4>Purpose</h4>
<p>Colorimeters have systematic spectral bias on specific displays. Using a <strong>spectrophotometer</strong> (i1 Pro etc., high accuracy) as reference and measuring the same patches simultaneously with your <strong>colorimeter</strong>, you create a CCMX correction for that probe × display pair, bringing the colorimeter close to spectro accuracy.</p>

<h4>Wizard steps</h4>
<ol>
    <li>Preflight, targets, probe/correction (set the spectrophotometer as active probe);</li>
    <li><strong>Measurement</strong> — run a loop measurement with the spectro and click "Save Data";</li>
    <li>Swap to the colorimeter (same position, same display state), run the loop measurement again and save;</li>
    <li><strong>Generation</strong> — in "CCMX Matrix Settings" pick:
        <ul>
            <li><strong>Reference measurement</strong>: the spectro dataset;</li>
            <li><strong>Target measurement</strong>: the colorimeter dataset;</li>
            <li><strong>Description</strong>: a recognizable name (e.g. "i1d3 for LG OLED");</li>
        </ul>
        then click "Generate CCMX Matrix". The .ccmx is added to the correction library and becomes selectable under "Spectral Correction".</li>
</ol>
<div class="doc-warn">⚠️ Both measurements must use the <strong>same patch sequence</strong> (white, red, green, blue) with identical display settings (brightness, color temperature, mode); keep the probe position consistent, or the matrix will introduce error.</div>
<div class="doc-tip">💡 No spectrophotometer? Try the built-in correction library first, or import an official EDR from i1Profiler.</div>
`
                },

                {
                    id: 'workflow-validation',
                    icon: '✅',
                    title: 'Workflow: Validation',
                    html: `
<h4>Purpose</h4>
<p>Re-measure the display <strong>after</strong> an ICC or 3D LUT is active and produce an acceptance verdict (pass / warning / fail) against industry thresholds, quantifying the calibration result.</p>

<h4>How to run</h4>
<ol>
    <li>Make sure the state under test is active (ICC installed &amp; enabled, or LUT loaded in the player);</li>
    <li>Select the Validation workflow and complete preflight and probe connection;</li>
    <li>Choose the acceptance standard in Target Settings (sRGB / Rec.709 / DCI-P3 / Rec.2020 / AdobeRGB);</li>
    <li>Start measurement (64 verification patches by default) and export the validation report.</li>
</ol>

<h4>Standard thresholds</h4>
<table>
    <tr><th>Standard</th><th>ΔE avg</th><th>ΔE max</th><th>White point</th><th>Gamma</th><th>Coverage</th></tr>
    <tr><td>sRGB / Rec.709</td><td>≤ 2.0</td><td>≤ 6.0</td><td>±200K / Δuv ≤ 0.005</td><td>±0.05</td><td>≥ 95%</td></tr>
    <tr><td>DCI-P3</td><td>≤ 3.0</td><td>≤ 8.0</td><td>±300K / Δuv ≤ 0.007</td><td>±0.05</td><td>≥ 90%</td></tr>
    <tr><td>Rec.2020</td><td>≤ 3.0</td><td>≤ 8.0</td><td>±200K / Δuv ≤ 0.005</td><td>±0.05</td><td>≥ 80%</td></tr>
    <tr><td>AdobeRGB</td><td>≤ 2.5</td><td>≤ 7.0</td><td>±200K / Δuv ≤ 0.005</td><td>±0.05</td><td>≥ 90%</td></tr>
</table>
<div class="doc-tip">💡 Rule of thumb: ΔE avg &lt; 1 is imperceptible; 1–2 excellent; 2–3.5 acceptable; &gt; 3.5 — recalibrate.</div>
`
                },

                {
                    id: 'measurement-settings',
                    icon: '⚙️',
                    title: 'Measurement Settings',
                    html: `
<p>These parameters live in the Advanced Mode "Advanced Settings" panel, or in wizard step 3 "Probe / Correction":</p>

<h4>Probe</h4>
<ul>
    <li><strong>Probe type</strong>: must match the connected instrument (auto-corrected on connection);</li>
    <li><strong>Spectral correction</strong>: pick a CCMX/CCSS file — see the Probe chapter;</li>
    <li><strong>Calibrate Probe</strong>: zero-offset calibration before measuring.</li>
</ul>

<h4>Display</h4>
<ul>
    <li><strong>Display type</strong>: LCD Generic / LCD White LED / LCD RGB LED (wide gamut) / OLED / WOLED / CRT / projector… This drives per-patch settling times (OLED settles fast; some LCDs need longer);</li>
    <li><strong>Refresh rate</strong>: auto-detect by default; override with 60/120/144/240 Hz if needed;</li>
    <li><strong>Measurement delay</strong>: settling time after each patch switch, default 500 ms. OLED can use 100–200 ms for speed; slow panels benefit from 1000 ms+.</li>
</ul>

<h4>Measurement quality</h4>
<ul>
    <li><strong>Averaging</strong>: average multiple readings per patch to reduce noise (1 = off; 2–4 recommended, proportionally slower);</li>
    <li><strong>Dark sampling</strong>: automatically re-samples low-light readings (threshold 0.2 cd/m², up to 3 retries). Essential for accurate black point — keep enabled;</li>
    <li><strong>Repeatability stats</strong>: live standard deviation and max deviation, used to judge stability.</li>
</ul>

<h4>Interruptions &amp; resume</h4>
<p>If the probe drops mid-run, the app auto-reconnects (up to 3 times) and continues. You can also "Stop &amp; save checkpoint" and resume later without restarting from scratch.</p>
<div class="doc-tip">💡 Always place the probe flush against the screen (no light leaks). A gap inflates dark readings dramatically. A counterweight makes i1-Style probes sit flush.</div>
`
                },

                {
                    id: 'advanced-mode',
                    icon: '🧰',
                    title: 'Advanced Mode',
                    html: `
<p>In Advanced mode the left panel offers a "Measurement Mode" dropdown with 9 modes:</p>
<table>
    <tr><th>Mode</th><th>Purpose</th></tr>
    <tr><td>Display analysis (color space)</td><td>Same as the Display Analysis workflow: gamut / gamma / white point</td></tr>
    <tr><td>Display correction (ICC)</td><td>Full dispcal + colprof pipeline with calibration white point / gamma / quality and patch count options</td></tr>
    <tr><td>Hardware calibration (3D LUT)</td><td>Measure then build a 3D LUT (17³/33³/65³) with rendering intent and black point compensation (BPC)</td></tr>
    <tr><td>Custom colors</td><td>Edit an RGB patch list manually (add / rename / delete / save as patch set) and measure anything</td></tr>
    <tr><td>CCMX matrix</td><td>Generate a matrix from spectro + colorimeter datasets (same as the CCMX workflow)</td></tr>
    <tr><td>Saturation/hue sweep</td><td>6 colors × 4 saturation levels + 12 hue steps + neutral axis = 40 patches (3–5 min), feeding the Saturation Tracking chart; auto chart switch optional</td></tr>
    <tr><td>HDR EOTF tracking</td><td>PQ (ST 2084) / HLG with target peak 400–4000 nits; ~21 log-spaced gray levels graded with ΔE ITP</td></tr>
    <tr><td>Uniformity</td><td>3×3 / 5×5 grid measured at 100% white / 50% / 30% gray; produces luminance &amp; chromaticity heatmaps</td></tr>
    <tr><td>AutoCal (closed loop)</td><td>Drives the monitor OSD via DDC/CI: baseline → compute adjustment → write to display → verify. Iterations / ΔE threshold / settle time configurable, with rehearsal mode and snapshot rollback</td></tr>
</table>

<h4>Uniformity guided mode</h4>
<p>With "Guided (confirm each point)" enabled, the measurement window places the patch over each grid cell in turn and pauses. Aim the probe at the highlighted region, then press <strong>Space</strong> or click "✓ Measure this point". A luminance/chromaticity heatmap is generated automatically at the end.</p>

<h4>AutoCal notes</h4>
<ul>
    <li>Click "Connect DDC/CI" first (display must support DDC/CI; OS permissions required);</li>
    <li>First run? Enable <strong>Rehearsal mode</strong> (computes the plan without writing to the display);</li>
    <li>A snapshot is taken before writing — use "Rollback" to restore the previous state.</li>
</ul>
`
                },

                {
                    id: 'results',
                    icon: '📊',
                    title: 'Understanding Results',
                    html: `
<h4>Basic display data</h4>
<ul>
    <li><strong>Peak luminance</strong>: 100% white (cd/m²). 120–150 suits office/sRGB work; lower for video;</li>
    <li><strong>Black level</strong>: 0% reading — lower is better; <strong>Contrast</strong> = peak / black;</li>
    <li><strong>Gamma</strong>: measured gray-scale gamma (high end) — deviation from target (e.g. 2.2) should be minimal;</li>
    <li><strong>White point CCT / x / y / ΔE</strong>: measured white vs target — ΔE ≤ 2 is good.</li>
</ul>

<h4>Current patch data</h4>
<p>Live readout of the latest patch: x, y chromaticity, luminance Y (cd/m²), CCT (K), ΔE and u' v'.</p>

<h4>Charts (right panel)</h4>
<ul>
    <li><strong>CIE 1931 chromaticity</strong>: measured RGBW points and gamut triangle, overlayable with 10+ references (sRGB / DCI-P3 / AdobeRGB / Rec.2020 / ProPhoto / ACES…);</li>
    <li><strong>Gamma curve</strong>: measured response vs reference curves (2.2 / 2.4 BT.1886 / sRGB / PQ / HLG / Log…);</li>
    <li><strong>Saturation tracking</strong>: target vs measured per saturation level (after a saturation sweep);</li>
    <li><strong>CCT tracking</strong>: per-gray-level color temperature and Δuv trend after a grayscale run;</li>
    <li><strong>Uniformity</strong>: heatmap after a uniformity run — green &lt; 3% deviation, red &gt; 10%; hover for per-point details.</li>
</ul>

<h4>Measurement progress panel</h4>
<p>During measurement: patch preview (name / RGB / Y), progress and ETA, average time per patch and repeatability stats. On a failed point, choose "🔄 Retry this point", "⏭ Skip &amp; mark" or "⏹ Stop &amp; save checkpoint"; the error area suggests next steps.</p>
<div class="doc-tip">💡 The <strong>confidence score</strong> in reports (rejected reading ratio, warm-up stability, …) summarizes overall measurement quality — recalibrate the probe and re-seat it if confidence is low.</div>
`
                },

                {
                    id: 'patch-window',
                    icon: '🪟',
                    title: 'Measurement Window',
                    html: `
<h4>Purpose</h4>
<p>The Measurement Window is a separate solid-color patch window shown on the screen for the probe to read during measurement. Open it from menu "View → Measurement Window" or the main-window button.</p>

<h4>Controls</h4>
<ul>
    <li><strong>＋ / −</strong>: grow / shrink; drag the bottom-right grip to resize;</li>
    <li><strong>⤢ Fullscreen</strong>: the entire screen becomes a solid patch (no window chrome to pollute readings); press <strong>Esc</strong> to exit;</li>
    <li><strong>✕</strong>: close; the bottom label shows the live RGB value.</li>
</ul>

<h4>Multi-display setups</h4>
<p>With multiple displays, the window automatically moves to the secondary display and fullscreens there during measurement while the primary display stays interactive.</p>

<h4>Guided confirmation</h4>
<p>In guided runs (e.g. uniformity) a floating bar appears below the fullscreen patch: <strong>Space / Enter</strong> confirms "✓ Measure this point", or click "⏹ Stop Measurement". Align the probe over the displayed region before confirming.</p>
<div class="doc-tip">💡 The window is drawn directly by Qt and bypasses the system ICC — the probe reads exactly what the GPU outputs. Browser-based display does not have this property (see the Web Measurement Server chapter).</div>
`
                },

                {
                    id: 'web-server',
                    icon: '🌐',
                    title: 'Web Measurement Server',
                    html: `
<h4>Purpose</h4>
<p>When started, phones / tablets / other computers on the same LAN can open the server address in a browser and act as a <strong>patch display</strong> (fullscreen color page) — handy for measuring a second device or one that cannot run this app.</p>

<h4>Enabling</h4>
<ul>
    <li>Menu "View → Web Measurement Server" toggles start / stop;</li>
    <li>Or "Settings → Preferences → 🌐 Web Measurement Server" → tick "Enable web measurement service".</li>
</ul>
<p>While running, Preferences shows a status badge (Running / Not running), the <strong>service address</strong> (e.g. <code>http://192.168.1.100:8080</code>) and a <strong>Copy</strong> button — paste it into any browser to open. Changing the port (1024–65535) restarts the service automatically.</p>

<h4>Browser side</h4>
<p>The page shows the current color fullscreen with the RGB value in the corner, syncing with the app every 100 ms. Run a Loop Measurement as usual to measure it.</p>

<h4>Color management caveat</h4>
<div class="doc-warn">⚠️ Browsers render <strong>through</strong> system color management, unlike the Qt window (which bypasses ICC). For native browser output, enable "Auto-clear system ICC" in Preferences (clears the GPU VCGT/LUT) and optionally "Null Profile scheme" (mounts a linear ICC so browsers bypass the system profile).</div>
<div class="doc-tip">💡 Device can't connect? Check same Wi-Fi network, firewall rules for the port, and that you entered the full address including the port.</div>
`
                },

                {
                    id: 'data-comparison',
                    icon: '🗂️',
                    title: 'Data & Comparison',
                    html: `
<h4>Saving measurements</h4>
<ul>
    <li><strong>Manual</strong>: "Save Data" writes a JSON file into <code>measurements/</code> named with timestamp and measurement ID;</li>
    <li><strong>Auto-save</strong>: on by default (configurable in Preferences) — <code>measurements/auto_save/date/time_mode.json + .ti3</code>;</li>
    <li>.ti3 is the ArgyllCMS standard measurement format, directly usable by dispcal/colprof etc.</li>
</ul>

<h4>Comparison window</h4>
<p>Open via menu "View → Data Comparison":</p>
<ol>
    <li><strong>Select data</strong> — tick two or more saved runs in the left panel (group by display / target / workflow / date);</li>
    <li><strong>Overview</strong> — CIE gamut and gamma overlay comparison; the key-parameters table highlights the best value of each metric in green (luminance, contrast, white point, ΔE, coverage…);</li>
    <li><strong>Patch details</strong> — per-patch RGB / xyY / CCT / ΔE side-by-side;</li>
    <li><strong>Trends</strong> — track white luminance / CCT / average gamma / Δu'v' across runs to spot drift and calibration decay.</li>
</ol>
<p>"Export" saves the comparison as an HTML report.</p>

<h4>Golden Baseline</h4>
<p>Right-click a measurement to <strong>mark it as Golden Baseline</strong> (per display + target standard). Any run can then be compared against it to instantly check whether the display drifted — ideal for periodic rechecks.</p>
<div class="doc-tip">💡 Save and mark a Golden Baseline right after each successful calibration — your "factory reference" for that display and standard.</div>
`
                },

                {
                    id: 'export',
                    icon: '📤',
                    title: 'Export & Reports',
                    html: `
<h4>Unified export dialog</h4>
<p>Menu "File → Export CSV…" or the top "Export" button opens the 📦 export dialog with five tabs:</p>
<table>
    <tr><th>Tab</th><th>Formats</th><th>Notes</th></tr>
    <tr><td>Color space</td><td>TI3 / CSV / JSON</td><td>Raw measurement data (gamut + grayscale, selectable)</td></tr>
    <tr><td>ICC correction</td><td>ICC Profile / TI3</td><td>Build a profile from saved or current data; type / quality / target white point / gamma / BPC; one-click "Apply ICC color profile"</td></tr>
    <tr><td>LUT correction</td><td>CUBE / 3DL / MGA / CLF</td><td>Quick (gamma only) or Advanced (ICC + Collink); sizes 17³–129³, rendering intent, Full/Video range</td></tr>
    <tr><td>Custom</td><td>CSV / JSON / TI3</td><td>Custom patch set data</td></tr>
    <tr><td>CCMX</td><td>CCMX / CSV</td><td>Correction matrix or measurement table</td></tr>
</table>

<h4>Quick generation</h4>
<p>After a measurement, "⚡ Quick ICC" / "⚡ Quick LUT" produce a file in one click using the measured white point and default settings; use the full dialog when you need fine control.</p>

<h4>Reports</h4>
<ul>
    <li><strong>PDF</strong> (wizard step 7): target parameters, probe &amp; display info, white point / gamma / gamut coverage, ΔE statistics and histogram, measurement confidence, pass/warn/fail verdict, plus gamma / CIE / ΔE charts;</li>
    <li><strong>HTML / JSON</strong>: web and machine-readable versions of the same data;</li>
    <li><strong>Preflight report</strong>: the preflight results can be archived as JSON.</li>
</ul>
<div class="doc-tip">💡 CSV contains two tables: gamut (Color, RGB, XYZ, xy, Y) and grayscale (RGB, XYZ, xy, Y) — opens directly in Excel / Numbers.</div>
`
                },

                {
                    id: 'preferences',
                    icon: '🎛️',
                    title: 'Preferences',
                    html: `
<p>Open via menu "Settings → Preferences". Four sections:</p>

<h4>🌗 Appearance</h4>
<ul>
    <li><strong>Dark room mode</strong>: further dims the UI background, text and accent saturation — reduces glare interference during dark-room calibration;</li>
    <li><strong>Font size</strong>: Standard / Large (115%) / Extra large (130%).</li>
</ul>

<h4>💾 Auto-save</h4>
<ul>
    <li><strong>Auto-save after measurement</strong>: on by default;</li>
    <li><strong>Folder</strong>: <code>measurements/auto_save</code> by default; format <code>date/time_mode.json + .ti3</code>.</li>
</ul>

<h4>🌐 Web Measurement Server</h4>
<ul>
    <li><strong>Enable web measurement service</strong>: start/stop with live status;</li>
    <li><strong>Port</strong>: 8080 by default (1024–65535); changes restart the service automatically;</li>
    <li><strong>Address + Copy</strong>: one-click copy of the full URL. See the Web Measurement Server chapter.</li>
</ul>

<h4>🎨 Advanced color management</h4>
<ul>
    <li><strong>Auto-clear system ICC</strong> (default on): clears the GPU LUT (VCGT) before measuring so the display's native state is measured;</li>
    <li><strong>Null Profile scheme</strong>: mounts a linear ICC so browsers bypass the system profile — only needed for Web measurement (the Qt window already bypasses ICC); requires the option above.</li>
</ul>
<div class="doc-tip">💡 Interface language lives in the menu ("Settings → 简体中文 / English"), not in Preferences. This documentation follows the interface language automatically.</div>
`
                },

                {
                    id: 'shortcuts',
                    icon: '⌨️',
                    title: 'Keyboard Shortcuts',
                    html: `
<table>
    <tr><th>Shortcut</th><th>Scope</th><th>Action</th></tr>
    <tr><td><code>⌘K</code></td><td>Main window</td><td>Connect / disconnect probe</td></tr>
    <tr><td><code>⌘M</code></td><td>Main window</td><td>Start loop measurement</td></tr>
    <tr><td><code>Esc</code></td><td>Main window</td><td>Stop measurement</td></tr>
    <tr><td><code>Esc</code></td><td>Patch window fullscreen</td><td>Exit fullscreen</td></tr>
    <tr><td><code>Space</code> / <code>Enter</code></td><td>Guided / fullscreen measurement</td><td>Confirm "✓ Measure this point"</td></tr>
</table>
<div class="doc-tip">💡 Every action is also available from the menu bar; shortcuts are shown in the Measure menu.</div>
`
                },

                {
                    id: 'faq',
                    icon: '❓',
                    title: 'FAQ',
                    html: `
<h4>The probe won't connect</h4>
<ul>
    <li>macOS: check System Settings → Privacy &amp; Security → USB device access for this app;</li>
    <li>First enumeration may take 10–20 seconds — watch the log; unplug/replug and retry;</li>
    <li>Make sure the selected probe type matches the device (auto-corrected after a successful connection);</li>
    <li>Windows: install the instrument driver; Linux: udev rules are required (preflight explains).</li>
</ul>

<h4>Preflight shows blocking items</h4>
<p>Blocking items (missing ArgyllCMS tools, probe not connected, missing USB permissions) prevent measurement from starting. Follow the suggestions shown for each item. Experienced users may tick "Advanced override" to proceed anyway — this <strong>may compromise accuracy</strong>.</p>

<h4>Measurement failed / probe dropped mid-run</h4>
<p>The app auto-reconnects (up to 3 times) and continues. Otherwise use "Stop &amp; save checkpoint", fix the issue, and resume from the checkpoint. Single failed points can be retried or skipped &amp; marked.</p>

<h4>Dark patches are slow to measure</h4>
<p>With dark sampling enabled, low-luminance patches get extra re-sampling for accuracy — normal behavior. Disable it or raise the threshold if you don't need deep-black precision.</p>

<h4>Results look wrong</h4>
<ul>
    <li>Check the <strong>spectral correction</strong> matches your display (built-in library / EDR / custom CCMX);</li>
    <li>Display not warmed up (30+ min) or ambient light hitting the screen;</li>
    <li>Night Shift / True Tone / f.lux still active;</li>
    <li>Probe not flush (light leak) or moved during measurement;</li>
    <li>"Auto-clear system ICC" disabled while a GPU VCGT/LUT is active.</li>
</ul>

<h4>Browser can't open the Web measurement address</h4>
<p>Confirm the device is on the same LAN, the status badge shows "Running", and the address includes the port (e.g. <code>http://192.168.x.x:8080</code>). On macOS, allow the firewall prompt on first start.</p>

<h4>How do I switch the interface language?</h4>
<p>Menu "Settings → 简体中文 / English". The whole UI — including this documentation — switches immediately and is remembered.</p>

<h4>Some menu items say "in development"?</h4>
<p>"File → New/Open/Save Profile" and "Probe Config" are still under development; everything else is fully functional. See "About Topos Calibrator" for version info.</p>
`
                }

            ]
        }
    };

    global.DOCS_CONTENT = DOCS_CONTENT;

})(typeof window !== 'undefined' ? window : globalThis);
