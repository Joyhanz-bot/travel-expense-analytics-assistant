"""Deterministic classification rules preserved from the original V1 app."""

from __future__ import annotations

import re


def classify_didi(reason: object, remark: object) -> tuple[str, str, str, bool]:
    txt = f"{reason} {remark}".lower()
    if "加班" in txt or re.search(r"\b2[2-3]:\d{2}\b", txt):
        return "其中：市内", "加班打车金额总计", "Python规则", False
    if "客户" in txt or "拜访" in txt:
        return "其中：市内", "拜访客户金额总计", "Python规则", False
    if "异地" in txt or "出差" in txt:
        return "其中：异地", "花费①打车", "Python规则", False
    return "", "", "待语义判断", True


def classify_payment(level3: object) -> tuple[str, str, str, bool]:
    mapping = {
        "网约车/出租": ("其中：异地", "花费①打车"),
        "油费": ("其中：异地", "花费①打车"),
        "境外交通": ("其中：异地", "花费①打车"),
        "大巴票": ("其中：异地", "花费①打车"),
        "短期出差住宿": ("其中：异地", "花费②住宿"),
        "长期出差住宿": ("其中：异地", "花费②住宿"),
        "火车票": ("其中：异地", "火车"),
        "飞机票": ("其中：异地", "其中：飞机"),
        "差旅工作餐": ("其中：异地", "花费④餐饮"),
        "加班": ("其中：市内", "加班打车金额总计"),
        "客户拜访": ("其中：市内", "拜访客户金额总计"),
    }
    if level3 in mapping:
        return (*mapping[level3], "Python Mapping", False)
    return "", "", "待语义判断", True


def classify_oa(level4: object, city: object) -> tuple[str, str, str, bool]:
    del city  # Kept in the signature to preserve the original V1 interface.
    mapping = {
        "出租车/网约车": ("其中：异地", "花费①打车"),
        "短期出差住宿": ("其中：异地", "花费②住宿"),
        "长期出差住宿": ("其中：异地", "花费②住宿"),
        "火车票": ("其中：异地", "火车"),
        "飞机票": ("其中：异地", "其中：飞机"),
        "差旅工作餐": ("其中：异地", "花费④餐饮"),
        "加班": ("其中：市内", "加班打车金额总计"),
        "因公外出": ("其中：市内", "拜访客户金额总计"),
        "客户拜访": ("其中：市内", "拜访客户金额总计"),
    }
    if level4 in mapping:
        return (*mapping[level4], "Python Mapping", False)
    return "", "", "待语义判断", True

