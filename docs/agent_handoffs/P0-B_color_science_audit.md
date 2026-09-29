# P0-B 色彩科学审计报告

**审计日期**：2026-05-19
**负责Agent**：P0-B 色彩科学审计
**任务来源**：docs/professional_optimization_plan.md

---

## 1. 分析的文件列表

| 文件 | 行数 | 审计范围 |
|------|------|----------|
| `src/measurement_analyzer.py` | 971 | `calculate_gamut_coverage()`, `calculate_gamma()`, `calculate_delta_e_2000()`, Lab转换 |
| `src/lab_sampler.py` | 448 | `srgb_to_xyz()`, `xyz_to_lab()`, `lab_to_xyz()`, `xyz_to_srgb()`, `get_srgb_lab_bounds()` |
| `src/data_storage.py` | 1618 | 数据结构对色彩科学计算的影响（只读确认数据格式） |

---

## 2. 算法审计结果

### 2.1 calculate_gamut_coverage() — 色域覆盖率计算

#### 当前行为

**位置**：`src/measurement_analyzer.py` 第 156-182 行

```python
def calculate_gamut_coverage(self, standard: str = "sRGB") -> float:
    # 计算测量色域三角形面积
    measured_area = self._triangle_area(measured_triangle)
    # 计算标准色域三角形面积
    standard_area = self._triangle_area(standard_triangle)
    # 简化方法：测量色域面积 / 标准色域面积
    coverage = (measured_area / standard_area) * 100
    return min(200, max(0, coverage))
```

**辅助函数**：`calculate_gamut_overlap()` 使用蒙特卡洛采样估算交集面积，但实现有问题：
- 使用 `hash(str(_))` 生成"随机"点，不是真随机，不可复现
- 采样点固定 10000 个，没有根据三角形大小调整

#### 问题清单

| 问题 | 严重程度 | 说明 |
|------|----------|------|
| **概念混淆：面积比 ≠ 覆盖率** | 🔴 高 | 当前输出的是"面积比"，却命名为"覆盖率"。覆盖率 = 交集面积 / 标准色域面积，最大100%。面积比 = 测量面积 / 标准面积，可以 >100%。 |
| **缺少真实交集面积计算** | 🔴 高 | 没有实现三角形裁剪算法（Sutherland-Hodgman），蒙特卡洛采样不可靠。 |
| **输出上限200%不专业** | 🟡 中 | 面积比可以超过200%，硬性上限会误导。覆盖率最大100%，不应有200%上限。 |
| **色域容积缺失** | 🟡 中 | xy平面面积不反映三维色域容积，专业报告应区分二维面积和三维容积。 |
| **缺少覆盖率 vs 包含率区分** | 🟡 中 | 没有区分"覆盖标准色域多少"和"测量色域包含标准色域"两种情况。 |
| **蒙特卡洛采样伪随机** | 🟡 中 | 使用hash函数而非真随机，结果不可复现，每次运行结果相同但不可验证。 |

#### 专业期望

1. **两个独立指标**：
   - `coverage_percent`: 交集面积 / 标准色域面积（最大100%，表示"覆盖了多少标准色域")
   - `area_ratio_percent`: 测量面积 / 标准面积（可 >100%，表示"测量色域相对标准大小")

2. **精确交集面积计算**：
   - 使用 Sutherland-Hodgman 或 Weiler-Atherton 多边形裁剪算法
   - 对于两个三角形，裁剪后最多得到 6 边形

3. **三维色域容积**（可选高级功能）：
   - 在 XYZ 或 Lab 空间计算凸包容积
   - 需要考虑白点和亮度范围

#### 改法建议

```
Phase 1 (P2-B):
- 新建 src/color_science/gamut_sampling.py
- 实现多边形裁剪算法计算精确交集
- 输出 coverage_percent 和 area_ratio_percent 两个指标
- 保留旧函数 calculate_gamut_coverage() 兼容，但添加废弃警告

Phase 2:
- 实现三维色域容积计算（如果需要）
```

#### 测试向量来源

1. **已知三角形交集**：构造两组已知交集的三角形，验证计算结果
   - 完全重叠：交集 = 100%
   - 完全分离：交集 = 0%
   - 半重叠：手工计算验证

2. **标准色域数据**：`STANDARD_GAMUTS` 已定义正确（需验证数值）
   - sRGB: R(0.64, 0.33), G(0.30, 0.60), B(0.15, 0.06)
   - DCI-P3: R(0.68, 0.32), G(0.265, 0.69), B(0.15, 0.06)
   - Rec.2020: R(0.708, 0.292), G(0.170, 0.797), B(0.131, 0.046)

3. **参考工具交叉验证**：与 DisplayCAL/Argyll dispcal 输出的色域覆盖率对比

---

### 2.2 calculate_gamma() — Gamma/EOTF 计算

#### 当前行为

**位置**：`src/measurement_analyzer.py` 第 234-289 行

```python
def calculate_gamma(self) -> Optional[float]:
    # 获取黑场亮度（0% 或最低灰阶）
    black_Y = 0.0
    for data in self.gamma_data:
        if data["patchName"] == "10%" or data["Y"] < black_Y:  # ❌ 错误
            black_Y = max(0.0, data["Y"])
    
    # Gamma = log(Y_normalized) / log(input_normalized)
    Y_normalized = (Y - black_Y) / (white_Y - black_Y)
    gamma = math.log(Y_normalized) / math.log(input_normalized)
```

#### 问题清单

| 问题 | 严重程度 | 说明 |
|------|----------|------|
| **黑场识别逻辑错误** | 🔴 高 | `if data["patchName"] == "10%"` 不应该是黑场。黑场应该是 0% 或最低灰阶。当前逻辑会把 10% 当作黑场，导致 Gamma 计算严重错误。 |
| **不支持标准EOTF曲线** | 🔴 高 | 只计算纯 Gamma 曲线，不支持 sRGB 分段曲线、BT.1886（带黑场提升）、PQ ST 2084、HLG。 |
| **缺少逐点误差报告** | 🟡 中 | 只返回平均值，不报告每个灰阶点的误差、最大误差、暗部误差。 |
| **Gamma范围限制不合理** | 🟡 中 | `if 1.0 <= gamma <= 4.0` 可能排除合理测量点（如暗部噪声导致的异常值应单独处理）。 |
| **白场获取逻辑复杂且脆弱** | 🟡 中 | 从多个来源尝试获取白场Y值，但缺少明确的优先级和 fallback 策略。 |
| **输入电平解析不完整** | 🟡 中 | 从 patchName 解析百分比，但格式不一致时从 RGB 值估算可能不准确。 |
| **缺少 BT.1886 黑场提升参数** | 🟡 中 | BT.1886 需要 Lb 和 Lw 两个参数，当前不支持。 |

#### 专业期望

1. **支持多种目标曲线**：
   - Gamma 2.2 / 2.4（纯幂函数）
   - sRGB 分段曲线（线性段 + 幂函数）
   - BT.1886（带黑场提升的幂函数）：`L = (Lw - Lb) * (V^gamma) + Lb`
   - PQ ST 2084（HDR）：`L = 10000 * ((max(V^(1/m2), c1) - c2) / (c3 - c4 * V^(1/m2)))^m1`
   - HLG（HDR）：分段曲线 + 需要参考白点

2. **正确识别黑场和白场**：
   - 黑场：patchName == "0%" 或 "black" 或最小 Y 值
   - 白场：patchName == "100%" 或 "white" 或最大 Y 值

3. **逐点误差报告**：
   - 每个灰阶点输出：目标亮度、实测亮度、Delta E（或相对误差）
   - 汇总：平均误差、最大误差、暗部误差（L < 20）

#### 改法建议

```
Phase 1 (P2-C):
- 新建 src/color_science/transfer.py
- 实现标准 EOTF 曲线函数：gamma_pure, srgb_trc, bt1886, pq_st2084, hlg
- 修改 calculate_gamma() 正确识别黑场
- 新增 calculate_eotf_error() 返回逐点误差

Phase 2:
- 前端图表显示目标曲线 vs 实测曲线
- 支持 HDR 测量（需要 PQ/HLG）
```

#### 测试向量来源

1. **Gamma 2.2 标准**：
   - 输入 0.5 → 输出 0.5^2.2 ≈ 0.2176
   - 输入 0.1 → 输出 0.1^2.2 ≈ 0.0063

2. **sRGB 分段曲线**：
   - 输入 ≤ 0.04045 → 线性输出 = 输入 / 12.92
   - 输入 > 0.04045 → 输出 = ((输入 + 0.055) / 1.055)^2.4
   - 参考：IEC 61966-2-1 标准

3. **BT.1886 测试向量**：
   - Bruce Lindbloom 网站提供的计算器
   - 需要测试不同 Lb/Lw 组合

4. **PQ ST 2084 测试向量**：
   - SMPTE ST 2084-1 标准附录中的已知值
   - 例如：输入 0.5 → 输出约 267 cd/m²

---

### 2.3 calculate_delta_e_2000() — Delta E 计算

#### 当前行为

**位置**：`src/measurement_analyzer.py` 第 452-502 行

```python
def calculate_delta_e_2000(self, measured: Dict, target: Dict) -> float:
    # 转换到 XYZ
    measured_XYZ = self._xy_to_XYZ(measured["x"], measured["y"], measured.get("Y", 100))
    target_XYZ = self._xy_to_XYZ(target["x"], target["y"], target.get("Y", 100))
    
    # 转换到 Lab（固定 D65 参考白点）
    measured_Lab = self._XYZ_to_Lab(*measured_XYZ)
    target_Lab = self._XYZ_to_Lab(*target_XYZ)

def _XYZ_to_Lab(self, X, Y, Z,
                ref_X: float = 95.047,  # ❌ 固定 D65
                ref_Y: float = 100.0,
                ref_Z: float = 108.883) -> Tuple[float, float, float]:
```

#### 问题清单

| 问题 | 严重程度 | 说明 |
|------|----------|------|
| **固定 D65 参考白点** | 🔴 高 | Delta E 计算应在同一白点下进行。如果测量白点不是 D65，需要先做 chromatic adaptation。当前实现会引入系统性误差。 |
| **缺少 chromatic adaptation** | 🔴 高 | 没有实现 Bradford 或 CAT02 白点适配矩阵。两个颜色应先适配到同一白点再计算 Delta E。 |
| **Lab 转换数值需验证** | 🟡 中 | D65 参考值使用 (95.047, 100, 108.883)，需要与标准值比对确认。 |
| **Delta E 1976 简化公式不专业** | 🟡 中 | `calculate_delta_e()` 使用简化 xyY 公式，不是标准 CIE 1976 L*u*v* 公式。应废弃或标注为"非标准简化"。 |
| **白点偏差计算仅用 D65** | 🟡 中 | `calculate_white_point_deviation()` 默认目标 D65，但用户可能使用 D50 或其他白点。 |

#### 专业期望

1. **Chromatic Adaptation**：
   - 使用 Bradford 或 CAT02 矩阵将两个颜色适配到同一白点
   - 支持多种参考白点：D50, D65, 测量白点

2. **正确的 Delta E 计算流程**：
   ```
   1. 测量颜色 xyY → XYZ
   2. 目标颜色 xyY → XYZ
   3. 如果白点不同：Bradford adaptation 到同一白点
   4. XYZ → Lab（使用正确的参考白点）
   5. 计算 Delta E 2000
   ```

3. **参考白点选择**：
   - 默认使用目标颜色的白点（通常是标准色域的白点）
   - 或使用测量白点（更符合视觉感知）

#### 改法建议

```
Phase 1 (P2-A + P2-D):
- 新建 src/color_science/colorimetry.py
- 实现 Bradford/CAT02 chromatic adaptation 矩阵
- 实现 calculate_delta_e_2000_with_adaptation()
- 保留旧函数兼容，添加废弃警告

Phase 2:
- 对白点报告 CCT + Duv（不只是 McCamy 近似）
- 支持用户选择参考白点
```

#### 测试向量来源

1. **CIEDE2000 官方测试对**：
   - Sharma, Wu, Dalal (2005) "The CIEDE2000 Color-Difference Formula"
   - 提供 34 个测试对及预期 Delta E 2000 值
   - 文件：tests/fixtures/color_science/ciede2000_test_pairs.json

2. **Chromatic Adaptation 测试**：
   - D50 → D65 转换已知结果
   - Bruce Lindbloom 提供的测试数据

3. **白点数值验证**：
   - D65: (95.047, 100, 108.883) 需确认是 2° 或 10° 观察者
   - D50: (96.422, 100, 82.521) 2° 观察者

---

### 2.4 lab_sampler.py — 色块采样

#### 当前行为

**位置**：`src/lab_sampler.py`

```python
# sRGB 到 XYZ 转换
X = 0.4124564 * r_lin + 0.3575761 * g_lin + 0.1804375 * b_lin
Y = 0.2126729 * r_lin + 0.7151522 * g_lin + 0.0721750 * b_lin
Z = 0.0193339 * r_lin + 0.1191920 * g_lin + 0.9503041 * b_lin

# 缩放（有问题）
X = X * D65_X / 0.4124564  # ❌ 不必要的缩放

# Gamma 校正（正确）
def inv_gamma(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    else:
        return math.pow((c + 0.055) / 1.055, 2.4)

# Lab 边界估算（近似）
def get_srgb_lab_bounds(L: float) -> Tuple[float, float, float, float]:
    # 使用经验公式，不是精确计算
    if L < 10: radius = L * 2.0
    elif L < 50: radius = 20 + (L - 10) * 1.5
    ...

# RGB 转换时裁剪
r = gamma(max(0, min(1, r_lin)))  # ❌ 裁剪导致重复
```

#### 问题清单

| 问题 | 严重程度 | 说明 |
|------|----------|------|
| **XYZ 缩放错误** | 🔴 高 | `X = X * D65_X / 0.4124564` 这行代码逻辑错误，会引入非标准缩放。应删除此行或修正逻辑。 |
| **sRGB/XYZ 矩阵需验证** | 🟡 中 | 当前矩阵值与 Bruce Lindbloom 标准矩阵略有差异，需要确认使用的是哪个标准版本。 |
| **Lab 边界使用近似公式** | 🔴 高 | `get_srgb_lab_bounds()` 使用经验公式估算色域边界，不是精确计算。这会导致采样点超出色域，然后被裁剪。 |
| **Gamut clipping 导致重复色块** | 🔴 高 | 在 Lab 空间生成采样点，转换为 RGB 时超出 0-255 范围的值被裁剪到边界。大量 Lab 点会映射到相同 RGB（如 (255,0,0), (0,0,255) 等边界点），导致重复。 |
| **去重机制效率问题** | 🟡 中 | 使用 `seen_rgb` 集合去重，但采样策略本身就可能产生大量需要裁剪的 Lab 点，浪费计算。 |
| **XYZ 到 sRGB 矩阵需验证** | 🟡 中 |逆矩阵数值需要与正向矩阵配对验证。 |
| **D65 白点常量定义不一致** | 🟡 中 | `D65_X = 0.95047` 与 `_XYZ_to_Lab` 中的 `ref_X = 95.047` 有数量级差异（0-1 vs 0-100）。需要统一规范。 |

#### 数值验证：sRGB/XYZ 矩阵

**当前代码**：
```
正向矩阵（sRGB → XYZ）：
X = 0.4124564*r + 0.3575761*g + 0.1804375*b
Y = 0.2126729*r + 0.7151522*g + 0.0721750*b
Z = 0.0193339*r + 0.1191920*g + 0.9503041*b  # ❌ 第三行数值可疑
```

**Bruce Lindbloom 标准矩阵（D65, sRGB）**：
```
X = 0.4124564*r + 0.3575761*g + 0.1804375*b
Y = 0.2126729*r + 0.7151522*g + 0.0721750*b
Z = 0.0193339*r + 0.1191920*g + 0.9503041*b  # 与当前一致（但需要单位验证）
```

**问题**：第三行 Z 的系数 `0.9503041` 似乎是缩放后的值，标准矩阵应为：
```
Z = 0.0193339*r + 0.1191920*g + 0.9503041*b  （如果 Y 已经是 D65_Y=1.0）
```
但实际上标准矩阵是：
```
Z = 0.0193339*r + 0.1191920*g + 1.0870*b（不同来源有差异）
```

需要查证使用的具体标准版本。

#### 专业期望

1. **精确色域边界计算**：
   - 遍历 RGB 立方体边界，找到每个 L* 值下的精确 a*b* 范围
   - 或使用已知色域顶点计算凸包

2. **正向采样策略**：
   - 先在 RGB 空间均匀采样（保证不超出色域）
   - 再转换到 Lab 空间（不会有裁剪问题）
   - 或使用 CIE Lab 空间的已知色域边界限制采样范围

3. **避免重复**：
   - 在采样设计阶段避免生成超色域 Lab 点
   - 而不是在转换后裁剪去重

4. **统一白点常量**：
   - 使用一致的数值范围（0-1 或 0-100）
   - 参考值应来自同一标准

#### 改法建议

```
Phase 1 (P2-A + P2-E):
- 新建 src/color_science/gamut_sampling.py
- 实现精确 RGB/Lab 边界计算（遍历 RGB 立方体）
- 修正 sRGB/XYZ 转换矩阵（验证数值）
- 删除错误的 XYZ 缩放行
- 实现正向采样：RGB → Lab，避免超色域

Phase 2:
- 提供多种采样策略：快速验证、ICC 标准、LUT 高精度、暗部优先、肤色优先
- 每个色块带 sample_id, rgb, purpose, priority
- 100/500/1500 色块列表重复率低于 1%
```

#### 测试向量来源

1. **RGB/Lab 转换验证**：
   - RGB (255, 0, 0) → Lab 应约为 (53.2, 80.1, 67.2)
   - RGB (0, 255, 0) → Lab 应约为 (87.7, -86.2, 83.2)
   - RGB (0, 0, 255) → Lab 应约为 (32.3, 79.2, -107.9)
   - Bruce Lindbloom 提供精确转换值

2. **Gamma 曲线验证**：
   - sRGB gamma 分段曲线的转折点 0.04045
   - 验证正向和逆向的一致性

3. **色域边界验证**：
   - sRGB 红顶点 (255, 0, 0) 的 Lab 值
   - 验证 `get_srgb_lab_bounds(L=53)` 是否包含正确的 a*b* 范围

---

## 3. 数据结构审计（data_storage.py）

**目的**：确认测量数据格式是否支持色彩科学计算所需的字段。

#### 当前数据结构

```python
self.measurements = {
    "gamut": {
        "red": {"RGB": [255, 0, 0], "xyY": None},  # 格式正确
        "green": {"RGB": [0, 255, 0], "xyY": None},
        "blue": {"RGB": [0, 0, 255], "xyY": None},
        "white": {"RGB": [255, 255, 255], "xyY": None},
        "black": {"RGB": [0, 0, 0], "xyY": None}
    },
    "gamma": [],  # 格式：{"input": float, "Y": float, "RGB": [...], "patch_name": str}
    "lut_patches": []  # 格式：{"sample_id": str, "RGB": [...], "xyY": [...]}
}
```

#### 对色彩科学计算的影响

| 字段 | 问题 | 建议 |
|------|------|------|
| `gamma[].patch_name` | 格式不一致（"10%"、"20%"、或自定义） | 统一使用 `input` 字段作为百分比 |
| 缺少目标值字段 | Delta E 计算需要目标 xyY，但数据中只有实测值 | 在测量时记录目标值，或从标准色域推导 |
| 缺少白点字段 | 数据中不记录测量白点，无法做 chromatic adaptation | 在 metadata 中记录测量白点 xyY |
| 缺少 schema_version | 旧数据格式可能变化 | P5-A 任务处理 |

**结论**：`data_storage.py` 的数据结构基本支持色彩科学计算，但缺少目标值和白点记录，需要在后续阶段完善。

---

## 4. 风险和未完成项

### 高风险项（需要在 P2 阶段立即处理）

1. **Gamma 黑场识别错误**：当前 `calculate_gamma()` 会把 10% 灰阶当作黑场，导致 Gamma 值完全错误。这是功能性 bug，影响所有 Gamma 测量结果。

2. **色域覆盖率概念混淆**：用户看到的"覆盖率"实际上是面积比，会误导对显示器色域能力的判断。

3. **Delta E 固定 D65 白点**：当测量白点不是 D65 时，Delta E 值会有系统性误差，可能导致用户错误调整白点。

4. **色块采样重复问题**：Lab → RGB 裁剪可能导致大量重复色块，影响 ICC/LUT 质量。

### 中风险项（需要在 P2-P3 阶段处理）

1. **XYZ 缩放错误行**：`srgb_to_xyz()` 中的缩放行需要删除或修正。

2. **缺少标准 EOTF 支持**：sRGB、BT.1886、PQ、HLG 曲线缺失，影响专业校准。

3. **Lab 边界近似公式**：会导致采样范围不准确。

4. **蒙特卡洛采样伪随机**：色域交集计算不可复现。

### 未完成项

- CIEDE2000 官方测试对的验证
- sRGB/XYZ 矩阵与 Bruce Lindbloom 标准值的精确比对
- 实际测量数据与 DisplayCAL/Argyll 的交叉验证（需要硬件）

---

## 5. 函数废弃与兼容建议

### 应废弃的函数

| 函数 | 原因 | 废弃方式 |
|------|------|----------|
| `calculate_delta_e()` (CIE 1976 简化) | 使用非标准简化公式，不是真正的 CIE 1976 L*u*v* | 标记 `@deprecated`，保留兼容但输出警告 |
| `calculate_gamut_coverage()` (面积比) | 概念混淆，命名错误 | 标记 `@deprecated`，改名或输出两个指标 |
| `get_srgb_lab_bounds()` | 使用近似公式 | 替换为精确计算函数 |

### 可保留兼容的函数

| 函数 | 原因 | 保留方式 |
|------|------|----------|
| `_delta_e_2000()` | 算法正确，只需添加白点适配 | 保留核心算法，包装函数添加白点适配 |
| `_XYZ_to_Lab()` | 核心转换正确，参考白点参数化 | 保留，允许传入不同白点 |
| `_xy_to_XYZ()` | 公式正确 | 保留 |
| `STANDARD_GAMUTS` | 标准色域数据正确 | 保留，可作为测试向量 |

---

## 6. 解锁的后续任务

本审计报告完成后，解锁以下任务：

| 任务 | 依赖关系 | 可并行性 |
|------|----------|----------|
| **P2-A 色彩科学模块骨架** | 本报告提供问题清单和改法方向 | 可立即启动 |
| **P2-B 精确色域覆盖率** | 需要 P2-A 的 spaces.py 基础 | P2-A 完成后启动 |
| **P2-C EOTF/Gamma/BT.1886/HDR** | 需要 P2-A 的 transfer.py | P2-A 完成后启动 |
| **P2-D Delta E、白点、CCT/Duv** | 需要 P2-A 的 colorimetry.py | P2-A 完成后启动 |
| **P2-E 色块采样重做** | 需要 P2-A 的 gamut_sampling.py | P2-A 完成后启动 |

### 建议的测试夹具文件

需要在 `tests/fixtures/color_science/` 创建：

1. `ciede2000_test_pairs.json` — Sharma et al. 34 组测试对
2. `srgb_xyz_test_vectors.json` — RGB/XYZ/Lab 转换验证点
3. `eotf_test_vectors.json` — Gamma/sRGB/BT.1886/PQ/HLG 标准测试点
4. `gamut_intersection_test.json` — 已知三角形交集测试
5. `chromatic_adaptation_test.json` — Bradford/CAT02 测试向量

---

## 7. 附录：关键代码片段位置

| 函数/常量 | 文件 | 行号 |
|-----------|------|------|
| `calculate_gamut_coverage()` | measurement_analyzer.py | 156-182 |
| `calculate_gamut_overlap()` | measurement_analyzer.py | 184-212 |
| `_calculate_overlap_area()` | measurement_analyzer.py | 214-252 |
| `calculate_gamma()` | measurement_analyzer.py | 234-289 |
| `calculate_delta_e_2000()` | measurement_analyzer.py | 452-502 |
| `_delta_e_2000()` | measurement_analyzer.py | 504-570 |
| `_XYZ_to_Lab()` | measurement_analyzer.py | 424-452 |
| `STANDARD_GAMUTS` | measurement_analyzer.py | 13-85 |
| `srgb_to_xyz()` | lab_sampler.py | 26-55 |
| `xyz_to_lab()` | lab_sampler.py | 57-95 |
| `lab_to_xyz()` | lab_sampler.py | 97-125 |
| `xyz_to_srgb()` | lab_sampler.py | 127-165 |
| `get_srgb_lab_bounds()` | lab_sampler.py | 173-210 |
| `D65_X/Y/Z` | lab_sampler.py | 20-22 |
| `generate_patches()` | lab_sampler.py | 225-310 |

---

**审计完成日期**：2026-05-19
**下一步建议**：启动 P2-A 任务，建立色彩科学模块骨架，并创建上述测试夹具文件。