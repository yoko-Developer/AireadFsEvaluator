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


class Csv4dbEvaluator:
    """
    CSV4DB形式で出力したAIReadの結果ファイルと正解データファイル(Ground Truth)を比較し、
    精度指標の算出および差分レポート(CSV/HTML)を出力するクラス。
    """

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

        logging.info(f"🚀 {num_of_file} 件の精度解析を開始します...")
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
            # 1. 数字部分だけを抽出して数値(int)にする（r2 や extra_r2 から "2" を取り出す）
            merged_df['r_num'] = merged_df['row_id'].str.extract(r'(\d+)').astype(int)
            # 2. 'extra' から始まるかどうかを判定する (False=0, True=1 になるので、r が先に来る)
            merged_df['r_has_extra'] = merged_df['row_id'].str.startswith('extra').astype(int)
            # 3. 「数字」→「extraかどうか」の順でソート
            merged_df = merged_df.sort_values(by=['r_num', 'r_has_extra'])
            # 4. 作業用カラムを削除してインデックスを振り直す
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
        else:
            logging.warning("❌ 評価対象データが見つかりませんでした。")


    # ==========================================
    # CSV読み込み
    # ==========================================
    def _load_csv_to_dataframe(self, gt_path: Path, pd_path: Path) -> Tuple[Optional[pandas.DataFrame], Optional[pandas.DataFrame]]:
        """正解データと比較対象データの両方のcsvを読み込む。"""
        gt_df: pandas.DataFrame = None
        pd_df: pandas.DataFrame = None
        try:
            gt_df = cast(pandas.DataFrame, pandas.read_csv(gt_path, header=0, dtype=str, encoding=fileutils.detect_encoding(gt_path)))
        except Exception as e:
            logging.warning(f"CSV load error for {gt_path.name}: {e}")
            return None, None

        try:
            pd_df = cast(pandas.DataFrame, pandas.read_csv(pd_path, header=0, dtype=str, encoding=fileutils.detect_encoding(pd_path)))
        except Exception as e:
            logging.warning(f"CSV load error for {pd_path.name}: {e}")
            return None, None

        return gt_df, pd_df

    # ==========================================
    # 列の紐付け (Column Alignment)
    # ==========================================
    def _align_columns_by_fuzzy_match(self, gt_df: pandas.DataFrame, pd_df: pandas.DataFrame) -> Tuple[pandas.DataFrame, pandas.DataFrame]:
        """列名と列データの両方の特徴を捉え、GTとPDの列を物理的に同期させる"""
        # ヘッダー行をデータの先頭行に差し込み、ヘッダ名を書き換えるので書き換える前のヘッダ行を控えておく
        gt_orig_cols = gt_df.columns.tolist()
        pd_orig_cols = pd_df.columns.tolist()

        # 列全体（ヘッダー＋データ）の特徴文字列を作成
        gt_profiles = self._create_column_profiles(gt_df, gt_orig_cols)
        pd_profiles = self._create_column_profiles(pd_df, pd_orig_cols)

        # 全組み合わせの類似度スコアを計算
        matches: List[Dict[str, float]] = self._calculate_column_similarity_scores(
            gt_orig_cols, gt_profiles, pd_orig_cols, pd_profiles
        )

        # スコア順に1対1でペアを確定
        col_mapping: Dict[str, str] = self._determine_column_mapping(matches, pd_orig_cols)

        # GT側の列名を c0_gt, c1_gt, ... に書き換え
        gt_df.columns = pandas.Index([f"c{i}_gt" for i in range(len(gt_orig_cols))])

        # --- PD側の列名書き換え（直前のcXXを引き継いでネーミングする） ---
        pd_col_new_names = []
        last_matched_col = "col_top"  # 紐付く前にいきなり過剰列が出た場合用
        extra_counts = {}         # 同じ列の横に複数の過剰列が出た場合の枝番用

        for pd_col in pd_orig_cols:
            if pd_col in col_mapping:
                # 紐付いた列の場合は、その名前(cXX)を適用し、最後に紐付いた名前として記憶
                matched_name = col_mapping[pd_col]
                pd_col_new_names.append(matched_name)
                last_matched_col = matched_name
            else:
                # 紐付かなかった列の場合は、直前に紐付いた名前を使って extra_cXX にする
                extra_counts[last_matched_col] = extra_counts.get(last_matched_col, 0) + 1
                count = extra_counts[last_matched_col]

                suffix = f"_{count}" if count > 1 else ""

                if last_matched_col == "col_top":
                    # 一番最初の列(c0)より前に出たゴミ列
                    pd_col_new_names.append(f"extra_pre{suffix}")
                else:
                    # 例: c9 の次に出たゴミ列なら "extra_c9" になる
                    pd_col_new_names.append(f"extra_{last_matched_col}{suffix}")

        # 全列名の末尾に"_pd"を追加
        pd_col_new_names = [name + "_pd" for name in pd_col_new_names]
        pd_df.columns = pandas.Index(pd_col_new_names)
        # ------------------------------------------------------------------------

        # 元のヘッダーをデータの-1行目として挿入（レポートでの表示用）
        self._insert_headers_as_data_row(gt_df, gt_orig_cols)
        self._insert_headers_as_data_row(pd_df, pd_orig_cols)

        return gt_df, pd_df


    def _create_column_profiles(self, df: pandas.DataFrame, cols: List[str], max_len: int = 1500) -> List[str]:
        """列のヘッダーとデータを結合し、列の特徴を表す文字列(プロファイル)を生成する"""
        profiles = []

        for col_name in cols:
            # 1. 列データから空欄(NaN)を除外し、すべて文字列に変換する
            valid_data = df[col_name].dropna().astype(str)

            # 2. データをひと繋ぎの文字列にする (例: ["100", "200"] -> "100200")
            data_str = "".join(valid_data)

            # 3. ヘッダー名とデータをくっつけ、不要な記号などのノイズを除去（正規化）する
            normalized_str = self._normalize_text(col_name + data_str)

            # 4. 計算量の爆発を防ぐため、指定文字数で切り出してリストに追加する
            profiles.append(normalized_str[:max_len])

        return profiles


    def _calculate_column_similarity_scores(
        self, gt_cols: List[str], gt_profs: List[str], pd_cols: List[str], pd_profs: List[str]
    ) -> List[Dict[str, float]]:
        """GTとPDの全列の組み合わせに対して類似度スコアを計算する"""
        scored_matches = []
        for gt_idx, (gt_col, gt_profile) in enumerate(zip(gt_cols, gt_profs)):
            gt_header_norm = self._normalize_text(gt_col)

            for pd_idx, (pd_col, pd_profile) in enumerate(zip(pd_cols, pd_profs)):
                pd_header_norm = self._normalize_text(pd_col)

                header_sim = self._get_similarity(gt_header_norm, pd_header_norm) # ヘッダ文字列同士の類似度
                full_sim = self._get_similarity(gt_profile, pd_profile) # ヘッダ＆値全てをマージした文字列同士の類似度

                # ヘッダーもデータも全く似ていない場合は足切り
                if header_sim < 0.3 and full_sim < 0.3:
                    continue

                # 表における列の物理的位置の類似度
                pos_sim = 1.0 - (abs(gt_idx / len(gt_cols) - pd_idx / len(pd_cols)))

                # スコアを確定
                score = (full_sim * 0.5) + (header_sim * 0.4) + (pos_sim * 0.1)

                scored_matches.append({'gt_idx': gt_idx, 'pd_idx': pd_idx, 'score': score})

        # スコアの高い順にソート
        return sorted(scored_matches, key=lambda x: x['score'], reverse=True)


    def _determine_column_mapping(self, sorted_matches: List[Dict[str, float]], pd_cols: List[str]) -> Dict[str, str]:
        """スコアの高い順に列の紐付け（1対1）を確定する"""
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
        """元のヘッダー名をインデックス -1 のデータ行として挿入する"""
        # ループを回さず、リストの結合で一括代入
        padding = [""] * (len(df.columns) - len(original_headers))
        df.loc[-1] = original_headers + padding
        df.index = df.index + 1
        df.sort_index(inplace=True)


    # ==========================================
    # 行の紐付け (Row Alignment)
    # ==========================================
    def _align_rows_by_fuzzy_match(self, gt_df: pandas.DataFrame, pd_df: pandas.DataFrame) -> Tuple[pandas.DataFrame, pandas.DataFrame]:
        """近似マッチングを用いて、正解行と推論行を紐付けたDataFrameを作成する"""
        # 行マッチの推論のため、DataFrameの1行分のデータを、すべて横にガッチャンコして1つの文字列にしたリストを作成
        gt_norm = gt_df.apply(lambda r: self._normalize_text(''.join(r.dropna().astype(str))), axis=1).tolist()
        pd_norm = pd_df.apply(lambda r: self._normalize_text(''.join(r.dropna().astype(str))), axis=1).tolist()

        # 正解行を基準にマッチする推論行を探索
        matched_pairs = []
        used_pd_row_idx = set()
        for gt_row_idx, gt_text in enumerate(gt_norm):
            if not gt_text:
                matched_pairs.append((gt_row_idx, None))
                continue

            best_idx, best_sim = None, -1.0
            for pd_row_idx, pd_text in enumerate(pd_norm):
                if pd_row_idx in used_pd_row_idx or not pd_text:
                    continue

                # 行の類似度計算
                sim = self._get_similarity(gt_text, pd_text)
                if sim > best_sim and sim > 0.35:
                    best_sim, best_idx = sim, pd_row_idx

            if best_idx is not None:
                matched_pairs.append((gt_row_idx, best_idx))
                used_pd_row_idx.add(best_idx)
            else:
                matched_pairs.append((gt_row_idx, None))

        # 正解データと比較対象データの1列目にrow_idを挿入
        gt_df.insert(0, 'row_id', [f"r{i}" for i in range(len(gt_df))])
        pd_df.insert(0, 'row_id', "")

        # 1. どこにもマッチしなかったPD（過剰行）のインデックスを昇順リストで用意しておく
        # （setの引き算を使って、全PDインデックスから使用済みを引く）
        unmatched_pd_row_indices = sorted(set(range(len(pd_df))) - used_pd_row_idx)

        # 比較対象データのrow_idを採番
        for gt_row_idx, pd_row_idx in matched_pairs:
            if pd_row_idx is not None:
                # 3. predictionテーブルにマッチした行がある場合、該当行より「上」にある過剰行をすべて吐き出す
                suffix: int = 0
                while unmatched_pd_row_indices and unmatched_pd_row_indices[0] < pd_row_idx:
                    extra_row_idx = unmatched_pd_row_indices.pop(0) # 先頭から取り出して削除
                    pd_df.loc[extra_row_idx, 'row_id'] = f"extra_r{gt_row_idx}" if suffix == 0 else f"extra_r{gt_row_idx}_{suffix}"
                    suffix += 1

                # 4. マッチした正規行を採番
                pd_df.loc[pd_row_idx, 'row_id'] = f"r{gt_row_idx}"

        # 5. 最後に残った（どこにも挟まれなかった末尾の）過剰行を採番
        for extra_row_idx in unmatched_pd_row_indices:
            pd_df.loc[extra_row_idx, 'row_id'] = f"extra_r{extra_row_idx}"

        return gt_df, pd_df


    # ==========================================
    # 個別レポート生成 (individual Report)
    # ==========================================
    def _save_individual_reports(self, diff_df: pandas.DataFrame, merged_df: pandas.DataFrame, file_name: str) -> None:
        """個別ファイルの差分結果を、用途別のCSV群とHTMLで保存する"""
        file_stem = Path(file_name).stem

        individual_dir = self.session_dir / "individual reports"
        individual_dir.mkdir(parents=True, exist_ok=True)

        ordered_cols = self._determine_report_column_order(merged_df)

        # --- CSV保存ディレクトリの準備 ---
        csv_dir = individual_dir / "csv" / file_stem
        csv_dir.mkdir(parents=True, exist_ok=True)

        # 1. 【差分リストCSV】分析・集計用（縦積み形式）
        diff_file = f"diff_list_{file_name}"
        if not diff_df.empty:
            diff_list_df = self._format_diff_for_csv(diff_df, ordered_cols)
            diff_list_df.to_csv(csv_dir / diff_file, index=False, encoding="utf-8-sig")
        else:
            # 空のDataFrameを保存する場合
            pandas.DataFrame({"message": ["no differences found."]}).to_csv(csv_dir / f"diff_list_{file_name}", index=False, encoding="utf-8-sig")
        logging.info(f"📄 差分レポート(CSV)を保存: {csv_dir / diff_file}")

        # 2. 【全データ比較CSV】全体俯瞰用（横並び形式）
        full_comparison_file = f"full_comparison_{file_name}"
        full_comparison_df = self._format_full_comparison_csv(merged_df, ordered_cols)
        full_comparison_df.to_csv(csv_dir / full_comparison_file, index=False, encoding="utf-8-sig")
        logging.info(f"📄 全データ比較レポートを保存: {csv_dir / full_comparison_file}")

        # --- HTML出力 (視認性の高いカスタムレポート) ---
        html_dir = individual_dir / "html"
        html_dir.mkdir(parents=True, exist_ok=True)
        html_file = f"diff_{file_stem}.html"
        self._export_html_report(merged_df, html_dir / html_file)
        logging.info(f"📄 差分レポート(HTML)を保存: {html_dir / html_file}")


    def _determine_report_column_order(self, merged_df: pandas.DataFrame) -> List[str]:
        """
        過剰列(extra_c0等)が推論結果の元々の位置に表示されるように、列の並び順を決定する
        c0_gt, c0_pd, c1_gt, c1_pd, ...
        → c0, c1, c2, ... （_gt, _pdを削除して、重複排除される）
        """
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


    # 個別CSVレポート生成 (CSV Report)
    def _format_diff_for_csv(self, diff_df: pandas.DataFrame, ordered_cols: List[str]) -> pandas.DataFrame:
        """
        横長の差分データを、人が目視で確認・フィルタリングしやすい
        「エラー箇所のみを縦にリストアップした形式」に変換する。
        """
        csv_rows = []
        for _, row in diff_df.iterrows():
            row_id = row.get('row_id', '')
            merge_status = row.get('row_presence', 'both')

            for col in ordered_cols:
                gt_val = str(row.get(f"{col}_gt", "")).strip()
                pd_val = str(row.get(f"{col}_pd", "")).strip()

                # 一致しているセルは出力しない（エラー箇所のみ抽出）
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
        """
        全ての行・列を含み、GTとPDを横に並べたCSV用DataFrameを作成する。
        Excelで開いた際、左側に管理情報（IDや精度）、右側にデータ本体が来るように構成。
        """
        # 管理用カラムの定義
        base_cols = ['row_id', 'row_presence', 'accuracy', "match_count", "item_count"]

        # データの並び替え: 各列IDごとに GT と PD を隣り合わせる
        # 例: [row_id, row_presence, accuracy, c0_gt, c0_pd, c1_gt, c1_pd, ...]
        data_cols = []
        for col in ordered_cols:
            if f"{col}_gt" in merged_df.columns:
                data_cols.append(f"{col}_gt")
            if f"{col}_pd" in merged_df.columns:
                data_cols.append(f"{col}_pd")

        return merged_df[base_cols + data_cols].copy()


    # 個別HTMLレポート生成 (HTML Report)
    def _export_html_report(self, merged_df: pandas.DataFrame, output_path: Path) -> None:
        """Pandas DataFrameから直接視認性の高い差分HTMLを生成・保存する"""

        # HTMLbody部のテーブルを構築
        ordered_cols = self._determine_report_column_order(merged_df)
        html_table = self._build_html_table(merged_df, ordered_cols)

        # CSS定義
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

        # フルHTMLの構築
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
        """データフレームからHTMLテーブルのタグ(文字列)を構築する"""
        lines = ['<table>', '<thead>', '<tr><th class="status-col">@@</th>']

        # 1行目: 列名
        for col in ordered_cols:
            lines.append(f'<th>{col}</th>')
        lines.append('</tr>')

        # 2行目: 列ステータス (--- / +++)
        lines.append('<tr class="col-status-row"><td class="status-col">@@</td>')
        for col in ordered_cols:
            has_gt = f"{col}_gt" in merged_df.columns
            has_pd = f"{col}_pd" in merged_df.columns
            if has_gt and not has_pd: lines.append('<td class="cell-missing">---</td>')
            elif not has_gt and has_pd: lines.append('<td class="cell-excess">+++</td>')
            else: lines.append('<td></td>')
        lines.append('</tr></thead><tbody>')

        # データ行
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
        """
        全評価データから統計情報を抽出し、サマリーレポートをセッションフォルダ直下にCSV出力する。
        """
        # フォルダは切らずに、ファイル名でサマリーであることを明示
        summary_path = self.session_dir / "summary_report.csv"

        file_metrics = []
        for file_name, df in all_results:
            # データ行のみを抽出
            if df.empty:
                continue

            # --- 行の統計 ---
            missing_rows = len(df[df['row_presence'] == 'left_only'])
            excess_rows = len(df[df['row_presence'] == 'right_only'])

            # --- 列（カラム）の統計 ---
            # 接尾辞を除いたベースとなる列名セットを作成
            gt_bases = {col.replace('_gt', '') for col in df.columns if col.endswith('_gt')}
            pd_bases = {col.replace('_pd', '') for col in df.columns if col.endswith('_pd')}
            # 欠損列: GTにはあるがPDにはない列
            missing_cols = len(gt_bases - pd_bases)
            # 過剰列: PDにはあるがGTにはない列
            excess_cols = len(pd_bases - gt_bases)

            # --- 指標の集計 ---
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

        # CSV保存（精度が低い順にソートして、改善優先度を見やすくする）
        file_summary_df = pandas.DataFrame(file_metrics)
        file_summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

        # コンソール表示
        logging.info(f"📊 Summary Report Created: {summary_path}\n")


    # ==========================================
    # ユーティリティ・計算処理
    # ==========================================
    @staticmethod
    def _normalize_text(text: str) -> str:
        """比較のノイズとなる記号を除去"""
        return re.sub(r'[【】\(\)（）※\*＊,、\s\t]', '', str(text))


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
        # "_gt", "_pd"で終わる列をそれぞれ抽出
        gt_cols = [col for col in row.index if col.endswith('_gt')]

        item_count = 0
        match_count = 0

        for gt_col in gt_cols:
            gt_val = str(row[gt_col]) if pandas.notna(row[gt_col]) else ""
            if gt_val == "":
                continue

            item_count += 1

            pd_col = gt_col.replace('_gt', '_pd')
            if pd_col in row.index:
                # 値の取得
                pd_val = str(row[pd_col]) if pandas.notna(row[pd_col]) else ""

                # 一致判定（文字列として比較）
                if gt_val == pd_val:
                    match_count += 1

        accuracy = (match_count / item_count) * 100 if item_count > 0 else 0
        accuracy = round(accuracy, 2)

        # 3つの値をセットで返す
        return pandas.Series([item_count, match_count, accuracy])


    def _extract_differences(self, df: pandas.DataFrame) -> pandas.DataFrame:
        """不一致行のみを抽出する（並び順は抽出元の自然な状態を維持する）"""
        # ソート処理を削除し、DataFrameの元の綺麗な並び順を維持したまま抽出する
        return df[(df['accuracy'] < 100) | (df['row_presence'] != 'both')].copy()
    