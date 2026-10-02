# standard library
import logging
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import cast, List, Tuple, Dict, Optional
from collections import Counter
from src.eval.logical_formids import logical_gt_formids
# third-party
import Levenshtein
import pandas
# local
from src import constants as const
from src.utils import fileutils 
from src.eval.excel_exporter import KessanExcelExporter
from src.service.classification_service import ClassificationService

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
        self.classification_service = ClassificationService(self.FORM_ID_MAP)

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

            # CSVデータ読込。
            # 複数帳票ページのdetailは、物理ページへ連結したCSVではなく、
            # そのGT detailが属する論理帳票のregion CSVだけを使う。
            # 分類はsidecarの全regionを使うため、ここで他帳票を捨てても分類5/5には影響しない。
            pd_load_file = pd_file
            ocr_scored_formids = []
            ocr_unscored_formids = []
            if "_detail" in pd_file.name:
                m = re.match(r'(.+)_([0-9]+)_detail\.csv$', pd_file.name)
                sidecar_path = self.predictions_dir / '.logical_region_formids.json'
                if m and sidecar_path.exists():
                    orig_name, page_index_text = m.group(1), m.group(2)
                    page_index = int(page_index_text)
                    gt_class_file = self.ground_truth_dir / f'{orig_name}_{page_index}.csv'
                    try:
                        sidecar = json.loads(sidecar_path.read_text(encoding='utf-8'))
                        base_gt_ids = []
                        if gt_class_file.exists():
                            gt_class_df = pandas.read_csv(gt_class_file, dtype=str, keep_default_na=False)
                            if 'formid' in gt_class_df.columns:
                                base_gt_ids = [str(x).strip() for x in gt_class_df['formid'].tolist() if str(x).strip()]

                        region_items = sidecar.get(orig_name, {}).get(str(page_index), [])
                        # GT分類CSVが表す帳票と同じformidのregionを「全部」使う。
                        # P1のBSは左右2領域で1つのGT明細を構成するため、1件目だけ選ぶと
                        # 右半分/左半分のどちらかしか採点できない。重複を保持したままregion順に連結する。
                        matching_items = [
                            x for x in region_items
                            if str(x.get('formid', '')).strip() in base_gt_ids and x.get('detail_file')
                        ]
                        matching_items.sort(key=lambda x: int(x.get('region', 0) or 0))
                        ocr_scored_formids = [str(x.get('formid', '')).strip() for x in matching_items]
                        ocr_unscored_formids = [
                            str(x.get('formid', '')).strip() for x in region_items
                            if str(x.get('formid', '')).strip() in self.FORM_ID_MAP
                            and str(x.get('formid', '')).strip() not in base_gt_ids
                        ]

                        candidates = []
                        for item in matching_items:
                            candidate = self.predictions_dir / '.logical_region_details' / str(item['detail_file'])
                            if candidate.exists():
                                candidates.append((item, candidate))

                        if len(candidates) == 1:
                            pd_load_file = candidates[0][1]
                            logging.info('  🧩 P%d OCR detail region選択: GT=%s -> R%s (%s)',
                                         page_index + 1, '/'.join(base_gt_ids), candidates[0][0].get('region'), candidates[0][1].name)
                        elif len(candidates) > 1:
                            # region CSVを元の物理順で連結。GTや値を見て「正解率が高い方」を選ばない。
                            temp_dir = self.session_dir / '.logical_ocr_inputs'
                            temp_dir.mkdir(parents=True, exist_ok=True)
                            combined_path = temp_dir / pd_file.name
                            frames = [pandas.read_csv(path, dtype=str, keep_default_na=False) for _, path in candidates]
                            pandas.concat(frames, ignore_index=True, sort=False).fillna('').to_csv(
                                combined_path, index=False, encoding='utf-8-sig'
                            )
                            pd_load_file = combined_path
                            logging.info('  🧩 P%d OCR detail region結合: GT=%s -> %s',
                                         page_index + 1, '/'.join(base_gt_ids),
                                         [f"R{x.get('region')}" for x, _ in candidates])
                    except Exception as e:
                        logging.warning('⚠ logical region detail選択に失敗。物理ページdetailへフォールバック: %s', e)

            # formid列を持つdetail GTは、帳票ごとに独立して比較する。
            # 例: P2のPL(amount_0/1)と製造原価(amount_0/1/2)を先に連結すると、
            # PLの「当期」列が製造原価側のamount_0へ誤対応して値が空になるため。
            grouped_merged = None
            if "_detail" in pd_file.name:
                m_group = re.match(r'(.+)_([0-9]+)_detail\.csv$', pd_file.name)
                sidecar_path_group = self.predictions_dir / '.logical_region_formids.json'
                if m_group and sidecar_path_group.exists():
                    try:
                        gt_probe = pandas.read_csv(gt_file, dtype=str, keep_default_na=False, nrows=2)
                        if 'formid' in gt_probe.columns:
                            orig_group, page_group_text = m_group.group(1), m_group.group(2)
                            sidecar_group = json.loads(sidecar_path_group.read_text(encoding='utf-8'))
                            region_group = sidecar_group.get(orig_group, {}).get(str(int(page_group_text)), [])
                            grouped_merged, ocr_scored_formids, ocr_unscored_formids = self._compare_detail_by_formid(
                                gt_file, orig_group, int(page_group_text), region_group
                            )
                    except Exception as e:
                        logging.warning('⚠ 帳票別OCR比較に失敗。従来比較へフォールバック: %s', e)

            # P3のGT detailには formid 列が無い旧マスタもある。
            # その場合 _compare_detail_by_formid() には入らないため、従来比較ルート側でも
            # 01_050_02 を検出して横持ち -> 25行縦持ちへ変換する。
            p3_position_mode = False
            if grouped_merged is None and "_detail" in pd_file.name and "01_050_02" in base_gt_ids:
                try:
                    raw_p3 = pandas.read_csv(pd_load_file, dtype=str, keep_default_na=False)
                    normalized_p3 = self._normalize_equity_matrix_detail(raw_p3)
                    if normalized_p3 is not None and not normalized_p3.empty and list(normalized_p3.columns) == ["account", "amount_0"]:
                        temp_dir = self.session_dir / '.logical_ocr_inputs'
                        temp_dir.mkdir(parents=True, exist_ok=True)
                        p3_path = temp_dir / f"{pd_file.stem}_P3_vertical.csv"
                        normalized_p3.to_csv(p3_path, index=False, encoding='utf-8-sig')
                        pd_load_file = p3_path
                        p3_position_mode = True
                        logging.info("  ↕ P%d P3旧GTルート: 横持ち -> 25行縦持ちへ変換", page_index + 1)
                except Exception as e:
                    logging.warning("⚠ P3旧GTルートの縦持ち変換に失敗: %s", e)

            if grouped_merged is None:
                gt_df, pd_df = self._load_csv_to_dataframe(gt_file, pd_load_file)
                if gt_df is None or pd_df is None:
                    continue
            else:
                gt_df = pd_df = None

            # ★分類CSVは、fuzzy alignment前の生formidを全件退避する。
            # GTが1行、Predictionが複数行でも2件目以降を落とさない。
            raw_gt_formids = []
            raw_pd_formids = []
            if "_detail" not in pd_file.name:
                if "formid" in gt_df.columns:
                    raw_gt_formids = [str(v).strip() for v in gt_df["formid"].tolist()
                                      if str(v).strip() and str(v).strip().lower() != "nan"]
                if "formid" in pd_df.columns:
                    raw_pd_formids = [str(v).strip() for v in pd_df["formid"].tolist()
                                      if str(v).strip() and str(v).strip().lower() != "nan"]

            if grouped_merged is None:
                # 正解データと対象データの比較すべき行列ペアを特定
                # P3旧GTは先頭に「株主資本」という階層見出しを1行持つが、
                # AIRead横持ち表には対応するセルがない。これはOCR評価項目ではなく
                # 構造見出しなので、P3の位置比較時だけ除外する。
                if p3_position_mode and len(gt_df) == len(pd_df) + 1 and not gt_df.empty:
                    first_gt = str(gt_df.iloc[0, 0]).strip()
                    if first_gt == "株主資本":
                        gt_df = gt_df.iloc[1:].reset_index(drop=True)
                        logging.info("  ↕ P%d P3旧GTルート: 先頭構造見出し『株主資本』をOCR採点から除外", page_index + 1)

                gt_df, pd_df = self._align_columns_by_fuzzy_match(gt_df, pd_df)
                if p3_position_mode:
                    # P3は既にGTと同じ25行位置へ展開済み。誤読された行名でfuzzy再配置しない。
                    gt_df = gt_df.reset_index(drop=True)
                    pd_df = pd_df.reset_index(drop=True)
                    gt_df['row_id'] = [f"r{i}" for i in range(len(gt_df))]
                    pd_df['row_id'] = [f"r{i}" for i in range(len(pd_df))]
                    logging.info("  ↕ P%d P3旧GTルート: 25行の論理位置で直接比較", page_index + 1)
                else:
                    gt_df, pd_df = self._align_rows_by_fuzzy_match(gt_df, pd_df)
                # 正解データと対象データをマージ
                merged_df = pandas.merge(gt_df, pd_df, on='row_id', how='outer', indicator='row_presence', validate="many_to_many").fillna('')

                # --- マージ後は行順が辞書順になってしまうので自然順に並び替え ---
                merged_df['r_num'] = merged_df['row_id'].str.extract(r'(\d+)').astype(int)
                merged_df['r_has_extra'] = merged_df['row_id'].str.startswith('extra').astype(int)
                merged_df = merged_df.sort_values(by=['r_num', 'r_has_extra'])
                merged_df = merged_df.drop(columns=['r_num', 'r_has_extra']).reset_index(drop=True)

                # 精度計算
                merged_df[['item_count', 'match_count', 'accuracy']] = merged_df.apply(self._calc_data_accuracy_by_row, axis=1)
            else:
                merged_df = grouped_merged

            if "_detail" in pd_file.name:
                merged_df.attrs["ocr_scored_formids"] = list(ocr_scored_formids)
                merged_df.attrs["ocr_unscored_formids"] = list(ocr_unscored_formids)

            # 分類判定はmerge後の列ではなく、AIRead生CSVの全formidを使う。
            if "_detail" not in pd_file.name:
                merged_df.attrs["raw_gt_formids"] = raw_gt_formids
                merged_df.attrs["raw_pd_formids"] = raw_pd_formids

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
                classification_details = []

                # Split-region classifications are captured before physical-page consolidation.
                # This is the source of truth for classification when present.
                logical_sidecar = {}
                sidecar_path = self.predictions_dir / ".logical_region_formids.json"
                if sidecar_path.exists():
                    try:
                        logical_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                        logging.info("🧩 分割帳票formidをsidecarから評価します: %s", sidecar_path)
                    except Exception as e:
                        logging.warning("⚠ logical formid sidecarを読めません: %s", e)

                for pdf_name, page_list in pdf_groups.items():
                    total_pages = 0
                    total_items = 0
                    total_matches = 0
                    page_df_list = []
                    detail_page_keys = set()

                    classification_total = 0
                    classification_matches = 0
                    
                    # ページごとの帳票タイトルを分類CSVから取得
                    page_title_map = {}
                    classification_ok_map = {}
                    logical_formids_map = {}
                    classification_result_map = {}

                    for page_file_name, df in page_list:
                        if "_detail" not in page_file_name:
                            page_key = page_file_name.replace(".csv", "")

                            result = self.classification_service.classify(
                                pdf_name=pdf_name,
                                page_file_name=page_file_name,
                                df=df,
                                logical_sidecar=logical_sidecar,
                            )

                            classification_result_map[page_key] = result

                            gt_ids = list(result["gt_formids"])
                            pd_ids = list(result["pd_formids"])

                            logical_formids_map[page_key] = list(gt_ids)

                            if gt_ids:
                                titles = [
                                    self.FORM_ID_MAP.get(fid, fid)
                                    for fid in gt_ids
                                ]
                                title_counts = Counter(titles)
                                shown = []

                                for title in dict.fromkeys(titles):
                                    n = title_counts[title]
                                    shown.append(
                                        f"{title} ? {n}" if n > 1 else title
                                    )

                                page_title_map[page_key] = " / ".join(shown)

                            classification_ok_map[page_key] = result["is_ocr_target"]

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
                            page_key = page_file_name.replace(".csv", "")
                            result = classification_result_map[page_key]

                            classification_details.append(result)

                            if result["is_target"]:
                                total_pages += 1
                                classification_total += result["classification_total"]
                                classification_matches += result["classification_matches"]

                            continue

                        # 明細データ(_detail)
                        page_key = page_file_name.replace("_detail.csv", "")
                        detail_page_keys.add(page_key)

                        item_sum = (
                            df["item_count"].sum()
                            if "item_count" in df.columns
                            else len(df)
                        )
                        match_sum = (
                            df["match_count"].sum()
                            if "match_count" in df.columns
                            else 0
                        )

                        # 分類〇のページだけOCR集計に入れる
                        is_classification_ok = classification_ok_map.get(page_key, True)

                        if is_classification_ok:
                            total_items += item_sum
                            total_matches += match_sum
                        else:
                            # Excel表示用に「分類不一致」を記録
                            df.attrs["classification_mismatch"] = True

                        # Excel詳細の水色サブヘッダは、実際にOCR採点したregionだけで区切る。
                        # 分類上の全帳票は別属性に保持し、GT明細が無い帳票は「評価対象外」と表示する。
                        all_logical_ids = list(logical_formids_map.get(page_key, []))
                        df.attrs["all_logical_gt_formids"] = all_logical_ids
                        scored_ids = list(df.attrs.get("ocr_scored_formids", []) or [])
                        df.attrs["logical_gt_formids"] = scored_ids or all_logical_ids

                        # GTの分類CSVから帳票タイトルを取得
                        detected_title = page_title_map.get(page_key)

                        # 念のためdetail内のformidも確認
                        if not detected_title:
                            detected_title = self._detect_title_by_formid(df)

                        if not detected_title:
                            # FORM_ID_MAPに未登録でも、分類対象かつdetailがあるページは
                            # Excel詳細から消さない。GUI/Markdownと同じ汎用タイトルにする。
                            detected_title = "決算書帳票"

                        if detected_title in form_totals:
                            # 決算5表として判定できたページだけ帳票別OCR精度へ集計
                            if is_classification_ok:
                                form_totals[detected_title][0] += match_sum
                                form_totals[detected_title][1] += item_sum

                        # 詳細Excelでは物理ページ番号を失わない。
                        # page_df_list の並び順をページ番号として扱うと、detail欠落ページがある時に
                        # 後続ページが前へ詰まり（例: P3がP2表示）、SummaryとExcelがずれる。
                        page_match = re.search(r'_(\d+)_detail\.csv$', page_file_name)
                        physical_page_no = int(page_match.group(1)) + 1 if page_match else 0
                        df.attrs["physical_page_no"] = physical_page_no
                        page_df_list.append((detected_title, df))

                    # 分類CSVは存在するがdetail CSVが存在しないページをExcel表示用に残す
                    for page_key, page_title in page_title_map.items():
                        if page_key not in detail_page_keys:
                            missing_df = pandas.DataFrame()
                            missing_df.attrs["missing_detail"] = True
                            page_match = re.search(r'_(\d+)$', page_key)
                            physical_page_no = int(page_match.group(1)) + 1 if page_match else 0
                            missing_df.attrs["physical_page_no"] = physical_page_no
                            page_df_list.append((page_title, missing_df))

                    # detail有無に関係なく、必ず元PDFの物理ページ順に戻す。
                    page_df_list.sort(key=lambda item: int(item[1].attrs.get("physical_page_no", 10**9)))
                            
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

                KessanExcelExporter.export_kessan_report(
                    excel_output_path, summary_list, detail_dfs, classification_details
                )
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
    def _normalize_equity_matrix_detail(self, df: pandas.DataFrame) -> pandas.DataFrame:
        """01_050_02 の横持ち表を、GTの25行構造と同じ位置へ展開する。

        OCR文字・OCR数値は補正しない。GTにだけ存在する階層見出し位置は空行にし、
        AIReadが認識した列見出し・行見出し・値を物理位置だけで縦持ちへ移す。
        """
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

        # GTの行順そのものに合わせた25行。3,4番目はGT側の
        # 「利益剰余金」「その他利益剰余金」に対応するが、AIReadに直接の認識値が
        # 無いため空欄のままにする（正解文字は絶対に注入しない）。
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

    def _compare_detail_by_formid(self, gt_file: Path, orig_name: str, page_index: int, region_items: list):
        """formid付きGT detailを、AIReadの同一formid regionと帳票単位で比較する。

        1物理ページに複数帳票がある場合、列構造が異なるregionを先に連結すると
        fuzzy column alignmentが別帳票の列へ吸われる。そこで帳票ごとに独立して
        column/row alignmentを行い、採点後のDataFrameだけを連結する。
        """
        try:
            gt_all = pandas.read_csv(gt_file, dtype=str, keep_default_na=False)
        except Exception as e:
            logging.warning("formid付きGT detail読込失敗: %s", e)
            return None, [], []
        if "formid" not in gt_all.columns:
            return None, [], []

        gt_ids = [str(v).strip() for v in gt_all["formid"].tolist() if str(v).strip()]
        ordered_ids = list(dict.fromkeys(gt_ids))
        merged_parts = []
        scored_ids = []
        temp_dir = self.session_dir / '.logical_ocr_inputs'
        temp_dir.mkdir(parents=True, exist_ok=True)

        for seq, formid in enumerate(ordered_ids, start=1):
            gt_part = gt_all[gt_all["formid"].astype(str).str.strip() == formid].drop(columns=["formid"])
            candidates = []
            for item in sorted(region_items, key=lambda x: int(x.get('region', 0) or 0)):
                if str(item.get('formid', '')).strip() != formid or not item.get('detail_file'):
                    continue
                path = self.predictions_dir / '.logical_region_details' / str(item['detail_file'])
                if path.exists():
                    candidates.append((item, path))
            if not candidates:
                logging.warning("  ⚠ P%d OCR detail: GT=%s に対応するregion detailなし", page_index + 1, formid)
                # 予測空CSVを作り、GT全項目を不一致として残す
                pd_part = pandas.DataFrame(columns=gt_part.columns)
            else:
                frames = [pandas.read_csv(path, dtype=str, keep_default_na=False) for _, path in candidates]
                pd_part = pandas.concat(frames, ignore_index=True, sort=False).fillna('')
                scored_ids.extend([formid] * len(candidates))
                logging.info("  🧩 P%d OCR帳票別比較: %s -> %s", page_index + 1, formid,
                             [f"R{x.get('region')}" for x, _ in candidates])

            # 株主資本等変動計算書だけはAIReadが横持ちマトリクスで返すため、
            # OCR文字を補正せず、比較用の縦持ちへ展開してから既存ロジックへ渡す。
            if formid == "01_050_02" and not pd_part.empty:
                pd_part = self._normalize_equity_matrix_detail(pd_part)
                logging.info("  ↕ P%d 株主資本等変動計算書: 横持ち -> 縦持ち比較へ変換 (%d行)",
                             page_index + 1, len(pd_part))

            gt_tmp = temp_dir / f"{orig_name}_{page_index}_GT_{seq}.csv"
            pd_tmp = temp_dir / f"{orig_name}_{page_index}_PD_{seq}.csv"
            gt_part.to_csv(gt_tmp, index=False, encoding='utf-8-sig')
            pd_part.to_csv(pd_tmp, index=False, encoding='utf-8-sig')
            gt_df, pd_df = self._load_csv_to_dataframe(gt_tmp, pd_tmp)
            if gt_df is None or pd_df is None:
                continue
            # P3の先頭「株主資本」は階層見出しで、横持ちAIRead表に対応セルがない。
            # 位置対応の前にこの1行だけ外し、25行対25行で比較する。
            if formid == "01_050_02" and len(gt_df) == len(pd_df) + 1 and not gt_df.empty:
                first_gt = str(gt_df.iloc[0, 0]).strip()
                if first_gt == "株主資本":
                    gt_df = gt_df.iloc[1:].reset_index(drop=True)
                    logging.info("  ↕ P%d 株主資本等変動計算書: 先頭構造見出し『株主資本』をOCR採点から除外", page_index + 1)
            gt_df, pd_df = self._align_columns_by_fuzzy_match(gt_df, pd_df)
            if formid == "01_050_02":
                # 株主資本等変動計算書は上でGTと同じ論理位置へ25行展開済み。
                # ここでfuzzy行寄せを行うと、OCR誤読された行名の類似度が低いため
                # 正しい物理位置から後半へ飛ばされる。P3だけ位置対応で比較する。
                gt_df = gt_df.reset_index(drop=True)
                pd_df = pd_df.reset_index(drop=True)
                gt_df['row_id'] = [f"r{i}" for i in range(len(gt_df))]
                pd_df['row_id'] = [f"r{i}" for i in range(len(pd_df))]
                logging.info("  ↕ P%d 株主資本等変動計算書: 25行の論理位置で直接比較", page_index + 1)
            else:
                gt_df, pd_df = self._align_rows_by_fuzzy_match(gt_df, pd_df)
            part = pandas.merge(gt_df, pd_df, on='row_id', how='outer', indicator='row_presence', validate='many_to_many')
            for _col in part.columns:
                if _col != 'row_presence':
                    part[_col] = part[_col].fillna('')
            part[['item_count', 'match_count', 'accuracy']] = part.apply(self._calc_data_accuracy_by_row, axis=1)
            # 帳票をまたいでrow_idが衝突しないようにする
            part['row_id'] = part['row_id'].astype(str).map(lambda x: f"f{seq}_{x}")
            part['logical_formid'] = formid
            merged_parts.append(part)

        if not merged_parts:
            return None, [], []
        merged = pandas.concat(merged_parts, ignore_index=True, sort=False)
        for _col in merged.columns:
            if _col != 'row_presence':
                merged[_col] = merged[_col].fillna('')
        unscored = [
            str(x.get('formid', '')).strip() for x in region_items
            if str(x.get('formid', '')).strip() in self.FORM_ID_MAP
            and str(x.get('formid', '')).strip() not in ordered_ids
        ]
        merged.attrs['ocr_scored_formids'] = scored_ids
        merged.attrs['ocr_unscored_formids'] = unscored
        merged.attrs['logical_detail_grouped'] = True
        return merged, scored_ids, unscored

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

        # CSVのヘッダ名は列対応の判定には使うが、OCR正解率の採点対象にはしない。
        # 以前は account / amount_0 / amount_1 等を1データ行として追加していたため、
        # ヘッダ一致が「OCR正解1件」として混入していた。
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

        # aligned の並び順そのものを row_id にする。
        # 以前は Prediction 側だけの行を extra_r0, extra_r1... としていたため、
        # 後段の自然順ソートで r0, extra_r0, r1, extra_r1... のように
        # 本来の位置から離れて「互い違い」に表示されることがあった。
        for pos, (gt_idx, pd_idx) in enumerate(aligned):
            row_id = f"r{pos}"
            if gt_idx is not None:
                gt_df.loc[gt_idx, "row_id"] = row_id
            if pd_idx is not None:
                pd_df.loc[pd_idx, "row_id"] = row_id

        # 念のため、対応復元に含まれなかった行があれば末尾へ送る。
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
        
        # CSVヘッダは _load_csv_to_dataframe() で既に列名として除外済み。
        # ここで r0 を除外すると、各帳票の「最初の実データ行」を採点しなくなるため、
        # row_id による特別扱いはしない。
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

        # 分母はGT（正解マスタ）に存在する評価項目だけで固定する。
        # Prediction側だけに存在する追加列は、列ずれや帳票固有の余分な出力であり、
        # ここで分母へ加えると同じGTでもAIRead出力形状によって総項目数が変動する。
        # GT空欄 / Prediction値ありの不一致は、対応済みの *_gt / *_pd ペア側で判定する。

        accuracy = (match_count / item_count) * 100 if item_count > 0 else 0
        accuracy = round(accuracy, 2)

        return pandas.Series([item_count, match_count, accuracy])

    def _extract_differences(self, df: pandas.DataFrame) -> pandas.DataFrame:
        """不一致行のみを抽出する（並び順は抽出元の自然な状態を維持する）"""
        return df[(df['accuracy'] < 100) | (df['row_presence'] != 'both')].copy()
    