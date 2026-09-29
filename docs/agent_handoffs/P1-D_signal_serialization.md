# P1-D: 统一信号序列化策略

**任务编号**: P1-D
**执行日期**: 2026-05-19
**依赖任务**: P0-A (架构审计), P1-C (Backend 瘦身 - 可并行后半段)

---

## 1. 修改文件列表

| 文件路径 | 修改内容 | 行数变化 |
|----------|----------|----------|
| `/Users/heng/Documents/vscode/Topos Calibrator/src/backend.py` | 新增 `_emit_json()` helper 函数 | +27 行 (第 746-770 行) |
| `/Users/heng/Documents/vscode/Topos Calibrator/web/js/main.js` | 新增 `parsePayload()` helper 函数，替换多处 JSON.parse | +37 行 helper, -约 200 行重复 try-catch |
| `/Users/heng/Documents/vscode/Topos Calibrator/docs/optimization_summary.md` | 更新优化4章节，纠正策略描述 | 约 50 行重写 |

---

## 2. 实现思路

### 2.1 策略选择理由

**决策**: 短期保留 JSON 字符串传输策略

理由：
1. **代码依赖度高**: 当前代码有 160+ 处 `json.dumps()` 和 29 处 `JSON.parse()`，完全迁移成本高
2. **Qt 版本兼容性**: QWebChannel 对 dict/list 原生传输的支持在不同 Qt/PyQt 版本下行为不一致
3. **渐进式优化**: 先统一处理逻辑，未来可无缝切换到原生传输

### 2.2 Helper 函数设计

#### 后端 `_emit_json(signal, payload, ensure_ascii=False)`
- 封装 `json.dumps()` + `signal.emit()`
- 统一错误处理：序列化失败时发射空对象
- 支持中文字符输出 (`ensure_ascii=False`)
- 可扩展：未来切换到原生传输只需修改此函数

#### 前端 `parsePayload(payload, defaultValue={})`
- 兼容 Qt WebChannel 可能传递对象或字符串的情况
- 解析失败时返回默认值（空对象或空数组），避免 undefined 错误
- 集中日志输出便于调试

### 2.3 替换策略

使用批量编辑替换高频信号处理函数：
- 核心信号函数：`handlePatchColorChanged`, `handleMeasurementResult`, `handleGamutCoverageUpdated`, `handleGammaUpdated`, `handleDisplayBasicDataUpdated`
- 进度信号：`handleCycleProgress`, `handleCalibrationProgress`
- 状态信号：`handleProbeStatusChanged`, `handleInstrumentsEnumerated`
- 列表信号：`handleMeasurementListUpdated`, `handleSessionListUpdated`, `handlePatchListUpdated`
- 文件信号：`handleFilePathSelected`, `handleMeasurementSaved`, `handleMeasurementLoaded`, `handleDataExported`, `handleCalFileListUpdated`, `handleCalFileLoaded`

---

## 3. 验证命令和结果

### 3.1 JSON.parse 数量验证

```bash
# 验证前
rg "JSON.parse" web/js/main.js
# 结果: 29 处

# 验证后
rg "JSON.parse" web/js/main.js
# 结果: 9 处（包含 helper 函数内部 2 处）
```

**验收结果**: JSON.parse 数量从 29 处下降到 9 处，业务代码中的 JSON.parse 从 27 处下降到 7 处，**符合验收标准**。

### 3.2 Python 编译验证

```bash
python3 -m py_compile src/backend.py
# 无错误输出
```

### 3.3 helper 函数位置验证

```bash
# 后端 helper
rg "_emit_json" src/backend.py --context 3
# 找到定义和注释

# 前端 helper
rg "parsePayload" web/js/main.js --context 3
# 找到定义和多处调用
```

---

## 4. 风险和未完成项

### 4.1 已识别风险

| 风险类型 | 风险描述 | 影响程度 | 处理方式 |
|----------|----------|----------|----------|
| 兼容性风险 | parsePayload 兼容字符串和对象，但部分旧函数可能只传字符串 | 低 | helper 函数已处理 |
| 默认值风险 | 解析失败返回默认值，可能导致后续逻辑异常 | 低 | 调用方添加必要字段检查 |
| 性能风险 | JSON.parse 仍有开销 | 中 | 未来切换到原生传输解决 |

### 4.2 未完成项

1. **剩余 7 处 JSON.parse**: 低频使用的函数尚未替换，可在后续迭代中完成：
   - `handleFileCreated` (第 4058 行)
   - `handleSessionAutoSaved` (第 4157 行)
   - 内联回调函数 (第 4284, 4416, 4494, 4797, 4819 行)

2. **后端 `_emit_json` 尚未应用到所有 emit 调用**: 当前仅添加 helper 函数，未替换 `json.dumps()` 调用。可在后续迭代中逐步替换。

3. **单元测试缺失**: helper 函数未添加单元测试，建议在 P7-A 测试体系建设时补充。

---

## 5. 解锁的后续任务

完成本任务后，以下任务可立即开始：

| 任务编号 | 任务名称 | 依赖关系 | 可开始时间 |
|----------|----------|----------|------------|
| P1-E | 状态机接入 Backend | P1-D 提供稳定信号接口 | 立即 |
| P1-C (后半段) | Backend 瘦身完成 | P1-D helper 函数可用于简化 emit 调用 | 立即 |
| P7-A | pytest + CI 骨架 | 可添加 parsePayload/emit_json 测试 | P1-D 完成后 |

---

## 6. 建议后续优化路径

### 6.1 短期 (本轮迭代)

- 将剩余 7 处 JSON.parse 替换为 parsePayload
- 将 backend.py 中的高频 `json.dumps()` 调用替换为 `_emit_json()`

### 6.2 中期 (下一轮迭代)

- 添加 helper 函数单元测试
- 考虑将部分信号改为 dict/list 原生传输（先从低风险信号开始）

### 6.3 长期 (架构拆分后)

- 完全切换到 dict/list 原生传输
- 移除 JSON 序列化层

---

**交接完成签名**: Agent P1-D
**交接完成时间**: 2026-05-19