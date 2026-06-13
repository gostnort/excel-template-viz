"""
Section Detector - Multi-area detection for Excel templates

Detects repeated sections in Excel templates based on YAML configuration.
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet

logger = logging.getLogger(__name__)


@dataclass
class AreaCoords:
    """Excel area coordinates"""
    start_row: int  # 1-based
    start_col: int  # 1-based
    end_row: int
    end_col: int
    
    def __str__(self) -> str:
        """Convert to Excel range string like 'A1:M2'"""
        return f"{self._col_to_letter(self.start_col)}{self.start_row}:{self._col_to_letter(self.end_col)}{self.end_row}"
    
    @staticmethod
    def _col_to_letter(col: int) -> str:
        """Convert column number to Excel letter"""
        result = ""
        while col > 0:
            col -= 1
            result = chr(65 + col % 26) + result
            col //= 26
        return result


@dataclass
class SectionConfig:
    """Section configuration from YAML"""
    input_area: str  # e.g., "A1:M2"
    move_to: str     # "down" | "up" | "left" | "right"
    offset: int      # number of rows/columns to move


@dataclass
class DetectedArea:
    """A detected area instance"""
    index: int  # 1-based area index
    area: str   # Excel range string
    coords: AreaCoords
    has_data: bool  # Whether area has non-formula content


def parse_area_range(area_str: str) -> AreaCoords:
    """
    Parse Excel area string to coordinates
    
    Args:
        area_str: Excel range like "A1:M2"
    
    Returns:
        AreaCoords with 1-based row/column indices
    
    Examples:
        "A1:M2" -> (1, 1, 2, 13)
        "B5:E10" -> (5, 2, 10, 5)
    """
    # Pattern: "A1:M2"
    pattern = r'^([A-Z]+)(\d+):([A-Z]+)(\d+)$'
    match = re.match(pattern, area_str.strip().upper())
    
    if not match:
        raise ValueError(f"Invalid Excel range format: {area_str}")
    
    start_col_letter, start_row_str, end_col_letter, end_row_str = match.groups()
    
    start_row = int(start_row_str)
    end_row = int(end_row_str)
    start_col = _letter_to_col(start_col_letter)
    end_col = _letter_to_col(end_col_letter)
    
    if start_row > end_row or start_col > end_col:
        raise ValueError(f"Invalid range: start must be before end: {area_str}")
    
    return AreaCoords(start_row, start_col, end_row, end_col)


def _letter_to_col(letter: str) -> int:
    """Convert Excel column letter to number (1-based)"""
    col = 0
    for char in letter:
        col = col * 26 + (ord(char) - 64)
    return col


def calculate_next_area(
    input_area: str,
    move_to: str,
    offset: int
) -> str:
    """
    Calculate next area coordinates
    
    Args:
        input_area: Current area e.g., "A1:M2"
        move_to: Direction ("down", "up", "left", "right")
        offset: Offset amount (rows or columns)
    
    Returns:
        Next area string
    
    Examples:
        ("A1:M2", "down", 2) -> "A3:M4"
        ("A1:M2", "right", 3) -> "D1:P2"
    """
    coords = parse_area_range(input_area)
    
    if move_to == "down":
        coords.start_row += offset
        coords.end_row += offset
    elif move_to == "up":
        coords.start_row -= offset
        coords.end_row -= offset
    elif move_to == "right":
        coords.start_col += offset
        coords.end_col += offset
    elif move_to == "left":
        coords.start_col -= offset
        coords.end_col -= offset
    else:
        raise ValueError(f"Invalid move_to direction: {move_to}")
    
    # Validate bounds
    if coords.start_row < 1 or coords.start_col < 1:
        raise ValueError(f"Area moved out of bounds: {coords}")
    
    return str(coords)


def is_cell_empty_content(cell: Cell) -> bool:
    """
    Check if cell is empty content
    
    Rules:
    - cell.value is None -> empty
    - cell.value is empty string -> empty
    - cell.data_type == 'f' (formula) -> empty
    - border, fill, font do not count as content
    
    Args:
        cell: openpyxl Cell object
    
    Returns:
        True if empty, False if has content
    """
    if cell is None:
        return True
    
    # Formula cells are considered empty
    if cell.data_type == 'f':
        return True
    
    # Check value
    value = cell.value
    if value is None:
        return True
    
    if isinstance(value, str) and not value.strip():
        return True
    
    # Has actual content
    return False


def _read_area_content(ws: Worksheet, coords: AreaCoords) -> list[list[Any]]:
    """Read cell values from area (excluding formulas)"""
    content = []
    
    for row_idx in range(coords.start_row, coords.end_row + 1):
        row_values = []
        for col_idx in range(coords.start_col, coords.end_col + 1):
            cell = ws.cell(row_idx, col_idx)
            
            # Skip formula cells (count as empty)
            if cell.data_type == 'f':
                row_values.append(None)
            else:
                row_values.append(cell.value)
        
        content.append(row_values)
    
    return content


def _is_area_completely_empty(ws: Worksheet, coords: AreaCoords) -> bool:
    """
    Check if area is completely empty
    
    Empty means: no non-formula values
    (border, color, formula, text_format don't count as content)
    """
    for row_idx in range(coords.start_row, coords.end_row + 1):
        for col_idx in range(coords.start_col, coords.end_col + 1):
            cell = ws.cell(row_idx, col_idx)
            if not is_cell_empty_content(cell):
                return False
    
    return True


def _areas_have_same_format(
    ws: Worksheet,
    area1_coords: AreaCoords,
    area2_coords: AreaCoords
) -> bool:
    """
    Check if two areas have the same format/structure
    
    Compare non-formula content positions (not values, just where content exists)
    """
    content1 = _read_area_content(ws, area1_coords)
    content2 = _read_area_content(ws, area2_coords)
    
    # Must have same dimensions
    if len(content1) != len(content2):
        return False
    
    # Check if empty/non-empty pattern matches
    for row1, row2 in zip(content1, content2):
        if len(row1) != len(row2):
            return False
        
        for val1, val2 in zip(row1, row2):
            is_empty1 = val1 is None or (isinstance(val1, str) and not val1.strip())
            is_empty2 = val2 is None or (isinstance(val2, str) and not val2.strip())
            
            # Pattern mismatch: one empty, one not
            if is_empty1 != is_empty2:
                return False
    
    return True


def detect_multi_areas(
    workbook_path: Path,
    sheet_name: str,
    section_config: SectionConfig
) -> list[DetectedArea]:
    """
    Detect multiple repeated areas in Excel sheet
    
    Args:
        workbook_path: Path to Excel file
        sheet_name: Worksheet name
        section_config: Section configuration from YAML
    
    Returns:
        List of detected areas
    
    Algorithm:
    1. Parse first area coordinates
    2. Read first area content as reference format
    3. Loop:
       a. Calculate next area coordinates
       b. Check if out of bounds -> stop
       c. Read next area content
       d. Compare format consistency (exclude formulas)
       e. Stop conditions:
          - Content format inconsistent with first area
          - Completely empty (no non-formula content)
       f. Add to results if valid
    4. Return all detected areas
    """
    logger.info(f"Detecting areas in {sheet_name} with config: {section_config}")
    
    wb = openpyxl.load_workbook(workbook_path, data_only=False)
    
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"Sheet '{sheet_name}' not found. Available: {wb.sheetnames}")
    
    ws = wb[sheet_name]
    
    # Parse first area
    first_coords = parse_area_range(section_config.input_area)
    
    detected_areas = []
    current_area_str = section_config.input_area
    area_index = 1
    
    # Add first area
    has_data = not _is_area_completely_empty(ws, first_coords)
    detected_areas.append(DetectedArea(
        index=area_index,
        area=current_area_str,
        coords=first_coords,
        has_data=has_data
    ))
    
    logger.info(f"First area: {current_area_str}, has_data: {has_data}")
    
    # Detect subsequent areas
    while True:
        try:
            # Calculate next area
            next_area_str = calculate_next_area(
                current_area_str,
                section_config.move_to,
                section_config.offset
            )
            next_coords = parse_area_range(next_area_str)
            
            # Check if out of sheet bounds
            if next_coords.end_row > ws.max_row or next_coords.end_col > ws.max_column:
                logger.info(f"Area {next_area_str} exceeds sheet bounds, stopping")
                break
            
            # Check if completely empty
            if _is_area_completely_empty(ws, next_coords):
                logger.info(f"Area {next_area_str} is completely empty, stopping")
                break
            
            # Check format consistency with first area
            if not _areas_have_same_format(ws, first_coords, next_coords):
                logger.info(f"Area {next_area_str} has different format, stopping")
                break
            
            # Valid area found
            area_index += 1
            has_data = not _is_area_completely_empty(ws, next_coords)
            detected_areas.append(DetectedArea(
                index=area_index,
                area=next_area_str,
                coords=next_coords,
                has_data=has_data
            ))
            
            logger.info(f"Detected area {area_index}: {next_area_str}, has_data: {has_data}")
            
            current_area_str = next_area_str
            
        except (ValueError, Exception) as e:
            logger.warning(f"Stopped detection: {e}")
            break
    
    wb.close()
    
    logger.info(f"Total detected areas: {len(detected_areas)}")
    return detected_areas


def parse_sections_from_yaml(yaml_dict: dict[str, Any]) -> list[SectionConfig] | None:
    """
    Parse sections configuration from YAML
    
    Args:
        yaml_dict: Loaded YAML dictionary
    
    Returns:
        List of SectionConfig objects, or None if no sections defined
    """
    sections_data = yaml_dict.get("sections")
    
    if not sections_data:
        return None
    
    if not isinstance(sections_data, list):
        raise ValueError("sections must be a list")
    
    sections = []
    for section_dict in sections_data:
        if not isinstance(section_dict, dict):
            continue
        
        input_area = section_dict.get("input_area")
        move_to = section_dict.get("move_to")
        offset = section_dict.get("offset")
        
        if not all([input_area, move_to, offset is not None]):
            logger.warning(f"Incomplete section config: {section_dict}")
            continue
        
        sections.append(SectionConfig(
            input_area=str(input_area),
            move_to=str(move_to).lower(),
            offset=int(offset)
        ))
    
    return sections if sections else None
