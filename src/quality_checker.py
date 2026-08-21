"""Non-destructive data quality checks for the standardized travel dataset."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .utils import format_date, is_blank


KEY_FIELDS = ["数据源", "申请单据号/订单号", "申请人", "费用日期", "币种", "金额"]
MAPPING_DEPENDENT_SOURCES = {"滴滴用车", "滴滴火车", "OA报销"}


def _blank_mask(series: pd.Series) -> pd.Series:
    return series.map(is_blank)


def run_quality_checks(master: pd.DataFrame) -> dict[str, Any]:
    if master.empty:
        empty_mask = pd.Series(dtype=bool)
        masks = {
            "missing_trip": empty_mask,
            "mapping_unmatched": empty_mask,
            "missing_key_fields": empty_mask,
            "invalid_amount": empty_mask,
            "duplicates": empty_mask,
            "unclassified": empty_mask,
        }
    else:
        missing_trip = _blank_mask(master["差旅申请单号"])
        mapping_unmatched = master["数据源"].isin(MAPPING_DEPENDENT_SOURCES) & missing_trip

        missing_key_fields = pd.Series(False, index=master.index)
        for field in KEY_FIELDS:
            missing_key_fields |= _blank_mask(master[field])

        numeric_amount = pd.to_numeric(master["金额"], errors="coerce")
        invalid_amount = numeric_amount.isna() | (numeric_amount <= 0)

        order_is_present = ~_blank_mask(master["申请单据号/订单号"])
        duplicates = order_is_present & master.duplicated(
            subset=["数据源", "申请单据号/订单号", "费用日期", "金额", "原始描述"],
            keep=False,
        )

        unclassified = (
            master["需人工确认"].astype(str).eq("是")
            | _blank_mask(master["场景"])
            | _blank_mask(master["类型"])
        )
        masks = {
            "missing_trip": missing_trip,
            "mapping_unmatched": mapping_unmatched,
            "missing_key_fields": missing_key_fields,
            "invalid_amount": invalid_amount,
            "duplicates": duplicates,
            "unclassified": unclassified,
        }

    definitions = [
        ("missing_trip", "差旅申请单号缺失", "标准宽表中的差旅申请单号为空"),
        ("mapping_unmatched", "Mapping 未匹配", "需要申请单 Mapping 的数据源未找到对应关系"),
        ("missing_key_fields", "关键字段缺失", f"缺少以下至少一个字段：{', '.join(KEY_FIELDS)}"),
        ("invalid_amount", "金额为空或异常", "金额为空、无法转换为数字或小于等于 0"),
        (
            "duplicates",
            "重复记录",
            "数据来源、单据号、费用日期、金额与原始描述均相同",
        ),
        ("unclassified", "无法完成分类", "场景或类型无法通过固定规则可靠确定"),
    ]

    summary: list[dict[str, Any]] = []
    issue_rows: dict[str, pd.DataFrame] = {}
    for key, label, description in definitions:
        mask = masks[key]
        count = int(mask.sum()) if len(mask) else 0
        summary.append(
            {
                "检查项目": label,
                "异常记录数": count,
                "检查结果": "✅ 无异常" if count == 0 else "⚠️ 需关注",
                "说明": description,
            }
        )
        issue_rows[key] = master.loc[mask].copy() if len(mask) else master.iloc[0:0].copy()

    return {
        "summary": summary,
        "issue_rows": issue_rows,
        "counts": {key: int(mask.sum()) if len(mask) else 0 for key, mask in masks.items()},
    }


def review_reason(row: pd.Series) -> str:
    scene_missing = is_blank(row.get("场景"))
    type_missing = is_blank(row.get("类型"))
    trip_missing = is_blank(row.get("差旅申请单号"))

    if scene_missing and type_missing:
        reason = "现有固定规则和 Mapping 无法根据原始费用类型或描述可靠确定场景与类型。"
    elif type_missing:
        reason = "已识别当前差旅场景，但现有固定规则无法可靠确定具体费用类型。"
    elif scene_missing:
        reason = "已识别费用类型，但现有固定规则无法可靠确定业务场景。"
    else:
        reason = "该记录被现有固定规则标记为需要人工确认。"

    if trip_missing:
        reason += " 差旅申请单号尚未完成关联。"
    return reason


def review_suggestion(row: pd.Series) -> str:
    if is_blank(row.get("差旅申请单号")):
        return "请人工确认场景和类型，并补充或核对差旅申请单 Mapping，完成后维护至月报底表。"
    return "请人工确认场景和类型后维护至月报底表。"


def review_card_data(row: pd.Series) -> dict[str, str]:
    return {
        "数据来源": str(row.get("数据源", "")),
        "申请人": str(row.get("申请人", "")),
        "日期": format_date(row.get("费用日期")),
        "原始描述": str(row.get("原始描述", "")),
        "当前场景": "未确定" if is_blank(row.get("场景")) else str(row.get("场景")),
        "当前类型": "未确定" if is_blank(row.get("类型")) else str(row.get("类型")),
        "原因": review_reason(row),
        "建议处理": review_suggestion(row),
    }
