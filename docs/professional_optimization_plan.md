# Topos Calibrator 专业化优化计划（AI 多 Agent 执行版）

更新时间：2026-05-19（v2 — 根据专业评审调整了阶段顺序、模块粒度、回滚策略、量化基准和并行策略）

本文档面向后续 AI 大模型/多 agent 执行。目标不是写愿望清单，而是把 Topos Calibrator 从“功能很丰富的校色工具原型”推进到“可验证、可复现、可交付的专业校色软件”。

## 0. 当前评价

### 已经做得不错的部分

- 技术路线是对的：Python + PyQt6/QWebEngine + QWebChannel + ArgyllCMS，适合快速做跨平台校色工具。
- 已经不是简单 UI 原型：`src/argyll_controller.py` 包含 spotread、dispcal、targen、colprof、collink、ccxxmake 等 ArgyllCMS 工作流封装。
- 已经考虑了专业场景：多探头、CCSS/CCMX、Null Profile、显卡 LUT 清理、断点续测、暗部多重采样、OLED 黑帧、防休眠、多屏显示、历史对比、自动保存。
- 数据链路已经成形：`src/data_storage.py` 能保存 JSON/TI3，会话目录、自动保存和历史列表都已经有基础。
- 前端交互已经覆盖很多工作流：`web/js/main.js` 有测量模式、ICC/LUT 导出、自定义色块、偏好设置、历史数据和对比窗口。

### 离“专业校色软件”还差什么

- 色彩科学层需要严格化。当前 `src/measurement_analyzer.py` 的色域覆盖率仍有“面积比近似”，Gamma/EOTF、CCT/Duv、Delta E、白点适配、采样策略需要用可验证算法和标准测试向量重做。
- 架构需要拆分。`src/backend.py` 超过 7700 行，状态、UI 信号、Argyll 调用、测量流程、文件管理、校准逻辑混在一起，后续模型很容易改坏。
- 工作流需要状态机。测量、校准、ICC、LUT、断点恢复、错误处理目前靠大量布尔变量协调，专业化后要有明确状态和事件。
- 数据模型需要版本化。历史数据中已经能看到重复 ID/重复记录风险，需要 session manifest、schema version、迁移和去重策略。
- 测量可靠性还需要量化。专业工具不能只显示一个结果，要报告重复性、漂移、噪声、置信度、环境风险、仪器修正状态。
- 文档和代码存在漂移。例如 `docs/optimization_summary.md` 说 QWebChannel 已改为 dict/list，但当前 `src/backend.py` 仍以 JSON 字符串信号为主。

## 1. 多 Agent 协作规则

后续每个 agent 都必须遵守：

- 只修改自己任务卡指定的文件范围；需要跨范围时先写清楚理由。
- 每个任务必须配测试或验证脚本；没有硬件时使用 fake Argyll/mock instrument。
- 每个任务完成后在 PR/交付说明中写：改了什么、风险是什么、如何验证、哪些后续任务被解锁。
- 不要同时让两个 agent 改 `src/backend.py` 的同一区域。架构拆分阶段先由一个 agent 抽公共接口，再让其他 agent 并行迁移。
- 色彩科学相关改动必须引用标准公式、测试向量或第三方工具交叉验证结果。
- 所有新数据格式必须带 `schema_version`，并保持旧数据可读。

建议后续新建目录：

```text
src/core/                  # 纯业务状态机，不依赖 PyQt UI
src/color_science/         # 色彩科学算法与标准数据
src/instruments/           # 探头和 ArgyllCMS 适配
src/workflows/             # 测量/校准/ICC/LUT 工作流
src/storage/               # 数据模型、迁移、manifest
tests/                     # 单元测试和集成测试
tests/fixtures/            # Argyll 输出样本、测量样本、标准测试向量
docs/agent_handoffs/       # 每个 agent 的交接报告
```

## 2. 总体路线图

| 阶段 | 目标 | 是否可并行 | 完成标志 |
|---|---|---:|---|
| P0 基线审计 | 固定现状、列风险、补测试夹具 | 高 | 有风险清单、测试夹具、可重复运行的基础测试 |
| P5 数据与报告 | 专业报告、数据版本、历史治理 | 高 | 支持迁移、去重、报告导出 |
| P2 色彩科学核心 | 重写标准算法和报告指标 | 高 | 有标准测试向量，算法误差在阈值内 |
| P1 架构拆分 | 把后端巨石拆成可测试模块 | 中 | `backend.py` 只负责 Qt 信号桥接和 UI 适配 |
| P3 测量可靠性 | 仪器、色块、稳定性、噪声控制 | 中 | 能输出重复性/漂移/置信度和环境风险 |
| P4 Argyll 专业工作流 | 校准、ICC、3D LUT、CCMX 全链路可靠化 | 中 | 每个工作流有状态机、manifest、失败恢复 |
| P6 UI/UX 专业化 | 让用户按专业流程完成任务 | 高 | 有预检、向导、验证页、清晰错误 |
| P7 QA/打包 | 跨平台测试、日志、打包发布 | 高 | CI 通过，可打包，可追踪 crash |
| P8 硬件验证 | 用真实设备和显示器校验结果 | 低 | 有验证矩阵和可复现实测报告 |

**回滚策略**：每个阶段完成后打 git tag（格式 `phase-P0-YYYYMMDD`）。如果下一阶段引入回归，通过 `git diff <tag>...HEAD` 审查变更，必要时执行 `git revert` 回到上一阶段基线。所有 agent 交付前必须确认当前代码基于最新 tag，避免交叉引入未完成变更。

## 3. P0 基线审计与测试夹具

目标：先把项目“钉住”，让后续 agent 有共同事实依据。

### P0-A 架构与状态流审计

- 负责文件：只读 `src/backend.py`, `src/main_window.py`, `web/js/main.js`
- 输出文件：`docs/agent_handoffs/P0-A_architecture_audit.md`
- 实现思路：
  1. 画出测量链路：前端点击 -> QWebChannel -> Backend -> ArgyllController -> PatchWindow -> 数据保存。
  2. 列出所有状态变量，如 `_cycle_running`, `_session_state`, `_lut_workflow_params`, `_null_profile_applied`, `_current_measure_mode`。
  3. 标注哪些状态可以合并为状态机。
  4. 找出线程边界：后台线程、Qt 主线程、QTimer、Argyll 子进程。
- 验收标准：
  - 文档包含 Mermaid 流程图。
  - 列出至少 20 个关键状态变量及其读写位置。
  - 明确 P1 拆分顺序。

### P0-B 色彩科学审计

- 负责文件：只读 `src/measurement_analyzer.py`, `src/lab_sampler.py`, `src/data_storage.py`
- 输出文件：`docs/agent_handoffs/P0-B_color_science_audit.md`
- 实现思路：
  1. 审查 `calculate_gamut_coverage()`：区分“面积比”“覆盖率”“色域容积”“交集面积”。
  2. 审查 `calculate_gamma()`：检查黑场、白场、输入电平、BT.1886/sRGB/PQ/HLG 处理。
  3. 审查 `calculate_delta_e_2000()`：检查参考白点、chromatic adaptation、Lab 转换。
  4. 审查 `lab_sampler.py`：检查 sRGB/XYZ 矩阵和 gamut clipping 是否会生成重复/裁剪色块。
- 验收标准：
  - 每个算法列出“当前行为、专业期望、改法、测试向量来源”。
  - 明确哪些函数要废弃，哪些可以保留兼容。

### P0-C Argyll 命令与输出夹具

- 负责文件：`tests/fixtures/argyll/`, `docs/agent_handoffs/P0-C_argyll_audit.md`
- 实现思路：
  1. 收集/手写典型 Argyll 输出样本：spotread 成功、spotread USB 断开、dispcal 进度、targen 输出、colprof 成功/失败、collink 成功/失败。
  2. 写 fake subprocess 输出说明，供 P1/P4 测试使用。
  3. 审查 `src/argyll_controller.py` 的命令参数是否和 ArgyllCMS 预期一致。
- 验收标准：
  - 至少 10 个 fixture 文件。
  - 每个 fixture 标明来源、预期解析结果。
  - 明确 fake Argyll 实现方式：使用 monkeypatch 拦截 `subprocess.Popen` 注入预设输出，或通过依赖注入替换 `ArgyllController`。两种方案均需在测试夹具目录中提供实现说明，供 P1/P4 agent 直接复用。

### P0-D 数据治理审计

- 负责文件：只读 `measurements/`, `src/data_storage.py`, `src/comparison_window.py`
- 输出文件：`docs/agent_handoffs/P0-D_data_audit.md`
- 实现思路：
  1. 扫描现有 `measurements/auto_save`，统计重复 ID、缺字段、旧格式。
  2. 列出 JSON、TI3、session 目录之间的对应关系。
  3. 给出 `schema_version` 和 manifest 设计建议。
- 验收标准：
  - 输出重复/异常记录列表。
  - 给出迁移脚本输入输出规范。

## 4. P1 架构拆分

目标：让后续 agent 能并行开发，不再围着一个巨大的 `Backend` 打架。

### P1-A 建立领域事件与状态机

- 负责文件：新增 `src/core/events.py`, `src/core/state.py`, `tests/test_state_machine.py`
- 依赖：P0-A
- 实现思路：
  1. 定义 `MeasurementState`: `IDLE`, `PRECHECK`, `CONNECTING`, `MEASURING`, `SUSPENDED`, `CALIBRATING`, `GENERATING_PROFILE`, `COMPLETED`, `FAILED`。
  2. 定义事件：`StartRequested`, `PatchDisplayed`, `MeasurementReceived`, `InstrumentDisconnected`, `ResumeRequested`, `StopRequested`, `WorkflowFailed`。
  3. 写纯 Python 状态机，不依赖 PyQt。
  4. 用测试覆盖合法/非法状态转换。
- 验收标准：
  - 状态机测试不少于 25 个 case。
  - Backend 仍可暂时不接入，但接口稳定。

### P1-B 抽象测量服务

- 负责文件：新增 `src/workflows/measurement_service.py`, `src/instruments/base.py`, `tests/test_measurement_service.py`
- 依赖：P1-A
- 实现思路：
  1. 把“显示色块 -> 等待稳定 -> 触发测量 -> 接收结果 -> 存储”抽成服务。
  2. 定义 `InstrumentAdapter` 接口：`connect()`, `disconnect()`, `measure()`, `calibrate()`, `status()`。
  3. 定义 `PatchPresenter` 接口：`show_rgb()`, `hide()`, `target_display_id()`。
  4. 用 fake instrument/fake patch presenter 测完整循环，不启动 GUI。
- 验收标准：
  - 可以在无 PyQt、无硬件环境跑测试。
  - 暗部多重采样和 OLED 黑帧逻辑能被单测覆盖。

### P1-C Backend 瘦身

- 负责文件：`src/backend.py`
- 依赖：P1-A, P1-B
- 实现思路：
  1. Backend 保留 QWebChannel 信号/slot。
  2. 将业务逻辑委托给 `MeasurementService`、`WorkflowService`、`StorageService`。
  3. 每次迁移只移动一组相关函数，保持 UI 行为不变。
  4. 不要一次性重写全文件，避免破坏现有可用功能。
- 验收标准：
  - `src/backend.py` 第一轮结束后，所有测量流程编排逻辑（`_cycle_*` 方法、测量回调）已委托给 `MeasurementService`。
  - 第二轮结束后，`src/backend.py` 职责仅限：QWebChannel 信号/slot 注册、UI 状态同步、简单的参数中转。所有业务逻辑（Argyll 调用、测量流程、文件管理、校准逻辑）已移到独立服务模块。
  - 不设立硬性行数目标，但要求每轮评审时确认 `backend.py` 不再包含可直接委托给其他服务的业务方法。
  - 现有 `python3 -m py_compile main.py src/*.py` 通过。

### P1-D 统一信号序列化策略

- 负责文件：`src/backend.py`, `web/js/main.js`, `docs/optimization_summary.md`
- 依赖：P1-C 可并行后半段
- 实现思路：
  1. 决定 QWebChannel 传输统一用 JSON 字符串还是 dict/list，不要文档和代码不一致。
  2. 建议短期保留 JSON 字符串，因为当前代码大量依赖 `JSON.parse`。
  3. 新增 helper：`emit_json(signal, payload)` 和前端 `parsePayload(payload)`。
  4. 删除重复的 try/parse 逻辑。
- 验收标准：
  - `rg "JSON.parse" web/js/main.js` 数量明显下降，集中到 helper。
  - `docs/optimization_summary.md` 与实际策略一致。

## 5. P2 色彩科学核心

目标：专业校色软件的可信度来自算法可验证。

### P2-A 新建色彩科学模块

- 负责文件：新增 `src/color_science/`
- 建议文件（4 个内聚模块，后续可按需拆分）：
  - `spaces.py`: RGB 色彩空间、白点、转换矩阵。
  - `transfer.py`: Gamma/sRGB/BT.1886/PQ/HLG/Log 曲线。
  - `colorimetry.py`: chromatic adaptation（Bradford/CAT02）+ Delta E（CIE76/CIE94/CIEDE2000）+ CCT/Duv。
  - `gamut_sampling.py`: xy 多边形交集、覆盖率、面积、容积、色块采样策略。
  - （注意：不在此阶段接入旧代码，新旧结果并行输出比对。`adaptation.py`/`delta_e.py`/`cct.py`/`sampling.py` 不单独建文件，待模块稳定后再评估是否有必要拆分。）
- 实现思路：
  1. 不直接改旧函数，先建新模块和测试。
  2. 标准数据写进 `tests/fixtures/color_science/`。
  3. 新旧结果并行输出一段时间，方便比对。
- 验收标准：
  - 每个模块有单元测试。
  - CIEDE2000 使用公开测试对，误差小于 `1e-4`。
  - sRGB/XYZ/Lab roundtrip 误差在可接受范围。

### P2-B 精确色域覆盖率

- 负责文件：`src/color_science/gamut_sampling.py`, `src/measurement_analyzer.py`
- 依赖：P2-A
- 实现思路：
  1. 实现三角形/多边形裁剪，计算 measured gamut 与 standard gamut 的真实交集面积。
  2. 输出两个指标：
     - `coverage_percent`: 标准色域被测量色域覆盖多少。
     - `volume_percent` 或 `area_ratio_percent`: 测量色域相对标准面积多大。
  3. 前端不要把面积比误称为覆盖率。
- 验收标准：
  - 当测量色域完全包含 sRGB 时，coverage 为 100%，area ratio 可以大于 100%。
  - 当测量色域面积大但偏移时，coverage 不会错误显示为超高。

### P2-C EOTF/Gamma/BT.1886/HDR

- 负责文件：`src/color_science/transfer.py`, `src/measurement_analyzer.py`, `web/js/charts.js`
- 依赖：P2-A
- 实现思路：
  1. 支持目标曲线：Gamma 2.2/2.4、sRGB、BT.1886、PQ ST 2084、HLG。
  2. 区分输入码值、归一化信号、目标亮度、实测亮度。
  3. 报告每个灰阶点的误差，而不只给一个平均 Gamma。
  4. BT.1886 需要使用实测黑场和白场。
- 验收标准：
  - 图表能显示目标曲线和实测曲线。
  - 输出平均误差、最大误差、暗部误差。

### P2-D Delta E、白点、CCT/Duv

- 负责文件：`src/color_science/colorimetry.py`, `src/measurement_analyzer.py`
- 依赖：P2-A
- 实现思路：
  1. Delta E 计算前先做白点适配，不要固定 D65。
  2. 对白点报告 CCT + Duv，不只报告 McCamy 近似 CCT。
  3. 对灰阶报告 xy 偏移、Duv、Delta E 组合。
- 验收标准：
  - D65、D50、A 光源附近结果符合标准参考值。
  - 报告中能解释“偏绿/偏品红”的方向。

### P2-E 色块采样重做

- 负责文件：`src/color_science/gamut_sampling.py`, `src/lab_sampler.py`, `src/backend.py`
- 依赖：P2-A
- 实现思路：
  1. 修正 `lab_sampler.py` 当前 sRGB/XYZ 转换和裁剪问题。
  2. 避免先生成超色域 Lab 再硬裁剪到 RGB，导致大量重复边界色块。
  3. 提供策略：快速验证、ICC 标准、LUT 高精度、暗部优先、肤色优先、灰阶优先。
  4. 每个色块带 `sample_id`, `rgb`, `purpose`, `priority`。
- 验收标准：
  - 100/500/1500 色块列表重复率低于 1%。
  - 灰阶、暗部、原色、二次色、肤色区域都有覆盖。

## 6. P3 测量可靠性

### P3-A 测量稳定性与重复性

- 负责文件：`src/workflows/measurement_service.py`, `src/color_science/statistics.py`
- 依赖：P1-B
- 实现思路：
  1. 对关键色块支持重复测量 N 次。
  2. 计算均值、标准差、最大偏差、是否超阈值。
  3. 对暗部使用 XYZ 线性平均，保留当前思路，但纳入统一统计模块。
  4. 记录每次测量的 raw XYZ/xyY、时间戳、探头状态。
- 验收标准：
  - 每个 session 可输出 repeatability summary。
  - 超过阈值时 UI 能提示重新测量。

### P3-B 显示稳定与延迟策略

- 负责文件：`src/workflows/settling.py`, `src/backend.py`, `src/patch_window.py`
- 依赖：P1-B
- 实现思路：
  1. 把当前硬编码延迟策略抽成 `SettlingPolicy`。
  2. 策略输入：显示技术、RGB、上一色块、探头、是否 HDR/OLED/投影。
  3. 输出：等待时间、是否插入黑帧、是否重复测量。
  4. 完成 `set_oled_window_size_percent()` 的 TODO，在 `PatchWindow` 实现 10%/18% window patch。
- 验收标准：
  - OLED 10% window patch 可实际显示，周围为纯黑。
  - miniLED/OLED/投影/LCD 有不同默认策略。

### P3-C 环境预检

- 负责文件：`src/workflows/preflight.py`, `src/display_lut_controller.py`, `web/js/main.js`
- 依赖：P1-C
- 实现思路：
  1. 预检项目：Argyll 工具、探头、显示器索引、HDR/ACM、Night Shift/True Tone、系统睡眠、权限、ICC/LUT 当前状态。
  2. 每项给出 `PASS/WARN/BLOCK`。
  3. 用户可导出预检报告用于排障。
- 验收标准：
  - 开始专业测量前必须显示预检结果。
  - BLOCK 项禁止继续，除非用户启用高级覆盖。

### P3-D 探头修正文件管理

- 负责文件：`src/instruments/corrections.py`, `src/backend.py`, `web/js/main.js`
- 依赖：P1-C
- 实现思路：
  1. 区分 CCSS 和 CCMX 的适用条件。
  2. 每个测量结果写入使用的 correction 文件 hash。
  3. 提供“分光仪制作 CCMX”向导：基准探头测量、目标探头测量、生成、验证。
- 验收标准：
  - 报告中明确显示 correction 文件、创建时间、目标显示技术。
  - 不允许在不兼容探头/显示技术上静默使用修正文件。

## 7. P4 Argyll 专业工作流

### P4-A Argyll 适配层重构

- 负责文件：`src/instruments/argyll_adapter.py`, `src/argyll_controller.py`
- 依赖：P1-B, P0-C
- 实现思路：
  1. `ArgyllController` 保留兼容，但新建 adapter 封装命令构造和输出解析。
  2. 命令构造用 dataclass 参数，不在业务代码拼散字符串。
  3. 输出解析用 fixture 测试，不依赖真实硬件。
  4. 统一进程生命周期：start、cancel、timeout、cleanup、日志。
- 验收标准：
  - spotread/dispcal/targen/colprof/collink 每类至少 5 个解析测试。
  - 错误消息可映射到用户可读建议。

### P4-B ICC Profile 工作流

- 负责文件：`src/workflows/icc_workflow.py`, `src/data_storage.py`, `web/js/main.js`
- 依赖：P2, P4-A
- 实现思路：
  1. 状态：Preflight -> Optional dispcal -> targen/dispread 或自有测量 -> TI3 -> colprof -> apply -> verify。
  2. 所有中间文件放到独立 session 目录。
  3. 生成 `manifest.json`，记录命令、参数、文件 hash、环境、探头、display id。
  4. colprof 参数按用途预设：摄影、视频、通用、软打样。
- 验收标准：
  - 失败后能从 session 目录恢复/重试。
  - ICC 生成后必须有验证测量任务。

### P4-C 3D LUT 工作流

- 负责文件：`src/workflows/lut_workflow.py`, `src/argyll_controller.py`, `web/js/main.js`
- 依赖：P2, P4-A
- 实现思路：
  1. 支持输出：Resolve `.cube`, madVR/DisplayCAL 兼容格式可作为后续。
  2. 源空间预设：Rec.709 Gamma 2.4、sRGB、Display P3、DCI-P3、Rec.2020 PQ/HLG。
  3. 目标：实测 ICC 或指定目标 ICC。
  4. 自动检查 intent/BPC 参数组合，保留当前防错思路。
- 验收标准：
  - 33/65 点 LUT 能生成并通过基本格式校验。
  - 生成报告包含源空间、目标空间、渲染意图、LUT size。

### P4-D 校准与验证闭环

- 负责文件：`src/workflows/validation_workflow.py`, `src/measurement_analyzer.py`, `web/js/charts.js`
- 依赖：P2, P4-B, P4-C
- 实现思路：
  1. 专业工具必须区分：校准前、校准后、验证。
  2. 同一 display/session 下可以保存多个 run。
  3. 验证色块独立于建模色块，避免“自己考自己”。
  4. 报告显示 before/after 对比、合格/不合格阈值。
- 验收标准：
  - sRGB/Rec.709 预设有默认合格阈值。
  - 验证数据不能覆盖建模数据。

## 8. P5 数据模型、报告与历史治理

### P5-A 数据 schema version 与迁移

- 负责文件：`src/storage/schema.py`, `src/storage/migrations.py`, `src/data_storage.py`
- 依赖：P0-D
- 实现思路：
  1. 新 JSON 根字段加入 `schema_version`。
  2. 设计统一结构：`session`, `environment`, `instrument`, `display`, `workflow`, `measurements`, `artifacts`, `analysis`.
  3. 写迁移器读取旧格式并输出新格式。
  4. 对历史重复记录做去重策略：按路径、hash、timestamp、measurement_id。
- 验收标准：
  - 旧数据全可读，不丢失字段。
  - 迁移后每条记录有稳定唯一 ID。

### P5-B Artifact Manifest

- 负责文件：`src/storage/manifest.py`, `src/data_storage.py`
- 依赖：P5-A
- 实现思路：
  1. 每个 session 目录包含 `manifest.json`。
  2. 记录 JSON/TI3/CAL/ICC/LUT/报告文件的 sha256、生成命令、时间、参数。
  3. UI 历史列表以 manifest 为准，不再到处猜文件名。
- 验收标准：
  - 删除或移动某个 artifact 后，manifest 校验能报错。
  - 历史列表不再出现重复 ID 记录。

### P5-C 专业报告导出

- 负责文件：新增 `src/reports/`, `web/report_template.html`
- 依赖：P2, P5-A
- 实现思路：
  1. HTML 报告优先，PDF 可后续通过打印/Playwright 导出。
  2. 报告内容：目标标准、设备、环境、校正文件、测量设置、白点、亮度、对比度、Gamma/EOTF、色域覆盖、Delta E、验证结论。
  3. 图表可复用 ECharts 配置，但报告数据要来自后端 analysis。
- 验收标准：
  - 每次 ICC/LUT 验证完成自动生成报告。
  - 报告能离线打开。

## 9. P6 UI/UX 专业化

### P6-A 专业工作流向导

- 负责文件：`web/index.html`, `web/js/main.js`, `web/css/style.css`
- 依赖：P1-C, P3-C
- 实现思路：
  1. 首页直接展示工作台，不做营销页。
  2. 左侧工作流：显示器检测、ICC 校准、3D LUT、CCMX、验证、历史报告。
  3. 每个工作流固定步骤：预检 -> 目标设置 -> 探头/修正 -> 测量 -> 生成 -> 验证 -> 报告。
  4. 当前 UI 的高级功能不要全塞在一个页面，按任务收敛。
- 验收标准：
  - 新用户按向导能完成 sRGB 检测。
  - 专业用户能展开高级参数。

### P6-B 测量过程可视化

- 负责文件：`web/js/charts.js`, `web/js/main.js`, `web/css/style.css`
- 依赖：P2, P3
- 实现思路：
  1. 测量中显示当前色块、目标、实测、剩余时间、重复性。
  2. 对异常点允许“重测当前点”“跳过并标记”“停止并保存断点”。
  3. 图表显示实时曲线但不要阻塞测量。
- 验收标准：
  - 大量色块测量时 UI 不明显卡顿（1000 色块并发测量时，UI 主线程帧率不低于 20fps，通过 Chrome DevTools Performance 面板验证）。
  - 用户能看到失败原因和下一步。

### P6-C 历史对比升级

- 负责文件：`src/comparison_window.py`, `web/comparison.html`, `web/js/comparison.js`
- 依赖：P5-A, P5-B
- 实现思路：
  1. 按 display、target、workflow、date 分组。
  2. before/after 对比固定展示相同指标。
  3. 支持标记 golden baseline。
- 验收标准：
  - 能比较同一显示器多次校准效果。
  - 不同目标标准的数据不会被误放在同一对比结论里。

## 10. P7 QA、CI、打包与运维

### P7-A 测试体系

- 负责文件：`tests/`, `pyproject.toml`
- 依赖：P1, P2
- 实现思路：
  1. 引入 pytest。
  2. 单元测试：color science、schema、state machine、Argyll parser。
  3. 集成测试：fake instrument 完整测量一轮。
  4. 回归测试：加载旧 measurements 样本。
- 验收标准：
  - `pytest` 可在无 GUI/无硬件环境通过。
  - CI 至少跑 macOS 和 Windows。

### P7-B 日志与诊断包

- 负责文件：`src/diagnostics/`, `src/backend.py`
- 依赖：P5-B
- 实现思路：
  1. 统一使用 logging，不要散落 print。
  2. 每个 session 单独日志文件。
  3. 一键导出诊断包：manifest、日志、环境、Argyll 输出、异常栈。
- 验收标准：
  - 用户反馈问题时能提供 zip 包。
  - 日志不泄露敏感路径以外的隐私数据。

### P7-C 跨平台打包

- 负责文件：新增 `packaging/`, `scripts/`
- 依赖：P7-A
- 实现思路：
  1. macOS：app bundle、权限提示、签名/公证预留。
  2. Windows：安装器、USB/Argyll 权限说明、HDR/ACM 预检。
  3. Linux：AppImage 或 deb，X11/Wayland 限制说明。
  4. ArgyllCMS 采用内置或外部检测策略要明确。
- 验收标准：
  - 三平台能启动，至少 macOS/Windows 完成手动 smoke test。
  - 缺少 Argyll 时有明确引导。

### P7-D 安全与权限模型

- 负责文件：新增 `docs/permissions.md`，修改 `src/workflows/preflight.py`
- 依赖：P3-C（预检模块）
- 实现思路：
  1. 整理 ArgyllCMS 所需的系统权限清单：
     - **macOS**: USB 权限（`com.apple.security.device.usb`）、屏幕录制权限（用于显卡 LUT 写入）、辅助功能权限（用于 DDC/CI 通信）。
     - **Windows**: USB HID 驱动权限、显示器 DDC/CI 通信、显卡 LUT 写入（需管理员或签名驱动）。
     - **Linux**: `/sys/class/backlight` 写权限、i2c-dev 设备权限（DDC/CI）、`/dev/usb/hid*` 读权限。
  2. 为每个权限提供三要素：检测方法、获取方式（用户引导）、验证命令。
  3. 预检阶段扫描每项权限状态，产出 PASS/WARN/BLOCK 结果。
  4. 打包时标注所需权限声明（macOS entitlements、Windows manifest）。
- 验收标准：
  - 预检报告能明确指出“缺少 USB 权限”并提供修复命令。
  - 三平台文档各记录一条完整的权限设置流程。
  - 用户反馈问题时，诊断包包含权限状态检查结果。

## 11. P8 真实硬件验证

### P8-A 硬件验证矩阵

- 负责文件：`docs/validation_matrix.md`
- 实现思路：
  1. 探头：i1Display Pro、i1Pro2/3、SpyderX 至少三类。
  2. 显示器：sRGB LCD、广色域 LCD、OLED、HDR/miniLED、投影可后续。
  3. 系统：macOS、Windows 11、Linux X11。
  4. 每组记录：预检、原生测量、校准、验证、报告。
- 验收标准：
  - 每个组合都有 pass/fail 和已知限制。

### P8-B 与参考工具交叉验证

- 负责文件：`docs/reference_comparison.md`
- 实现思路：
  1. 与 DisplayCAL/Argyll 原生命令/厂商软件做同屏同探头对比。
  2. 比较白点、亮度、Gamma、色域、Delta E。
  3. 差异超过阈值时回到 P2/P4 修算法或命令。
- 验收标准：
  - 关键指标差异有解释。
  - 至少完成一个完整 reference report。

## 12. 第一批建议任务分配

第一轮只安排 P0 审计 agent，不安排任何代码修改 agent。所有 P0 handoff 输出完成后，统一评审再启动第二轮。

| Agent | 任务 | 文件边界 | 可并行性 |
|---|---|---|---|
| Agent 1 | P0-A 架构审计 | 只读后端/前端，写 handoff | 可并行 |
| Agent 2 | P0-B 色彩科学审计 | 只读 analyzer/sampler/storage，写 handoff | 可并行 |
| Agent 3 | P0-C Argyll fixture | 新增 tests/fixtures/argyll | 可并行 |
| Agent 4 | P0-D 数据治理审计 | 只读 measurements/storage，写 handoff | 可并行 |

第一轮不允许任何 agent 修改 `src/backend.py`。先做审计、测试夹具，把项目现状钉住。

**第二轮建议**（P0 完成后启动）：

| Agent | 任务 | 文件边界 | 依赖 |
|---|---|---|---|
| Agent 5 | P5-A/P5-B 数据 schema + manifest | 新增 src/storage/ | P0-D |
| Agent 6 | P2-A color_science 骨架 | 新增 src/color_science/ + tests | P0-B |
| Agent 7 | P1-A 状态机 | 新增 src/core/ + tests | P0-A |
| Agent 8 | P7-A pytest + CI 骨架 | 新增 tests/ + pyproject.toml | P0-C |

## 13. 给后续 AI Agent 的通用提示词模板

```text
你正在 Topos Calibrator 项目中执行 docs/professional_optimization_plan.md 的任务 <任务ID>。

请严格遵守：
1. 只修改任务卡指定文件范围。
2. 先阅读相关源码和本任务依赖的 handoff 文档。
3. 每个行为变更必须配测试或验证脚本。
4. 不要重构无关代码。
5. 完成后在 docs/agent_handoffs/<任务ID>_<简短名称>.md 写交接报告。

交接报告必须包含：
- 修改文件列表
- 实现思路
- 验证命令和结果
- 风险和未完成项
- 解锁的后续任务
```

## 14. 优先级建议

最高优先级：

1. P0 审计与测试夹具。
2. P5 数据 schema/manifest —— 必须先于色彩科学定下来，否则算法产出的 analysis 字段格式会与最终 schema 不一致。
3. P2 色彩科学核心——与 P5 可并行，但 P5 的 schema 输出应作为 P2 的输入约束。
4. P1 状态机和测量服务抽象——与 P2/P5 可部分并行，但 P1-C（backend 瘦身）需等 P5 数据格式稳定后再深度介入。

**实际执行顺序**：第 12 节的两轮分配即体现了这一优先级——第一轮全是 P0，第二轮 P5 + P2 + P1-A + P7-A 并行。

原因：专业校色软件最怕“看起来很专业，但结果不可验证”。先把数据格式、算法、状态、测试钉牢，再做 UI 和打包，后续迭代会稳很多。

