"""Shared display, formatting, and export helpers."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd


STANDARD_COLS = [
    "数据源",
    "差旅申请单号",
    "申请单据号/订单号",
    "申请人",
    "员工邮箱",
    "一级部门",
    "二级部门",
    "费用日期",
    "城市",
    "境内外",
    "场景",
    "类型",
    "币种",
    "金额",
    "住宿晚数",
    "是否敏感",
    "原始描述",
    "分类方式",
    "需人工确认",
]

CLASSIFICATION_DISPLAY = {
    "Python规则": "固定规则",
    "Python Mapping": "固定 Mapping",
    "待语义判断": "待人工确认",
}

SOURCE_DISPLAY = {"OA报销": "OA 报销"}


def blank_row() -> dict[str, Any]:
    return {column: "" for column in STANDARD_COLS}


def is_blank(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return str(value).strip() in {"", "nan", "NaT", "None"}


def format_date(value: Any) -> str:
    if is_blank(value):
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%Y-%m-%d")


def classification_display(value: Any) -> str:
    text = "" if is_blank(value) else str(value)
    return CLASSIFICATION_DISPLAY.get(text, text)


def prepare_display_dataframe(master: pd.DataFrame) -> pd.DataFrame:
    display = master.copy()
    if "数据源" in display.columns:
        display["数据源"] = display["数据源"].replace(SOURCE_DISPLAY)
    if "费用日期" in display.columns:
        display["费用日期"] = display["费用日期"].map(format_date)
    if "金额" in display.columns:
        display["金额"] = pd.to_numeric(display["金额"], errors="coerce")
    if "住宿晚数" in display.columns:
        display["住宿晚数"] = pd.to_numeric(display["住宿晚数"], errors="coerce")
    if "分类方式" in display.columns:
        display["分类方式"] = display["分类方式"].map(classification_display)
    return display


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str) -> bytes:
    output = BytesIO()
    export_df = df.copy()
    if "数据源" in export_df.columns:
        export_df["数据源"] = export_df["数据源"].replace(SOURCE_DISPLAY)
    if "费用日期" in export_df.columns:
        parsed_dates = pd.to_datetime(export_df["费用日期"], errors="coerce")
        export_df["费用日期"] = parsed_dates.dt.date.where(parsed_dates.notna(), None)
    if "分类方式" in export_df.columns:
        export_df["分类方式"] = export_df["分类方式"].map(classification_display)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name=sheet_name)
        worksheet = writer.sheets[sheet_name]
        header_map = {cell.value: cell.column for cell in worksheet[1]}
        date_column = header_map.get("费用日期")
        amount_column = header_map.get("金额")
        for row in range(2, worksheet.max_row + 1):
            if date_column:
                worksheet.cell(row=row, column=date_column).number_format = "yyyy-mm-dd"
            if amount_column:
                worksheet.cell(row=row, column=amount_column).number_format = "#,##0.00"

        for column_cells in worksheet.columns:
            values = [str(cell.value) if cell.value is not None else "" for cell in column_cells]
            width = min(max(max((len(value) for value in values), default=0) + 2, 10), 36)
            worksheet.column_dimensions[column_cells[0].column_letter].width = width
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

    return output.getvalue()
