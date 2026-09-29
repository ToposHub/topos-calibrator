# P6-B 测量过程可视化 - 交接报告

**任务ID**: P6-B
**完成日期**: 2026-05-19
**负责Agent**: P6-B 测量过程可视化

---

## 1. 修改的文件列表

| 文件 | 修改内容 | 新增行数 |
|------|----------|----------|
| `web/css/style.css` | 测量过程可视化 UI 样式 | +543 行 |
| `web/js/charts.js` | 实时图表更新模块（requestAnimationFrame） | +293 行 |
| `web/js/main.js` | 测量进度面板、异常处理、错误显示 | +767 行 |

---

## 2. 实现思路（性能优化策略）

### 2.1 实时图表更新（charts.js）

**核心策略：使用 requestAnimationFrame + 批量更新**

```
性能优化设计：

1. requestAnimationFrame 替代 setTimeout
   - 与浏览器渲染周期同步，避免视觉卡顿
   - 自动暂停在页面不可见时，节省资源

2. 批量更新（Batch Update）
   - 累积多个数据点到 pendingUpdates 队列
   - 单次 setOption 更新多个点，减少 ECharts 重绘次数
   - 使用 lazyUpdate: true 选项进一步优化

3. 节流控制（Throttle）
   - minUpdateInterval = 50ms（确保 UI 响应性）
   - maxBatchSize = 20（限制单次更新数据量）
   - 达到任一条件才触发更新

4. 数据缓存
   - pendingUpdates.ciePoints / gammaPoints 缓存待更新数据
   - 避免频繁操作 ECharts option 对象

5. 按需渲染
   - 只在数据变化时触发更新
   - 无数据时不执行 RAF 循环
```

**关键代码结构**：

```javascript
// 实时更新状态
const realtimeChartState = {
    pendingUpdates: { ciePoints: [], gammaPoints: [] },
    minUpdateInterval: 50,  // 最小更新间隔（ms）
    maxBatchSize: 20,       // 单次批量更新最大数据点数
    rafId: null,
    isUpdating: false
};

// 核心：使用 RAF 进行异步更新
function scheduleRealtimeUpdate() {
    if (realtimeChartState.isUpdating) return;
    if (realtimeChartState.rafId === null) {
        realtimeChartState.rafId = requestAnimationFrame(processRealtimeUpdates);
    }
}

// 批量更新（单次 setOption）
function batchUpdateCIEChart(points) {
    // 批量添加所有点
    for (const point of points) {
        measurePointsSeries.data.push(newPoint);
    }
    // 单次设置 option
    cieChart.setOption(option, { lazyUpdate: true });
}
```

### 2.2 测量进度面板（main.js）

**功能设计**：

```
测量进度面板包含：

1. 当前色块显示
   - 80x80 px RGB preview box
   - 色块名称 + RGB 值
   - 实测 xyY 数据
   - 亮度偏差颜色指示（绿色/黄色/红色）

2. 进度条区域
   - 当前进度 (已测/总数)
   - 百分比显示
   - 进度条动画（shimmer effect）

3. 统计信息
   - 已测量数量
   - 已跳过数量（高亮警告）
   - 剩余时间估算
   - 平均测量耗时

4. 重复性统计（可选显示）
   - 标准差
   - 最大偏差
   - 重复性评估（优秀/良好/较差）

5. 错误提示区域
   - 错误标题 + 消息
   - 下一步建议步骤

6. 异常处理按钮
   - 重测当前点
   - 跳过并标记
   - 停止并保存断点
```

### 2.3 异常点处理功能

**三个核心功能**：

1. **重测当前点** (`remeasureCurrentPatch`)
   - 清除当前色块的测量历史
   - 清除已测量标记
   - 显示色块并触发测量

2. **跳过并标记** (`skipCurrentPatch`)
   - 将色块添加到 `skippedPatches` 列表
   - 记录跳过原因和时间戳
   - 清除测量数据
   - 通知后端跳过

3. **停止并保存断点** (`stopAndSaveCheckpoint`)
   - 显示确认对话框
   - 停止测量流程
   - 保存当前数据
   - 提示下次继续位置

### 2.4 失败原因显示

**错误类型映射**：

```javascript
const errorTypes = {
    'instrument_disconnected': {
        title: '探头连接断开',
        suggestions: [
            '请检查 USB 连接是否稳固',
            '确认仪器电源是否正常',
            '尝试重新连接探头后继续'
        ]
    },
    'measurement_timeout': {
        title: '测量超时',
        suggestions: [
            '检查探头是否正确放置',
            '确认屏幕显示正确色块',
            '尝试增加测量延迟时间'
        ]
    },
    'invalid_result': { ... },
    'argyll_error': { ... }
};
```

---

## 3. 验证方法

### 3.1 性能验证

**目标**：1000 色块测量时 UI 帧率不低于 20fps（即帧间隔 < 50ms）

**验证方法**：

1. **Chrome DevTools Performance 面板**：
   - 打开 DevTools -> Performance
   - 开始录制
   - 执行 1000 色块循环测量
   - 分析帧率分布

2. **性能统计函数**：
   ```javascript
   // 获取更新统计
   const stats = getRealtimeUpdateStats();
   console.log('更新次数:', stats.updateCount);
   console.log('平均每帧更新:', stats.avgUpdatesPerFrame);
   console.log('待处理点数:', stats.pendingPoints);
   ```

3. **预期结果**：
   - `minUpdateInterval = 50ms` 确保每帧至少有 50ms 空闲
   - `maxBatchSize = 20` 限制单次渲染开销
   - 使用 RAF 与浏览器同步，避免过度渲染

### 3.2 功能验证

| 功能 | 验证方法 |
|------|----------|
| 测量进度面板 | 开始循环测量后观察面板显示 |
| 当前色块预览 | 检查 RGB preview 是否随测量更新 |
| 进度条更新 | 观察进度条百分比变化 |
| 重复性统计 | 多次测量同一点后检查统计显示 |
| 重测功能 | 点击"重测当前点"，检查是否重新测量 |
| 跳过功能 | 点击"跳过并标记"，检查跳过列表 |
| 断点保存 | 点击"停止并保存断点"，确认保存成功 |
| 错误显示 | 模拟错误场景，检查错误提示和建议 |

### 3.3 代码验证

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"

# 检查语法
python3 -m py_compile main.py

# 检查 JS 语法（需要 node）
# node --check web/js/charts.js
# node --check web/js/main.js
```

---

## 4. 风险和未完成项

### 4.1 已知风险

| 风险 | 影响 | 建议 |
|------|------|------|
| 后端 `skip_current_patch` 方法未实现 | 跳过功能无法真正生效 | P4 阶段需要添加后端支持 |
| 后端进度信号不含 RGB 数据 | 当前色块预览需额外获取 | 建议后端在进度信号中添加 rgb 字段 |
| 重复性统计仅基于最近5点 | 大量测量时统计不够全面 | 可考虑更完整的统计方法 |

### 4.2 未完成项

- [ ] 与现有测量流程的完整集成（需修改 `handleCycleProgress` 调用）
- [ ] 断点恢复功能的后端支持（恢复到指定色块索引）
- [ ] 更完善的性能监控面板（实时显示帧率）
- [ ] 可配置的更新间隔参数（高级用户调整）

---

## 5. 解锁的后续任务

| 任务 | 依赖 | 说明 |
|------|------|------|
| **P6-C 历史对比升级** | P6-B ✅ | 可开始实现测量过程历史记录 |
| **P4-D 校准与验证闭环** | P6-B ✅ | 测量进度面板可集成验证流程 |
| **P7-A 测试体系** | P6-B ✅ | 可添加 UI 性能测试用例 |

---

## 6. 使用示例

### 6.1 启用测量进度面板

```javascript
// 在测量开始时调用
showMeasurementProgressPanel();

// 或在 handleCycleProgress 中自动调用
// 面板会在循环测量开始时自动显示
```

### 6.2 使用实时图表更新

```javascript
// 处理测量结果时调用
handleMeasurementResultEnhanced(resultJson);

// 测量结束时刷新
flushRealtimeUpdates();
```

### 6.3 设置错误信息

```javascript
// 显示错误
setMeasurementError('instrument_disconnected', { detail: 'USB 断开' });

// 清除错误
clearMeasurementError();
```

### 6.4 获取性能统计

```javascript
const stats = getRealtimeUpdateStats();
console.log(`更新次数: ${stats.updateCount}`);
console.log(`待处理点: ${stats.pendingPoints}`);
```

---

## 7. 性能优化关键点

### 7.1 为什么使用 requestAnimationFrame

| 方案 | 问题 |
|------|------|
| setTimeout(fn, delay) | 无法与渲染同步，可能阻塞 |
| setInterval(fn, delay) | 即使页面不可见也会执行 |
| requestAnimationFrame | ✅ 与渲染同步，自动暂停，节省资源 |

### 7.2 为什么使用批量更新

```
单点更新（慢）：
每收到一个点 -> getOption() -> push data -> setOption() -> 重绘
1000 点 = 1000 次重绘

批量更新（快）：
累积 20 点 -> getOption() -> push 20 点 -> setOption() -> 重绘
1000 点 = 50 次重绘（20倍提速）
```

### 7.3 为什么使用 lazyUpdate

ECharts `setOption(option, { lazyUpdate: true })` 会：
- 合并多次 setOption 的变更
- 等到下次渲染才实际更新
- 避免中间无效渲染

---

**交接完成日期**: 2026-05-19
**下一步建议**: 集成到现有测量流程，修改 handleCycleProgress 和 handleMeasurementResult 调用增强版本。