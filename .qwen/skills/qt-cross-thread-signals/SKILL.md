---
name: qt-cross-thread-signals
description: Qt 跨线程信号发射的正确方式（子线程向主线程/QWebChannel 发送信号）
source: auto-skill
extracted_at: '2026-06-03T14:44:30.605Z'
---

# Qt 跨线程信号发射

## 问题现象

当在 Python 后台线程中通过 `QTimer.singleShot` 发射 PyQt 信号时，信号无法正确传递到前端（尤其是 QWebChannel）。前端 UI 显示"进行中"状态但永远不收到完成信号。

## 原因分析

1. **`QTimer.singleShot` 在子线程无效**：子线程没有 Qt 事件循环，`QTimer.singleShot(0, callback)` 无法触发回调
2. **信号发射后 QWebChannel 未接收**：即使使用 `QMetaObject.invokeMethod`，QWebChannel 可能无法正确处理

## 正确做法

直接从子线程调用回调函数，在回调中发射 `pyqtSignal`。Qt 的 `pyqtSignal` 会自动处理跨线程通信（使用队列连接 QueuedConnection），确保信号在主线程的事件循环中正确传递。

```python
# 错误做法 ❌
def run_in_thread():
    result = do_work()
    QTimer.singleShot(0, lambda: signal.emit(result))  # 不会触发！

# 正确做法 ✅
def completed_callback(result):
    signal.emit(result)  # Qt 自动跨线程处理

def run_in_thread():
    result = do_work()
    completed_callback(result)  # 直接调用
```

## 应用场景

- 后台线程执行耗时任务后需要通知前端
- `PreflightService.run_checks_async` 完成预检后通知 Backend
- 任何需要从子线程向 QWebChannel 发送信号的情况

## 相关文件

- `src/workflows/preflight_service.py` - 预检服务
- `src/backend.py` - Backend 类的信号定义

## 调试技巧

使用 `print()` 而非 `logger.info()` 来调试线程问题，因为 session logger 可能不输出到终端。