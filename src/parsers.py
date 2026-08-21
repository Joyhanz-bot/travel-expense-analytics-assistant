"""Excel source recognition and V1-compatible travel data transformations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .classifier import classify_didi, classify_oa, classify_payment
from .utils import STANDARD_COLS, blank_row


SOURCE_LABELS = {
    "ctrip": "携程",
    "didi_car": "滴滴用车",
    "didi_train": "滴滴火车",
    "payment": "Payment",
    "oa": "OA 报销",
}

SOURCE_SIGNATURES = {
    "ctrip": {"关联行程号", "项目类别", "订单号", "含税金额"},
    "didi_car": {"订单号", "用车人", "实付总金额", "申请事由"},
    "didi_train": {"订单号", "乘车人", "实付金额", "乘车日期"},
    "payment": {"凭证类型", "三级费用类型", "记账日期", "摘要"},
    "oa": {"凭证类型", "四级费用类型", "申请人", "费用日期", "摘要"},
}

MAPPING_REQUIRED_COLUMNS = {"差旅申请单号", "费用订单号/申请单据号"}


def _reset_file(file: Any) -> None:
    if hasattr(file, "seek"):
        file.seek(0)


def read_excel(file: Any, **kwargs: Any) -> pd.DataFrame:
    _reset_file(file)
    dataframe = pd.read_excel(file, **kwargs)
    _reset_file(file)
    return dataframe


def get_mapping(mapping_file: Any) -> dict[str, str]:
    if mapping_file is None:
        return {}
    dataframe = read_excel(mapping_file)
    missing = MAPPING_REQUIRED_COLUMNS.difference(dataframe.columns)
    if missing:
        raise ValueError(f"Mapping 缺少必要字段：{', '.join(sorted(missing))}")

    result: dict[str, str] = {}
    for _, row in dataframe.iterrows():
        result[str(row["费用订单号/申请单据号"])] = str(row["差旅申请单号"])
    return result


def inspect_mapping_file(mapping_file: Any) -> dict[str, Any]:
    if mapping_file is None:
        return {"valid": False, "row_count": 0, "message": "尚未选择 Mapping 文件"}
    try:
        dataframe = read_excel(mapping_file)
    except Exception as exc:
        return {"valid": False, "row_count": 0, "message": f"无法读取 Mapping：{exc}"}

    missing = MAPPING_REQUIRED_COLUMNS.difference(dataframe.columns)
    if missing:
        return {
            "valid": False,
            "row_count": len(dataframe),
            "message": f"缺少必要字段：{', '.join(sorted(missing))}",
        }
    return {"valid": True, "row_count": len(dataframe), "message": "Mapping 字段检查通过"}


def identify_source_from_columns(columns: list[Any]) -> str | None:
    column_set = {str(column) for column in columns}
    for source_type, required_columns in SOURCE_SIGNATURES.items():
        if required_columns.issubset(column_set):
            return source_type
    return None


def inspect_source_file(file: Any) -> dict[str, Any]:
    filename = getattr(file, "name", Path(str(file)).name)
    try:
        dataframe = read_excel(file)
    except Exception as exc:
        return {
            "file": file,
            "filename": filename,
            "recognized": False,
            "source_type": None,
            "source_name": "未识别数据源",
            "row_count": 0,
            "message": f"文件无法读取：{exc}",
        }

    source_type = identify_source_from_columns(list(dataframe.columns))
    if source_type is None:
        return {
            "file": file,
            "filename": filename,
            "recognized": False,
            "source_type": None,
            "source_name": "未识别数据源",
            "row_count": len(dataframe),
            "message": "字段结构与当前支持的数据源不匹配",
        }

    return {
        "file": file,
        "filename": filename,
        "recognized": True,
        "source_type": source_type,
        "source_name": SOURCE_LABELS[source_type],
        "row_count": len(dataframe),
        "message": "数据源识别成功",
    }


def transform(file: Any, mapping: dict[str, str], source_type: str | None = None) -> pd.DataFrame:
    dataframe = read_excel(file)
    source_type = source_type or identify_source_from_columns(list(dataframe.columns))
    output: list[dict[str, Any]] = []

    if source_type == "ctrip":
        for _, row in dataframe.iterrows():
            item = blank_row()
            order = str(row["订单号"])
            trip = str(row["关联行程号"]).split("_")[0]
            category = str(row["项目类别"])
            if category == "机票":
                scene, expense_type = "其中：异地", "其中：飞机"
                mode, review, nights = "Python Mapping", False, ""
            elif category == "月结酒店":
                scene, expense_type = "其中：异地", "花费②住宿"
                mode, review = "Python Mapping", False
                try:
                    nights = max(
                        (pd.to_datetime(row["退房日期"]) - pd.to_datetime(row["入住日期"])).days,
                        0,
                    )
                except Exception:
                    nights = ""
            else:
                scene, expense_type = "其中：异地", ""
                mode, review, nights = "待语义判断", True, ""
            city = row["到达城市"] if pd.notna(row["到达城市"]) else row["出发城市"]
            item.update(
                {
                    "数据源": "携程",
                    "差旅申请单号": trip,
                    "申请单据号/订单号": order,
                    "申请人": row["薯名"] if pd.notna(row["薯名"]) else row["姓名"],
                    "一级部门": row["一级部门"],
                    "二级部门": row["二级部门"],
                    "费用日期": row["出发日期"] if pd.notna(row["出发日期"]) else row["入住日期"],
                    "城市": city,
                    "境内外": "境内",
                    "场景": scene,
                    "类型": expense_type,
                    "币种": row["币种"],
                    "金额": row["含税金额"],
                    "住宿晚数": nights,
                    "原始描述": row["备注"],
                    "分类方式": mode,
                    "需人工确认": "是" if review else "否",
                }
            )
            output.append(item)

    elif source_type == "didi_car":
        for _, row in dataframe.iterrows():
            item = blank_row()
            order = str(row["订单号"])
            scene, expense_type, mode, review = classify_didi(row["申请事由"], row["备注"])
            department = str(row["一级部门/二级部门"]).split("/")
            item.update(
                {
                    "数据源": "滴滴用车",
                    "差旅申请单号": mapping.get(order, ""),
                    "申请单据号/订单号": order,
                    "申请人": row["用车人"],
                    "员工邮箱": row["员工邮箱"],
                    "一级部门": department[0] if department else "",
                    "二级部门": department[1] if len(department) > 1 else "",
                    "费用日期": row["用车日期"],
                    "城市": row["出发城市"],
                    "境内外": "境内",
                    "场景": scene,
                    "类型": expense_type,
                    "币种": "CNY",
                    "金额": row["实付总金额"],
                    "是否敏感": row["是否敏感订单"],
                    "原始描述": f'{row["申请事由"]} / {row["备注"]}',
                    "分类方式": mode,
                    "需人工确认": "是" if review else "否",
                }
            )
            output.append(item)

    elif source_type == "didi_train":
        for _, row in dataframe.iterrows():
            item = blank_row()
            order = str(row["订单号"])
            item.update(
                {
                    "数据源": "滴滴火车",
                    "差旅申请单号": mapping.get(order, ""),
                    "申请单据号/订单号": order,
                    "申请人": row["乘车人"],
                    "员工邮箱": row["员工邮箱"],
                    "一级部门": row["一级部门"],
                    "二级部门": row["二级部门"],
                    "费用日期": row["乘车日期"],
                    "城市": f'{row["出发站"]}-{row["到达站"]}',
                    "境内外": "境内",
                    "场景": "其中：异地",
                    "类型": "火车",
                    "币种": "CNY",
                    "金额": row["实付金额"],
                    "原始描述": row["申请事由"],
                    "分类方式": "Python Mapping",
                    "需人工确认": "否",
                }
            )
            output.append(item)

    elif source_type == "payment":
        for _, row in dataframe.iterrows():
            item = blank_row()
            summary = str(row["摘要"])
            parts = summary.split("-")
            applicant = parts[0] if parts else ""
            document = parts[1] if len(parts) > 1 else ""
            department = parts[2].split("/") if len(parts) > 2 else []
            scene, expense_type, mode, review = classify_payment(str(row["三级费用类型"]))
            item.update(
                {
                    "数据源": "Payment",
                    "差旅申请单号": "",
                    "申请单据号/订单号": document,
                    "申请人": applicant,
                    "一级部门": department[0] if department else "",
                    "二级部门": department[1] if len(department) > 1 else "",
                    "费用日期": row["记账日期"],
                    "城市": row["城市"],
                    "境内外": "境外",
                    "场景": scene,
                    "类型": expense_type,
                    "币种": row["币种"],
                    "金额": row["金额"],
                    "原始描述": summary,
                    "分类方式": mode,
                    "需人工确认": "是" if review else "否",
                }
            )
            output.append(item)

    elif source_type == "oa":
        for _, row in dataframe.iterrows():
            item = blank_row()
            summary = str(row["摘要"])
            document = summary.split("-")[0]
            scene, expense_type, mode, review = classify_oa(
                str(row["四级费用类型"]), str(row["城市"])
            )
            nights: int | str = ""
            if (
                "住宿" in str(row["四级费用类型"])
                and pd.notna(row["住宿标准单价"])
                and float(row["住宿标准单价"]) != 0
            ):
                nights = round(float(row["金额"]) / float(row["住宿标准单价"]))
            item.update(
                {
                    "数据源": "OA报销",
                    "差旅申请单号": mapping.get(document, ""),
                    "申请单据号/订单号": document,
                    "申请人": row["申请人"],
                    "员工邮箱": row["员工邮箱"],
                    "一级部门": row["一级部门"],
                    "二级部门": row["二级部门"],
                    "费用日期": row["费用日期"],
                    "城市": row["城市"],
                    "境内外": "境内",
                    "场景": scene,
                    "类型": expense_type,
                    "币种": row["币种"],
                    "金额": row["金额"],
                    "住宿晚数": nights,
                    "原始描述": summary,
                    "分类方式": mode,
                    "需人工确认": "是" if review else "否",
                }
            )
            output.append(item)

    return pd.DataFrame(output, columns=STANDARD_COLS)

