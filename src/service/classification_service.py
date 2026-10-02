import logging
import re
from collections import Counter
from typing import Dict, List

import pandas

from src.eval.logical_formids import logical_gt_formids


class ClassificationService:
    """AIReadの帳票分類結果を正解データと比較するサービス。"""

    def __init__(self, form_id_map: Dict[str, str]) -> None:
        self.form_id_map = form_id_map

    def classify(
        self,
        pdf_name: str,
        page_file_name: str,
        df: pandas.DataFrame,
        logical_sidecar: dict,
    ) -> dict:
        """1物理ページ分の帳票分類を評価する。"""

        page_no, page_index = self._get_page_no(page_file_name)

        gt_formids = self._get_gt_formids(
            pdf_name=pdf_name,
            page_no=page_no,
            df=df,
        )

        pd_formids = self._get_pd_formids(
            pdf_name=pdf_name,
            page_index=page_index,
            df=df,
            logical_sidecar=logical_sidecar,
        )

        is_target = bool(gt_formids)

        gt_counter = Counter(gt_formids)
        pd_counter = Counter(pd_formids)

        classification_total = sum(gt_counter.values())
        classification_matches = sum((gt_counter & pd_counter).values())

        gt_title = (
            " / ".join(self.form_id_map.get(x, x) for x in gt_formids)
            if is_target
            else "評価対象外"
        )

        pd_title = (
            " / ".join(self.form_id_map.get(x, x) for x in pd_formids)
            if pd_formids
            else "不明"
        )

        logging.info("  P%s GT formid: %s", page_no, gt_formids or ["なし"])
        logging.info("  P%s AIRead formid: %s", page_no, pd_formids or ["なし"])

        return {
            "filename": pdf_name,
            "page": page_no,
            "gt_title": gt_title,
            "pd_title": pd_title,
            "gt_formid": " / ".join(gt_formids),
            "pd_formid": " / ".join(pd_formids),
            "gt_formids": gt_formids,
            "pd_formids": pd_formids,
            "is_target": is_target,
            "is_match": is_target and gt_counter == pd_counter,
            "classification_total": classification_total,
            "classification_matches": classification_matches,
            "is_ocr_target": (
                sum((gt_counter & pd_counter).values()) > 0
            ),
        }

    def _get_gt_formids(
        self,
        pdf_name: str,
        page_no: int,
        df: pandas.DataFrame,
    ) -> List[str]:
        gt_formids = list(df.attrs.get("raw_gt_formids", []))

        if not gt_formids:
            for _, row in df.iterrows():
                formid = str(row.get("c1_gt", "") or "").strip()
                if formid and formid != "formid":
                    gt_formids.append(formid)

        gt_formids = [
            x for x in gt_formids
            if x.lower() not in {"unknown", "none", "不明"}
        ]

        return logical_gt_formids(pdf_name, page_no, gt_formids)

    def _get_pd_formids(
        self,
        pdf_name: str,
        page_index: int,
        df: pandas.DataFrame,
        logical_sidecar: dict,
    ) -> List[str]:
        raw_pd_formids = list(df.attrs.get("raw_pd_formids", []))

        region_items = (
            logical_sidecar
            .get(pdf_name, {})
            .get(str(page_index), [])
        )

        if region_items:
            raw_pd_formids = [
                str(item.get("formid", "")).strip()
                for item in region_items
            ]

        if not raw_pd_formids:
            for _, row in df.iterrows():
                formid = str(row.get("c1_pd", "") or "").strip()
                if formid and formid != "formid":
                    raw_pd_formids.append(formid)

        return [
            formid
            for formid in raw_pd_formids
            if formid in self.form_id_map
        ]

    @staticmethod
    def _get_page_no(page_file_name: str) -> tuple[int, int]:
        match = re.search(r"_(\d+)\.csv$", page_file_name)

        if not match:
            return 0, -1

        page_index = int(match.group(1))
        return page_index + 1, page_index
