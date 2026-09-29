"""测试数据对比窗口能否正确加载历史数据"""
import json
from pathlib import Path

# 模拟后端逻辑
measurements_dir = Path("/Users/heng/Documents/vscode/Topos Calibrator/measurements")
auto_save_path = measurements_dir / "auto_save"

measurements = []

if auto_save_path.exists():
    for date_dir in auto_save_path.iterdir():
        if date_dir.is_dir():
            for json_file in date_dir.glob("*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    metadata = data.get("metadata", {})
                    meas_data = data.get("measurements", {})
                    
                    measurements.append({
                        "id": json_file.stem,
                        "name": metadata.get("display_name", json_file.stem),
                        "display_name": metadata.get("display_name", ""),
                        "probe": metadata.get("probe", ""),
                        "measure_mode": metadata.get("measure_mode", ""),
                        "timestamp": metadata.get("timestamp", 0),
                        "has_gamut": "gamut" in meas_data,
                        "has_gamma": "gamma" in meas_data,
                        "has_lut": "lut" in meas_data,
                        "json_path": str(json_file)
                    })
                except Exception as e:
                    print(f"读取 {json_file} 失败: {e}")

# 按时间戳排序
measurements.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

print(f"\n找到 {len(measurements)} 条记录")
print(f"\n前3条记录:")
for i, m in enumerate(measurements[:3]):
    print(f"  {i+1}. ID: {m['id']}")
    print(f"     名称: {m['display_name']}")
    print(f"     探头: {m['probe']}")
    print(f"     模式: {m['measure_mode']}")
    print(f"     时间: {m['timestamp']}")
    print()

# 模拟后端发射的信号格式
result = {"measurements": measurements}
print(f"\n信号数据长度: {len(json.dumps(result, ensure_ascii=False))}")
print(f"\n信号数据格式: {list(result.keys())}")
print(f"\n第一条记录完整数据:")
print(json.dumps(measurements[0] if measurements else {}, indent=2, ensure_ascii=False))
