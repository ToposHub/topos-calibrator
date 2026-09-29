# P7-B 日志与诊断包完成报告

**执行时间**: 2026-05-19
**执行者**: AI Agent (Qwen Code)
**任务来源**: docs/professional_optimization_plan.md

---

## 1. 创建/修改的文件列表

| 文件路径 | 说明 | 状态 |
|---------|------|------|
| `src/diagnostics/__init__.py` | 模块入口，导出所有公共接口 | 已存在，未修改 |
| `src/diagnostics/logger.py` | 日志模块（SessionLogger） | 已存在，未修改 |
| `src/diagnostics/diagnostics.py` | 诊断包生成 | 修复 `_sanitize_path` 方法缺失 bug，修复 manifest 写入顺序 bug |
| `src/backend.py` | 集成日志系统 | 添加导入、初始化日志器、替换 print 语句、添加诊断包导出功能 |
| `tests/test_diagnostics/__init__.py` | 测试模块入口 | 新增 |
| `tests/test_diagnostics/test_logger.py` | Logger 单元测试（29 个测试） | 新增 |
| `tests/test_diagnostics/test_diagnostics.py` | Diagnostics 单元测试（38 个测试） | 新增 |

---

## 2. 实现思路

### 日志架构

```
SessionLogger (单例模式)
├── _sessions: Dict[str, LogSession]  # 会话级日志管理
├── _current_session_id: str          # 当前会话 ID
├── _log_level: int                   # 全局日志级别
└── _log_dir: Path                    # 日志目录

LogSession
├── session_id: str                   # 会话 ID (YYYYMMDD-HHMMSS 格式)
├── log_file: Path                    # 日志文件路径
├── logger: logging.Logger            # Python logging 实例
└── handlers: List[Handler]           # 文件和控制台处理器

全局函数接口：
├── get_logger(name)                  # 获取命名日志器
├── init_session_logger(session_id)   # 初始化会话日志
├── get_session_logger()              # 获取当前会话日志器
├── close_session_logger(session_id)  # 关闭会话日志
└── set_log_level(level)              # 设置日志级别
```

### 诊断包结构

```
DiagnosticsPack (ZIP 文件)
├── diagnostics_manifest.json         # 诊断包元信息
│   ├── version: "1.0"
│   ├── session_id: "..."
│   ├── created_at: "..."
│   ├── environment: {...}            # OS/Python/Argyll 版本
│   ├── exceptions: [...]             # 异常栈列表
│   ├── included_files: [...]         # 包含的文件列表
│   └── export_options: [...]         # 导出选项
├── logs/                             # Session 日志文件
├── measurements/                     # 测量数据 (.json)
├── argyll_output/                    # Argyll 输出 (.ti1, .ti3, .log)
├── manifests/                        # Session manifests
├── icc_profiles/                     # ICC profiles（可选，隐私敏感）
├── cal_files/                        # CAL 文件（可选，隐私敏感）
└── other/                            # 其他文件
```

### Backend 集成

在 `Backend.__init__` 中：
```python
# 初始化会话日志
self._session_id = init_session_logger()
self._logger = get_session_logger()
self._diagnostics_collector = DiagnosticsCollector(self._session_id)
```

新增 QWebChannel 接口：
- `get_export_options()` - 获取可用的导出选项
- `export_diagnostics_pack(session_id, output_path, include_private)` - 导出诊断包
- `get_session_id()` - 获取当前会话 ID
- `set_log_level(level)` - 设置日志级别

### 隐私保护机制

1. **路径脱敏**：所有用户路径（/Users/xxx、/home/xxx）自动替换为 /Users/***、/home/***
2. **隐私文件排除**：ICC (.icc, .icm) 和 CAL (.cal) 文件默认不导出
3. **用户可选择**：通过 `include_private` 参数可选择是否包含隐私敏感文件

---

## 3. 验证命令和结果

### 编译验证

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"
python3 -m py_compile src/diagnostics/__init__.py src/diagnostics/logger.py src/diagnostics/diagnostics.py src/backend.py tests/test_diagnostics/__init__.py tests/test_diagnostics/test_logger.py tests/test_diagnostics/test_diagnostics.py
```

**结果**: 所有文件编译成功，无错误。

### 测试验证

```bash
cd "/Users/heng/Documents/vscode/Topos Calibrator"
python3 -m pytest tests/test_diagnostics/test_logger.py tests/test_diagnostics/test_diagnostics.py -v
```

**结果**:
```
=================================== 67 passed in 0.22s ====================================
```

### 测试覆盖

**Logger 测试 (29 个)**:
- SessionLogger: 单例、初始化、日志目录、会话创建/关闭
- PathSanitization: /Users/、/home/、Windows 路径、字典脱敏
- GlobalFunctions: get_logger、init_session_logger、close_session_logger、set_log_level
- LogAdapter: 创建、各级别方法、异常记录
- LogLevels: 级别映射、无效级别处理
- ConcurrentSessions: 多会话、线程安全

**Diagnostics 测试 (38 个)**:
- EnvironmentInfo: 自动填充、时间戳、路径脱敏
- ExceptionRecord: 创建、转换
- DiagnosticsPack: 创建、环境信息、异常记录、转换
- DiagnosticsCollector: 创建、环境收集、Argyll 检测、异常记录
- ExportDiagnosticsPack: ZIP 创建、manifest、选项、会话目录、隐私排除
- PathSanitizationInFile: JSON/文本文件脱敏、二进制复制
- ExportOptions: 获取、描述、创建收集器
- PrivateExtensions: 集合验证

---

## 4. 风险和未完成项

### 已修复的 Bug

1. **`DiagnosticsCollector._sanitize_path` 缺失**：类中调用了该方法但未定义，已添加实现。
2. **Manifest 写入顺序错误**：manifest 在 `_collect_session_files` 之前写入，导致 `included_files` 不包含 session 文件，已修复。

### 风险

1. **前端集成未完成**：`web/js/main.js` 需添加诊断包导出 UI（按钮、选项选择、下载）。
2. **ArgyllCMS 检测可能失败**：在没有安装 ArgyllCMS 的环境中，`_detect_argyll()` 会返回空字符串，这不影响诊断包导出，但环境信息会不完整。
3. **日志目录默认位置**：当前默认使用 `measurements/logs` 目录，可能需要用户配置。

### 未完成项

1. **前端 UI 集成**：需要添加诊断包导出的前端界面。
2. **诊断包下载 API**：需要 Web 端提供文件下载接口。
3. **日志级别配置持久化**：`set_log_level` 当前仅影响运行时，未持久化到配置文件。

---

## 5. 解锁的后续任务

| 任务 | 依赖 | 说明 |
|------|------|------|
| **P6-A 前端工作流集成** | P7-B | 需添加诊断包导出 UI |
| **P7-C 跨平台打包** | P7-B | 诊断包功能需要包含在打包后的应用中 |
| **P7-D 安全与权限模型** | P7-B | 诊断包导出时需要检查权限状态 |

---

## 6. 接口使用示例

### 在 Backend 中使用日志

```python
from src.diagnostics import get_logger, init_session_logger, get_session_logger

# 初始化会话日志
session_id = init_session_logger()

# 获取当前会话日志器
logger = get_session_logger()
logger.info("测量开始")
logger.warning("探头连接不稳定")
logger.error("测量失败")

# 获取命名日志器（用于模块）
module_logger = get_logger("argyll")
module_logger.debug("Argyll 命令: dispwin -v")
```

### 导出诊断包

```python
from src.diagnostics import export_diagnostics_pack, get_export_options

# 查看可用选项
options = get_export_options()
# {"logs": "Session logs", "environment": "Environment info", ...}

# 导出诊断包（不含隐私文件）
zip_path = export_diagnostics_pack(
    session_id="20260519-103000",
    output_path=Path("/path/to/diagnostics.zip"),
    options={"logs", "environment", "argyll_output"},
    include_private=False
)

# 导出诊断包（含隐私文件）
zip_path = export_diagnostics_pack(
    session_id="20260519-103000",
    include_private=True
)
```

### 记录异常

```python
from src.diagnostics import DiagnosticsCollector

collector = DiagnosticsCollector()

try:
    # 某些操作
    pass
except Exception as e:
    collector.record_exception(e, {"operation": "measurement", "patch": "white"})
```

---

## 7. 文件结构

```
src/diagnostics/
├── __init__.py          # 模块入口
├── logger.py            # 日志模块
│   ├── SessionLogger    # 会话级日志管理器（单例）
│   ├── LogSession       # 会话日志信息
│   ├── LogAdapter       # 日志适配器
│   └── 全局函数          # get_logger, init_session_logger, etc.
└── diagnostics.py       # 诊断包模块
    ├── EnvironmentInfo  # 环境信息
    ├── ExceptionRecord  # 异常记录
    ├── DiagnosticsPack  # 诊断包结构
    ├── DiagnosticsCollector  # 收集器
    └── export_diagnostics_pack  # 导出函数

tests/test_diagnostics/
├── __init__.py          # 测试模块入口
├── test_logger.py       # Logger 测试 (29 个)
└── test_diagnostics.py  # Diagnostics 测试 (38 个)
```

---

**报告完成时间**: 2026-05-19
**下一步**: 等待评审，可解锁 P6-A/P7-C/P7-D 任务