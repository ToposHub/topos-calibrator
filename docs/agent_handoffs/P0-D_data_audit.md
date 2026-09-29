# P0-D 数据治理审计报告

**执行时间**: 2026-05-19
**执行者**: AI Agent (Qwen Code)
**任务来源**: docs/professional_optimization_plan.md

---

## 1. 分析的文件和目录

### 1.1 只读分析文件

| 文件 | 说明 |
|------|------|
| `src/data_storage.py` | 数据存储模块，包含 MeasurementData、SessionData、DataStorage、SessionStorage、CGATSExporter 类 |
| `src/comparison_window.py` | 数据对比窗口，使用 DataStorage 加载历史数据 |

### 1.2 分析的目录结构

```
measurements/
├── auto_save/                    # 自动保存目录
│   ├── latest -> 2026-04-16/     # 符号链接指向最新日期
│   ├── 2026-04-11/               # 1 个 JSON + 1 个 TI3
│   ├── 2026-04-12/               # 8 个 JSON + 8 个 TI3
│   └── 2026-04-16/               # 4 个 JSON + 4 个 TI3 + 2 个 CAL
├── sessions/                     # 空目录（未使用）
├── calibration_20260411_*.cal    # 3 个旧格式 CAL 文件
├── calibration_20260416_*.cal    # 2 个旧格式 CAL 文件
├── display_profile_2026-04-11.ti3 # 1 个旧格式 TI3 文件
```

**统计汇总**:
- auto_save JSON 文件: 12 个
- auto_save TI3 文件: 12 个（每个 JSON 都有对应 TI3）
- auto_save CAL 文件: 2 个（部分有对应 JSON）
- 根目录遗留 CAL: 5 个
- 根目录遗留 TI3: 1 个

---

## 2. 数据问题列表

### 2.1 重复 ID 检查

**结论**: 当前无重复 measurement_id

所有 12 个 JSON 文件的 measurement_id 唯一：
```
20260416_050138_cf7e54
20260416_030651_ffa1f8
20260416_025930_96a01f
20260416_022801_12334d
20260412_032407_a83186
20260412_031923_ff74ce
20260412_030710_52abd5
20260412_024412_bf96d2
20260412_023820_44d6b4
20260412_001341_7d484a
20260412_001220_1321a0
20260411_224303_8802dd
```

**风险点**: ID 生成机制依赖于时间戳 + 随数后缀，理论上同秒内多次保存可能产生冲突（概率极低但未做防重检查）。

### 2.2 缺字段问题

| 文件 | 缺失字段 | 严重程度 |
|------|----------|----------|
| `230030-346-icc.json` | probe="", display_type="", display_model="" | 高 |
| `001312-092-gamut.json` | probe="", display_type="", display_model="" | 高 |
| `001510-028-gamut.json` | probe="", display_type="", display_model="" | 高 |
| `023909-433-gamut.json` | probe="", display_type="", display_model="" | 高 |

**共 4 个文件缺少硬件 metadata**，占总数的 33%。

### 2.3 测量数据 Null 问题

| 文件 | gamut null 数量 | 说明 |
|------|-----------------|------|
| `022801-579-dispcal.json` | 4 (red, green, blue, black) | dispcal 模式只测白点 |
| `025930-351-dispcal.json` | 4 (red, green, blue, black) | dispcal 模式只测白点 |

**说明**: dispcal 模式的 gamut 测量数据为 null 是预期行为（dispcal 主要做灰阶校准），但 JSON 结构中仍保留空字段，不够清晰。

### 2.4 文件命名与 ID 不匹配

**问题描述**: 文件名中的时间戳与 metadata.measurement_id 中的时间戳不完全一致

| 文件名 | 文件名时间戳 | measurement_id 时间戳 | 差值 |
|--------|--------------|----------------------|------|
| `001312-092-gamut.json` | 00:13:12 | 00:12:20 | ~52秒 |
| `001510-028-gamut.json` | 00:15:10 | 00:13:41 | ~89秒 |
| `023909-433-gamut.json` | 02:39:09 | 02:38:20 | ~49秒 |

**原因分析**: 
- `measurement_id` 在 MeasurementData 初始化时生成（测量开始时间）
- 文件名在 `save_measurement_bundle()` 时生成（保存时间）
- 两者时间差反映测量持续时间

**风险**: 按文件名查找时无法直接关联到 metadata.measurement_id。

### 2.5 CAL 文件与 JSON 不对应

| CAL 文件 | 对应 JSON | 状态 |
|----------|-----------|------|
| `022801-580-dispcal.cal` | `022801-580-dispcal.json` | **缺失** |
| `025930-352-dispcal.cal` | `025930-352-dispcal.json` | **缺失** |

**说明**: CAL 文件的毫秒后缀与 JSON/TI3 不同（580 vs 579, 352 vs 351），导致无法找到对应的 JSON 文件。

**根因**: `copy_cal_file_to_auto_save()` 在保存 CAL 时独立生成时间戳，而非使用已有文件名。

### 2.6 TI3 文件缺少仪器信息

所有 auto_save TI3 文件的 `TARGET_INSTRUMENT` 和 `DISPLAY_TYPE_REF` 为空字符串：

```
TARGET_INSTRUMENT ""
DISPLAY_TYPE_REF ""
```

这导致生成的 TI3 文件无法直接用于 ccxxmake（需要仪器基准信息）。

### 2.7 根目录遗留旧格式文件

| 文件 | 格式 | 问题 |
|------|------|------|
| `calibration_20260411_000119.cal` | `calibration_YYYYMMDD_HHMMSS.cal` | 无对应 JSON |
| `calibration_20260411_072451.cal` | 同上 | 无对应 JSON |
| `calibration_20260411_085123.cal` | 同上 | 无对应 JSON |
| `calibration_20260416_021446.cal` | 同上 | 无对应 JSON |
| `calibration_20260416_025130.cal` | 同上 | 无对应 JSON |
| `display_profile_2026-04-11.ti3` | `display_profile_YYYY-MM-DD.ti3` | 无对应 JSON，526 色块 |

**问题**: 这些文件命名格式不一致，且无 JSON metadata 文件关联。

### 2.8 Schema Version 缺失

所有 JSON 文件顶层结构：
```json
{
  "metadata": { ... },
  "measurements": { ... }
}
```

**缺失字段**:
- `schema_version` - 无法识别数据版本
- `session_id` - 无法关联到会话
- `environment` - 无环境信息（OS、Argyll 版本等）
- `artifacts` - 无文件清单和 hash

### 2.9 Sessions 目录未使用

`measurements/sessions/` 目录为空，SessionStorage 的会话管理功能未实际启用。

---

## 3. JSON/TI3/Session 对应关系

### 3.1 当前 auto_save 文件对应关系

```
日期目录 2026-04-16/
├── 022801-579-dispcal.json  ←→ 022801-579-dispcal.ti3
├── 022801-580-dispcal.cal   ← 无对应 JSON ⚠️
├── 025930-351-dispcal.json  ←→ 025930-351-dispcal.ti3
├── 025930-352-dispcal.cal   ← 无对应 JSON ⚠️
├── 030651-412-icc.json      ←→ 030651-412-icc.ti3
├── 050138-511-icc.json      ←→ 050138-511-icc.ti3

日期目录 2026-04-12/
├── 001312-092-gamut.json    ←→ 001312-092-gamut.ti3
├── 001510-028-gamut.json    ←→ 001510-028-gamut.ti3
├── 023909-433-gamut.json    ←→ 023909-433-gamut.ti3
├── 024412-785-gamut.json    ←→ 024412-785-gamut.ti3
├── 030710-294-gamut.json    ←→ 030710-294-gamut.ti3
├── 031923-881-gamut.json    ←→ 031923-881-gamut.ti3
├── 032407-804-gamut.json    ←→ 032407-804-gamut.ti3

日期目录 2026-04-11/
├── 230030-346-icc.json      ←→ 230030-346-icc.ti3
```

### 3.2 当前关联机制

- **文件名前缀匹配**: JSON 和 TI3 使用相同文件名前缀 `HHMMSS-mmm-mode`
- **无 manifest 文件**: 目录中无 manifest.json 记录文件关系
- **无 session.json**: 每次测量未生成会话元数据文件
- **代码依赖路径推断**: `get_all_saved_measurements()` 和 `get_saved_calibration_list()` 通过遍历目录和文件名推断关系

### 3.3 问题总结

| 问题类型 | 数量 | 影响 |
|----------|------|------|
| CAL 无对应 JSON | 2 | 无法追溯校准参数 |
| 旧格式遗留文件 | 6 | 无法纳入历史列表 |
| 缺 metadata 字段 | 4 | 无法识别硬件环境 |
| TI3 缺仪器信息 | 12 | ccxxmake 不兼容 |

---

## 4. Schema Version 和 Manifest 设计建议

### 4.1 推荐数据 Schema (v1.0)

```json
{
  "schema_version": "1.0.0",
  "session_id": "20260416-030651-ffa1f8",
  "created_at": "2026-04-16T03:06:51.412652",
  "updated_at": "2026-04-16T03:06:51.412652",
  
  "software": {
    "name": "Topos Calibrator",
    "version": "0.1.0"
  },
  
  "environment": {
    "os": "darwin",
    "os_version": "14.4.0",
    "argyll_version": "3.2.1",
    "python_version": "3.11.4"
  },
  
  "instrument": {
    "probe": "i1d3",
    "probe_serial": null,
    "correction_file": null,
    "correction_hash": null
  },
  
  "display": {
    "type": "l",
    "model": "PHL 439P1",
    "display_id": "1",
    "display_name": "Main Monitor",
    "resolution": [3840, 2160],
    "refresh_rate": 60
  },
  
  "workflow": {
    "mode": "icc",
    "target": "sRGB",
    "gamma_target": 2.2,
    "white_point_target": "D65",
    "parameters": {}
  },
  
  "measurements": {
    "gamut": { ... },
    "gamma": [ ... ],
    "lut_patches": [ ... ]
  },
  
  "artifacts": {
    "measurement_json": {
      "filename": "measurement.json",
      "sha256": "abc123..."
    },
    "ti3": {
      "filename": "profile.ti3",
      "sha256": "def456..."
    },
    "cal": {
      "filename": "calibration.cal",
      "sha256": "ghi789..."
    },
    "icc": null,
    "lut": null
  },
  
  "status": "completed",
  "notes": ""
}
```

### 4.2 Session Manifest 设计

每个 session 目录应包含 `manifest.json`：

```json
{
  "schema_version": "1.0.0",
  "session_id": "20260416-030651-ffa1f8",
  
  "created_at": "2026-04-16T03:06:51.412652",
  "updated_at": "2026-04-16T03:06:51.412652",
  
  "storage_type": "auto_save",
  "date_dir": "2026-04-16",
  
  "files": [
    {
      "type": "measurement",
      "filename": "030651-412-icc.json",
      "sha256": "abc123...",
      "size_bytes": 12345,
      "generated_by": "MeasurementData.to_json()"
    },
    {
      "type": "ti3",
      "filename": "030651-412-icc.ti3",
      "sha256": "def456...",
      "size_bytes": 8765,
      "generated_by": "CGATSExporter.export_ti3()"
    }
  ],
  
  "workflow": {
    "mode": "icc",
    "target": "sRGB",
    "status": "completed"
  },
  
  "instrument": {
    "probe": "i1d3",
    "correction_file": null
  },
  
  "display": {
    "model": "PHL 439P1",
    "display_name": "Main Monitor"
  },
  
  "checksums_validated": true,
  "integrity_status": "ok"
}
```

### 4.3 文件命名规范建议

**推荐统一命名格式**：
```
{session_id}/{filename}
```

例如：
```
sessions/20260416-030651-ffa1f8/
├── manifest.json
├── measurement.json
├── profile.ti3
├── calibration.cal
├── icc_profile.icc  (可选)
└── report.html      (可选)
```

**auto_save 保留日期目录结构**：
```
auto_save/2026-04-16/
├── 20260416-030651-ffa1f8/
│   ├── manifest.json
│   ├── measurement.json
│   └── profile.ti3
```

---

## 5. 迁移脚本输入输出规范

### 5.1 迁移脚本功能需求

| 功能 | 输入 | 输出 |
|------|------|------|
| 添加 schema_version | auto_save/*.json | auto_save/*.json (更新) |
| 补充缺失 metadata | auto_save/*.json + 用户输入 | auto_save/*.json (更新) |
| 生成 manifest | auto_save/YYYY-MM-DD/ | manifest.json |
| 迁移旧格式文件 | measurements/*.cal, *.ti3 | auto_save/YYYY-MM-DD/ |
| 去重检查 | 全部 JSON | duplicates_report.json |
| ID 关联修复 | JSON + 文件名 | manifest.json (关联记录) |

### 5.2 迁移脚本接口规范

```python
class DataMigration:
    """数据迁移工具"""
    
    def migrate_v0_to_v1(self, source_dir: Path, target_dir: Path) -> Dict:
        """
        迁移旧格式数据到 v1 schema
        
        Args:
            source_dir: 源目录 (measurements/auto_save 或 measurements/)
            target_dir: 目标目录 (measurements/auto_save/)
            
        Returns:
            {
                "migrated_count": int,
                "skipped_count": int,
                "errors": List[str],
                "manifests_created": List[str]
            }
        """
    
    def add_schema_version(self, json_path: Path) -> bool:
        """为单个 JSON 文件添加 schema_version"""
    
    def generate_manifest(self, session_dir: Path) -> Path:
        """为 session 目录生成 manifest.json"""
    
    def check_duplicates(self, base_dir: Path) -> Dict:
        """检查重复记录，返回重复项列表"""
    
    def validate_integrity(self, manifest_path: Path) -> Dict:
        """验证 manifest 中记录的文件完整性"""
```

### 5.3 迁移脚本 CLI 规范

```bash
# 扫描并报告问题
python scripts/migrate_data.py --scan measurements/

# 执行迁移（添加 schema_version）
python scripts/migrate_data.py --migrate measurements/auto_save/ --target-schema 1.0

# 生成 manifest
python scripts/migrate_data.py --manifest measurements/auto_save/2026-04-16/

# 检查重复
python scripts/migrate_data.py --dedup measurements/

# 验证完整性
python scripts/migrate_data.py --verify measurements/auto_save/
```

### 5.4 迁移策略建议

**Phase 1: 只读分析** (本报告)
- 完成数据问题清单
- 设计 schema 和 manifest 结构

**Phase 2: Schema 添加** (P5-A)
- 为所有 JSON 文件添加 `schema_version: "1.0.0"`
- 保持原有数据结构不变
- 新增字段放在顶层

**Phase 3: Manifest 生成** (P5-B)
- 为每个日期目录生成汇总 manifest
- 记录文件 sha256 和关联关系
- 标记 CAL 文件的对应 JSON（通过时间戳近似匹配）

**Phase 4: 旧数据迁移** (后续)
- 迁移根目录遗留文件到 auto_save
- 生成 session 目录结构
- 提供用户界面补充缺失 metadata

---

## 6. 解锁的后续任务

本审计报告完成后，解锁以下任务：

| 任务 | 依赖 | 说明 |
|------|------|------|
| **P5-A 数据 schema version 与迁移** | P0-D | 设计 schema v1.0，实现迁移脚本骨架 |
| **P5-B Artifact Manifest** | P0-D, P5-A | 实现 manifest.json 生成和验证 |
| **P1-C Backend 瘦身** | P5-A (部分) | Backend 的数据保存逻辑需适配新 schema |
| **P6-C 历史对比升级** | P5-B | comparison_window 需以 manifest 为数据源 |
| **P7-A 测试体系** | P5-A | 迁移脚本需配单元测试 |

---

## 7. 风险和限制

### 7.1 迁移风险

| 风险 | 影响 | 建议 |
|------|------|------|
| 旧数据缺失 metadata | 无法自动补充硬件信息 | 提供用户手动补充界面 |
| CAL 文件时间戳不一致 | 无法精确关联 | 使用时间戳范围匹配 + 用户确认 |
| TI3 文件仪器信息缺失 | ccxxmake 不兼容 | 迁移时从 JSON metadata 补充 |

### 7.2 未完成项

- 未检查 JSON 数据的数值合理性（如 xyY 范围）
- 未验证 TI3 与 JSON 数据一致性
- 未设计 ICC/LUT 文件的 manifest 结构（非当前数据）

### 7.3 建议

1. **优先处理**: 为所有新保存数据添加 schema_version
2. **次优先**: 修复 CAL 文件命名逻辑，确保与 JSON 时间戳一致
3. **中优先**: 生成 auto_save 目录的 manifest.json
4. **低优先**: 迁移根目录遗留文件（可在用户需要时手动处理）

---

## 8. 附录：代码审计发现

### 8.1 MeasurementData 类问题

**文件**: `src/data_storage.py`

| 方法 | 问题 | 建议 |
|------|------|------|
| `_generate_id()` | 使用时间戳+随机后缀，无防重检查 | 添加碰撞检测 |
| `save_measurement_bundle()` | CAL 文件独立生成时间戳 | 使用 JSON 文件名前缀 |
| `to_dict()` | 无 schema_version | 添加顶层字段 |

### 8.2 SessionStorage 类问题

| 方法 | 问题 | 建议 |
|------|------|------|
| `save_session()` | 未实际使用 | 启用或删除 |
| `sessions_path` | 目录为空 | 考虑废弃或整合到 auto_save |

### 8.3 CGATSExporter 类问题

| 方法 | 问题 | 建议 |
|------|------|------|
| `_generate_ti3_content()` | TARGET_INSTRUMENT 和 DISPLAY_TYPE_REF 为空 | 从 MeasurementData.metadata 补充 |

---

**报告完成时间**: 2026-05-19
**下一步**: 等待 P0 全部审计完成后，启动第二轮 P5-A/P5-B 数据 schema + manifest 实现