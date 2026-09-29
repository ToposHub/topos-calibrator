# P3-D: 探头修正文件管理实现报告

**任务编号**: P3-D
**执行日期**: 2026-05-19
**任务类型**: 新增修正文件管理模块
**依赖文档**: `docs/agent_handoffs/P1-B_measurement_service.md`

---

## 1. 创建/修改的文件列表

| 文件路径 | 类型 | 说明 |
|----------|------|------|
| `/Users/heng/Documents/vscode/Topos Calibrator/src/instruments/corrections.py` | 新增 | 修正文件管理核心模块（978 行） |
| `/Users/heng/Documents/vscode/Topos Calibrator/tests/test_instruments/__init__.py` | 新增 | 测试模块初始化 |
| `/Users/heng/Documents/vscode/Topos Calibrator/tests/test_instruments/test_corrections.py` | 新增 | 单元测试（46 个测试 case，812 行） |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/backend.py` | 修改 | 集成修正文件管理 API（+~150 行） |
| `/Users/heng/Documents/vscode/Topos Calibrator/src/data_storage.py` | 修改 | 添加修正文件信息存储方法（+~40 行） |
| `/Users/heng/Documents/vscode/Topos Calibrator/web/js/main.js` | 修改 | 前端修正文件选择和兼容性检查（+~150 行） |
| `/Users/heng/Documents/vscode/Topos Calibrator/web/index.html` | 修改 | 添加修正文件信息显示区域 |
| `/Users/heng/Documents/vscode/Topos Calibrator/web/css/style.css` | 修改 | 添加修正文件信息样式 |

---

## 2. 实现思路

### 2.1 CCSS 与 CCMX 区分

**CCSS (Spectral Correction)**:
- 分光仪生成的光谱修正数据
- 适用于特定显示技术的色度计
- 包含光谱数据而非矩阵

**CCMX (Matrix Correction)**:
- 需要分光仪作为基准的矩阵修正
- 包含 3x3 XYZ 校正矩阵
- 记录目标探头、基准探头、显示技术

实现通过 `CorrectionType` 枚举区分，解析器根据文件扩展名和内容自动识别。

### 2.2 适用条件检查

每个修正文件记录以下元数据（从 CGATS 格式解析）：

| 字段 | CGATS 关键字 | 说明 |
|------|-------------|------|
| `instrument` | INSTRUMENT | 目标探头类型（CCMX 必需） |
| `technology` | TECHNOLOGY | 目标显示技术代码 |
| `reference_instrument` | REFERENCE | 基准探头类型（CCMX 必需） |
| `created` | CREATED | 创建时间戳 |
| `descriptor` | DESCRIPTOR | 描述字符串 |
| `file_hash` | (计算) | SHA-256 文件哈希 |

**兼容性检查逻辑**：
1. 探头匹配检查：同家族探头兼容（如 i1d3 和 i1d2）
2. 显示技术兼容：LCD 通用 'l' 兼容所有 LCD 变体
3. 分光仪警告：分光仪不需要 CCMX，使用时发出警告
4. 不兼容时阻止：探头不匹配会阻止使用，显示技术不匹配仅警告

### 2.3 测量结果关联

每个测量结果写入使用的修正文件 hash：

```python
# MeasurementData 新增方法
def set_correction_file(
    self,
    correction_hash: str,
    correction_path: str = "",
    correction_descriptor: str = "",
    correction_type: str = "",
    correction_instrument: str = "",
    correction_technology: str = "",
    correction_reference: str = "",
    correction_created: str = ""
):
```

保存测量时自动关联当前使用的修正文件。

### 2.4 CCMX 制作向导支持

`CCMXCreationWizard` 类提供：

- 状态管理：IDLE → REFERENCE_MEASURING → REFERENCE_COMPLETE → TARGET_MEASURING → TARGET_COMPLETE → GENERATING
- 测量验证：检查必需色块（白、红、绿、蓝）
- 参数生成：提供 ccxxmake 调用所需参数

---

## 3. 验证命令和结果

### 3.1 运行测试

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"
python3 -m pytest tests/test_instruments/test_corrections.py -v
```

结果：**46 passed in 0.09s**

### 3.2 运行全部模块测试

```bash
python3 -m pytest tests/test_core tests/test_workflows tests/test_instruments -v
```

结果：**354 passed in 42.50s**

### 3.3 解析实际 CCMX 文件

```bash
python3 -c "
from src.instruments.corrections import CorrectionFileParser
parser = CorrectionFileParser()
metadata = parser.parse_file('corrections/i1d3_matrix_20260405_074500.ccmx')
print('Valid:', metadata.is_valid)
print('Matrix:', metadata.matrix)
"
```

结果：
```
Valid: True
Matrix: [[1.051322, -0.0242306, -0.0119285], [0.0144179, 0.990586, -0.00333015], [0.0172358, -0.0122439, 0.987409]]
```

### 3.4 语法检查

```bash
python3 -m py_compile src/instruments/corrections.py src/backend.py src/data_storage.py
```

结果：**Syntax check passed**

---

## 4. 风险和未完成项

### 4.1 已识别风险

| 风险类型 | 风险描述 | 影响程度 | 建议 |
|----------|----------|----------|------|
| CCMX 解析健壮性 | CGATS 格式变体可能导致解析失败 | 低 | 已处理 END_DATA_FORMAT 冲突问题 |
| 前端兼容性检查 | check_correction_compatibility 异步调用 | 低 | 失败时允许设置（用户覆盖） |
| 显示技术命名 | ArgyllCMS 技术代码不一致（'a' 多义） | 低 | OLED AMOLED 'a' 与 LCD 变体分开处理 |

### 4.2 未完成项

1. **CCMX 制作向导 UI**: 前端向导界面尚未实现，仅提供后端支持
2. **修正文件验证**: 未实现 CCMX 精度验证逻辑
3. **报告导出**: 测量报告需显示修正文件信息（P5-C 任务）
4. **历史数据迁移**: 旧测量数据无修正文件 hash，需添加迁移脚本

---

## 5. 解锁的后续任务

完成本任务后，以下任务可立即开始：

| 任务编号 | 任务名称 | 依赖关系 | 可开始时间 |
|----------|----------|----------|------------|
| P4-A | Argyll 适配层重构 | 依赖 P1-B, P0-C, P3-D | 立即 |
| P5-C | 专业报告导出 | 依赖 P2, P5-A, P3-D | P5-A 完成后 |
| P6-A | 专业工作流向导 | 依赖 P1-C, P3-C, P3-D | 立即 |

---

## 6. API 变更记录

### Backend 新增 Slot

```python
@pyqtSlot(result=str)
def get_correction_files_detailed(self) -> str:
    """获取带详细元数据的修正文件列表"""

@pyqtSlot(str, result=str)
def get_correction_metadata(self, file_path: str) -> str:
    """获取单个修正文件详细元数据"""

@pyqtSlot(str, str, str, result=str)
def check_correction_compatibility(
    self,
    correction_path: str,
    probe_type: str,
    display_technology: str = ""
) -> str:
    """检查修正文件兼容性"""
```

### Backend 修改方法

`set_correction_file_path`:
- 新增兼容性检查和警告输出
- 新增修正文件元数据显示（描述、探头、显示技术、创建时间）
- 记录修正文件 hash 用于测量关联

### MeasurementData 新增方法

```python
def set_correction_file(...)
def get_correction_hash() -> str
def get_correction_info() -> Dict
```

---

## 7. 测试覆盖率统计

- 总测试数: 46
- 测试类: 13 个
- 分类覆盖:
  - 类型枚举: 2
  - 显示技术转换: 4
  - 探头信息: 3
  - 文件解析: 6
  - 元数据序列化: 3
  - 管理器功能: 10
  - CCMX 向导: 9
  - 兼容性结果: 1
  - 探头家族: 3
  - 显示技术兼容: 3
  - 便捷函数: 2

---

**任务完成签名**: Agent P3-D
**任务完成时间**: 2026-05-19