import csv
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import Levenshtein
import pandas

from src.utils import fileutils


class OcrEvaluationService:
    """AIReadのOCR結果を正解データと比較して評価するサービス。"""

    def __init__(
        self,
        predictions_dir: Path,
        session_dir: Path,
        form_id_map: Dict[str, str],
    ) -> None:
        self.predictions_dir = predictions_dir
        self.session_dir = session_dir
        self.form_id_map = form_id_map

    def _load_csv_to_dataframe(
        self,
        gt_path: Path,
        pd_path: Path,
    ) -> Tuple[Optional[pandas.DataFrame], Optional[pandas.DataFrame]]:
        """����f�[�^�Ɣ�r�Ώۃf�[�^�̗�����csv��ǂݍ��ށB"""

        def safe_read_csv(file_path: Path) -> Optional[pandas.DataFrame]:
            try:
                enc = fileutils.detect_encoding(file_path)

                rows = []
                with open(file_path, 'r', encoding=enc, newline='') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if row:
                            rows.append([str(cell).strip() for cell in row])

                if not rows:
                    return pandas.DataFrame()

                max_cols = max(len(r) for r in rows)
                padded_rows = [
                    r + [''] * (max_cols - len(r))
                    for r in rows
                ]

                headers = padded_rows[0]
                data_rows = padded_rows[1:]

                col_names = []
                counts = {}

                for idx, h in enumerate(headers):
                    h_str = h if h != '' else f"col_{idx}"
                    counts[h_str] = counts.get(h_str, 0) + 1

                    if counts[h_str] > 1:
                        col_names.append(f"{h_str}_{counts[h_str]-1}")
                    else:
                        col_names.append(h_str)

                df = pandas.DataFrame(
                    data_rows,
                    columns=col_names,
                    dtype=str,
                ).fillna('')

                return df

            except Exception as e:
                logging.warning(
                    f"CSV load error for {file_path.name}: {e}"
                )
                return None

        gt_df = safe_read_csv(gt_path)
        pd_df = safe_read_csv(pd_path)

        if gt_df is None or pd_df is None:
            return None, None

        return gt_df, pd_df
    def _align_columns_by_fuzzy_match(
        self,
        gt_df: pandas.DataFrame,
        pd_df: pandas.DataFrame,
    ) -> Tuple[pandas.DataFrame, pandas.DataFrame]:
        """GT��PD�̗������ʂƗގ��x�őΉ��t����B"""

        gt_orig_cols = gt_df.columns.tolist()
        pd_orig_cols = pd_df.columns.tolist()

        gt_profiles = self._create_column_profiles(gt_df, gt_orig_cols)
        pd_profiles = self._create_column_profiles(pd_df, pd_orig_cols)

        matches: List[Dict[str, float]] = self._calculate_column_similarity_scores(
            gt_orig_cols,
            gt_profiles,
            pd_orig_cols,
            pd_profiles,
        )

        col_mapping: Dict[str, str] = self._determine_column_mapping(
            matches,
            pd_orig_cols,
        )

        gt_df.columns = pandas.Index(
            [f"c{i}_gt" for i in range(len(gt_orig_cols))]
        )

        pd_col_new_names = []
        last_matched_col = "col_top"
        extra_counts = {}

        for pd_col in pd_orig_cols:
            if pd_col in col_mapping:
                matched_name = col_mapping[pd_col]
                pd_col_new_names.append(matched_name)
                last_matched_col = matched_name
            else:
                extra_counts[last_matched_col] = (
                    extra_counts.get(last_matched_col, 0) + 1
                )
                count = extra_counts[last_matched_col]

                suffix = f"_{count}" if count > 1 else ""

                if last_matched_col == "col_top":
                    pd_col_new_names.append(f"extra_pre{suffix}")
                else:
                    pd_col_new_names.append(
                        f"extra_{last_matched_col}{suffix}"
                    )

        pd_col_new_names = [name + "_pd" for name in pd_col_new_names]
        pd_df.columns = pandas.Index(pd_col_new_names)

        return gt_df, pd_df

    def _create_column_profiles(
        self,
        df: pandas.DataFrame,
        cols: List[str],
        max_len: int = 1500,
    ) -> List[str]:
        profiles = []

        for col_name in cols:
            valid_data = df[col_name].dropna().astype(str)
            data_str = "".join(valid_data)
            normalized_str = self._normalize_text(col_name + data_str)
            profiles.append(normalized_str[:max_len])

        return profiles

    def _calculate_column_similarity_scores(
        self,
        gt_cols: List[str],
        gt_profs: List[str],
        pd_cols: List[str],
        pd_profs: List[str],
    ) -> List[Dict[str, float]]:
        scored_matches = []

        for gt_idx, (gt_col, gt_profile) in enumerate(
            zip(gt_cols, gt_profs)
        ):
            gt_header_norm = self._normalize_text(gt_col)

            for pd_idx, (pd_col, pd_profile) in enumerate(
                zip(pd_cols, pd_profs)
            ):
                pd_header_norm = self._normalize_text(pd_col)

                header_sim = self._get_similarity(
                    gt_header_norm,
                    pd_header_norm,
                )
                full_sim = self._get_similarity(
                    gt_profile,
                    pd_profile,
                )

                if header_sim < 0.3 and full_sim < 0.3:
                    continue

                pos_sim = 1.0 - (
                    abs(
                        gt_idx / len(gt_cols)
                        - pd_idx / len(pd_cols)
                    )
                )

                score = (
                    (full_sim * 0.5)
                    + (header_sim * 0.4)
                    + (pos_sim * 0.1)
                )

                scored_matches.append(
                    {
                        'gt_idx': gt_idx,
                        'pd_idx': pd_idx,
                        'score': score,
                    }
                )

        return sorted(
            scored_matches,
            key=lambda x: x['score'],
            reverse=True,
        )

    def _determine_column_mapping(
        self,
        sorted_matches: List[Dict[str, float]],
        pd_cols: List[str],
    ) -> Dict[str, str]:
        mapping = {}
        matched_gt, matched_pd = set(), set()

        for match in sorted_matches:
            gt_idx = int(match['gt_idx'])
            pd_idx = int(match['pd_idx'])

            if gt_idx not in matched_gt and pd_idx not in matched_pd:
                mapping[pd_cols[pd_idx]] = f"c{gt_idx}"
                matched_gt.add(gt_idx)
                matched_pd.add(pd_idx)

        return mapping

    def _insert_headers_as_data_row(
        self,
        df: pandas.DataFrame,
        original_headers: List[str],
    ) -> None:
        padding = [""] * (len(df.columns) - len(original_headers))
        df.loc[-1] = original_headers + padding
        df.index = df.index + 1
        df.sort_index(inplace=True)

    @staticmethod
    def _normalize_text(text: str) -> str:
        """�󔒕�����������Ĕ�r�p�̕�����ɐ��K������B"""

        text_str = str(text or '')
        return re.sub(r'[\s\t\u3000]', '', text_str)

    @staticmethod
    def _get_similarity(text1: str, text2: str) -> float:
        """2�̕�����̗ގ��x��v�Z����B"""

        sim = 1.0 - (
            Levenshtein.distance(text1, text2)
            / max(len(text1), len(text2), 1)
        )

        if text1 in text2 or text2 in text1:
            sim = max(sim, 0.8)

        return sim

    @staticmethod
    def _calc_data_accuracy_by_row(
        row: pandas.Series,
    ) -> pandas.Series:
        """�s�P�ʂ̍��ڐ��E��v���E���𗦂�v�Z����B"""

        gt_cols = [
            col for col in row.index
            if col.endswith('_gt')
        ]

        item_count = 0
        match_count = 0

        for gt_col in gt_cols:
            gt_val = (
                str(row[gt_col])
                if pandas.notna(row[gt_col])
                else ""
            )

            pd_col = gt_col.replace('_gt', '_pd')
            pd_val = ""

            if pd_col in row.index:
                pd_val = (
                    str(row[pd_col])
                    if pandas.notna(row[pd_col])
                    else ""
                )

            if gt_val == "" and pd_val == "":
                continue

            item_count += 1

            gt_norm = OcrEvaluationService._normalize_text(gt_val)
            pd_norm = OcrEvaluationService._normalize_text(pd_val)

            if gt_norm == pd_norm:
                match_count += 1

        accuracy = (
            (match_count / item_count) * 100
            if item_count > 0
            else 0
        )
        accuracy = round(accuracy, 2)

        return pandas.Series(
            [item_count, match_count, accuracy]
        )

    def _extract_differences(
        self,
        df: pandas.DataFrame,
    ) -> pandas.DataFrame:
        """�s��v�s�݂̂𒊏o����B"""

        return df[
            (df['accuracy'] < 100)
            | (df['row_presence'] != 'both')
        ].copy()
    def _align_rows_by_fuzzy_match(
        self,
        gt_df: pandas.DataFrame,
        pd_df: pandas.DataFrame,
    ) -> Tuple[pandas.DataFrame, pandas.DataFrame]:
        """
        GT��Prediction�̍s����ێ����Ȃ���Ή��t����B
        �擪���ڗ�(c0)���Ɏg���A�r���̗]���ȍs����e����B
        """

        gt_rows = gt_df.reset_index(drop=True)
        pd_rows = pd_df.reset_index(drop=True)

        gt_count = len(gt_rows)
        pd_count = len(pd_rows)

        def row_similarity(gt_row, pd_row) -> float:
            gt_label = self._normalize_text(
                str(gt_row.get("c0_gt", ""))
            )
            pd_label = self._normalize_text(
                str(pd_row.get("c0_pd", ""))
            )

            gt_full = self._normalize_text(
                ''.join(gt_row.astype(str).tolist())
            )
            pd_full = self._normalize_text(
                ''.join(pd_row.astype(str).tolist())
            )

            label_sim = self._get_similarity(gt_label, pd_label)
            full_sim = self._get_similarity(gt_full, pd_full)

            if gt_label and pd_label:
                return (label_sim * 0.8) + (full_sim * 0.2)

            return full_sim

        gap_penalty = -0.25

        dp = [
            [0.0 for _ in range(pd_count + 1)]
            for _ in range(gt_count + 1)
        ]

        trace = [
            [None for _ in range(pd_count + 1)]
            for _ in range(gt_count + 1)
        ]

        for i in range(1, gt_count + 1):
            dp[i][0] = dp[i - 1][0] + gap_penalty
            trace[i][0] = "gt_only"

        for j in range(1, pd_count + 1):
            dp[0][j] = dp[0][j - 1] + gap_penalty
            trace[0][j] = "pd_only"

        for i in range(1, gt_count + 1):
            for j in range(1, pd_count + 1):
                sim = row_similarity(
                    gt_rows.iloc[i - 1],
                    pd_rows.iloc[j - 1],
                )

                match_score = dp[i - 1][j - 1] + (sim - 0.5)

                gt_only_score = dp[i - 1][j] + gap_penalty
                pd_only_score = dp[i][j - 1] + gap_penalty

                best_score = max(
                    match_score,
                    gt_only_score,
                    pd_only_score,
                )

                dp[i][j] = best_score

                if best_score == match_score:
                    trace[i][j] = "match"
                elif best_score == gt_only_score:
                    trace[i][j] = "gt_only"
                else:
                    trace[i][j] = "pd_only"

        aligned = []

        i = gt_count
        j = pd_count

        while i > 0 or j > 0:
            action = trace[i][j]

            if action == "match":
                aligned.append((i - 1, j - 1))
                i -= 1
                j -= 1

            elif action == "gt_only":
                aligned.append((i - 1, None))
                i -= 1

            elif action == "pd_only":
                aligned.append((None, j - 1))
                j -= 1

            else:
                break

        aligned.reverse()

        gt_df = gt_rows.copy()
        pd_df = pd_rows.copy()

        gt_df.insert(0, "row_id", "")
        pd_df.insert(0, "row_id", "")

        for pos, (gt_idx, pd_idx) in enumerate(aligned):
            row_id = f"r{pos}"

            if gt_idx is not None:
                gt_df.loc[gt_idx, "row_id"] = row_id

            if pd_idx is not None:
                pd_df.loc[pd_idx, "row_id"] = row_id

        next_pos = len(aligned)

        for idx in gt_df.index:
            if not gt_df.loc[idx, "row_id"]:
                gt_df.loc[idx, "row_id"] = f"r{next_pos}"
                next_pos += 1

        for idx in pd_df.index:
            if not pd_df.loc[idx, "row_id"]:
                pd_df.loc[idx, "row_id"] = f"r{next_pos}"
                next_pos += 1

        return gt_df, pd_df


    def _normalize_equity_matrix_detail(self, df: pandas.DataFrame) -> pandas.DataFrame:
        """01_050_02??????GT?25??????????????"""
        if df is None or df.empty or len(df.columns) < 7:
            return df

        src = df.fillna('').astype(str).reset_index(drop=True)
        label_col = src.columns[0]
        value_cols = list(src.columns[1:])
        if len(value_cols) < 6 or len(src) < 7:
            return df

        def cell(row_idx: int, col) -> str:
            if row_idx < 0 or row_idx >= len(src):
                return ""
            return str(src.iloc[row_idx].get(col, '')).strip()

        def label(row_idx: int) -> str:
            return cell(row_idx, label_col)

        def out(account: str = "", amount: str = "") -> dict:
            return {'account': str(account).strip(), 'amount_0': str(amount).strip()}

        rows = [
            out(value_cols[0]),
            out(label(1), cell(1, value_cols[0])),
            out(label(6), cell(6, value_cols[0])),
            out(),
            out(),
            out(value_cols[1]),
            out(label(1), cell(1, value_cols[1])),
            out(label(6), cell(6, value_cols[1])),
            out(value_cols[2]),
            out(label(1), cell(1, value_cols[2])),
            out(label(3), cell(3, value_cols[2])),
            out(label(5), cell(5, value_cols[2])),
            out(label(6), cell(6, value_cols[2])),
            out(label(0) if label(0) else value_cols[3]),
            out(label(1), cell(1, value_cols[3])),
            out(label(5), cell(5, value_cols[3])),
            out(label(6), cell(6, value_cols[3])),
            out(value_cols[4]),
            out(label(1), cell(1, value_cols[4])),
            out(label(5), cell(5, value_cols[4])),
            out(label(6), cell(6, value_cols[4])),
            out(value_cols[5]),
            out(label(1), cell(1, value_cols[5])),
            out(label(5), cell(5, value_cols[5])),
            out(label(6), cell(6, value_cols[5])),
        ]
        return pandas.DataFrame(rows, columns=['account', 'amount_0'])


    def _compare_detail_by_formid(
        self,
        gt_file: Path,
        orig_name: str,
        page_index: int,
        region_items: list,
    ):
        """formid???GT detail?AIRead?logical region detail??????"""
        try:
            gt_all = pandas.read_csv(gt_file, dtype=str, keep_default_na=False)
        except Exception as e:
            logging.warning("formid??GT detail????: %s", e)
            return None, [], []

        if "formid" not in gt_all.columns:
            return None, [], []

        gt_ids = [
            str(v).strip()
            for v in gt_all["formid"].tolist()
            if str(v).strip()
        ]
        ordered_ids = list(dict.fromkeys(gt_ids))
        merged_parts = []
        scored_ids = []

        temp_dir = self.session_dir / '.logical_ocr_inputs'
        temp_dir.mkdir(parents=True, exist_ok=True)

        for seq, formid in enumerate(ordered_ids, start=1):
            gt_part = (
                gt_all[
                    gt_all["formid"].astype(str).str.strip() == formid
                ]
                .drop(columns=["formid"])
            )

            candidates = []

            for item in sorted(
                region_items,
                key=lambda x: int(x.get('region', 0) or 0),
            ):
                if (
                    str(item.get('formid', '')).strip() != formid
                    or not item.get('detail_file')
                ):
                    continue

                path = (
                    self.predictions_dir
                    / '.logical_region_details'
                    / str(item['detail_file'])
                )

                if path.exists():
                    candidates.append((item, path))

            if not candidates:
                logging.warning(
                    "  P%d OCR detail: GT=%s ?????region detail??",
                    page_index + 1,
                    formid,
                )
                pd_part = pandas.DataFrame(columns=gt_part.columns)
            else:
                frames = [
                    pandas.read_csv(
                        path,
                        dtype=str,
                        keep_default_na=False,
                    )
                    for _, path in candidates
                ]

                pd_part = (
                    pandas.concat(
                        frames,
                        ignore_index=True,
                        sort=False,
                    )
                    .fillna('')
                )

                scored_ids.extend([formid] * len(candidates))

                logging.info(
                    "  P%d OCR?????: %s -> %s",
                    page_index + 1,
                    formid,
                    [f"R{x.get('region')}" for x, _ in candidates],
                )

            if formid == "01_050_02" and not pd_part.empty:
                pd_part = self._normalize_equity_matrix_detail(pd_part)
                logging.info(
                    "  P%d ??????????: ??? -> ?????????? (%d?)",
                    page_index + 1,
                    len(pd_part),
                )

            gt_tmp = temp_dir / f"{orig_name}_{page_index}_GT_{seq}.csv"
            pd_tmp = temp_dir / f"{orig_name}_{page_index}_PD_{seq}.csv"

            gt_part.to_csv(
                gt_tmp,
                index=False,
                encoding='utf-8-sig',
            )
            pd_part.to_csv(
                pd_tmp,
                index=False,
                encoding='utf-8-sig',
            )

            gt_df, pd_df = self._load_csv_to_dataframe(
                gt_tmp,
                pd_tmp,
            )

            if gt_df is None or pd_df is None:
                continue

            if (
                formid == "01_050_02"
                and len(gt_df) == len(pd_df) + 1
                and not gt_df.empty
            ):
                first_gt = str(gt_df.iloc[0, 0]).strip()

                if first_gt == "??????????":
                    gt_df = gt_df.iloc[1:].reset_index(drop=True)
                    logging.info(
                        "  P%d ??????????: "
                        "???????OCR????????",
                        page_index + 1,
                    )

            gt_df, pd_df = self._align_columns_by_fuzzy_match(
                gt_df,
                pd_df,
            )

            if formid == "01_050_02":
                gt_df = gt_df.reset_index(drop=True)
                pd_df = pd_df.reset_index(drop=True)

                gt_df['row_id'] = [
                    f"r{i}" for i in range(len(gt_df))
                ]
                pd_df['row_id'] = [
                    f"r{i}" for i in range(len(pd_df))
                ]

                logging.info(
                    "  P%d ??????????: "
                    "25???????????",
                    page_index + 1,
                )
            else:
                gt_df, pd_df = self._align_rows_by_fuzzy_match(
                    gt_df,
                    pd_df,
                )

            part = pandas.merge(
                gt_df,
                pd_df,
                on='row_id',
                how='outer',
                indicator='row_presence',
                validate='many_to_many',
            )

            for _col in part.columns:
                if _col != 'row_presence':
                    part[_col] = part[_col].fillna('')

            part[
                ['item_count', 'match_count', 'accuracy']
            ] = part.apply(
                self._calc_data_accuracy_by_row,
                axis=1,
            )

            part['row_id'] = part['row_id'].astype(str).map(
                lambda x: f"f{seq}_{x}"
            )
            part['logical_formid'] = formid

            merged_parts.append(part)

        if not merged_parts:
            return None, [], []

        merged = pandas.concat(
            merged_parts,
            ignore_index=True,
            sort=False,
        )

        for _col in merged.columns:
            if _col != 'row_presence':
                merged[_col] = merged[_col].fillna('')

        unscored = [
            str(x.get('formid', '')).strip()
            for x in region_items
            if str(x.get('formid', '')).strip() in self.form_id_map
            and str(x.get('formid', '')).strip() not in ordered_ids
        ]

        merged.attrs['ocr_scored_formids'] = scored_ids
        merged.attrs['ocr_unscored_formids'] = unscored
        merged.attrs['logical_detail_grouped'] = True

        return merged, scored_ids, unscored
