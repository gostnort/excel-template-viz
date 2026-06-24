"""外部数据源与 Input_sheet 读写（路径 B）。见 docs/data_flow_design.md。"""

from __future__ import annotations

import argparse
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries

from .core_toml import GetTomlValues, TomlDefault


logger = logging.getLogger(__name__)


def _normalize_id(value: Any) -> int:
    """
    函数名: _normalize_id
    作用: 将 ID 规范为整数主键
    输入:
        value (Any) - 原始 ID
    输出:
        int - 整数主键
    """
    if isinstance(value, bool):
        raise ValueError("ID cannot be boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        raise ValueError("ID cannot be empty")
    if "." in text:
        return int(float(text))
    return int(text)


def _cell_empty(value: Any) -> bool:
    """单元格无有效文本内容时视为空。"""
    return value is None or str(value).strip() == ""


def _column_names_for_rule(rule: TomlDefault) -> list[str]:
    """数据源列查找顺序：先 field 再 Input_label。"""
    names: list[str] = []
    if rule.field:
        names.append(rule.field)
    if rule.Input_label not in names:
        names.append(rule.Input_label)
    return names


def _lookup_row_value(row: dict[str, Any], rule: TomlDefault) -> Any:
    """在已匹配的数据源行中按 rule 取列值。"""
    for key in _column_names_for_rule(rule):
        if key in row:
            return row[key]
    return None


def _load_sheet_rows(workbook_path: Path, sheet_name: str) -> list[dict[str, Any]]:
    """
    函数名: _load_sheet_rows
    作用: 将本地 xlsx 工作表读为行字典列表（首行为表头）
    输入:
        workbook_path (Path) - xlsx 路径
        sheet_name (str) - 工作表名
    输出:
        list[dict[str, Any]] - 每行 {列标题: 值}
    """
    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        if sheet_name and sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
        else:
            ws = wb.active
        if ws is None:
            return []
        row_iter = ws.iter_rows(values_only=True)
        header_row = next(row_iter, None)
        if header_row is None:
            return []
        headers = [str(cell).strip() if cell is not None else "" for cell in header_row]
        rows: list[dict[str, Any]] = []
        # 跳过整行空行，按表头键组装 dict
        for values in row_iter:
            if all(_cell_empty(v) for v in values):
                continue
            item: dict[str, Any] = {}
            for idx, header in enumerate(headers):
                if not header or idx >= len(values):
                    continue
                item[header] = values[idx]
            rows.append(item)
        return rows
    finally:
        wb.close()


def _find_row_by_id(rows: list[dict[str, Any]], id_column: str, id_value: Any) -> dict[str, Any] | None:
    """
    函数名: _find_row_by_id
    作用: 在数据源行列表中按 ID 列匹配一行
    输入:
        rows - 表数据
        id_column (str) - ID 列名（通常为 field=ID）
        id_value (Any) - 待查 ID
    输出:
        dict | None - 匹配行或 None
    """
    target = str(id_value).strip()
    for row in rows:
        if id_column not in row:
            continue
        cell = row[id_column]
        if cell is None:
            continue
        if str(cell).strip() == target:
            return row
        # Excel 数字 ID 可能与字符串形式比较
        try:
            if str(int(float(cell))) == target:
                return row
        except (ValueError, TypeError):
            pass
    return None




class Template2DB:
    """按 source_file / source_sheet / Input_label 读外部表并生成标准记录。"""

    def __init__(self, cfg: GetTomlValues) -> None:
        self.cfg = cfg


    def resolve_source_path(self, source_key: str) -> Path | None:
        """
        函数名: resolve_source_path
        作用: 将 [[sources]] 中的别名解析为磁盘路径
        输入:
            source_key (str) - 如 source1
        输出:
            Path | None - 路径未配置或为空时返回 None
        """
        if not source_key:
            return None
        for item in self.cfg.sources:
            if source_key not in item:
                continue
            raw = item[source_key]
            if raw is None or str(raw).strip() == "":
                return None
            return Path(str(raw))
        return None


    def apply_regex(self, value: Any, pattern: str | None) -> Any:
        """
        函数名: apply_regex
        作用: 对单元格值做正则提取；有捕获组取 group(1)
        输入:
            value (Any) - 原始值
            pattern (str | None) - TOML regex
        输出:
            Any - 提取结果或原值
        """
        if pattern is None or str(pattern).strip() == "":
            return value
        if value is None:
            return value
        text = str(value)
        match = re.search(pattern, text)
        if not match:
            return value
        if match.lastindex:
            return match.group(1)
        return match.group(0)


    def generate_auto_id(self) -> int:
        """无 id=true 字段时生成整数主键。"""
        return uuid.uuid4().int >> 64


    def _id_column_name(self) -> str | None:
        """优先取 id=true 且已映射 field 的列名作为查行键。"""
        for rule in self.cfg.field_rules:
            if rule.id and rule.field:
                return rule.field
        for rule in self.cfg.field_rules:
            if rule.id:
                return rule.Input_label
        return None


    def fetch_row_by_id(self, id_value: Any) -> dict[str, Any]:
        """
        函数名: fetch_row_by_id
        作用: 路径 B：按 ID 从各 source_sheet 取列并合并为一条记录
        输入:
            id_value (Any) - 用户指定或 textbox 中的 ID
        输出:
            dict[str, Any] - 标准记录（含 id、field、Input_label）
        """
        record: dict[str, Any] = {}
        id_column = self._id_column_name()
        has_id = False
        sheet_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        # 每个 rule 可能指向不同 source_file / source_sheet
        for rule in self.cfg.field_rules:
            if not rule.source_file or not rule.source_sheet:
                continue
            source_path = self.resolve_source_path(rule.source_file)
            if source_path is None or not source_path.is_file():
                logger.warning("source path missing for %s", rule.source_file)
                continue
            cache_key = (str(source_path), rule.source_sheet)
            if cache_key not in sheet_cache:
                sheet_cache[cache_key] = _load_sheet_rows(source_path, rule.source_sheet)
            rows = sheet_cache[cache_key]
            lookup_col = id_column or "ID"
            matched = _find_row_by_id(rows, lookup_col, id_value)
            if matched is None:
                continue
            raw_value = _lookup_row_value(matched, rule)
            mapped = self.apply_regex(raw_value, rule.regex)
            if rule.field:
                record[rule.field] = mapped
            record[rule.Input_label] = mapped
            if rule.id:
                record["id"] = _normalize_id(mapped)
                has_id = True
        # 数据源未标 id 时沿用入参或自动生成
        if not has_id:
            if id_value is not None and str(id_value).strip() != "":
                record["id"] = _normalize_id(id_value)
            else:
                record["id"] = self.generate_auto_id()
        return record




class ExcelWriter:
    """Input_sheet 写回、区域检测、打印区域读取；列定位用 Input_label 不用 index。"""

    def __init__(self, cfg: GetTomlValues) -> None:
        self.cfg = cfg


    def _worksheet_name(self, workbook_path: Path) -> str:
        """解析 cfg.worksheet 或回退 active sheet。"""
        wb = load_workbook(workbook_path, read_only=True)
        try:
            if self.cfg.worksheet and self.cfg.worksheet in wb.sheetnames:
                return self.cfg.worksheet
            return wb.active.title
        finally:
            wb.close()


    def _parse_area_range(self, area_str: str) -> tuple[int, int, int, int]:
        """解析 A1 区域为 (min_row, min_col, max_row, max_col)。"""
        min_col, min_row, max_col, max_row = range_boundaries(area_str)
        return min_row, min_col, max_row, max_col


    def _calculate_next_area(self, input_area: str, move_to: str, offset: int) -> str:
        """
        函数名: _calculate_next_area
        作用: 按 sections.move_to / offset 计算下一 input_area
        输入:
            input_area (str) - 当前区域如 A2:G2
            move_to (str) - down/up/left/right
            offset (int) - 偏移量
        输出:
            str - 下一区域字符串
        """
        min_row, min_col, max_row, max_col = self._parse_area_range(input_area)
        row_span = max_row - min_row
        col_span = max_col - min_col
        direction = move_to.strip().lower()
        if direction == "down":
            min_row += offset
            max_row = min_row + row_span
        elif direction == "up":
            min_row -= offset
            max_row = min_row + row_span
        elif direction == "right":
            min_col += offset
            max_col = min_col + col_span
        elif direction == "left":
            min_col -= offset
            max_col = min_col + col_span
        else:
            raise ValueError(f"unsupported move_to: {move_to}")
        return f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}"


    def _area_filled_positions(
        self,
        ws: Any,
        min_row: int,
        min_col: int,
        max_row: int,
        max_col: int,
    ) -> frozenset[tuple[int, int]]:
        """返回区域内非空单元格的相对坐标集合，用于多区域停止判断。"""
        filled: set[tuple[int, int]] = set()
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                if not _cell_empty(ws.cell(row=row, column=col).value):
                    filled.add((row - min_row, col - min_col))
        return frozenset(filled)


    def _area_is_empty(
        self,
        ws: Any,
        min_row: int,
        min_col: int,
        max_row: int,
        max_col: int,
    ) -> bool:
        """区域内无任何非空单元格。"""
        return len(self._area_filled_positions(ws, min_row, min_col, max_row, max_col)) == 0


    def detect_areas(self, excel_path: Path) -> list[dict[str, Any]]:
        """
        函数名: detect_areas
        作用: 从 sections[0] 起循环检测重复 input_area
        输入:
            excel_path (Path) - 模板 xlsx
        输出:
            list[dict] - 各区域 index、area、起止行列
        """
        if not self.cfg.sections:
            return []
        section = self.cfg.sections[0]
        input_area = str(section.get("input_area", "")).strip()
        if not input_area:
            return []
        move_to = str(section.get("move_to", "down"))
        offset_raw = section.get("offset", 1)
        offset = int(offset_raw)
        sheet_name = self._worksheet_name(excel_path)
        wb = load_workbook(excel_path, read_only=True, data_only=True)
        try:
            ws = wb[sheet_name]
            areas: list[dict[str, Any]] = []
            current = input_area
            reference_pattern: frozenset[tuple[int, int]] | None = None
            index = 1
            while True:
                min_row, min_col, max_row, max_col = self._parse_area_range(current)
                if min_row < 1 or min_col < 1:
                    break
                pattern = self._area_filled_positions(ws, min_row, min_col, max_row, max_col)
                if index > 1:
                    # 停止：全空或与首区域填充模式不一致
                    if self._area_is_empty(ws, min_row, min_col, max_row, max_col):
                        break
                    if reference_pattern is not None and pattern != reference_pattern:
                        break
                areas.append(
                    {
                        "index": index,
                        "area": current,
                        "start_row": min_row,
                        "start_col": min_col,
                        "end_row": max_row,
                        "end_col": max_col,
                    }
                )
                if reference_pattern is None and pattern:
                    reference_pattern = pattern
                current = self._calculate_next_area(current, move_to, offset)
                index += 1
                next_min_row, next_min_col, _, _ = self._parse_area_range(current)
                if next_min_row < 1 or next_min_col < 1 or next_min_row > ws.max_row:
                    break
            return areas
        finally:
            wb.close()


    def _header_map(self, ws: Any, header_row: int, min_col: int, max_col: int) -> dict[str, int]:
        """表头行 Input_label → 列号（1-based）。"""
        mapping: dict[str, int] = {}
        for col in range(min_col, max_col + 1):
            value = ws.cell(row=header_row, column=col).value
            if _cell_empty(value):
                continue
            mapping[str(value).strip()] = col
        return mapping


    def read_area_rows(self, excel_path: Path, area: str) -> list[dict[str, Any]]:
        """
        函数名: read_area_rows
        作用: 读取区域内数据行，键为表头 Input_label
        输入:
            excel_path (Path) - xlsx
            area (str) - 如 A2:G2
        输出:
            list[dict[str, Any]] - 行列表
        """
        min_row, min_col, max_row, max_col = self._parse_area_range(area)
        header_row = min_row - 1 if min_row > 1 else min_row
        sheet_name = self._worksheet_name(excel_path)
        wb = load_workbook(excel_path, read_only=True, data_only=True)
        try:
            ws = wb[sheet_name]
            headers = self._header_map(ws, header_row, min_col, max_col)
            rows: list[dict[str, Any]] = []
            for row_idx in range(min_row, max_row + 1):
                if self._area_is_empty(ws, row_idx, min_col, row_idx, max_col):
                    continue
                row_dict: dict[str, Any] = {}
                for label, col_idx in headers.items():
                    row_dict[label] = ws.cell(row=row_idx, column=col_idx).value
                rows.append(row_dict)
            return rows
        finally:
            wb.close()


    def _record_value_for_label(self, record: dict[str, Any], label: str, rule: TomlDefault | None) -> Any:
        """写回时优先 record[Input_label]，其次 record[field]。"""
        if label in record:
            return record[label]
        if rule and rule.field and rule.field in record:
            return record[rule.field]
        return None


    def write_back(
        self,
        excel_path: Path,
        output_path: Path,
        records: list[dict[str, Any]] | dict[str, Any],
        areas: list[str] | None = None,
    ) -> None:
        """
        函数名: write_back
        作用: 按 Input_label 对表头列写回纯值并另存
        输入:
            excel_path (Path) - 源模板
            output_path (Path) - 输出路径
            records - 单条或多条记录
            areas (list[str] | None) - 未传则 detect_areas
        输出: 无
        """
        if isinstance(records, dict):
            record_list = [records]
        else:
            record_list = records
        if areas is None:
            detected = self.detect_areas(excel_path)
            areas = [item["area"] for item in detected]
        if not areas:
            # 无检测结果时回退 sections[0].input_area
            if self.cfg.sections:
                first_area = str(self.cfg.sections[0].get("input_area", "")).strip()
                if first_area:
                    areas = [first_area]
            if not areas:
                raise ValueError("no input areas configured")
        label_to_rule = {rule.Input_label: rule for rule in self.cfg.field_rules}
        sheet_name = self._worksheet_name(excel_path)
        wb = load_workbook(excel_path)
        try:
            ws = wb[sheet_name]
            # 每个 area 对应一条 record，按表头列号写入
            for area, record in zip(areas, record_list):
                min_row, min_col, max_row, max_col = self._parse_area_range(area)
                header_row = min_row - 1 if min_row > 1 else min_row
                headers = self._header_map(ws, header_row, min_col, max_col)
                data_row = min_row if max_row >= min_row else min_row
                for label, col_idx in headers.items():
                    rule = label_to_rule.get(label)
                    # index=-1 且无 field 的列仅展示，默认不写回
                    if rule is not None and rule.index < 0 and not rule.field:
                        continue
                    value = self._record_value_for_label(record, label, rule)
                    if value is None:
                        continue
                    ws.cell(row=data_row, column=col_idx).value = value
            output_path.parent.mkdir(parents=True, exist_ok=True)
            wb.save(output_path)
        finally:
            wb.close()


    def get_print_areas(self, excel_path: Path) -> dict[str, str | None]:
        """
        函数名: get_print_areas
        作用: 读取各 sheet 的 print_area 元数据（只读，不做打印）
        输入:
            excel_path (Path) - xlsx
        输出:
            dict[str, str | None] - 工作表名 → 区域字符串
        """
        wb = load_workbook(excel_path, read_only=True)
        try:
            result: dict[str, str | None] = {}
            for name in wb.sheetnames:
                raw = wb[name].print_area
                if raw is None:
                    result[name] = None
                else:
                    text = str(raw)
                    # 去掉工作表前缀与 $ 绝对引用
                    if "!" in text:
                        text = text.split("!", 1)[1]
                    result[name] = text.replace("$", "")
            return result
        finally:
            wb.close()




def _demo_main() -> None:
    """
    函数名: _demo_main
    作用: 蓝本 Phase 6：用 docs 样本做全量三段验证（路径 A/B + ExcelWriter）
    输入: 无（可选 argparse 覆盖默认样本路径）
    输出: 无（stdout）
    """
    # 模块级不 import core_store，避免与蓝本依赖方向冲突；仅 __main__ 串联
    import tomlkit
    from .core_registry import PROJECT_ROOT
    from .core_store import SecureSQLite, UiProvider, default_db_path
    from .core_toml import _config_from_dict
    docs_dir = PROJECT_ROOT / "docs"
    default_toml = docs_dir / "sample_template.toml"
    default_excel = docs_dir / "sample_template.xlsx"
    default_source_xlsx = docs_dir / "执法堂业绩.xlsx"
    default_template_id = "sample_template"
    default_source_id = "8129"
    default_second_id = "250"
    default_textbox = (
        "8129\tClark Kent\t"
        "recreate himself without changing his dob on records on 1978/02/29"
    )
    parser = argparse.ArgumentParser(description="Data Sheet Core sample verification")
    parser.add_argument("--template-id", default=default_template_id, help="DB basename / template id")
    parser.add_argument("--toml", type=Path, default=default_toml, help="TOML config path")
    parser.add_argument("--excel", type=Path, default=default_excel, help="Input_sheet template xlsx")
    parser.add_argument("--textbox", type=str, default=default_textbox, help="path A: tab-separated string")
    parser.add_argument("--source-id", type=str, default=default_source_id, help="path B: external row ID")
    parser.add_argument("--output", type=Path, default=None, help="write-back xlsx; default exports/{template_id}/sample_template_demo_out.xlsx")
    args = parser.parse_args()
    toml_path = Path(args.toml)
    excel_path = Path(args.excel)
    out_path = args.output or (PROJECT_ROOT / "exports" / args.template_id / "sample_template_demo_out.xlsx")
    if not toml_path.is_file():
        raise SystemExit(f"TOML not found: {toml_path}")
    if not excel_path.is_file():
        raise SystemExit(f"template xlsx not found: {excel_path}")
    try:
        raw = tomlkit.loads(toml_path.read_text(encoding="utf-8"))
    except tomlkit.exceptions.ParseError as exc:
        raise SystemExit(f"TOML parse error in {toml_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"TOML root must be a table: {toml_path}")
    cfg = _config_from_dict(raw)
    if cfg is None:
        raise SystemExit(f"TOML has no valid field rules: {toml_path}")
    # TOML 里可能是本机绝对路径；样本库回退到 docs/执法堂业绩.xlsx
    for item in cfg.sources:
        for key, value in item.items():
            if value is None or str(value).strip() == "":
                continue
            candidate = Path(str(value))
            if not candidate.is_file() and default_source_xlsx.is_file():
                item[key] = str(default_source_xlsx)
    db = SecureSQLite(default_db_path(args.template_id))
    ui = UiProvider(cfg, db)
    t2db = Template2DB(cfg)
    writer = ExcelWriter(cfg)
    read_payload: dict[str, Any] = {
        "toml": str(toml_path),
        "excel": str(excel_path),
        "source_xlsx": str(t2db.resolve_source_path("source1") or ""),
    }
    try:
        # 路径 A：textbox 拆分（仅 section 1 展示；落库由下方 incoming 一次覆盖）
        read_payload["textbox_raw"] = args.textbox
        read_payload["textbox_split"] = ui.split_by_determiner(args.textbox)
        read_payload["textbox_incoming"] = ui.record_from_textbox(args.textbox)
        areas = writer.detect_areas(excel_path)
        read_payload["excel_areas"] = areas
        read_payload["excel_rows"] = [
            writer.read_area_rows(excel_path, item["area"]) for item in areas
        ]
        try:
            read_payload["print_areas"] = writer.get_print_areas(excel_path)
        except AttributeError as exc:
            read_payload["print_areas_error"] = str(exc)
        # 路径 B + Excel 行：拼成 incoming 后各写一次（TOML 覆盖，非 store merge）
        source_primary = t2db.fetch_row_by_id(args.source_id)
        read_payload["source_incoming_primary"] = source_primary
        excel_row_primary = read_payload["excel_rows"][0][0] if read_payload["excel_rows"] and read_payload["excel_rows"][0] else {}
        incoming_primary = {**source_primary, **excel_row_primary}
        read_payload["persist_incoming_primary"] = incoming_primary
        ui.persist_fields(incoming_primary)
        write_records: list[dict[str, Any]] = []
        row_primary = db.query_by_id(int(incoming_primary.get("ID#", args.source_id)))
        if row_primary is not None:
            write_records.append(row_primary)
        if len(areas) > 1:
            source_second = t2db.fetch_row_by_id(default_second_id)
            read_payload["source_incoming_second"] = source_second
            excel_row_second = read_payload["excel_rows"][1][0] if read_payload["excel_rows"][1] else {}
            incoming_second = {**source_second, **excel_row_second}
            read_payload["persist_incoming_second"] = incoming_second
            ui.persist_fields(incoming_second)
            row_second = db.query_by_id(int(incoming_second.get("ID#", default_second_id)))
            if row_second is not None:
                write_records.append(row_second)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        writer.write_back(excel_path, out_path, write_records)
        read_payload["output_excel"] = str(out_path)
        print("=== 1. 从 Excel / 数据源读取的数据 ===")
        print(json.dumps(read_payload, ensure_ascii=False, indent=2, default=str))
        print("=== 2. 写入 DB 后的数据 ===")
        print(json.dumps(db.query_all(), ensure_ascii=False, indent=2, default=str))
        print("=== 3. Gradio 可获得的数据 ===")
        print("labels:", json.dumps(ui.get_labels(), ensure_ascii=False))
        print("data:", json.dumps(ui.get_data(), ensure_ascii=False, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _demo_main()
