#!/usr/bin/env python3
"""
Topos Calibrator - 全自动测量驱动脚本

用户只需把探头（i1 Display Pro 等）贴在屏幕中央，运行本脚本即可完成：
  连接探头 → 仪器自校准 → 全屏色块测量 → 导出 TI3 → colprof 生成 ICC → dispwin 安装到系统

用法 (需在图形会话中运行，不能通过 SSH):
    python scripts/auto_calibrate.py                # 完整流程
    python scripts/auto_calibrate.py --grid 5       # 更密的采样网格（5^3=125 块，更慢更准）
    python scripts/auto_calibrate.py --skip-measure # 跳过测量，用现有 TI3 重新生成 ICC
    python scripts/auto_calibrate.py --quality h    # colprof 高精度模式

说明:
    - macOS 下脚本自动通过 caffeinate 阻止测量期间休眠，无需外部包裹
    - 测量期间整个屏幕会依次显示纯色色块，请勿移动探头、勿操作电脑
    - 全程约 2-5 分钟（取决于 --grid 与 --settle-ms）
    - 建议 macOS 关闭 Night Shift / True Tone，否则系统会动态改变屏幕色彩
"""

import argparse
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.argyll_controller import ArgyllController, DisplayType, ProbeType  # noqa: E402
from src.data_storage import CGATSExporter, MeasurementData  # noqa: E402
from src.patch_window import PatchWindow  # noqa: E402

LOG_PREFIX = "[auto]"


def log(msg: str):
    print(f"{LOG_PREFIX} {msg}", flush=True)


def pump(app: QApplication, seconds: float):
    """在不冻结 UI 事件循环的前提下等待指定秒数（色块窗口需要重绘事件）"""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def build_patch_list(grid_n: int, grey_percents) -> list:
    """构建测量色块列表: [(r, g, b, 名称), ...]"""
    patches = []
    seen = set()

    def add(r, g, b, name):
        if (r, g, b) not in seen:
            seen.add((r, g, b))
            patches.append((r, g, b, name))

    # 先白后黑：白块用于探头读数稳定，黑块用于黑位基准
    add(255, 255, 255, "white")
    add(0, 0, 0, "black")

    # 灰阶（gamma 曲线）
    for pct in grey_percents:
        v = round(255 * pct / 100)
        add(v, v, v, f"grey_{pct}%")

    # RGB 原色 + CMY 二次色
    add(255, 0, 0, "red")
    add(0, 255, 0, "green")
    add(0, 0, 255, "blue")
    add(0, 255, 255, "cyan")
    add(255, 0, 255, "magenta")
    add(255, 255, 0, "yellow")

    # RGB 立方体网格（采样色域空间）
    levels = [round(255 * i / (grid_n - 1)) for i in range(grid_n)]
    for r in levels:
        for g in levels:
            for b in levels:
                add(r, g, b, f"cube_{r}_{g}_{b}")

    return patches


def _ensure_caffeinate():
    """
    macOS 下用 caffeinate 包裹自身，防止约 4 分钟测量期间显示器休眠

    通过 os.execvp 原地替换进程（caffeinate -is 阻止系统睡眠与空闲休眠），
    并设置环境变量标记防止递归。
    """
    if platform.system() != "Darwin" or os.environ.get("TOPOS_IN_CAFFEINATE"):
        return
    os.environ["TOPOS_IN_CAFFEINATE"] = "1"
    os.execvp("caffeinate", ["caffeinate", "-is", sys.executable, os.path.abspath(__file__)]
              + sys.argv[1:])


def main():
    _ensure_caffeinate()
    parser = argparse.ArgumentParser(description="全自动测量 → ICC 生成 → 系统安装")
    parser.add_argument("--grid", type=int, default=4, help="RGB 立方体每维采样数 (默认 4)")
    parser.add_argument("--greys", type=str, default="10,25,40,55,70,80,90,95",
                        help="灰阶百分比列表，逗号分隔")
    parser.add_argument("--settle-ms", type=int, default=500, help="每块显示后的稳定等待 (毫秒)")
    parser.add_argument("--timeout", type=float, default=15.0, help="单块测量超时 (秒)")
    parser.add_argument("--quality", type=str, default="m", choices=["l", "m", "h", "u"],
                        help="colprof 精度 (默认 m)")
    parser.add_argument("--algo", type=str, default="s", choices=["s", "l", "x"],
                        help="colprof 算法: s=矩阵shaper(推荐) l=Lab LUT x=XYZ LUT")
    parser.add_argument("--profile-name", type=str, default=None, help="ICC Profile 描述名称")
    parser.add_argument("--skip-measure", action="store_true",
                        help="跳过测量，使用 --ti3 指定的现有文件生成 ICC")
    parser.add_argument("--ti3", type=str, default=None, help="--skip-measure 模式使用的 TI3 文件")
    parser.add_argument("--no-install", action="store_true", help="生成后不安装到系统")
    parser.add_argument("--dry-run", action="store_true", help="只显示色块清单，不连接探头")
    args = parser.parse_args()

    grey_percents = [float(x) for x in args.greys.split(",")]
    patches = build_patch_list(args.grid, grey_percents)
    log(f"共 {len(patches)} 个色块 (网格 {args.grid}^3 + 灰阶 {len(grey_percents)} + 基准块)")

    if args.dry_run:
        for p in patches:
            print("   ", p)
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = PROJECT_ROOT / "measurements" / "sessions" / f"auto_{stamp}"
    session_dir.mkdir(parents=True, exist_ok=True)
    log(f"输出目录: {session_dir}")

    # ---------- Qt 应用与全屏色块窗口 ----------
    app = QApplication.instance() or QApplication(sys.argv)
    win = PatchWindow(screen=app.screens()[0])
    win.set_color(0, 0, 0)
    win.show_fullscreen_patch()
    win.start_guardian()
    pump(app, 0.5)

    # ---------- 连接探头（--skip-measure 模式无需探头） ----------
    controller = ArgyllController()
    if not args.skip_measure:
        controller.set_probe_type(ProbeType.I1_DISPLAY_PRO)
        controller.set_display_type(DisplayType.LCD)
        controller.set_current_patch_rgb((255, 255, 255))

        results_q: queue.Queue = queue.Queue()
        # 控制器回调契约：单个 (x, y, Y) 元组参数
        controller.set_callbacks(
            on_measurement=lambda result: results_q.put(tuple(result)),
            on_error=lambda msg: log(f"⚠ 探头错误: {msg}"),
        )

        log("连接探头中（首次可能触发系统授权或驱动初始化，约 10 秒）...")
        if not controller.connect():
            log(f"❌ 连接失败: {controller.get_error_message()}")
            log("   请确认探头已插好、没有其他软件（如 Calibrite Profiler）占用设备")
            win.exit_fullscreen_patch()
            sys.exit(1)
        log(f"✓ 探头已连接: {controller.get_error_message() or 'OK'}")

    ti3_path = session_dir / "measurement.ti3"

    try:
        if not args.skip_measure:
            # i1d3 在 spotread 初始化阶段已自动完成内部校准（滤镜轮复位），
            # 无需再发校准命令（spotread 的 'k' 才是校准键，控制器 calibrate()
            # 写入的 'c' 实际是"触发一次测量"，对发光模式无意义）
            pump(app, 0.5)

            # ---------- 预热读数 ----------
            win.set_color(255, 255, 255)
            log("显示白场预热 5 秒...")
            pump(app, 5.0)

            def measure_once(rgb, name, timeout):
                """显示颜色 → 等稳定 → 触发测量 → 等结果；返回 (x, y, Y) 或 None"""
                r, g, b = rgb
                while not results_q.empty():
                    results_q.get_nowait()
                controller.set_current_patch_rgb(rgb)
                win.set_color(r, g, b)
                pump(app, args.settle_ms / 1000.0)
                if not controller.measure():
                    log(f"   ⚠ {name}: 触发测量失败")
                    return None
                deadline = time.perf_counter() + timeout
                while time.perf_counter() < deadline:
                    app.processEvents()
                    try:
                        x, y, Y = results_q.get(timeout=0.02)
                        if not (0 <= x <= 1 and 0 <= y <= 1 and x + y <= 1.05 and Y >= 0):
                            log(f"   ⚠ {name}: 读数异常 x={x} y={y} Y={Y}")
                            return None
                        return (x, y, Y)
                    except queue.Empty:
                        if not controller.is_connected():
                            log(f"   ⚠ {name}: 测量中探头断开")
                            return None
                log(f"   ⚠ {name}: 测量超时 ({timeout}s)")
                return None

            # ---------- 正式测量 ----------
            data = MeasurementData()
            data.set_probe("i1d3")
            data.set_display_type("LCD")
            data.set_measure_mode("auto_icc")

            log(f"开始测量 {len(patches)} 个色块（全程请勿移动探头）...")
            measured, failed = [], []
            t0 = time.perf_counter()
            for i, (r, g, b, name) in enumerate(patches, 1):
                result = measure_once((r, g, b), name, args.timeout)
                if result is None:
                    result = measure_once((r, g, b), name + "(重试)", args.timeout)
                if result is None:
                    failed.append(name)
                    continue
                x, y, Y = result
                data.update_lut_measurement(f"S{i}", (r, g, b), x, y, Y)
                measured.append((r, g, b, name, x, y, Y))
                pct = i * 100 // len(patches)
                print(f"\r[auto] 进度 {pct:3d}%  ({i}/{len(patches)})  "
                      f"{name}: Y={Y:7.2f} cd/m²", end="", flush=True)

                # 白/黑场对比自检：若黑场读数接近白场，说明探头没贴住色块区域
                if name == "black" and measured:
                    white = next((m for m in measured if m[3] == "white"), None)
                    if white and (Y > white[6] * 0.5 + 1):
                        log(f"\n⚠ 警告: 黑场 Y={Y:.2f} 与白场 Y={white[6]:.2f} 差异过小，"
                            f"探头可能未贴住测量区域或遮光不良")
            print()
            elapsed = time.perf_counter() - t0
            log(f"测量完成: 成功 {len(measured)} / 失败 {len(failed)}，"
                f"耗时 {elapsed:.0f} 秒 (平均 {elapsed / max(len(measured), 1):.1f}s/块)")
            if failed:
                log(f"   失败色块: {failed}")
            if len(measured) < 9:
                log("❌ 有效测量太少，无法生成可靠的 ICC，退出")
                sys.exit(1)

            # 白场读数 sanity check
            white = next((m for m in measured if m[3] == "white"), None)
            if white:
                log(f"白场: x={white[4]:.4f} y={white[5]:.4f} Y={white[6]:.2f} cd/m² "
                    f"(亮度 {white[6]:.0f} nit 级别)")

            # ---------- 导出 TI3 ----------
            if not CGATSExporter().export_ti3(data, str(ti3_path)):
                log("❌ TI3 导出失败")
                sys.exit(1)
            log(f"✓ TI3 已导出: {ti3_path}")
        else:
            if not args.ti3 or not Path(args.ti3).exists():
                log("❌ --skip-measure 需要有效的 --ti3 文件路径")
                sys.exit(1)
            ti3_path = Path(args.ti3)
            log(f"使用现有 TI3: {ti3_path}")

        # ---------- 生成 ICC ----------
        profile_name = args.profile_name or f"Topos Auto {stamp}"
        base = session_dir / "profile"
        # colprof 要求输入文件必须与输出基名同名（<base>.ti3）
        ti3_for_colprof = session_dir / "profile.ti3"
        if ti3_path.resolve() != ti3_for_colprof.resolve():
            shutil.copy(ti3_path, ti3_for_colprof)
        log(f"生成 ICC Profile ({args.algo}, 质量 {args.quality})...")
        cmd = ["colprof", "-v", f"-q{args.quality}", f"-a{args.algo}",
               "-D", profile_name, str(base)]
        log(f"   {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=str(session_dir), capture_output=True, text=True,
                              timeout=600)
        output = (proc.stdout or "") + (proc.stderr or "")
        for line in output.splitlines():
            line = line.strip()
            if line and "tcget" not in line and "tcset" not in line:
                print(f"   [colprof] {line}")
        icc_path = Path(str(base) + ".icc")
        if proc.returncode != 0 or not icc_path.exists():
            log(f"❌ colprof 失败 (exit={proc.returncode})")
            sys.exit(1)
        log(f"✓ ICC 已生成: {icc_path} ({icc_path.stat().st_size} 字节)")

        # ---------- 安装到系统 ----------
        if not args.no_install:
            log("安装 ICC 到 macOS 系统 (dispwin -I)...")
            inst = subprocess.run(["dispwin", "-I", str(icc_path)],
                                  capture_output=True, text=True, timeout=60)
            out = (inst.stdout or "") + (inst.stderr or "")
            for line in out.splitlines():
                line = line.strip()
                if line:
                    print(f"   [dispwin] {line}")
            if inst.returncode == 0:
                log("✓ ICC 已安装并设置为当前显示器配置文件")
                log("   可在 系统设置 → 显示器 → 颜色配置文件 中看到它；"
                    "或打开 ColorSync 实用工具验证")
            else:
                log(f"⚠ dispwin 安装返回码 {inst.returncode}，请手动导入: "
                    f"{icc_path} → ~/Library/ColorSync/Profiles/")
    finally:
        log("清理: 断开探头、退出全屏...")
        controller.disconnect()
        win.exit_fullscreen_patch()
        win.stop_guardian()
        win.set_color(0, 0, 0)
        pump(app, 0.3)

    log("全部完成 ✅")


if __name__ == "__main__":
    main()
