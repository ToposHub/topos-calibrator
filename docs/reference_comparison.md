# 参考工具交叉验证指南

**任务**: P8-B 与参考工具交叉验证
**创建日期**: 2026-05-19
**目的**: 确保 Topos Calibrator 测量结果与行业认可工具一致，建立可信度基线

---

## 1. 参考工具概述

### 1.1 DisplayCAL

**简介**: 开源显示器校准软件，基于 ArgyllCMS，广泛用于专业领域

**适用场景**:
- ICC Profile 生成
- 3D LUT 生成
- 校准验证
- 色域测量

**验证优势**:
- 算法成熟，多年迭代
- 社区验证充分
- 与 ArgyllCMS 完全兼容
- 报告格式标准化

**命令路径**:
```bash
# Linux/macOS
displayCAL

# 或直接调用 Argyll 命令
dispcal -v -m -H -q l -t 6500 -g 2.2 -k 0 display_name
dispread -v -m -H -k display_name.cal display_name
colprof -v -q m -D "display_name" display_name
```

**报告输出**:
- HTML 格式验证报告
- 包含 Delta E 统计、色域覆盖、Gamma 曲线
- 可直接对比关键指标

### 1.2 ArgyllCMS 原生命令

**简介**: Topos Calibrator 的底层测量引擎，直接调用可作为真值参考

**关键命令**:

| 命令 | 功能 | 输出格式 |
|------|------|----------|
| `spotread` | 单点测量 | XYZ/xyY |
| `dispcal` | 显示器校准 | .cal 文件 |
| `dispread` | 灰阶/色块测量 | .ti1/.ti3 |
| `colprof` | ICC Profile 生成 | .icc |
| `collink` | 3D LUT 生成 | .cube |
| `ccxxmake` | CCSS/CCMX 制作 | .ccss/.ccmx |

**验证用法**:
```bash
# 单点测量（白点）
spotread -e -N
# 输出: XYZ = 95.05 100.00 108.88, xyY = 0.3127 0.3290 100.0

# 灰阶测量
dispread -v -m -H -k display_name.cal display_name
# 生成 .ti3 文件，包含完整灰阶数据

# 查看测量结果
xicc -p -v display_name.ti3
```

**验证优势**:
- 直接使用相同引擎，排除中间层差异
- 输出格式可解析对比
- 可追溯命令参数

### 1.3 厂商软件

**X-Rite i1Profiler**:
- 支持探头: i1 Pro 2/3, i1 Display Pro
- 特点: 原厂校正文件集成
- 适用: X-Rite 探头用户
- 报告: PDF 格式，详细 Delta E 分析

**Datacolor SpyderX Software**:
- 支持探头: SpyderX, Spyder5
- 特点: 简化流程，一键校准
- 适用: 摄影入门用户
- 报告: 简化版色域覆盖和 Gamma

**CalMAN / LightSpace**:
- 适用: 专业影视、广播
- 特点: 支持 HDR/Rec.2020 验证
- 报告: 详细 EOTF 曲线分析

**对比建议**:
- 厂商软件作为"黑盒"参考
- 只对比最终指标，不对比过程
- 注意厂商可能使用私有算法

---

## 2. 对比指标清单

### 2.1 白点指标

| 指标 | Topos 计算 | 参考来源 | 容差阈值 |
|------|------------|----------|----------|
| CCT (K) | `cct_duv_from_xy()` | spotread 输出 | ±50K |
| Duv | `calculate_duv()` | DisplayCAL 报告 | ±0.002 |
| x 偏移 | 测量值 - D65.x | 参考报告 | ±0.002 |
| y 偏移 | 测量值 - D65.y | 参考报告 | ±0.002 |
| Delta E (白点) | `delta_e_ciede2000()` | DisplayCAL 报告 | < 1.0 |

**对比方法**:
```python
# Topos 计算
from src.color_science.colorimetry import cct_duv_from_xy
measured_x, measured_y = 0.314, 0.331
cct, duv = cct_duv_from_xy(measured_x, measured_y)

# 参考值（DisplayCAL 报告或 spotread）
reference_cct = 6500
reference_duv = 0.005

# 差异
cct_diff = abs(cct - reference_cct)
duv_diff = abs(duv - reference_duv)
```

### 2.2 亮度指标

| 指标 | Topos 计算 | 参考来源 | 容差阈值 |
|------|------------|----------|----------|
| 白场亮度 (cd/m²) | 白点 Y 值 | spotread/dispcal | ±2% |
| 黑场亮度 (cd/m²) | 黑点 Y 值 | spotread | ±0.01 cd/m² |
| 对比度 | 白场/黑场 | DisplayCAL 报告 | ±5% |

**对比方法**:
```python
# Topos 从测量数据获取
white_Y = gamut_data["white"]["Y"]
black_Y = gamut_data["black"]["Y"]
contrast_ratio = white_Y / black_Y if black_Y > 0 else None

# 参考值（Argyll dispcal 输出）
# "White = 120.0 cd/m², Black = 0.05 cd/m², Contrast = 2400:1"
```

### 2.3 Gamma/EOTF 指标

| 指标 | Topos 计算 | 参考来源 | 容差阈值 |
|------|------------|----------|----------|
| 平均 Gamma | `calculate_gamma()` | DisplayCAL 报告 | ±0.05 |
| Gamma 曲线 | `calculate_gamma_curve()` | ECharts 图表 | 视觉对比 |
| BT.1886 Lw/Lb | `calculate_bt1886_errors()` | dispcal 参数 | ±1 cd/m² |
| EOTF 最大误差 | `calculate_eotf_errors()` | DisplayCAL 报告 | ±2 cd/m² |

**对比方法**:
```python
from src.measurement_analyzer import MeasurementAnalyzer

analyzer = MeasurementAnalyzer()
analyzer.set_gamma_data(gray_scale_data)
avg_gamma = analyzer.calculate_gamma()

# 参考值（DisplayCAL 报告）
# "Gamma: 2.18 (target: 2.2)"
reference_gamma = 2.18

gamma_diff = abs(avg_gamma - reference_gamma)
```

### 2.4 色域覆盖指标

| 指标 | Topos 计算 | 参考来源 | 容差阈值 |
|------|------------|----------|----------|
| 覆盖率 (%) | `gamut_coverage_percent()` | DisplayCAL 报告 | ±2% |
| 面积比 (%) | `gamut_area_ratio_percent()` | DisplayCAL 报告 | ±3% |
| 色域三角形 | RGB xy 坐标 | spotread 原色测量 | ±0.005 |

**注意**: DisplayCAL 报告的"覆盖率"实际是面积比，需区分：
- **覆盖率** = 交集面积 / 标准面积 (最大 100%)
- **面积比** = 测量面积 / 标准面积 (可超过 100%)

Topos 已在 P2-B 实现正确的区分计算。

### 2.5 Delta E 指标

| 指标 | Topos 计算 | 参考来源 | 容差阈值 |
|------|------------|----------|----------|
| Delta E 平均值 | `analyze_grayscale_series()` | DisplayCAL 报告 | ±0.5 |
| Delta E 最大值 | 分析结果 summary | DisplayCAL 报告 | ±1.0 |
| Delta E 分布 | 验证点统计 | DisplayCAL 报告 | 视觉对比 |

**对比方法**:
```python
from src.measurement_analyzer import MeasurementAnalyzer

analyzer = MeasurementAnalyzer()
result = analyzer.analyze_grayscale_series(gray_scale_data, white_point_name="D65")
avg_delta_e = result["summary"]["avg_delta_e"]
max_delta_e = result["summary"]["max_delta_e"]

# 参考值（DisplayCAL 报告）
# "Average Delta E: 1.42, Maximum Delta E: 3.8"
```

---

## 3. 对比方法规范

### 3.1 测量条件一致性

**必须保持一致**:

| 条件 | 说明 | 控制方法 |
|------|------|----------|
| 同一显示器 | 排除设备差异 | 固定 display_id |
| 同一探头 | 排除仪器差异 | 固定探头型号 |
| 同一校正文件 | 排除修正差异 | 使用相同 CCSS/CCMX |
| 相同测量位置 | 排除屏幕不均匀 | 固定探头位置（屏幕中心） |
| 相同环境光 | 排除环境干扰 | 关闭环境光或固定照度 |
| 相同预热时间 | 排除漂移 | 显示器预热 30 分钟以上 |

**预热要求**:
- LCD 显示器: 30 分钟
- OLED 显示器: 60 分钟（稳定更快但需防止烧屏）
- 投影仪: 30 分钟

### 3.2 相同色块组

**基础对比色块组**:

| 色块 | RGB | 目的 |
|------|-----|------|
| 红色 | (255, 0, 0) | 色域边界 |
| 绿色 | (0, 255, 0) | 色域边界 |
| 蓝色 | (0, 0, 255) | 色域边界 |
| 白色 | (255, 255, 255) | 白点、亮度 |
| 黑色 | (0, 0, 0) | 黑场、对比度 |
| 灰阶 0% | (0, 0, 0) | 黑场验证 |
| 灰阶 10% | (26, 26, 26) | 暗部 Gamma |
| 灰阶 20% | (51, 51, 51) | Gamma 中段 |
| 灰阶 50% | (128, 128, 128) | Gamma 中点 |
| 灰阶 80% | (204, 204, 204) | 亮部 Gamma |
| 灰阶 100% | (255, 255, 255) | 白场验证 |

**扩展对比色块组**（可选）:

| 色块 | RGB | 目的 |
|------|-----|------|
| 黄色 | (255, 255, 0) | 二次色 |
| 品红 | (255, 0, 255) | 二次色 |
| 青色 | (0, 255, 255) | 二次色 |
| 肤色 1 | (200, 150, 120) | 肤色验证 |
| 肤色 2 | (180, 130, 100) | 肤色验证 |
| 灰阶 30% | (77, 77, 77) | Gamma 细分 |
| 灰阶 70% | (179, 179, 179) | Gamma 细分 |

### 3.3 测量顺序

**推荐顺序**（最小化漂移影响）:

1. 白场预热（显示白色 5 分钟）
2. 黑场测量（探头校准后立即测量）
3. 白场测量（校准基准）
4. 原色测量（R -> G -> B）
5. 灰阶测量（从暗到亮：0% -> 10% -> ... -> 100%）
6. 二次色测量（可选）

**测量间隔**:
- 色块切换延迟: 500ms - 1000ms
- OLED 黑帧插入: 显示黑屏 1-2 秒后再切换

### 3.4 对比执行步骤

```
Step 1: 环境准备
├── 关闭环境光（或固定照度 < 5 lux）
├── 显示器预热 30 分钟
├── 探头预热（按厂商要求）
└── 固定探头位置（屏幕中心）

Step 2: Topos 测量
├── 连接探头
├── 校准探头（白色校准板）
├── 测量色块组
├── 导出 JSON + TI3
└── 保存报告

Step 3: 参考工具测量
├── 使用相同色块组
├── 使用相同校正文件
├── 导出报告/数据
└── 记录命令参数

Step 4: 数据对比
├── 解析两方输出
├── 计算指标差异
├── 填写 Reference Report
└── 分析差异原因

Step 5: 差异处理
├── 差异在容差内: 记录为"一致"
├── 差异超容差: 回到 P2/P4 检查
└── 已知差异: 添加解释说明
```

---

## 4. 差异分析流程

### 4.1 差异阈值判定

| 指标 | 一致阈值 | 需检查阈值 | 需修正阈值 |
|------|----------|------------|------------|
| CCT | ≤ 50K | 50K - 200K | > 200K |
| Duv | ≤ 0.002 | 0.002 - 0.01 | > 0.01 |
| 白场亮度 | ≤ 2% | 2% - 5% | > 5% |
| 黑场亮度 | ≤ 0.01 cd/m² | 0.01 - 0.05 | > 0.05 |
| Gamma | ≤ 0.05 | 0.05 - 0.1 | > 0.1 |
| 色域覆盖 | ≤ 2% | 2% - 5% | > 5% |
| Delta E 平均 | ≤ 0.5 | 0.5 - 1.0 | > 1.0 |
| Delta E 最大 | ≤ 1.0 | 1.0 - 2.0 | > 2.0 |

### 4.2 差异原因分类

**A类 - 算法差异**（需回 P2 修正）:

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| Gamma 值偏高/偏低 0.1+ | 黑场识别错误 | 检查 `identify_black_patch()` |
| CCT 差异 200K+ | CCT 计算方法不同 | 检查 McCamy vs Robertson |
| Delta E 差异 1.0+ | 白点适配缺失 | 检查 `calculate_delta_e_2000()` |
| 色域覆盖差异 5%+ | 多边形交集算法 | 检查 `gamut_coverage_percent()` |

**B类 - 测量差异**（需回 P3/P4 修正）:

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 亮度差异 5%+ | 测量延迟不足 | 检查 settling policy |
| 黑场不稳定 | OLED 黑帧缺失 | 检查 `set_oled_window_size_percent()` |
| 漂移趋势明显 | 预热不足 | 增加预热时间 |
| 色块顺序影响 | 显示器响应延迟 | 调整切换延迟 |

**C类 - 已知差异**（可解释，无需修正）:

| 现象 | 解释 | 示例 |
|------|------|------|
| CCT 差异 50K 内 | McCamy 近似误差 | D65 实际计算为 6505K |
| Gamma 小幅差异 | 曲线拟合方法不同 | 线性拟合 vs 最小二乘 |
| 色域覆盖差异 2% | 边界采样密度不同 | 蒙特卡洛 vs 精确算法 |

### 4.3 回滚修正流程

```
差异发现 -> 差异分类 -> 修正任务

A类差异:
├── Gamma 问题 -> 回到 P2-C (transfer.py)
├── CCT/Duv 问题 -> 回到 P2-D (colorimetry.py)
├── Delta E 问题 -> 回到 P2-D (colorimetry.py)
└── 色域覆盖问题 -> 回到 P2-B (gamut_sampling.py)

B类差异:
├── 亮度不稳定 -> 回到 P3-A (statistics.py)
├── 黑场问题 -> 回到 P3-B (settling.py)
└── 测量命令问题 -> 回到 P4-A (argyll_adapter.py)

修正后验证:
├── 重新运行测试向量
├── 重新与参考工具对比
└── 更新 Reference Report
```

---

## 5. Reference Report 模板

### 5.1 模板结构

以下是完整的 Reference Report 模板，每次对比验证应填写一份：

---

# Reference Comparison Report

**报告编号**: `RCR-YYYYMMDD-NNN`
**生成日期**: YYYY-MM-DD
**验证人员**: 姓名/Agent ID

---

## A. 测量环境

| 项目 | 值 |
|------|-----|
| 操作系统 | macOS 14.x / Windows 11 / Linux |
| ArgyllCMS 版本 | v3.x.x |
| Topos Calibrator 版本 | v0.x.x |
| 参考工具 | DisplayCAL v3.x.x / ArgyllCMS 原生 |
| 参考工具版本 | v3.x.x |

---

## B. 设备信息

| 项目 | Topos | 参考 |
|------|-------|------|
| 显示器型号 | Dell U2723QE | 同 |
| 显示器类型 | LCD IPS | 同 |
| 显示器序号 | ABC123 | 同 |
| 显示器预热时间 | 30 分钟 | 同 |
| 探头型号 | i1 Display Pro | 同 |
| 探头序号 | XYZ789 | 同 |
| 校正文件 | LCD-CCSS-XYZ789.ccss | 同 |
| 校正文件 Hash | sha256:abc123... | 同 |
| 探头位置 | 屏幕中心 | 同 |
| 环境光照度 | < 5 lux | 同 |

---

## C. Topos 测量结果

### C.1 白点

| 指标 | 值 |
|------|-----|
| x | 0.3127 |
| y | 0.3290 |
| Y (cd/m²) | 120.5 |
| CCT (K) | 6505 |
| Duv | 0.0038 |
| Delta E (vs D65) | 0.5 |

### C.2 亮度与对比度

| 指标 | 值 |
|------|-----|
| 白场亮度 (cd/m²) | 120.5 |
| 黑场亮度 (cd/m²) | 0.08 |
| 对比度 | 1506:1 |

### C.3 Gamma

| 指标 | 值 |
|------|-----|
| 平均 Gamma | 2.18 |
| 目标 Gamma | 2.2 |
| Gamma 偏差 | -0.02 |
| BT.1886 Lw | 120.5 cd/m² |
| BT.1886 Lb | 0.08 cd/m² |
| EOTF 最大误差 | 1.8 cd/m² |

### C.4 色域覆盖 (sRGB)

| 指标 | 值 |
|------|-----|
| 覆盖率 | 99.5% |
| 面积比 | 102.3% |
| 红 (x, y) | (0.639, 0.330) |
| 绿 (x, y) | (0.300, 0.598) |
| 蓝 (x, y) | (0.152, 0.062) |

### C.5 Delta E (灰阶)

| 指标 | 值 |
|------|-----|
| Delta E 平均 | 1.42 |
| Delta E 最大 | 3.8 |
| 最大点 | 灰阶 10% |
| 暗部 Delta E | 2.5 |
| 亮部 Delta E | 1.0 |

---

## D. 参考工具测量结果

### D.1 白点

| 指标 | 值 | 来源 |
|------|-----|------|
| x | 0.3125 | DisplayCAL 报告 |
| y | 0.3292 | DisplayCAL 报告 |
| Y (cd/m²) | 118.0 | DisplayCAL 报告 |
| CCT (K) | 6500 | DisplayCAL 报告 |
| Duv | 0.004 | DisplayCAL 报告 |

### D.2 亮度与对比度

| 指标 | 值 | 来源 |
|------|-----|------|
| 白场亮度 (cd/m²) | 118.0 | DisplayCAL 报告 |
| 黑场亮度 (cd/m²) | 0.07 | DisplayCAL 报告 |
| 对比度 | 1671:1 | DisplayCAL 报告 |

### D.3 Gamma

| 指标 | 值 | 来源 |
|------|-----|------|
| 平均 Gamma | 2.20 | DisplayCAL 报告 |
| 目标 Gamma | 2.2 | 显示设置 |

### D.4 色域覆盖 (sRGB)

| 指标 | 值 | 来源 |
|------|-----|------|
| 覆盖率 | 99% | DisplayCAL 报告 |
| 红 (x, y) | (0.640, 0.330) | DisplayCAL 报告 |
| 绿 (x, y) | (0.300, 0.600) | DisplayCAL 报告 |
| 蓝 (x, y) | (0.150, 0.060) | DisplayCAL 报告 |

### D.5 Delta E

| 指标 | 值 | 来源 |
|------|-----|------|
| Delta E 平均 | 1.5 | DisplayCAL 报告 |
| Delta E 最大 | 4.2 | DisplayCAL 报告 |

---

## E. 差异对比

### E.1 白点差异

| 指标 | Topos | 参考 | 差异 | 状态 | 解释 |
|------|-------|------|------|------|------|
| x | 0.3127 | 0.3125 | 0.0002 | ✅ 一致 | 在容差内 |
| y | 0.3290 | 0.3292 | 0.0002 | ✅ 一致 | 在容差内 |
| CCT | 6505K | 6500K | 5K | ✅ 一致 | McCamy 近似误差 |
| Duv | 0.0038 | 0.004 | 0.0002 | ✅ 一致 | 在容差内 |
| Y | 120.5 | 118.0 | 2.1% | ⚠️ 需检查 | 轻微差异 |

### E.2 亮度差异

| 指标 | Topos | 参考 | 差异 | 状态 | 解释 |
|------|-------|------|------|------|------|
| 白场 | 120.5 | 118.0 | 2.1% | ⚠️ 需检查 | 测量延迟差异？ |
| 黑场 | 0.08 | 0.07 | 0.01 | ✅ 一致 | 在容差内 |
| 对比度 | 1506:1 | 1671:1 | 10% | ⚠️ 需检查 | 白场差异导致 |

### E.3 Gamma差异

| 指标 | Topos | 参考 | 差异 | 状态 | 解释 |
|------|-------|------|------|------|------|
| Gamma | 2.18 | 2.20 | 0.02 | ✅ 一致 | 在容差内 |

### E.4 色域差异

| 指标 | Topos | 参考 | 差异 | 状态 | 解释 |
|------|-------|------|------|------|------|
| 覆盖率 | 99.5% | 99% | 0.5% | ✅ 一致 | 在容差内 |
| 红 x | 0.639 | 0.640 | 0.001 | ✅ 一致 | 在容差内 |
| 绿 y | 0.598 | 0.600 | 0.002 | ✅ 一致 | 在容差内 |

### E.5 Delta E差异

| 指标 | Topos | 参考 | 差异 | 状态 | 解释 |
|------|-------|------|------|------|------|
| Delta E 平均 | 1.42 | 1.5 | 0.08 | ✅ 一致 | 在容差内 |
| Delta E 最大 | 3.8 | 4.2 | 0.4 | ✅ 一致 | 在容差内 |

---

## F. 差异分析结论

### F.1 需修正项目

| 项目 | 问题类型 | 建议 | 优先级 |
|------|----------|------|--------|
| 白场亮度差异 2.1% | B类-测量 | 检查测量延迟设置 | 中 |

### F.2 已知差异（可接受）

| 项目 | 解释 |
|------|------|
| CCT 5K差异 | McCamy近似计算D65为6505K，与6500K标准值有小幅偏差 |
| Gamma 0.02差异 | 曲线拟合方法差异，线性拟合vs DisplayCAL的最小二乘法 |

### F.3 一致性总结

| 指标类 | 一致项数 | 总项数 | 一致率 |
|--------|----------|--------|--------|
| 白点 | 4 | 5 | 80% |
| 亮度 | 1 | 3 | 33% |
| Gamma | 1 | 1 | 100% |
| 色域 | 5 | 5 | 100% |
| Delta E | 2 | 2 | 100% |
| **总计** | **13** | **16** | **81%** |

---

## G. 验证结论

**整体评价**: ✅ 基本一致

**结论说明**:
- 关键色彩指标（CCT、Gamma、色域、Delta E）与参考工具一致
- 亮度测量有轻微差异（约2%），建议检查测量延迟设置
- 无需回滚修正，差异在可接受范围

**后续行动**:
1. 记录亮度差异到已知差异列表
2. 如后续发现更多亮度差异，回 P3-B 检查 settling policy

---

## H. 原始数据路径

| 数据类型 | Topos 路径 | 参考路径 |
|----------|------------|----------|
| 测量 JSON | measurements/20260519_001.json | - |
| TI3 文件 | measurements/20260519_001.ti3 | DisplayCAL/output.ti3 |
| 报告 HTML | reports/20260519_001.html | DisplayCAL/report.html |
| 日志 | logs/20260519_001.log | DisplayCAL/log.txt |

---

**报告生成**: Topos Calibrator Reference Comparison System
**模板版本**: v1.0 (2026-05-19)

---

### 5.2 模板字段说明

**必填字段**:
- A. 测量环境：操作系统、软件版本
- B. 设备信息：显示器、探头、校正文件
- C/D. 测量结果：关键指标值
- E. 差异对比：差异计算和状态
- G. 验证结论：最终评价

**可选字段**:
- F. 差异分析：仅当有需修正项目时填写
- H. 原始数据：用于追溯

**状态标记**:
- ✅ 一致：差异在容差阈值内
- ⚠️ 需检查：差异超阈值但不大
- ❌ 需修正：差异明显超阈值，需回到 P2/P4

---

## 6. 已知差异解释库

以下差异已在历史验证中发现并解释，后续对比可引用：

### 6.1 算法相关

| 差异 | 量级 | 解释 | 引用 |
|------|------|------|------|
| CCT 值偏差 | ±50K | McCamy 近似 D65 = 6505K，非精确 6500K | P2-D 交接报告 |
| Gamma 值偏差 | ±0.05 | 曲线拟合方法差异（线性 vs 最小二乘） | P2-C 交接报告 |
| 色域覆盖差异 | ±1-2% | 多边形交集算法精度差异 | P2-B 交接报告 |

### 6.2 测量相关

| 差异 | 量级 | 解释 | 引用 |
|------|------|------|------|
| 亮度差异 | ±2-5% | 测量延迟设置差异，探头稳定时间不同 | P3-B 交接报告 |
| 黑场差异 | ±0.01 cd/m² | OLED 黑帧策略差异 | P3-B 交接报告 |
| 漂移趋势 | 渐变 | 预热时间不足，显示器未稳定 | 测量最佳实践 |

### 6.3 工具相关

| 差异 | 量级 | 解释 | 引用 |
|------|------|------|------|
| DisplayCAL vs Argyll | 小 | DisplayCAL 使用相同引擎，差异应很小 | 本文档 |
| 厂商软件差异 | 中等 | 厂商可能使用私有算法和校正数据 | 本文档 |

---

## 7. 验收标准

### 7.1 文档验收

| 标准 | 要求 | 说明 |
|------|------|------|
| 关键指标差异有解释模板 | ✅ | Section 5.1 提供完整模板 |
| 至少一个完整 reference report 模板结构 | ✅ | Section 5.1 包含完整模板 |
| 文档清晰 | ✅ | 分章节、有表格、有流程图 |

### 7.2 对比验证验收（实际执行时）

| 标准 | 要求 |
|------|------|
| 一致率 >= 80% | 关键指标差异在容差内 |
| 无需修正项目 | 或已记录修正计划 |
| 已知差异有解释 | 引用已知差异解释库 |

---

## 8. 附录

### A. DisplayCAL 报告解析要点

DisplayCAL HTML 报告关键数据位置：

```html
<!-- 白点 -->
<div class="whitepoint">
  <span class="cct">6500 K</span>
  <span class="duv">Duv: 0.004</span>
</div>

<!-- Gamma -->
<div class="gamma">
  <span class="value">Gamma: 2.18</span>
  <span class="target">Target: 2.2</span>
</div>

<!-- Delta E -->
<table class="delta-e">
  <tr><td>Average</td><td>1.42</td></tr>
  <tr><td>Maximum</td><td>3.8</td></tr>
</table>
```

### B. Argyll spotread 输出解析

```
Result is XYZ = 95.05 100.00 108.88, xyY = 0.3127 0.3290 100.0
CCT = 6505 K (Duv = 0.0038)
```

解析：
- XYZ: 直接读取数值
- xyY: 直接读取数值
- CCT: 从括号前读取
- Duv: 从括号内读取

### C. 差异追踪表

每次验证应记录到此表：

| RCR编号 | 日期 | 探头 | 显示器 | 一致率 | 状态 | 备注 |
|---------|------|------|--------|--------|------|------|
| RCR-20260519-001 | 2026-05-19 | i1d3 | Dell U2723QE | 81% | ✅ 基本一致 | 亮度轻微差异 |

---

**文档创建**: 2026-05-19
**任务**: P8-B 与参考工具交叉验证
**状态**: ✅ 完成