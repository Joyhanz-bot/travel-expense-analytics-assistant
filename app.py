from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.parsers import (
    SOURCE_LABELS,
    get_mapping,
    inspect_mapping_file,
    inspect_source_file,
    transform,
)
from src.quality_checker import review_card_data, run_quality_checks
from src.utils import (
    STANDARD_COLS,
    dataframe_to_excel_bytes,
    format_date,
    prepare_display_dataframe,
)


ROOT = Path(__file__).resolve().parent
SAMPLE_MAPPING_PATH = ROOT / "travel_mapping.xlsx"
SAMPLE_SOURCE_PATHS = [
    ROOT / "ctrip_statement.xlsx",
    ROOT / "didi_car.xlsx",
    ROOT / "didi_train.xlsx",
    ROOT / "payment.xlsx",
    ROOT / "oa_reimbursement.xlsx",
]

CORE_DISPLAY_COLUMNS = [
    "数据源",
    "差旅申请单号",
    "申请单据号/订单号",
    "申请人",
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
    "原始描述",
    "分类方式",
    "需人工确认",
]

SOURCE_DISPLAY = {"OA报销": "OA 报销"}


def _file_signature(file: Any) -> tuple[str, int]:
    filename = getattr(file, "name", Path(str(file)).name)
    size = getattr(file, "size", None)
    if size is None and isinstance(file, Path) and file.exists():
        size = file.stat().st_size
    return filename, int(size or 0)


def _input_signature(mode: str, mapping_file: Any, source_files: list[Any]) -> tuple[Any, ...]:
    return (
        mode,
        _file_signature(mapping_file) if mapping_file is not None else None,
        tuple(_file_signature(file) for file in source_files),
    )


def _source_name(value: Any) -> str:
    return SOURCE_DISPLAY.get(str(value), str(value))


def process_sources(mapping_file: Any, inspections: list[dict[str, Any]]) -> dict[str, Any]:
    mapping = get_mapping(mapping_file)
    frames: list[pd.DataFrame] = []
    source_stats: dict[str, dict[str, Any]] = {}
    processing_errors: list[dict[str, str]] = []

    for inspection in inspections:
        if not inspection["recognized"]:
            continue

        source_name = inspection["source_name"]
        stats = source_stats.setdefault(
            source_name,
            {
                "数据来源": source_name,
                "原始记录数": 0,
                "成功处理数": 0,
                "待人工确认数": 0,
                "处理错误数": 0,
            },
        )
        stats["原始记录数"] += inspection["row_count"]

        try:
            standardized = transform(
                inspection["file"],
                mapping,
                source_type=inspection["source_type"],
            )
        except Exception as exc:
            stats["处理错误数"] += inspection["row_count"]
            processing_errors.append(
                {
                    "数据来源": source_name,
                    "文件": inspection["filename"],
                    "原因": str(exc),
                }
            )
            continue

        frames.append(standardized)
        stats["成功处理数"] += len(standardized)
        stats["待人工确认数"] += int((standardized["需人工确认"] == "是").sum())

    master = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=STANDARD_COLS)
    )

    source_overview: list[dict[str, Any]] = []
    for stats in source_stats.values():
        needs_attention = stats["待人工确认数"] > 0 or stats["处理错误数"] > 0
        source_overview.append(
            {
                "数据来源": stats["数据来源"],
                "原始记录数": stats["原始记录数"],
                "成功处理数": stats["成功处理数"],
                "待人工确认数": stats["待人工确认数"],
                "处理状态": "⚠️ 需关注" if needs_attention else "✅ 正常",
            }
        )

    fixed_count = int(master["分类方式"].isin(["Python规则", "Python Mapping"]).sum())
    review_count = int((master["需人工确认"] == "是").sum())
    quality = run_quality_checks(master)

    return {
        "master": master,
        "source_overview": source_overview,
        "processing_errors": processing_errors,
        "quality": quality,
        "source_count": len(source_stats),
        "raw_count": sum(item["原始记录数"] for item in source_stats.values()),
        "integrated_count": len(master),
        "fixed_count": fixed_count,
        "review_count": review_count,
    }


def render_source_recognition(
    mapping_info: dict[str, Any], inspections: list[dict[str, Any]]
) -> None:
    st.subheader("Step 2｜已识别数据源")

    if mapping_info["valid"]:
        st.success(f"✅ 差旅申请关联表 Mapping：{mapping_info['row_count']} 条")
    else:
        st.warning(f"⚠️ Mapping 文件需检查：{mapping_info['message']}")

    recognized = [item for item in inspections if item["recognized"]]
    unrecognized = [item for item in inspections if not item["recognized"]]

    if recognized:
        columns = st.columns(min(len(recognized), 5))
        for index, item in enumerate(recognized):
            with columns[index % len(columns)]:
                with st.container(border=True):
                    st.markdown(f"**✅ {item['source_name']}**")
                    st.metric("原始记录", item["row_count"])
                    st.caption("已按字段结构识别")
    else:
        st.info("尚未识别到支持的数据源。")

    for item in unrecognized:
        st.warning(f"⚠️ 未识别数据源：{item['filename']}。{item['message']}")


def render_kpis(result: dict[str, Any]) -> None:
    st.subheader("处理结果总览")
    columns = st.columns(5)
    columns[0].metric("数据源数量", result["source_count"])
    columns[1].metric("原始记录数", result["raw_count"])
    columns[2].metric("成功整合记录数", result["integrated_count"])
    columns[3].metric("固定规则完成分类数", result["fixed_count"])
    columns[4].metric("需人工确认数", result["review_count"])


def render_source_overview(result: dict[str, Any]) -> None:
    st.subheader("数据源处理概览")
    overview = pd.DataFrame(result["source_overview"])
    if overview.empty:
        st.info("当前没有成功识别的数据源。")
        return
    st.dataframe(overview, width="stretch", hide_index=True)

    for error in result["processing_errors"]:
        st.warning(f"{error['数据来源']} 处理失败：{error['原因']}")


def render_master_table(master: pd.DataFrame) -> None:
    st.subheader("标准化差旅月报宽表")
    st.caption("这是本次处理的核心输出。表格按统一字段呈现，可用于后续月报分析和人工维护。")
    display = prepare_display_dataframe(master)
    st.dataframe(
        display[CORE_DISPLAY_COLUMNS],
        width="stretch",
        hide_index=True,
        height=520,
        column_config={
            "金额": st.column_config.NumberColumn("金额", format="%.2f"),
            "住宿晚数": st.column_config.NumberColumn("住宿晚数", format="%.0f"),
            "原始描述": st.column_config.TextColumn("原始描述", width="large"),
        },
    )


def render_quality_checks(result: dict[str, Any]) -> None:
    st.subheader("数据质量检查")
    quality = result["quality"]
    counts = quality["counts"]

    if not any(counts.values()):
        st.success("✅ 未发现数据质量异常。")
    else:
        if counts["missing_trip"]:
            st.warning(f"⚠️ {counts['missing_trip']} 条差旅申请单号缺失")
        if counts["mapping_unmatched"]:
            st.warning(f"⚠️ {counts['mapping_unmatched']} 条 Mapping 未匹配")
        if counts["missing_key_fields"]:
            st.warning(f"⚠️ {counts['missing_key_fields']} 条关键字段缺失")
        if counts["invalid_amount"]:
            st.warning(f"⚠️ {counts['invalid_amount']} 条金额为空或异常")
        if counts["duplicates"]:
            st.warning(f"⚠️ {counts['duplicates']} 条重复记录")
        if counts["unclassified"]:
            st.error(f"🔴 {counts['unclassified']} 条需要人工确认")

    summary = pd.DataFrame(quality["summary"])
    st.dataframe(summary, width="stretch", hide_index=True)
    st.caption("质量检查只标记问题，不会自动删除或改写任何记录。")

    issue_columns = [
        "数据源",
        "差旅申请单号",
        "申请单据号/订单号",
        "申请人",
        "费用日期",
        "金额",
        "原始描述",
    ]
    issue_labels = {
        "missing_trip": "差旅申请单号缺失",
        "mapping_unmatched": "Mapping 未匹配",
        "missing_key_fields": "关键字段缺失",
        "invalid_amount": "金额为空或异常",
        "duplicates": "重复记录",
    }
    for key, label in issue_labels.items():
        issue_rows = quality["issue_rows"][key]
        if issue_rows.empty:
            continue
        with st.expander(f"{label}｜{len(issue_rows)} 条", expanded=False):
            display = prepare_display_dataframe(issue_rows)
            st.dataframe(display[issue_columns], width="stretch", hide_index=True)


def render_human_review(master: pd.DataFrame) -> pd.DataFrame:
    st.subheader("待人工确认")
    review_df = master.loc[master["需人工确认"] == "是"].copy()

    if review_df.empty:
        st.success("本次所有记录均已通过固定规则或固定 Mapping 完成分类。")
        return review_df

    st.error(f"当前有 {len(review_df)} 条记录无法通过固定规则可靠分类。")
    st.caption(
        "对于固定规则无法可靠分类的记录，当前保留人工确认。后续可按需增加语义辅助分类能力。"
    )

    for _, row in review_df.iterrows():
        card = review_card_data(row)
        with st.container(border=True):
            st.markdown(
                f"**🔴 {_source_name(card['数据来源'])}｜{card['申请人']}｜待人工确认**"
            )
            top_columns = st.columns(3)
            top_columns[0].markdown(f"**日期**  \n{card['日期'] or '缺失'}")
            top_columns[1].markdown(f"**当前场景**  \n{card['当前场景']}")
            top_columns[2].markdown(f"**当前类型**  \n{card['当前类型']}")
            st.markdown("**原始描述**")
            st.write(card["原始描述"] or "缺失")
            st.markdown(f"**未能自动分类的原因**  \n{card['原因']}")
            st.markdown(f"**建议处理**  \n{card['建议处理']}")

    return review_df


def render_downloads(master: pd.DataFrame, review_df: pd.DataFrame) -> None:
    st.subheader("结果导出")
    master_bytes = dataframe_to_excel_bytes(master, "差旅费用标准宽表")
    columns = st.columns(2)
    columns[0].download_button(
        "下载标准化差旅月报底表",
        data=master_bytes,
        file_name="travel_monthly_master.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        type="primary",
    )

    if review_df.empty:
        columns[1].button("当前无待人工确认清单", disabled=True, width="stretch")
    else:
        review_bytes = dataframe_to_excel_bytes(review_df, "待人工确认")
        columns[1].download_button(
            "下载待人工确认清单",
            data=review_bytes,
            file_name="travel_review_items.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
    st.caption("结果文件为新生成的标准化输出，不会修改任何原始上传文件。")


def main() -> None:
    st.set_page_config(page_title="差旅数据整合与分类工具", page_icon="📊", layout="wide")
    st.title("差旅数据整合与分类工具")
    st.caption("多源差旅数据标准化 · Mapping · 分类 · 质量检查 · 月报宽表输出")
    st.info(
        "用于将携程、滴滴、Payment、OA 等不同结构的差旅数据统一整理为标准化月报底表。"
        "Python 负责数据读取、字段标准化、Mapping、分类、派生字段计算及质量检查；"
        "无法通过固定规则可靠判断的记录保留人工确认。所有演示数据均为模拟数据。"
    )

    st.subheader("Step 1｜选择数据")
    mode = st.radio(
        "选择数据模式",
        ["使用内置模拟数据", "上传自有测试文件"],
        horizontal=True,
        help="建议首次体验时使用内置模拟数据。",
    )
    st.caption("当前支持：携程、滴滴用车、滴滴火车、Payment、OA 报销。系统根据字段结构识别，无需提前修改文件名。")

    if mode == "使用内置模拟数据":
        mapping_file: Any = SAMPLE_MAPPING_PATH
        source_files: list[Any] = SAMPLE_SOURCE_PATHS
        st.success("已选择内置模拟数据，可直接开始整合。")
    else:
        upload_columns = st.columns(2)
        with upload_columns[0]:
            mapping_file = st.file_uploader(
                "上传差旅申请关联表 Mapping",
                type=["xlsx"],
                help="至少需要包含“差旅申请单号”和“费用订单号/申请单据号”字段。",
            )
        with upload_columns[1]:
            source_files = st.file_uploader(
                "上传一个或多个差旅数据源文件",
                type=["xlsx"],
                accept_multiple_files=True,
                help="可同时上传携程、滴滴用车、滴滴火车、Payment 和 OA 报销文件。",
            )
        if mapping_file is None or not source_files:
            st.info("请上传差旅申请关联表 Mapping，并上传至少一个差旅数据源文件。")
            return

    signature = _input_signature(mode, mapping_file, source_files)
    if st.session_state.get("input_signature") != signature:
        st.session_state["input_signature"] = signature
        st.session_state.pop("processing_result", None)

    mapping_info = inspect_mapping_file(mapping_file)
    inspections = [inspect_source_file(file) for file in source_files]
    render_source_recognition(mapping_info, inspections)

    recognized_count = sum(1 for item in inspections if item["recognized"])
    can_process = mapping_info["valid"] and recognized_count > 0

    st.subheader("Step 3｜运行数据整合")
    st.info("处理流程：数据读取 → 字段标准化 → Mapping → 分类 → 合并 → 质量检查")
    if st.button(
        "开始数据整合",
        type="primary",
        width="stretch",
        disabled=not can_process,
    ):
        try:
            with st.spinner("正在完成数据读取、标准化、Mapping、分类、合并与质量检查…"):
                st.session_state["processing_result"] = process_sources(
                    mapping_file, inspections
                )
        except Exception as exc:
            st.error(f"数据整合未完成：{exc}")
            return

    result = st.session_state.get("processing_result")
    if result is None:
        st.caption("点击“开始数据整合”后，将显示处理结果、标准宽表、质量问题和下载入口。")
        return

    st.divider()
    render_kpis(result)
    render_source_overview(result)
    render_master_table(result["master"])
    render_quality_checks(result)
    review_df = render_human_review(result["master"])
    render_downloads(result["master"], review_df)


if __name__ == "__main__":
    main()
