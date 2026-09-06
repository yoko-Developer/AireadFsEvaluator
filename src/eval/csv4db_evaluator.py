# standard library
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import cast, List, Tuple, Dict, Optional
# third-party
import Levenshtein
import pandas
# local
from src import constants as const
from src.utils import fileutils 
from src.eval.excel_exporter import KessanExcelExporter

class Csv4dbEvaluator:
    """
    CSV4DB形式で出力したAIReadResultファイルと正解データファイル(Ground Truth)を比較し、
    精度指標の算出および差分レポート(CSV/HTML/Excel)を出力するクラス
    """

    # ★formidから帳票タイトルへのマッピング定数★
    FORM_ID_MAP = {
        "01_010_02": "貸借対照表 (BS)",
        "01_020_02": "損益計算書 (PL)",
        "01_030_02": "製造原価報告書",
        "01_040_02": "販売費及び一般管理費明細書",
        "01_050_02": "株主資本等変動計算書"
    }

    def __init__(self, session: str, prediction_dir: Path, ground_truth_dir: Path, results_base_dir: Path) -> None:
        self.session: str = session
        self.predictions_dir: Path = prediction_dir
        self.ground_truth_dir: Path = ground_truth_dir
        self.results_base_dir: Path = results_base_dir
        self.session_dir: Path = Path()

        self._prepare()


    def _prepare(self) -> None:
        self._prepare_dir()


    def _prepare_dir(self) -> None:
        """
        結果を保存するセッション用ディレクトリを作成する
        ※ すでに存在する場合はフォルダ内のファイルを消す
        """
        self.session_dir = self.results_base_dir / self.session
        if self.session_dir.exists():
            shutil.rmtree(self.session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)


    def _prepare_dir_using_timestamp(self) -> None:
        """結果を保存するセッション用ディレクトリ(タイムスタンプ付き)を作成する"""
        timestamp = datetime.now().strftime(const.DATE_FORMAT)
        base_name = f"{self.session}_{timestamp}"
        self.session_dir = self.results_base_dir / base_name

        postfix_num = 1
        while self.session_dir.exists():
            self.session_dir = self.results_base_dir / f"{base_name}_{postfix_num}"
            postfix_num += 1
        self.session_dir.mkdir(parents=True, exist_ok=False)


    # ==========================================
    # メインパイプライン
    # ==========================================
    def compare_with_pandas(self) -> None:
        """
        Pandasを用いた全ファイルの比較メインプロセス。
        """
        # prediction files（比較対象ファイル）
        pd_files = [f for f in sorted(self.predictions_dir.iterdir()) if f.is_file() and f.suffix == '.csv']
        num_of_file = len(pd_files)

        # 統計集計用に (ファイル名, 統合データフレーム) のリストを保持
        evaluation_results: List[Tuple[str, pandas.DataFrame]] = []

        logging.info(f"🚀 {num_of_file} 件の精度解析を開始")
        logging.info(f"📁 出力先セッション: {self.session_dir}")

        for i, pd_file in enumerate(pd_files, start=1):
            # ground truth file（正解データファイル）
            gt_file = self.ground_truth_dir / pd_file.name
            if gt_file.exists():
                logging.info(f"[{i}/{num_of_file}] 📄 正解データ: {gt_file} | 比較対象: {pd_file}")
            else :
                logging.warning(f"[{i}/{num_of_file}] ⚠️  スキップ: {pd_file.name} (正解データが ground_truth フォルダに存在しません)")
                continue

            # CSVデータ読込
            gt_df, pd_df = self._load_csv_to_dataframe(gt_file, pd_file)
            if gt_df is None or pd_df is None:
                continue

            # 正解データと対象データの比較すべき行列ペアを特定
            gt_df, pd_df = self._align_columns_by_fuzzy_match(gt_df, pd_df)
            gt_df, pd_df = self._align_rows_by_fuzzy_match(gt_df, pd_df)
            # 正解データと対象データをマージ
            merged_df = pandas.merge(gt_df, pd_df, on='row_id', how='outer', indicator='row_presence', validate="many_to_many").fillna('')
            
            # --- マージ後は行順が辞書順になってしまうので、行順を[r1, r2,..., r10, r11,...]のように自然にするために並び替え ---
            merged_df['r_num'] = merged_df['row_id'].str.extract(r'(\d+)').astype(int)
            merged_df['r_has_extra'] = merged_df['row_id'].str.startswith('extra').astype(int)
            merged_df = merged_df.sort_values(by=['r_num', 'r_has_extra'])
            merged_df = merged_df.drop(columns=['r_num', 'r_has_extra']).reset_index(drop=True)

            # 精度計算
            merged_df[['item_count', 'match_count', 'accuracy']] = merged_df.apply(self._calc_data_accuracy_by_row, axis=1)

            # ファイル別レポート出力
            diff_df = self._extract_differences(merged_df)
            self._save_individual_reports(diff_df, merged_df, pd_file.name)

            # 統計用に結果を保存
            evaluation_results.append((pd_file.name, merged_df))

        # サマリーレポートの生成
        if evaluation_results:
            self._save_summary_report(evaluation_results)

            try:
                base_excel_path = self.session_dir / "kessan_matrix_report.xlsx"
                excel_output_path = base_excel_path
                counter = 1
                while True:
                    try:
                        if excel_output_path.exists():
                            with open(excel_output_path, "a"): pass
                        break
                    except IOError:
                        excel_output_path = self.session_dir / f"kessan_matrix_report_{counter}.xlsx"
                        counter += 1

                pdf_groups = {}
                for file_name, df in evaluation_results:
                    base_pdf_name = re.sub(r'_\d+(_detail)?\.csv$', '', file_name)
                    if base_pdf_name not in pdf_groups:
                        pdf_groups[base_pdf_name] = []
                    pdf_groups[base_pdf_name].append((file_name, df))

                summary_list = []
                detail_dfs = []

                for pdf_name, page_list in pdf_groups.items():
                    total_pages = 0
                    total_items = 0
                    total_matches = 0
                    page_df_list = []

                    classification_total = 0
                    classification_matches = 0
                    
                    # ページごとの帳票タイトルを分類CSVから取得
                    page_title_map = {}

                    for page_file_name, df in page_list:
                        if "_detail" not in page_file_name:
                            page_key = page_file_name.replace(".csv", "")

                            for _, row in df.iterrows():
                                gt_formid = str(row.get("c1_gt", "")).strip()

                                if gt_formid and gt_formid != "formid":
                                    title = self.FORM_ID_MAP.get(gt_formid)
                                    if title:
                                        page_title_map[page_key] = title
                                    break
                    
                    form_totals = {
                        "貸借対照表 (BS)": [0, 0],
                        "損益計算書 (PL)": [0, 0],
                        "製造原価報告書": [0, 0],
                        "販売費及び一般管理費明細書": [0, 0],
                        "株主資本等変動計算書": [0, 0],
                    }

                    # ★直前の検出タイトルを記憶する変数★
                    last_detected_title = None

                    for page_file_name, df in page_list:
                        
                        # 分類データ（_detail ではない通常CSV）
                        if "_detail" not in page_file_name:
                            gt_formid = ""
                            pd_formid = ""

                            for _, row in df.iterrows():
                                gt = str(row.get("c1_gt", "")).strip()
                                pd = str(row.get("c1_pd", "")).strip()

                                if gt and gt != "formid":
                                    gt_formid = gt
                                    pd_formid = pd
                                    break

                            if gt_formid:
                                classification_total += 1
                                if gt_formid == pd_formid:
                                    classification_matches += 1

                            continue                        
                        
                        # 明細データ(_detail)または比較DataFrame
                        if "_detail" in page_file_name:
                            total_pages += 1
                            item_sum = df['item_count'].sum() if 'item_count' in df.columns else len(df)
                            match_sum = df['match_count'].sum() if 'match_count' in df.columns else 0

                            total_items += item_sum
                            total_matches += match_sum

                            p_acc_num = round((match_sum / item_sum * 100), 1) if item_sum > 0 else 100.0

                            # 同じページの分類CSVから帳票タイトルを取得
                            page_key = page_file_name.replace("_detail.csv", "")

                            detected_title = page_title_map.get(page_key)

                            # 念のためdetail内のformidも確認
                            if not detected_title:
                                detected_title = self._detect_title_by_formid(df)

                            if not detected_title:
                                detected_title = f"決算書 ({page_file_name})"

                        if detected_title in form_totals:
                            form_totals[detected_title][0] += match_sum
                            form_totals[detected_title][1] += item_sum

                            page_df_list.append((detected_title, df))
                            
                    def form_acc(title):
                        matches, items = form_totals[title]
                        return round(matches / items * 100, 1) if items > 0 else "-"

                    bs_acc = form_acc("貸借対照表 (BS)")
                    pl_acc = form_acc("損益計算書 (PL)")
                    seizo_acc = form_acc("製造原価報告書")
                    sg_acc = form_acc("販売費及び一般管理費明細書")
                    ss_acc = form_acc("株主資本等変動計算書")                            

                    acc = round((total_matches / total_items * 100), 2) if total_items > 0 else 0.0

                    summary_list.append({
                        "filename": pdf_name,
                        "total_pages": total_pages,
                        "total_items": total_items,
                        "total_matches": total_matches,
                        "accuracy": acc,
                        "classification_total": classification_total,
                        "classification_matches": classification_matches,
                        "BS_acc": bs_acc,
                        "PL_acc": pl_acc,
                        "販管費_acc": sg_acc,
                        "株主資本_acc": ss_acc,
                        "製造原価_acc": seizo_acc
                    })

                    if page_df_list:
                        detail_dfs.append((pdf_name, page_df_list))

                KessanExcelExporter.export_kessan_report(excel_output_path, summary_list, detail_dfs)
                logging.info(f"✨ 決算5表マトリックスExcelを出力しました: {excel_output_path}")

            except Exception as e:
                logging.error(f"❌ Excel出力中にエラーが発生しました: {e}")

        else:
            logging.warning("❌ 評価対象データが見つかりません。")

    def _detect_title_by_formid(self, df: pandas.DataFrame) -> Optional[str]:
        """データフレームの全セルからformid（01_010_02等）を検出し、正しい帳票タイトルを返す"""
        try:
            for col in df.columns:
                for val in df[col].dropna():
                    v_str = str(val).strip()
                    for f_id, title in self.FORM_ID_MAP.items():
                        if f_id in v_str:
                            return title
        except Exception:
            pass
        return None

    # ==========================================
    # CSV読み込み
    # ==========================================
    def _load_csv_to_dataframe(self, gt_path: Path, pd_path: Path) -> Tuple[Optional[pandas.DataFrame], Optional[pandas.DataFrame]]:
        """正解データと比較対象データの両方のcsvを読み込む。（数値のカンマで列が壊れるのを防止）"""
        import csv

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
                padded_rows = [r + [''] * (max_cols - len(r)) for r in rows]

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

                df = pandas.DataFrame(data_rows, columns=col_names, dtype=str).fillna('')
                return df

            except Exception as e:
                logging.warning(f"CSV load error for {file_path.name}: {e}")
                return None

        gt_df = safe_read_csv(gt_path)
        pd_df = safe_read_csv(pd_path)

        if gt_df is None or pd_df is None:
            return None, None

        return gt_df, pd_df
    
    # ==========================================
    # 列の紐付け (Column Alignment)
    # ==========================================
    def _align_columns_by_fuzzy_match(self, gt_df: pandas.DataFrame, pd_df: pandas.DataFrame) -> Tuple[pandas.DataFrame, pandas.DataFrame]:
        """列名と列データの両方の特徴を捉え、GTとPDの列を物理的に同期させる"""
        gt_orig_cols = gt_df.columns.tolist()
        pd_orig_cols = pd_df.columns.tolist()

        gt_profiles = self._create_column_profiles(gt_df, gt_orig_cols)
        pd_profiles = self._create_column_profiles(pd_df, pd_orig_cols)

        matches: List[Dict[str, float]] = self._calculate_column_similarity_scores(
            gt_orig_cols, gt_profiles, pd_orig_cols, pd_profiles
        )

        col_mapping: Dict[str, str] = self._determine_column_mapping(matches, pd_orig_cols)

        gt_df.columns = pandas.Index([f"c{i}_gt" for i in range(len(gt_orig_cols))])

        pd_col_new_names = []
        last_matched_col = "col_top"
        extra_counts = {}

        for pd_col in pd_orig_cols:
            if pd_col in col_mapping:
                matched_name = col_mapping[pd_col]
                pd_col_new_names.append(matched_name)
                last_matched_col = matched_name
            else:
                extra_counts[last_matched_col] = extra_counts.get(last_matched_col, 0) + 1
                count = extra_counts[last_matched_col]

                suffix = f"_{count}" if count > 1 else ""

                if last_matched_col == "col_top":
                    pd_col_new_names.append(f"extra_pre{suffix}")
                else:
                    pd_col_new_names.append(f"extra_{last_matched_col}{suffix}")

        pd_col_new_names = [name + "_pd" for name in pd_col_new_names]
        pd_df.columns = pandas.Index(pd_col_new_names)

        self._insert_headers_as_data_row(gt_df, gt_orig_cols)
        self._insert_headers_as_data_row(pd_df, pd_orig_cols)

        return gt_df, pd_df


    def _create_column_profiles(self, df: pandas.DataFrame, cols: List[str], max_len: int = 1500) -> List[str]:
        profiles = []
        for col_name in cols:
            valid_data = df[col_name].dropna().astype(str)
            data_str = "".join(valid_data)
            normalized_str = self._normalize_text(col_name + data_str)
            profiles.append(normalized_str[:max_len])
        return profiles


    def _calculate_column_similarity_scores(
        self, gt_cols: List[str], gt_profs: List[str], pd_cols: List[str], pd_profs: List[str]
    ) -> List[Dict[str, float]]:
        scored_matches = []
        for gt_idx, (gt_col, gt_profile) in enumerate(zip(gt_cols, gt_profs)):
            gt_header_norm = self._normalize_text(gt_col)

            for pd_idx, (pd_col, pd_profile) in enumerate(zip(pd_cols, pd_profs)):
                pd_header_norm = self._normalize_text(pd_col)

                header_sim = self._get_similarity(gt_header_norm, pd_header_norm)
                full_sim = self._get_similarity(gt_profile, pd_profile)

                if header_sim < 0.3 and full_sim < 0.3:
                    continue

                pos_sim = 1.0 - (abs(gt_idx / len(gt_cols) - pd_idx / len(pd_cols)))
                score = (full_sim * 0.5) + (header_sim * 0.4) + (pos_sim * 0.1)

                scored_matches.append({'gt_idx': gt_idx, 'pd_idx': pd_idx, 'score': score})

        return sorted(scored_matches, key=lambda x: x['score'], reverse=True)


    def _determine_column_mapping(self, sorted_matches: List[Dict[str, float]], pd_cols: List[str]) -> Dict[str, str]:
        mapping = {}
        matched_gt, matched_pd = set(), set()

        for match in sorted_matches:
            gt_idx, pd_idx = int(match['gt_idx']), int(match['pd_idx'])
            if gt_idx not in matched_gt and pd_idx not in matched_pd:
                mapping[pd_cols[pd_idx]] = f"c{gt_idx}"
                matched_gt.add(gt_idx)
                matched_pd.add(pd_idx)

        return mapping


    def _insert_headers_as_data_row(self, df: pandas.DataFrame, original_headers: List[str]) -> None:
        padding = [""] * (len(df.columns) - len(original_headers))
        df.loc[-1] = original_headers + padding
        df.index = df.index + 1
        df.sort_index(inplace=True)


    # ==========================================
    # 行の紐付け (Row Alignment)
    # ==========================================
    def _align_rows_by_fuzzy_match(
        self,
        gt_df: pandas.DataFrame,
        pd_df: pandas.DataFrame
    ) -> Tuple[pandas.DataFrame, pandas.DataFrame]:
        """
        GTとPredictionの行順を保ちながら対応付ける。
        科目列(c0)を主に使い、途中の欠損行・余分な行を許容する。
        """

        gt_rows = gt_df.reset_index(drop=True)
        pd_rows = pd_df.reset_index(drop=True)

        gt_count = len(gt_rows)
        pd_count = len(pd_rows)

        def row_similarity(gt_row, pd_row) -> float:
            # 科目列を最優先
            gt_label = self._normalize_text(
                str(gt_row.get("c0_gt", ""))
            )
            pd_label = self._normalize_text(
                str(pd_row.get("c0_pd", ""))
            )

            # 行全体も補助的に見る
            gt_full = self._normalize_text(
                ''.join(gt_row.astype(str).tolist())
            )
            pd_full = self._normalize_text(
                ''.join(pd_row.astype(str).tolist())
            )

            label_sim = self._get_similarity(gt_label, pd_label)
            full_sim = self._get_similarity(gt_full, pd_full)

            # 科目が両方ある場合は科目を主役にする
            if gt_label and pd_label:
                return (label_sim * 0.8) + (full_sim * 0.2)

            # 科目が空欄の行は行全体で判断
            return full_sim

        # ------------------------------------------
        # 動的計画法で「順番を壊さない」最適な対応を探す
        # ------------------------------------------
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
                    pd_rows.iloc[j - 1]
                )

                # 類似度0.5を基準に、
                # 似ている行はプラス、似ていない行はマイナス
                match_score = dp[i - 1][j - 1] + (sim - 0.5)

                gt_only_score = (
                    dp[i - 1][j] + gap_penalty
                )

                pd_only_score = (
                    dp[i][j - 1] + gap_penalty
                )

                best_score = max(
                    match_score,
                    gt_only_score,
                    pd_only_score
                )

                dp[i][j] = best_score

                if best_score == match_score:
                    trace[i][j] = "match"
                elif best_score == gt_only_score:
                    trace[i][j] = "gt_only"
                else:
                    trace[i][j] = "pd_only"

        # ------------------------------------------
        # 後ろからたどって対応関係を復元
        # ------------------------------------------
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

        # ------------------------------------------
        # row_idを付ける
        # ------------------------------------------
        gt_df = gt_rows.copy()
        pd_df = pd_rows.copy()

        gt_df.insert(0, "row_id", "")
        pd_df.insert(0, "row_id", "")

        gt_number = 0
        extra_number = 0

        for gt_idx, pd_idx in aligned:

            if gt_idx is not None:
                row_id = f"r{gt_number}"
                gt_df.loc[gt_idx, "row_id"] = row_id

                if pd_idx is not None:
                    pd_df.loc[pd_idx, "row_id"] = row_id

                gt_number += 1

            elif pd_idx is not None:
                pd_df.loc[pd_idx, "row_id"] = (
                    f"extra_r{extra_number}"
                )
                extra_number += 1

        # 念のためrow_idが付かなかった行にもIDを付ける
        for idx in gt_df.index:
            if not gt_df.loc[idx, "row_id"]:
                gt_df.loc[idx, "row_id"] = f"r{gt_number}"
                gt_number += 1

        for idx in pd_df.index:
            if not pd_df.loc[idx, "row_id"]:
                pd_df.loc[idx, "row_id"] = (
                    f"extra_r{extra_number}"
                )
                extra_number += 1

        return gt_df, pd_df

    # ==========================================
    # 個別レポート生成 (individual Report)
    # ==========================================
    def _save_individual_reports(self, diff_df: pandas.DataFrame, merged_df: pandas.DataFrame, file_name: str) -> None:
        file_stem = Path(file_name).stem

        individual_dir = self.session_dir / "individual reports"
        individual_dir.mkdir(parents=True, exist_ok=True)

        ordered_cols = self._determine_report_column_order(merged_df)

        csv_dir = individual_dir / "csv" / file_stem
        csv_dir.mkdir(parents=True, exist_ok=True)

        diff_file = f"diff_list_{file_name}"
        if not diff_df.empty:
            diff_list_df = self._format_diff_for_csv(diff_df, ordered_cols)
            diff_list_df.to_csv(csv_dir / diff_file, index=False, encoding="utf-8-sig")
        else:
            pandas.DataFrame({"message": ["no differences found."]}).to_csv(csv_dir / f"diff_list_{file_name}", index=False, encoding="utf-8-sig")
        logging.info(f"📄 差分レポート(CSV)を保存: {csv_dir / diff_file}")

        full_comparison_file = f"full_comparison_{file_name}"
        full_comparison_df = self._format_full_comparison_csv(merged_df, ordered_cols)
        full_comparison_df.to_csv(csv_dir / full_comparison_file, index=False, encoding="utf-8-sig")
        logging.info(f"📄 全データ比較レポートを保存: {csv_dir / full_comparison_file}")

        html_dir = individual_dir / "html"
        html_dir.mkdir(parents=True, exist_ok=True)
        html_file = f"diff_{file_stem}.html"
        self._export_html_report(merged_df, html_dir / html_file)
        logging.info(f"📄 差分レポート(HTML)を保存: {html_dir / html_file}")


    def _determine_report_column_order(self, merged_df: pandas.DataFrame) -> List[str]:
        gt_cols = [re.sub(r'_gt$', '', c) for c in merged_df.columns if c.endswith('_gt')]
        pd_cols = [re.sub(r'_pd$', '', c) for c in merged_df.columns if c.endswith('_pd')]

        ordered_cols = list(gt_cols)
        for i, pd_col in enumerate(pd_cols):
            if pd_col.startswith("extra_") and pd_col not in ordered_cols:
                insert_idx = 0
                if i > 0 and pd_cols[i-1] in ordered_cols:
                    insert_idx = ordered_cols.index(pd_cols[i-1]) + 1
                ordered_cols.insert(insert_idx, pd_col)
        return ordered_cols


    def _format_diff_for_csv(self, diff_df: pandas.DataFrame, ordered_cols: List[str]) -> pandas.DataFrame:
        csv_rows = []
        for _, row in diff_df.iterrows():
            row_id = row.get('row_id', '')
            merge_status = row.get('row_presence', 'both')

            for col in ordered_cols:
                gt_val = str(row.get(f"{col}_gt", "")).replace(' ', '').strip()
                pd_val = str(row.get(f"{col}_pd", "")).replace(' ', '').strip()
                
                if gt_val == pd_val:
                    continue

                status = "相違 (->)"
                if merge_status == 'left_only' or (gt_val and not pd_val):
                    status = "欠損 (---)"
                elif merge_status == 'right_only' or (not gt_val and pd_val):
                    status = "過剰 (+++)"

                csv_rows.append({
                    'row_id': row_id,
                    'col_id': col,
                    'ステータス': status,
                    '正解(Ground Truth)': gt_val,
                    '推論(Prediction)': pd_val
                })

        return pandas.DataFrame(csv_rows)


    def _format_full_comparison_csv(self, merged_df: pandas.DataFrame, ordered_cols: List[str]) -> pandas.DataFrame:
        base_cols = ['row_id', 'row_presence', 'accuracy', "match_count", "item_count"]

        data_cols = []
        for col in ordered_cols:
            if f"{col}_gt" in merged_df.columns:
                data_cols.append(f"{col}_gt")
            if f"{col}_pd" in merged_df.columns:
                data_cols.append(f"{col}_pd")

        return merged_df[base_cols + data_cols].copy()


    def _export_html_report(self, merged_df: pandas.DataFrame, output_path: Path) -> None:
        ordered_cols = self._determine_report_column_order(merged_df)
        html_table = self._build_html_table(merged_df, ordered_cols)

        custom_style = """
        <style>
            body { font-family: "Helvetica Neue", Helvetica, "Segoe UI", Arial, sans-serif; color: #333; margin: 30px; line-height: 1.4; }
            h2 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; margin-bottom: 20px; }
            .legend { background-color: #f8f9fa; border: 1px solid #e9ecef; padding: 15px; border-radius: 6px; margin-bottom: 25px; font-size: 0.95em; }
            .label { padding: 2px 8px; border-radius: 3px; font-weight: bold; margin-right: 5px; }
            table { border-collapse: collapse; width: 100%; font-size: 13px; table-layout: auto; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
            td, th { border: 1px solid #c0c6cc; padding: 8px 10px; word-break: break-all; vertical-align: top; }
            th { background-color: #f1f3f5; color: #495057; text-align: left; }
            .status-col { font-weight: bold; text-align: center; background-color: #e9ecef !important; color: #495057; width: 40px; }
            .col-status-row td { background-color: #fdfdfe; border-bottom: 2px solid #adb5bd; font-size: 11px; text-align: center; font-weight: bold; }
            .cell-missing, .row-missing td { background-color: #ffeef0 !important; color: #b91c1c; }
            .cell-excess, .row-excess td { background-color: #e6ffed !important; color: #116329; }
            .cell-diff { background-color: #fff8c5 !important; }
            .val-gt { color: #0056b3; font-weight: bold; font-size: 0.95em; margin-bottom: 4px; border-bottom: 1px solid #cce5ff; padding-bottom: 2px; }
            .val-pd { color: #d32f2f; font-size: 0.95em; }
        </style>
        """

        full_html = f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="utf-8">
            <title>OCR Accuracy Detail Report</title>
            {custom_style}
        </head>
        <body>
            <h2>CSV 差分解析レポート</h2>
            <div class="legend">
                <b>【記号凡例】</b><br>
                <span class="label" style="background-color: #ffeef0; color: #b91c1c;">--- 欠損</span> 正解データにのみ存在する行・列（読み飛ばし）<br>
                <span class="label" style="background-color: #e6ffed; color: #116329;">+++ 過剰</span> 推論結果にのみ存在する行・列（誤検知・ゴミ）<br>
                <span class="label" style="background-color: #fff8c5; color: #333;">&rarr; 相違</span> 上段(<span style="color: #0056b3; font-weight: bold;">青</span>): 正解データ / 下段(<span style="color: #d32f2f; font-weight: bold;">赤</span>): 推論結果(エラー)
            </div>
            {html_table}
        </body>
        </html>
        """

        with open(output_path, "w", encoding="utf-8-sig") as f:
            f.write(full_html)


    def _build_html_table(self, merged_df: pandas.DataFrame, ordered_cols: List[str]) -> str:
        lines = ['<table>', '<thead>', '<tr><th class="status-col">@@</th>']

        for col in ordered_cols:
            lines.append(f'<th>{col}</th>')
        lines.append('</tr>')

        lines.append('<tr class="col-status-row"><td class="status-col">@@</td>')
        for col in ordered_cols:
            has_gt = f"{col}_gt" in merged_df.columns
            has_pd = f"{col}_pd" in merged_df.columns
            if has_gt and not has_pd: lines.append('<td class="cell-missing">---</td>')
            elif not has_gt and has_pd: lines.append('<td class="cell-excess">+++</td>')
            else: lines.append('<td></td>')
        lines.append('</tr></thead><tbody>')

        for _, row in merged_df.iterrows():
            r_status = "row-missing" if row['row_presence'] == 'left_only' else \
                       "row-excess" if row['row_presence'] == 'right_only' else \
                       "row-diff" if row.get('accuracy', 100) < 100 else ""

            s_mark = "---" if r_status == "row-missing" else "+++" if r_status == "row-excess" else "→" if r_status == "row-diff" else ""
            lines.append(f'<tr class="{r_status}"><td class="status-col">{s_mark}</td>')

            for col in ordered_cols:
                has_gt = f"{col}_gt" in merged_df.columns
                has_pd = f"{col}_pd" in merged_df.columns
                gt_val = str(row.get(f"{col}_gt", "")).strip()
                pd_val = str(row.get(f"{col}_pd", "")).strip()

                if has_gt and not has_pd:
                    lines.append(f'<td class="cell-missing">{gt_val}</td>')
                elif not has_gt and has_pd:
                    lines.append(f'<td class="cell-excess">{pd_val}</td>')
                elif gt_val != pd_val:
                    lines.append(f'<td class="cell-diff"><div class="val-gt">{gt_val}</div><div class="val-pd">{pd_val}</div></td>')
                else:
                    lines.append(f'<td>{pd_val}</td>')
            lines.append('</tr>')

        lines.append('</tbody></table>')
        return "".join(lines)


    # ==========================================
    # サマリーレポート生成 (Summary Report)
    # ==========================================
    def _save_summary_report(self, all_results: List[Tuple[str, pandas.DataFrame]]) -> None:
        summary_path = self.session_dir / "summary_report.csv"

        file_metrics = []
        for file_name, df in all_results:
            if df.empty:
                continue

            missing_rows = len(df[df['row_presence'] == 'left_only'])
            excess_rows = len(df[df['row_presence'] == 'right_only'])

            gt_bases = {col.replace('_gt', '') for col in df.columns if col.endswith('_gt')}
            pd_bases = {col.replace('_pd', '') for col in df.columns if col.endswith('_pd')}
            missing_cols = len(gt_bases - pd_bases)
            excess_cols = len(pd_bases - gt_bases)

            file_metrics.append({
                'ファイル名': file_name,
                '項目精度(%)': round((df['match_count'].sum() / df['item_count'].sum() * 100), 2) if df['item_count'].sum() > 0 else 0,
                '項目正解数': df['match_count'].sum().astype(int),
                '項目数': df['item_count'].sum().astype(int),
                '欠損行数(---)': missing_rows,
                '過剰行数(+++)': excess_rows,
                '欠損列数(---)': missing_cols,
                '過剰列数(+++)': excess_cols
            })

        file_summary_df = pandas.DataFrame(file_metrics)
        file_summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

        logging.info(f"📊 Summary Report Created: {summary_path}\n")


    # ==========================================
    # ユーティリティ・計算処理
    # ==========================================
    @staticmethod
    def _normalize_text(text: str) -> str:
        """★カンマもピリオドも一切消さない！スペース（空白・タブ・全角空白）のみを除去して100%厳格評価★"""
        text_str = str(text or '')
        return re.sub(r'[\s\t\u3000]', '', text_str)

    @staticmethod
    def _get_similarity(text1: str, text2: str) -> float:
        """編集距離と包含関係を考慮した類似度スコア算出"""
        sim = 1.0 - (Levenshtein.distance(text1, text2) / max(len(text1), len(text2), 1))
        if text1 in text2 or text2 in text1:
            sim = max(sim, 0.8)
        return sim


    @staticmethod
    def _calc_data_accuracy_by_row(row: pandas.Series) -> pandas.Series:
        """行単位の正解データ数/推論データと正解データとの一致数/精度を計算"""
        
        # CSVのヘッダー行はOCRの採点対象外
        if str(row.get("row_id", "")).strip() == "r0":
            return pandas.Series([0, 0, 100.0])
        gt_cols = [col for col in row.index if col.endswith('_gt')]

        item_count = 0
        match_count = 0

        for gt_col in gt_cols:
            gt_val = str(row[gt_col]) if pandas.notna(row[gt_col]) else ""

            pd_col = gt_col.replace('_gt', '_pd')
            pd_val = ""
            if pd_col in row.index:
                pd_val = str(row[pd_col]) if pandas.notna(row[pd_col]) else ""

            # GTもPredictionも空なら評価対象外
            if gt_val == "" and pd_val == "":
                continue

            # どちらか一方に値があれば評価対象
            item_count += 1

            gt_norm = Csv4dbEvaluator._normalize_text(gt_val)
            pd_norm = Csv4dbEvaluator._normalize_text(pd_val)

            if gt_norm == pd_norm:
                match_count += 1
        
        accuracy = (match_count / item_count) * 100 if item_count > 0 else 0
        accuracy = round(accuracy, 2)

        return pandas.Series([item_count, match_count, accuracy])

    def _extract_differences(self, df: pandas.DataFrame) -> pandas.DataFrame:
        """不一致行のみを抽出する（並び順は抽出元の自然な状態を維持する）"""
        return df[(df['accuracy'] < 100) | (df['row_presence'] != 'both')].copy()
    