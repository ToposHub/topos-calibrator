# P5-A/P5-B Schema Version 与迁移 + Artifact Manifest 完成报告

**执行时间**: 2026-05-19
**执行者**: AI Agent (Qwen Code)
**任务来源**: docs/professional_optimization_plan.md

---

## 1. 创建的文件列表

| 文件路径 | 说明 |
|---------|------|
| `src/storage/__init__.py` | 模块入口，导出所有公共接口 |
| `src/storage/schema.py` | Schema v1.0 结构定义（687 行） |
| `src/storage/migrations.py` | 数据迁移器实现（390 行） |
| `src/storage/manifest.py` | Artifact Manifest 实现（773 行） |
| `tests/test_schema.py` | Schema 单元测试（41 个测试） |
| `tests/test_manifest.py` | Manifest 单元测试（40 个测试） |

**新增目录**: `src/storage/`

---

## 2. 实现思路

### P5-A Schema Version 与迁移

#### Schema v1.0 结构设计

基于 P0-D handoff 中的建议，设计了以下结构：

```
SchemaV1 {
    schema_version: "1.0"           # 必须字段
    session_id: YYYYMMDD-HHMMSS-XXXXXX  # 唯一 ID
    created_at, updated_at          # 时间戳
    
    software: SoftwareInfo          # 软件信息
    environment: EnvironmentInfo    # 环境信息（自动填充）
    instrument: InstrumentInfo      # 仪器信息（含 correction_file, correction_hash）
    display: DisplayInfo            # 显示器信息
    workflow: WorkflowInfo          # 工作流信息
    
    measurements: {
        gamut: GamutMeasurement     # 色域测量
        gamma: []                   # 灰阶测量
        lut_patches: []             # LUT 色块测量
    }
    
    artifacts: ArtifactsInfo        # 文件清单
    analysis: AnalysisInfo          # 分析结果（可选）
    
    status: draft/completed/archived
    notes: ""
}
```

#### 关键设计决策

1. **使用 dataclass**: 所有结构使用 `@dataclass` 定义，便于序列化和类型检查。
2. **向后兼容**: `MeasurementSchema.from_legacy_dict()` 可完整转换旧格式数据，不丢失字段。
3. **稳定唯一 ID**: session_id 格式为 `YYYYMMDD-HHMMSS-XXXXXX`，时间戳 + 随机后缀确保唯一性。
4. **自动环境填充**: `EnvironmentInfo.__post_init__()` 自动获取 OS 和 Python 版本。

#### 迁移策略

- `MigrationManager` 支持原地迁移和目标目录迁移
- 迁移前可选创建备份（`measurements_backup_TIMESTAMP`）
- 去重策略支持四种模式：`hash`, `measurement_id`, `path`, `timestamp`, `composite`
- 迁移时计算文件 SHA256 并添加到 `artifacts` 字段

### P5-B Artifact Manifest

#### Manifest 结构

```
ArtifactManifest {
    schema_version: "1.0"
    session_id: ""
    created_at, updated_at
    
    storage_type: auto_save/sessions
    date_dir: YYYY-MM-DD
    
    files: [ManifestEntry]          # 文件列表
    
    workflow: {...}                 # 工作流摘要
    instrument: {...}               # 仪器摘要
    display: {...}                  # 显示器摘要
    
    checksums_validated: bool
    integrity_status: ok/warning/error
    integrity_errors: []
}
```

#### ManifestEntry 结构

```
ManifestEntry {
    type: measurement/ti3/cal/icc/lut/report
    filename: ""
    sha256: ""                      # 文件内容 hash
    size_bytes: 0
    generated_at: ""
    generated_by: ""                # 生成命令或方法
    parameters: {}
}
```

#### 验证机制

- `validate_manifest()` 检查所有记录文件的：
  1. 是否存在
  2. SHA256 hash 是否匹配
  3. 文件大小是否匹配
- 检测未记录的文件（作为 warning）
- 删除或移动文件后，manifest 验证能正确报错

---

## 3. 验证命令和结果

### 运行测试

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"
python3 -m pytest tests/test_schema.py tests/test_manifest.py -v
```

### 结果

```
============================== 81 passed in 0.15s ==============================
```

### 测试覆盖

**Schema 测试 (41 个)**:
- SchemaVersion: 版本获取、支持检查、比较
- SchemaV1: 初始化、session_id 格式、转换、加载、设置方法
- MeasurementSchema: 旧格式转换、往返转换
- validate_schema: 必需字段检查、版本验证
- Dataclasses: 所有数据类的初始化

**Manifest 测试 (40 个)**:
- ManifestEntry: 初始化、转换、加载
- ArtifactManifest: 添加/移除/获取文件
- 文件 hash/大小计算
- generate_manifest: 空目录、有文件、旧格式 JSON
- save/load: 往返转换
- validate_manifest: 完整性检查、缺失文件、hash 不匹配
- ManifestManager: 批量操作
- 删除/移动文件场景验证

---

## 4. 验收标准达成情况

| 验收标准 | 达成情况 |
|---------|---------|
| 旧数据全可读，不丢失字段 | ✓ `MeasurementSchema.from_legacy_dict()` 完整转换所有字段 |
| 迁移后每条记录有稳定唯一 ID | ✓ session_id 格式稳定，measurement_id 转换为 session_id |
| 删除或移动 artifact 后 manifest 校验报错 | ✓ 测试 `TestManifestDeletionScenario` 验证通过 |

---

## 5. 风险和未完成项

### 风险

1. **旧数据缺失 metadata**: 无法自动补充硬件信息，需要用户手动补充界面（后续任务）
2. **CAL 文件时间戳不一致**: P0-D 中发现的 CAL 与 JSON 时间戳差异问题未在此任务解决
3. **TI3 文件仪器信息缺失**: TI3 文件生成时 `TARGET_INSTRUMENT` 和 `DISPLAY_TYPE_REF` 为空的问题未在此任务解决

### 未完成项

1. **数据迁移脚本 CLI**: `migrate_data.py` 命令行工具未创建（后续 P5-A 扩展任务）
2. **与 Backend 集成**: `src/backend.py` 和 `src/data_storage.py` 未修改以使用新 schema
3. **ICC/LUT 文件 manifest**: 仅定义了结构，未实现完整的 ICC/LUT 工作流 manifest

---

## 6. 解锁的后续任务

| 任务 | 依赖 | 说明 |
|------|------|------|
| **P1-C Backend 瘦身** | P5-A | Backend 的数据保存逻辑需适配新 schema |
| **P5-C 专业报告导出** | P5-A, P2 | 报告模板可使用 SchemaV1.analysis 字段 |
| **P6-C 历史对比升级** | P5-B | comparison_window 需以 manifest 为数据源 |
| **P7-A 测试体系** | P5-A | 迁移脚本需配集成测试 |

---

## 7. 接口使用示例

### 创建新格式数据

```python
from src.storage import SchemaV1

schema = SchemaV1()
schema.set_instrument("i1d3", "SN12345", "correction.ccss", "abc123")
schema.set_display("l", "PHL 439P1", "1", "Main Monitor", (3840, 2160), 60)
schema.set_workflow("icc", "sRGB", 2.2, "D65")
schema.update_gamut_measurement("white", (255, 255, 255), 0.3127, 0.3290, 100.0)
schema.add_artifact("measurement_json", "measurement.json", "sha256_hash")

# 保存
import json
with open("measurement.json", "w") as f:
    f.write(schema.to_json())
```

### 从旧格式转换

```python
from src.storage import MeasurementSchema

legacy_data = {
    "metadata": {"measurement_id": "20260416_030651_ffa1f8", "probe": "i1d3", ...},
    "measurements": {"gamut": {...}, "gamma": [...]}
}

schema = MeasurementSchema.from_legacy_dict(legacy_data)
# schema.session_id == "20260416-030651-ffa1f8"
```

### 生成和验证 Manifest

```python
from src.storage import generate_manifest, validate_manifest, save_manifest

manifest = generate_manifest(session_dir)
save_manifest(manifest, session_dir)

# 验证
is_valid, errors = validate_manifest(manifest, session_dir)
if not is_valid:
    print("完整性问题:", errors)
```

---

## 8. 文件结构

```
src/storage/
├── __init__.py          # 模块入口
├── schema.py            # Schema v1.0 定义
│   ├── SchemaVersion    # 版本管理
│   ├── SchemaV1         # v1 数据结构
│   ├── MeasurementSchema # 旧格式转换
│   └── validate_schema  # 验证函数
│   └── dataclasses      # SoftwareInfo, EnvironmentInfo, ...
├── migrations.py        # 迁移工具
│   ├── MigrationManager # 迁移管理器
│   ├── migrate_v0_to_v1 # 迁移函数
│   └── deduplicate_records # 去重
│   └── LegacyDataReader # 旧数据读取
└── manifest.py          # Manifest 管理
    ├── ManifestEntry    # 文件条目
    ├── ArtifactManifest # Manifest 结构
    ├── generate_manifest # 生成函数
    ├── validate_manifest # 验证函数
    └── ManifestManager  # 批量管理

tests/
├── test_schema.py       # Schema 测试 (41 个)
└── test_manifest.py     # Manifest 测试 (40 个)
```

---

**报告完成时间**: 2026-05-19
**下一步**: 等待评审，可解锁 P1-C/P5-C/P6-C/P7-A 任务