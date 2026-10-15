"""通用流形对齐与表格映射测试工具 (Generic Geodesic Alignment Test Runner).

使用说明:
    1. 默认运行第11个范例 (11_real_estate_chart):
       python test/dirty_data_tests/run_generic_align_test.py

    2. 运行指定编号的内置基准用例 (01 到 11):
       python test/dirty_data_tests/run_generic_align_test.py --suite 11
       python test/dirty_data_tests/run_generic_align_test.py --list-suites

    3. 传入任意外部 xlsx 物理表格进行端到端对齐测试:
       python test/dirty_data_tests/run_generic_align_test.py --source my_source.xlsx --template my_template.xlsx
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 确保在 Windows 控制台或管道下不发生编码崩溃
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import openpyxl
import tomllib

from geodesic_align.digit_processor import TableView
from geodesic_align.example_workflow import align_sample, load_header_rows, render_toml
from geodesic_align.manifold_evolution import record_manifold_sediment
from test.dirty_data_tests.test_dirty_data_geodesic import DATASETS_DIR, SUITE_CONFIGS


def _pick_first_sheet(file_path: Path) -> str:
    """自动获取工作簿的第一个工作表名称。"""
    wb = openpyxl.load_workbook(file_path, read_only=True)
    try:
        names = wb.sheetnames
        return names[0] if names else "Sheet1"
    finally:
        wb.close()


def run_alignment_case(
    source_path: Path,
    template_path: Path,
    source_sheet: str | None = None,
    template_sheet: str | None = None,
    output_toml_path: Path | None = None,
    enable_sediment: bool = True,
) -> tuple[list, dict[str, float], str]:
    """
    通用对齐测试核心函数：
    加载源表与模板表 -> 测地线流形对齐 -> 渲染 TOML -> 可选流形外在曲率吸收。
    """
    if not source_path.is_file():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    if not template_path.is_file():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    src_sheet = source_sheet or _pick_first_sheet(source_path)
    tpl_sheet = template_sheet or _pick_first_sheet(template_path)

    print(f"\n[1/4] Loading tables...")
    print(f"  * Source: {source_path.name} -> Sheet: [{src_sheet}]")
    print(f"  * Template: {template_path.name} -> Sheet: [{tpl_sheet}]")

    t_start = time.perf_counter()
    src_headers, src_rows = load_header_rows(source_path, src_sheet)
    dst_headers, dst_rows = load_header_rows(template_path, tpl_sheet)
    load_ms = (time.perf_counter() - t_start) * 1000

    print(f"  * Source columns ({len(src_headers)} cols, {len(src_rows)} rows): {src_headers[:6]} ...")
    print(f"  * Dest columns ({len(dst_headers)} cols, {len(dst_rows)} rows): {dst_headers}")

    source_table = TableView(
        source_key="source1",
        physical="excel",
        headers=src_headers,
        rows=src_rows,
        sheet=src_sheet,
        header_row=1,
    )
    dest_table = TableView(
        source_key="dest",
        physical="excel",
        headers=dst_headers,
        rows=dst_rows,
        sheet=tpl_sheet,
        header_row=1,
    )

    print(f"\n[2/4] Executing geodesic alignment (align_sample)...")
    t_align_start = time.perf_counter()
    decisions, elapsed_map = align_sample([source_table], dest_table)
    align_total_ms = (time.perf_counter() - t_align_start) * 1000

    print(f"\n=== Alignment Decisions Summary (Total: {len(decisions)}) ===")
    print(f"{'Input_label':<22} | {'Role':<8} | {'Source / Formula / Regex':<42} | {'Confidence'}")
    print("-" * 88)
    for d in decisions:
        if d.cell_role == "formula":
            detail = f"Formula: {d.formula}"
        elif d.cell_role == "regex":
            detail = f"Regex: {d.regex} ({d.source}.{d.field})"
        elif d.cell_role == "data":
            detail = f"Data: {d.source}.{d.field}" + (" (ID)" if d.is_id else "")
        else:
            detail = "[Outspan / Manual Input]"
        print(f"{d.input_label:<22} | {d.cell_role:<8} | {detail:<42} | {d.confidence:.2f}")

    print(f"\n[3/4] Rendering & validating TOML configuration...")
    toml_text = render_toml(source_path, template_path, [source_table], dest_table, decisions)
    # 验证合法性
    tomllib.loads(toml_text)
    print("  [OK] TOML structural syntax verified successfully")

    if output_toml_path:
        output_toml_path.parent.mkdir(parents=True, exist_ok=True)
        output_toml_path.write_text(toml_text, encoding="utf-8")
        print(f"  [OK] TOML saved to: {output_toml_path}")

    if enable_sediment:
        print(f"\n[4/4] Grassmannian Manifold Sediment Memory...")
        sediment = record_manifold_sediment([source_table], dest_table, decisions)
        if sediment.records:
            for r in sediment.records:
                print(f"  * [Transition] Column '{r['col']}': rho={r['rho_before']:.2f} -> Tangent subspace dimension k={r['k_dim']}")
        else:
            print("  * No outspan columns; tangent subspace dimension preserved")

    print(f"\n[TIME] load={load_ms:.1f}ms | map={elapsed_map.get('map', 0):.1f}ms | text={elapsed_map.get('text', 0):.1f}ms | total={align_total_ms:.1f}ms\n")
    return decisions, elapsed_map, toml_text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generic Geodesic Alignment Test Runner (supports built-in suites 01-11 or custom Excel files)"
    )
    parser.add_argument(
        "--suite",
        type=str,
        default="11",
        help="Run built-in benchmark suite ID (01 to 11), defaults to 11 (real_estate_chart)",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Path to custom source workbook (.xlsx)",
    )
    parser.add_argument(
        "--template",
        type=str,
        default=None,
        help="Path to custom template workbook (.xlsx)",
    )
    parser.add_argument(
        "--source-sheet",
        type=str,
        default=None,
        help="Source sheet name (defaults to first sheet)",
    )
    parser.add_argument(
        "--template-sheet",
        type=str,
        default=None,
        help="Template sheet name (defaults to first sheet)",
    )
    parser.add_argument(
        "--output-toml",
        type=str,
        default=None,
        help="Optional path to save generated TOML config",
    )
    parser.add_argument(
        "--list-suites",
        action="store_true",
        help="List all built-in benchmark suites and exit",
    )

    args = parser.parse_args()

    if args.list_suites:
        print("\n=== Available Benchmark Suites ===")
        for cfg in SUITE_CONFIGS:
            print(f"[{cfg['id']}] {cfg['domain']}")
            print(f"  * Source: {cfg['src_file']} [{cfg['src_sheet']}]")
            print(f"  * Template: {cfg['tpl_file']} [{cfg['tpl_sheet']}]")
            print(f"  * Dirty pattern: {cfg['dirty_pattern']}\n")
        return

    # 1. 自定义文件模式
    if args.source and args.template:
        src = Path(args.source).resolve()
        tpl = Path(args.template).resolve()
        out = Path(args.output_toml).resolve() if args.output_toml else None
        run_alignment_case(src, tpl, args.source_sheet, args.template_sheet, out)
        return

    # 2. 内置套件模式
    target_id = args.suite.strip()
    match = None
    for cfg in SUITE_CONFIGS:
        if cfg["id"] == target_id or cfg["id"].startswith(target_id) or target_id in cfg["id"]:
            match = cfg
            break

    if not match:
        print(f"Error: suite ID '{target_id}' not found. Use --list-suites to view available options.")
        sys.exit(1)

    print(f"\n=== Running Suite: [{match['id']}] {match['domain']} ===")
    print(f"Dirty pattern: {match['dirty_pattern']}")

    src = DATASETS_DIR / match["src_file"]
    tpl = DATASETS_DIR / match["tpl_file"]
    out = Path(args.output_toml).resolve() if args.output_toml else None
    run_alignment_case(src, tpl, match["src_sheet"], match["tpl_sheet"], out)


if __name__ == "__main__":
    main()
