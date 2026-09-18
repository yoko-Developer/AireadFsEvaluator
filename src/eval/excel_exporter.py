from pathlib import Path
from typing import List, Dict, Any, Tuple
import re
import os
import csv
import pandas as pd
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

class KessanExcelExporter:
    """
    決算5表評価結果をセル単位比較Excelとして出力するクラス（formidによる動的タイトル決定対応版）
    """

    PASTEL_PINK_FILL = PatternFill(start_color="F875DD", end_color="F875DD", fill_type="solid")
    LIGHT_BLUE_FILL = PatternFill(start_color="E1F5FE", end_color="E1F5FE", fill_type="solid")
    SUBTOTAL_FILL = PatternFill(start_color="F5E6FA", end_color="F5E6FA", fill_type="solid")
    ALERT_FILL = PatternFill(start_color="FF6EC7", end_color="FF6EC7", fill_type="solid")
    PAGE_TITLE_FILL = PatternFill(start_color="F0C0FE", end_color="F0C0FE", fill_type="solid")
    HEADER_ROW_FILL = PatternFill(start_color="F1F3F5", end_color="F1F3F5", fill_type="solid")

    TITLE_FONT = Font(name="Yu Gothic", size=14, bold=True, color="000000")
    HEADER_FONT = Font(name="Yu Gothic", size=11, bold=True, color="FFFFFF")
    REGULAR_FONT = Font(name="Yu Gothic", size=10, color="000000")
    HEADER_ROW_FONT = Font(name="Yu Gothic", size=10, bold=True, color="495057")
    SUBTOTAL_FONT = Font(name="Yu Gothic", size=10, bold=True, color="4A148C")
    TOTAL_FONT = Font(name="Yu Gothic", size=11, bold=True, color="000000")
    PAGE_TITLE_FONT = Font(name="Yu Gothic", size=10, bold=True, color="4A148C")
    ALERT_FONT = Font(name="Yu Gothic", size=10, bold=True, color="FFFFFF")

    THIN_BORDER = Border(
        left=Side(style='thin', color='B0BEC5'),
        right=Side(style='thin', color='B0BEC5'),
        top=Side(style='thin', color='B0BEC5'),
        bottom=Side(style='thin', color='B0BEC5')
    )

    DOUBLE_BOTTOM_BORDER = Border(
        left=Side(style='thin', color='B0BEC5'),
        right=Side(style='thin', color='B0BEC5'),
        top=Side(style='thin', color='B0BEC5'),
        bottom=Side(style='double', color='000000')
    )

    SYSTEM_KEYS = {"page", "formid", "account", "amount_0", "amount_1", "amount_2", "amount_3", "amount", "金額"}

    # formidから帳票タイトルへのマッピング
    FORM_ID_MAP = {
        "01_010_02": "貸借対照表 (BS)",
        "01_020_02": "損益計算書 (PL)",
        "01_030_02": "製造原価報告書",
        "01_040_02": "販売費及び一般管理費明細書",
        "01_050_02": "株主資本等変動計算書",
        "01_060_02": "キャッシュ・フロー計算書",
        "01_070_02": "個別注記表"
    }

    @classmethod
    def clean_str(cls, val: Any) -> str:
        if pd.isna(val) or val is None:
            return ""
        s = str(val).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s

    @classmethod
    def normalize_text(cls, text: str) -> str:
        text_str = cls.clean_str(text)
        return re.sub(r'[\s\t\u3000]', '', text_str)

    @classmethod
    def is_system_header_row(cls, gt_text: str, pd_text: str) -> bool:
        clean_gt = cls.normalize_text(gt_text).lower()
        clean_pd = cls.normalize_text(pd_text).lower()
        return clean_gt in cls.SYSTEM_KEYS or clean_pd in cls.SYSTEM_KEYS

    @classmethod
    def get_title_from_df(cls, df_page: pd.DataFrame, default_title: str) -> str:
        """DataFrame内の全セルからformidを検索し、正しい帳票名を取得する"""
        try:
            for col in df_page.columns:
                for val in df_page[col].dropna():
                    clean_v = cls.clean_str(val)
                    for f_id, f_name in cls.FORM_ID_MAP.items():
                        if f_id in clean_v:
                            return f_name
        except Exception:
            pass
        return default_title
    
    @classmethod
    def detect_page_sections(cls, df_page: pd.DataFrame, primary_title: str) -> List[Dict[str, Any]]:
        """1物理ページ内で、評価対象として特定できる論理帳票だけを分離する。

        重要: 「科目」が再登場しただけでは分割しない。
        現時点では、再登場後に棚卸資産特有の科目が複数確認できた場合のみ
        「棚卸資産」として独立評価する。特定できない候補は primary_title に含めたままにする。
        """
        if df_page is None or df_page.empty:
            return [{"start": 0, "end": 0, "label": primary_title, "inferred": False}]

        accounts = []
        for _, row in df_page.iterrows():
            gt = cls.clean_str(row.get("c0_gt", ""))
            pdv = cls.clean_str(row.get("c0_pd", ""))
            accounts.append(gt or pdv)

        # 「account」はCSVのシステムヘッダなので帳票境界には使わない。
        # 最初の「科目」は主帳票自身のヘッダ。2回目以降の「科目」だけを
        # ページ内の別帳票候補として扱う。
        subject_headers = [
            i for i, text in enumerate(accounts)
            if cls.normalize_text(text) == "科目"
        ]
        candidates = subject_headers[1:]

        inventory_terms = {
            cls.normalize_text(v) for v in
            {"製品", "商品", "原材料", "材料", "仕掛品", "半成品", "仕掛品(半成品)", "貯蔵品"}
        }

        inventory_start = None
        for pos, start in enumerate(candidates):
            end = candidates[pos + 1] if pos + 1 < len(candidates) else len(accounts)
            sec_norms = {cls.normalize_text(v) for v in accounts[start:end] if cls.normalize_text(v)}
            hit_count = len(inventory_terms & sec_norms)
            if hit_count >= 2:
                inventory_start = start
                break

        if inventory_start is None:
            return [{"start": 0, "end": len(accounts), "label": primary_title, "inferred": False}]

        return [
            {"start": 0, "end": inventory_start, "label": primary_title, "inferred": False},
            {"start": inventory_start, "end": len(accounts), "label": "棚卸資産", "inferred": True},
        ]

    @classmethod
    def calc_section_accuracy(cls, df_page: pd.DataFrame, start: int, end: int) -> Tuple[int, int, float]:
        """詳細DataFrameの指定範囲を、Excel詳細と同じセル単位ルールで採点する。"""
        total = 0
        matches = 0
        c_indices = sorted({
            int(m.group(1))
            for col in df_page.columns
            for m in [re.fullmatch(r"c(\d+)_gt", str(col))]
            if m
        })
        rows = list(df_page.iloc[start:end].iterrows())
        for _, row in rows:
            c0_gt = cls.clean_str(row.get("c0_gt", ""))
            c0_pd = cls.clean_str(row.get("c0_pd", ""))
            if cls.is_system_header_row(c0_gt, c0_pd):
                continue
            for i in c_indices:
                gt = cls.clean_str(row.get(f"c{i}_gt", ""))
                pdv = cls.clean_str(row.get(f"c{i}_pd", ""))
                ngt, npd = cls.normalize_text(gt), cls.normalize_text(pdv)
                if not ngt and not npd:
                    continue
                total += 1
                if ngt == npd:
                    matches += 1
        acc = matches / total if total else 0.0
        return matches, total, acc

    @classmethod
    def get_inventory_stats(cls, page_df_list: List[Tuple[str, pd.DataFrame]]) -> Tuple[int, int, float]:
        """1PDF内の棚卸資産セクションだけを集計する。"""
        matches = total = 0
        for raw_title, df_page in page_df_list:
            if bool(df_page.attrs.get("missing_detail", False)) or bool(df_page.attrs.get("classification_mismatch", False)):
                continue
            primary = cls.get_title_from_df(df_page, raw_title)
            for sec in cls.detect_page_sections(df_page, primary):
                if sec["label"] == "棚卸資産":
                    m, t, _ = cls.calc_section_accuracy(df_page, sec["start"], sec["end"])
                    matches += m
                    total += t
        return matches, total, (matches / total if total else 0.0)

    @classmethod
    def get_classification_stats(cls, page_df_list: List[Tuple[str, pd.DataFrame]]) -> Tuple[int, int]:
        """Markdown/GUI本体と同じ考え方で分類対象ページを集計する。

        - 表紙など「評価対象外（不明）」だけを分母から除外
        - 分類不一致ページは、明細CSVがなくても分母に含めて不正解にする
        - 「決算書帳票」のような汎用タイトルでも、明細が存在して分類一致なら正解として数える
        - 個別注記表など既知formidの分類のみ評価ページも分母に含める
        """
        known_titles = set(cls.FORM_ID_MAP.values())
        matches = total = 0

        for raw_title, df_page in page_df_list:
            is_missing_detail = bool(df_page.attrs.get("missing_detail", False))
            is_classification_mismatch = bool(df_page.attrs.get("classification_mismatch", False))
            title = cls.get_title_from_df(df_page, raw_title)

            # 分類不一致は必ず「分類対象の不正解」。
            # 明細CSVなしだからといって分母から落としてはいけない。
            if is_classification_mismatch:
                total += 1
                continue

            # 明細が存在するページは evaluator が分類一致として detail_dfs に載せているため、
            # formidから帳票名を特定できない「決算書帳票」等も分類正解として数える。
            if not is_missing_detail:
                total += 1
                matches += 1
                continue

            # 明細CSVがなくても、既知帳票として分類だけ評価されるページは正解扱い。
            if title in known_titles:
                total += 1
                matches += 1
                continue

            # それ以外（決算報告書の表紙など）は「評価対象外（不明）」なので数えない。

        return matches, total

    @classmethod
    def get_classification_stats_from_results(
        cls, output_path: Path
    ) -> Dict[str, Tuple[int, int]]:
        """GUI/Markdownと同じ full_comparison 分類CSVからPDF別の分類結果を作る。

        detail_dfs から分類を推測しない。
        results 配下の通常CSV（_detail以外）の c1_gt / c1_pd を直接読み、
        GT formid が存在するページだけを分類対象にする。
        同名CSVが複数ある場合はGUIと同じく最新更新ファイルを採用する。
        """
        results_dir = Path(output_path).parent
        if results_dir.name.lower() != "results":
            # 通常は results/決算5表_精度評価マトリックス.xlsx。
            # 念のため親を遡って results を探す。
            for parent in Path(output_path).parents:
                if parent.name.lower() == "results":
                    results_dir = parent
                    break

        latest_files_map: Dict[str, Tuple[Path, float]] = {}

        if results_dir.exists():
            for root, _, files in os.walk(results_dir):
                for name in files:
                    if not name.endswith(".csv"):
                        continue
                    if "full_comparison" not in name:
                        continue
                    if "_detail" in name:
                        continue

                    fp = Path(root) / name
                    try:
                        mtime = fp.stat().st_mtime
                    except OSError:
                        continue

                    prev = latest_files_map.get(name)
                    if prev is None or mtime > prev[1]:
                        latest_files_map[name] = (fp, mtime)

        stats: Dict[str, List[int]] = {}

        for fp, _ in latest_files_map.values():
            gt_formid = ""
            pd_formid = ""

            try:
                with open(fp, "r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        gt_raw = str(row.get("c1_gt", "") or "").strip()
                        pd_raw = str(row.get("c1_pd", "") or "").strip()

                        # c1_gt/c1_pd は formid だけとは限らないため、
                        # セル値の完全一致ではなく既知formidを文字列中から抽出する。
                        if not gt_formid:
                            for f_id in cls.FORM_ID_MAP:
                                if f_id in gt_raw:
                                    gt_formid = f_id
                                    break

                        if not pd_formid:
                            for f_id in cls.FORM_ID_MAP:
                                if f_id in pd_raw:
                                    pd_formid = f_id
                                    break

                        if gt_formid and pd_formid:
                            break
            except Exception:
                continue

            # GT側に既知formidが無いページ（決算報告書の表紙など）だけ評価対象外。
            # PD側が不明・別formidでもGTが既知なら「分類不一致」として分母には残す。
            if not gt_formid:
                continue

            file_stem = (
                fp.name
                .replace("full_comparison_", "")
                .replace("diff_list_", "")
                .replace(".csv", "")
            )

            # 末尾 _0, _1 ... がページ番号なのでPDF名から外す。
            pdf_name = re.sub(r"_\d+$", "", file_stem)

            bucket = stats.setdefault(pdf_name, [0, 0])  # matches, total
            bucket[1] += 1
            if gt_formid == pd_formid:
                bucket[0] += 1

        return {name: (v[0], v[1]) for name, v in stats.items()}

    @classmethod
    def get_primary_statement_stats(cls, page_df_list: List[Tuple[str, pd.DataFrame]]) -> Dict[str, Tuple[int, int, float]]:
        """決算5表の主帳票を単独採点する。棚卸資産同居時は主帳票から切り離す。"""
        five_titles = {
            "貸借対照表 (BS)", "損益計算書 (PL)", "製造原価報告書",
            "販売費及び一般管理費明細書", "株主資本等変動計算書"
        }
        result: Dict[str, List[int]] = {}
        for raw_title, df_page in page_df_list:
            if bool(df_page.attrs.get("missing_detail", False)) or bool(df_page.attrs.get("classification_mismatch", False)):
                continue
            primary = cls.get_title_from_df(df_page, raw_title)
            if primary not in five_titles:
                continue
            main = cls.detect_page_sections(df_page, primary)[0]
            m, t, _ = cls.calc_section_accuracy(df_page, main["start"], main["end"])
            bucket = result.setdefault(primary, [0, 0])
            bucket[0] += m
            bucket[1] += t
        return {k: (v[0], v[1], (v[0] / v[1] if v[1] else 0.0)) for k, v in result.items()}

    @classmethod
    def export_kessan_report(
        cls, 
        output_path: Path, 
        summary_data: List[Dict[str, Any]], 
        detail_dfs: List[Tuple[str, List[Tuple[str, pd.DataFrame]]]],
        classification_details: List[Dict[str, Any]] = None
    ) -> None:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        # -------------------------------------------------------------
        # シート1: 📊 決算5表 マトリックス集計表
        # -------------------------------------------------------------
        ws_matrix = wb.create_sheet(title="マトリックス表")
        ws_matrix.views.sheetView[0].showGridLines = False

        ws_matrix.cell(row=1, column=1, value="決算5表 精度評価マトリックスレポート").font = cls.TITLE_FONT

        headers = [
            "No", "PDFファイル名", "総ページ数",
            "分類正解数", "分類総数", "分類正解率",
            "総項目数", "正解数", "正解率",
            "BS", "PL", "製造原価", "販管費", "株主資本", "棚卸資産"
        ]

        for col_idx, header in enumerate(headers, start=1):
            cell = ws_matrix.cell(row=2, column=col_idx, value=header)
            cell.fill = cls.PASTEL_PINK_FILL
            cell.font = cls.HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = cls.THIN_BORDER

        ws_matrix.row_dimensions[2].height = 28

        kessan_map = {
            "BS": ["BS", "BS_acc", "貸借対照表", "貸借対照表_acc"],
            "PL": ["PL", "PL_acc", "損益計算書", "損益計算書_acc"],
            "製造原価": ["製造原価", "製造原価_acc", "製造原価報告書", "製造原価報告書_acc"],
            "販管費": ["販管費", "販管費_acc", "販売費及び一般管理費明細書", "販売費及び一般管理費明細書_acc"],
            "株主資本": ["株主資本", "株主資本_acc", "株主資本等変動計算書", "株主資本等変動計算書_acc"]
        }

        # PDF名 -> 棚卸資産セクション単独の (正解数, 総項目数, 正解率)
        inventory_stats = {
            sheet_name: cls.get_inventory_stats(page_df_list)
            for sheet_name, page_df_list in detail_dfs
        }

        # 分類はGUI/Markdownと同じ results 配下の分類CSVを直接集計する。
        # detail_dfs からの推測は、分類×ページや「決算書帳票」でズレるため使わない。
        classification_stats = cls.get_classification_stats_from_results(output_path)

        # GUI/Markdownでは「決算報告書（表紙）」等の不明ページは
        # 分類評価の分母から除外される。
        # 一方 summary_data の classification_total は物理ページ数になる場合があるため、
        # detail_dfs に存在する「表紙」ページ数だけを明示的に差し引く。
        primary_statement_stats = {
            sheet_name: cls.get_primary_statement_stats(page_df_list)
            for sheet_name, page_df_list in detail_dfs
        }

        row_idx = 3
        for idx, data in enumerate(
            sorted(
                summary_data,
                key=lambda data: int(re.search(r'株式会社(\d+)', data.get("filename", "")).group(1))
                if re.search(r'株式会社(\d+)', data.get("filename", ""))
                else 999999999
            ),
            start=1
        ):

            ws_matrix.cell(row=row_idx, column=1, value=idx).alignment = Alignment(horizontal="center", vertical="center")
            ws_matrix.cell(row=row_idx, column=2, value=data.get("filename", "")).alignment = Alignment(horizontal="left", vertical="center")
            
            c3 = ws_matrix.cell(row=row_idx, column=3, value=data.get("total_pages", 0))
            c3.number_format = '#,##0'
            c3.alignment = Alignment(horizontal="center", vertical="center")

            # 分類集計は detail_dfs 側で「formid が判定できる分類対象ページ」だけを数える。
            # 表紙など formid 不明の評価対象外ページは分母から除外する。
            # summary_data の total_pages / classification_total をそのまま使うと、
            # 評価対象外ページまで分類総数に入るケースがあるため使用しない。
            filename = data.get("filename", "")

            # 分類は修正済みEvaluator本体の確定値をそのまま使用する。
            # Excel側では分類を再計算しない。
            classification_matches = int(data.get("classification_matches", 0) or 0)
            classification_total = int(data.get("classification_total", 0) or 0)

            c4 = ws_matrix.cell(row=row_idx, column=4, value=classification_matches)
            c4.number_format = '#,##0'
            c4.alignment = Alignment(horizontal="center", vertical="center")

            c5 = ws_matrix.cell(row=row_idx, column=5, value=classification_total)
            c5.number_format = '#,##0'
            c5.alignment = Alignment(horizontal="center", vertical="center")

            classification_acc = (
                classification_matches / classification_total
                if classification_total > 0
                else 0
            )

            c6 = ws_matrix.cell(row=row_idx, column=6, value=classification_acc)
            c6.number_format = '0.0%'
            c6.alignment = Alignment(horizontal="center", vertical="center")

            # OCR
            c7 = ws_matrix.cell(row=row_idx, column=7, value=data.get("total_items", 0))
            c7.number_format = '#,##0'
            c7.alignment = Alignment(horizontal="center", vertical="center")

            c8 = ws_matrix.cell(row=row_idx, column=8, value=data.get("total_matches", 0))
            c8.number_format = '#,##0'
            c8.alignment = Alignment(horizontal="center", vertical="center")

            ocr_acc = data.get("accuracy", 0.0) / 100.0
            c9 = ws_matrix.cell(row=row_idx, column=9, value=ocr_acc)
            c9.number_format = '0.0%'
            c9.alignment = Alignment(horizontal="center", vertical="center")
            
            kessan_types = ["BS", "PL", "製造原価", "販管費", "株主資本"]
            title_for_type = {
                "BS": "貸借対照表 (BS)",
                "PL": "損益計算書 (PL)",
                "製造原価": "製造原価報告書",
                "販管費": "販売費及び一般管理費明細書",
                "株主資本": "株主資本等変動計算書",
            }
            pdf_primary_stats = primary_statement_stats.get(filename, {})
            # ここはページ全体の旧summary値ではなく、detect_page_sections()で分けた
            # 論理帳票単独値だけを使う（例: 227 P3 販管費 57/59、棚卸資産 11/11）。
            for c_offset, k_type in enumerate(kessan_types, start=10):
                stat = pdf_primary_stats.get(title_for_type[k_type])
                c = ws_matrix.cell(row=row_idx, column=c_offset)
                if stat and stat[1] > 0:
                    c.value = stat[2]
                    c.number_format = '0.0%'
                else:
                    c.value = "-"
                c.alignment = Alignment(horizontal="center", vertical="center")

            # 棚卸資産はページ内論理帳票として独立採点（AIReadのformidとは別）
            inv_matches, inv_total, inv_acc = inventory_stats.get(filename, (0, 0, 0.0))
            c15 = ws_matrix.cell(row=row_idx, column=15)
            if inv_total > 0:
                c15.value = inv_acc
                c15.number_format = '0.0%'
            else:
                c15.value = "-"
            c15.alignment = Alignment(horizontal="center", vertical="center")

            for col in range(1, len(headers) + 1):
                c = ws_matrix.cell(row=row_idx, column=col)
                c.font = cls.REGULAR_FONT
                c.border = cls.THIN_BORDER

            row_idx += 1
            
        total_row = row_idx
        ws_matrix.cell(row=total_row, column=1, value="")
        ws_matrix.cell(
            row=total_row,
            column=2,
            value="【 累計合計/平均 】"
        ).alignment = Alignment(horizontal="center", vertical="center")

        # 総ページ数
        c3_tot = ws_matrix.cell(
            row=total_row,
            column=3,
            value=f"=SUM(C3:C{total_row-1})"
        )
        c3_tot.number_format = '#,##0'
        c3_tot.alignment = Alignment(horizontal="center", vertical="center")

        # 分類正解数
        c4_tot = ws_matrix.cell(
            row=total_row,
            column=4,
            value=f"=SUM(D3:D{total_row-1})"
        )
        c4_tot.number_format = '#,##0'
        c4_tot.alignment = Alignment(horizontal="center", vertical="center")

        # 分類総数
        c5_tot = ws_matrix.cell(
            row=total_row,
            column=5,
            value=f"=SUM(E3:E{total_row-1})"
        )
        c5_tot.number_format = '#,##0'
        c5_tot.alignment = Alignment(horizontal="center", vertical="center")

        # 分類正解率
        classification_tot_acc = ws_matrix.cell(
            row=total_row,
            column=6,
            value=f"=IF(E{total_row}>0,D{total_row}/E{total_row},0)"
        )
        classification_tot_acc.number_format = '0.0%'
        classification_tot_acc.alignment = Alignment(horizontal="center", vertical="center")

        # OCR総項目数
        c7_tot = ws_matrix.cell(
            row=total_row,
            column=7,
            value=f"=SUM(G3:G{total_row-1})"
        )
        c7_tot.number_format = '#,##0'
        c7_tot.alignment = Alignment(horizontal="center", vertical="center")

        # OCR正解数
        c8_tot = ws_matrix.cell(
            row=total_row,
            column=8,
            value=f"=SUM(H3:H{total_row-1})"
        )
        c8_tot.number_format = '#,##0'
        c8_tot.alignment = Alignment(horizontal="center", vertical="center")

        # OCR正解率
        ocr_tot_acc = ws_matrix.cell(
            row=total_row,
            column=9,
            value=f"=IF(G{total_row}>0,H{total_row}/G{total_row},0)"
        )
        ocr_tot_acc.number_format = '0.0%'
        ocr_tot_acc.alignment = Alignment(horizontal="center", vertical="center")

        # 帳票別平均
        col_letters = ['J', 'K', 'L', 'M', 'N', 'O']

        for c_let in col_letters:
            col_cell = ws_matrix.cell(
                row=total_row,
                column=openpyxl.utils.column_index_from_string(c_let)
            )
            col_cell.value = f'=IFERROR(AVERAGE({c_let}3:{c_let}{total_row-1}), "-")'
            col_cell.number_format = '0.0%'
            col_cell.alignment = Alignment(horizontal="center", vertical="center")
            
        for col in range(1, len(headers) + 1):
            c = ws_matrix.cell(row=total_row, column=col)
            c.font = cls.TOTAL_FONT
            c.fill = cls.LIGHT_BLUE_FILL
            c.border = cls.DOUBLE_BOTTOM_BORDER

        ws_matrix.column_dimensions['A'].width = 6
        ws_matrix.column_dimensions['B'].width = 35
        ws_matrix.column_dimensions['C'].width = 12
        ws_matrix.column_dimensions['D'].width = 12
        ws_matrix.column_dimensions['E'].width = 12
        ws_matrix.column_dimensions['F'].width = 14
        ws_matrix.column_dimensions['G'].width = 14
        ws_matrix.column_dimensions['H'].width = 12
        ws_matrix.column_dimensions['I'].width = 12

        for c_letter in col_letters:
            ws_matrix.column_dimensions[c_letter].width = 16
        ws_matrix.column_dimensions['O'].width = 16

        # -------------------------------------------------------------
        # シート2: 📊 分類結果マトリックス（ページ別）
        # -------------------------------------------------------------
        ws_class_matrix = wb.create_sheet(title="分類結果マトリックス")
        ws_class_matrix.views.sheetView[0].showGridLines = False
        ws_class_matrix.cell(row=1, column=1, value="帳票分類 ページ別マトリックス").font = cls.TITLE_FONT

        sorted_class_details = sorted(classification_details or [], key=lambda x: (
            int(re.search(r'株式会社(\d+)', str(x.get("filename", ""))).group(1))
            if re.search(r'株式会社(\d+)', str(x.get("filename", ""))) else 999999999,
            int(x.get("page", 999999999)) if str(x.get("page", "")).isdigit() else 999999999
        ))
        class_by_pdf = {}
        max_page = 0
        for item in sorted_class_details:
            filename = str(item.get("filename", ""))
            page = int(item.get("page", 0) or 0)
            class_by_pdf.setdefault(filename, {})[page] = item
            max_page = max(max_page, page)

        # 1ページにつき「総数・正解数・正解率」の3列。評価対象外は 0 / 0 / -。
        ws_class_matrix.merge_cells(start_row=2, start_column=1, end_row=3, end_column=1)
        ws_class_matrix.merge_cells(start_row=2, start_column=2, end_row=3, end_column=2)
        ws_class_matrix.cell(row=2, column=1, value="No")
        ws_class_matrix.cell(row=2, column=2, value="PDFファイル名")
        col = 3
        for page in range(1, max_page + 1):
            ws_class_matrix.merge_cells(start_row=2, start_column=col, end_row=2, end_column=col + 2)
            ws_class_matrix.cell(row=2, column=col, value=f"P{page}")
            for offset, label in enumerate(("総数", "正解数", "正解率")):
                ws_class_matrix.cell(row=3, column=col + offset, value=label)
            col += 3

        for r in (2, 3):
            for c in range(1, col):
                cell = ws_class_matrix.cell(row=r, column=c)
                cell.fill = cls.PASTEL_PINK_FILL
                cell.font = cls.HEADER_FONT
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                cell.border = cls.THIN_BORDER

        row = 4
        for pdf_no, (filename, page_map) in enumerate(class_by_pdf.items(), 1):
            ws_class_matrix.cell(row=row, column=1, value=pdf_no)
            ws_class_matrix.cell(row=row, column=2, value=filename)
            col = 3
            for page in range(1, max_page + 1):
                item = page_map.get(page)
                if item is None:
                    values = ("-", "-", "-")
                elif bool(item.get("is_target", False)):
                    passed = 1 if bool(item.get("is_match", False)) else 0
                    values = (1, passed, passed)
                else:
                    values = (0, 0, "-")
                for offset, value in enumerate(values):
                    cell = ws_class_matrix.cell(row=row, column=col + offset, value=value)
                    if offset == 2 and isinstance(value, (int, float)):
                        cell.number_format = '0.0%'
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                col += 3
            for c in range(1, col):
                cell = ws_class_matrix.cell(row=row, column=c)
                cell.font = cls.REGULAR_FONT
                cell.border = cls.THIN_BORDER
            row += 1

        ws_class_matrix.freeze_panes = "C4"
        ws_class_matrix.column_dimensions['A'].width = 6
        ws_class_matrix.column_dimensions['B'].width = 38
        for c in range(3, 3 + max_page * 3):
            ws_class_matrix.column_dimensions[get_column_letter(c)].width = 11

        # -------------------------------------------------------------
        # シート3: 📋 分類結果詳細
        # -------------------------------------------------------------
        ws_class = wb.create_sheet(title="分類結果詳細")
        ws_class.views.sheetView[0].showGridLines = False
        ws_class.cell(row=1, column=1, value="帳票分類結果詳細").font = cls.TITLE_FONT

        class_headers = [
            "No", "PDFファイル名", "Page", "正解帳票", "AIRead分類結果",
            "正解formid", "AIRead formid", "判定", "総数", "正解数", "正解率"
        ]
        for col_idx, header in enumerate(class_headers, start=1):
            cell = ws_class.cell(row=2, column=col_idx, value=header)
            cell.fill = cls.PASTEL_PINK_FILL
            cell.font = cls.HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = cls.THIN_BORDER

        def classification_sort_key(item):
            filename = str(item.get("filename", ""))
            m = re.search(r'株式会社(\d+)', filename)
            company_no = int(m.group(1)) if m else 999999999
            page = item.get("page", 999999999)
            try:
                page = int(page)
            except (TypeError, ValueError):
                page = 999999999
            return company_no, page, filename

        current_pdf = None
        pdf_no = 0
        row_idx_class = 3
        for item in sorted(classification_details or [], key=classification_sort_key):
            filename = str(item.get("filename", ""))
            if filename != current_pdf:
                pdf_no += 1
                current_pdf = filename

            is_target = bool(item.get("is_target", False))
            judgment = "○" if item.get("is_match", False) else ("×" if is_target else "―")
            values = [
                pdf_no, filename, item.get("page", ""),
                item.get("gt_title", ""), item.get("pd_title", ""),
                item.get("gt_formid", ""), item.get("pd_formid", ""), judgment,
                1 if is_target else 0,
                1 if item.get("is_match", False) else 0,
                (1 if item.get("is_match", False) else 0) if is_target else "-"
            ]
            for col_idx, value in enumerate(values, start=1):
                cell = ws_class.cell(row=row_idx_class, column=col_idx, value=value)
                cell.font = cls.REGULAR_FONT
                cell.border = cls.THIN_BORDER
                if col_idx == 11 and isinstance(value, (int, float)):
                    cell.number_format = '0.0%'
                cell.alignment = Alignment(
                    horizontal="left" if col_idx in {2, 4, 5} else "center",
                    vertical="center", wrap_text=True
                )
            row_idx_class += 1

        ws_class.freeze_panes = "A3"
        ws_class.auto_filter.ref = f"A2:K{max(2, row_idx_class - 1)}"
        for col_letter, width in {
            "A": 6, "B": 38, "C": 8, "D": 30, "E": 30,
            "F": 16, "G": 16, "H": 8, "I": 9, "J": 9, "K": 11
        }.items():
            ws_class.column_dimensions[col_letter].width = width

        # -------------------------------------------------------------
        # シート4以降: 📄 詳細シート
        # -------------------------------------------------------------
        def company_number(item):
            sheet_name = item[0]
            match = re.search(r'株式会社(\d+)', sheet_name)
            return int(match.group(1)) if match else 999999999

        for sheet_name, page_df_list in sorted(detail_dfs, key=company_number):

            # ファイル名の「株式会社○○○」から会社番号を取得してシート名にする
            company_match = re.search(r'株式会社(\d+)', sheet_name)
            if company_match:
                safe_title = company_match.group(1)
            else:
                safe_title = re.sub(r'[\\/*?:\[\]]', '', sheet_name)[:28]

            ws_detail = wb.create_sheet(title=safe_title)
            ws_detail.views.sheetView[0].showGridLines = False

            max_c_count = 1
            for _, df_p in page_df_list:
                gt_cols = [c for c in df_p.columns if re.match(r'^c\d+_gt$', c)]
                max_c_count = max(max_c_count, len(gt_cols))

            total_cols_count = 1 + (max_c_count * 3) + 1

            ws_detail.row_dimensions[1].height = 24
            ws_detail.row_dimensions[3].height = 22
            ws_detail.row_dimensions[4].height = 22

            # 対象PDFファイル名
            ws_detail.merge_cells(
                start_row=1,
                start_column=1,
                end_row=1,
                end_column=total_cols_count
            )
            file_cell = ws_detail.cell(
                row=1,
                column=1,
                value=f"対象PDF：{sheet_name}.pdf"
            )
            file_cell.font = cls.TITLE_FONT
            file_cell.alignment = Alignment(horizontal="left", vertical="center")

            ws_detail.merge_cells("A3:A4")
            ws_detail.cell(row=3, column=1, value="No")

            last_col_letter = get_column_letter(total_cols_count)
            ws_detail.merge_cells(f"{last_col_letter}3:{last_col_letter}4")
            ws_detail.cell(row=3, column=total_cols_count, value="行正解率")

            for c_i in range(max_c_count):
                start_c = 2 + (c_i * 3)
                end_c = start_c + 2
                start_let = get_column_letter(start_c)
                end_let = get_column_letter(end_c)

                grp_title = "科目" if c_i == 0 else f"金額{c_i}" if max_c_count > 2 else "金額"
                ws_detail.merge_cells(f"{start_let}3:{end_let}3")
                ws_detail.cell(row=3, column=start_c, value=grp_title)

                ws_detail.cell(row=4, column=start_c, value="マスタ")
                ws_detail.cell(row=4, column=start_c + 1, value="読み取り")
                ws_detail.cell(row=4, column=start_c + 2, value="判定")

            for r in [3, 4]:
                for c in range(1, total_cols_count + 1):
                    cell = ws_detail.cell(row=r, column=c)
                    cell.fill = cls.PASTEL_PINK_FILL
                    cell.font = cls.HEADER_FONT
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.border = cls.THIN_BORDER

            current_row = 5

            for page_no, (raw_p_title, df_page) in enumerate(page_df_list, start=1):
                # detail CSVが存在しないページかどうか
                is_missing_detail = bool(df_page.attrs.get("missing_detail", False))
                is_classification_mismatch = bool(df_page.attrs.get("classification_mismatch", False))

                # 通常ページはformidからタイトル取得、detailなしページはGTのタイトルをそのまま使う
                p_title = (
                    raw_p_title
                    if is_missing_detail or is_classification_mismatch
                    else cls.get_title_from_df(df_page, raw_p_title)
                )

                page_sections = (
                    cls.detect_page_sections(df_page, p_title)
                    if not is_missing_detail and not is_classification_mismatch
                    else [{"start": 0, "end": len(df_page), "label": p_title, "inferred": False}]
                )
                # 複数帳票ページだけ、各帳票の先頭に水色の帳票別ヘッダを表示する。
                # 1帳票ページは従来どおりピンクのページヘッダだけにする。
                section_start_map = (
                    {sec["start"]: sec for sec in page_sections}
                    if len(page_sections) > 1
                    else {}
                )
                section_end_map = {sec["end"]: sec for sec in page_sections}
                section_counts = {i: [0, 0] for i in range(len(page_sections))}  # total, matches

                # 水色ヘッダに帳票単独の総数・正解数・正解率を先に表示するため事前計算
                section_display_stats = {}
                for sec in page_sections:
                    sec_matches, sec_total, sec_acc = cls.calc_section_accuracy(
                        df_page, sec["start"], sec["end"]
                    )
                    section_display_stats[sec["start"]] = (sec_matches, sec_total, sec_acc)
                
                title_row_idx = current_row
                ws_detail.merge_cells(
                    start_row=title_row_idx,
                    start_column=1,
                    end_row=title_row_idx,
                    end_column=total_cols_count
                )
                ws_detail.row_dimensions[title_row_idx].height = 22
                current_row += 1
                
                # 分類が不一致のページは、OCR採点対象外として表示する
                if is_classification_mismatch:
                    ws_detail.merge_cells(
                        start_row=current_row,
                        start_column=1,
                        end_row=current_row,
                        end_column=total_cols_count
                    )

                    msg_cell = ws_detail.cell(
                        row=current_row,
                        column=1,
                        value="OCR評価対象外（分類不一致）"
                    )
                    msg_cell.fill = cls.HEADER_ROW_FILL
                    msg_cell.font = cls.HEADER_ROW_FONT
                    msg_cell.alignment = Alignment(horizontal="center", vertical="center")

                    title_text = f"📄 {p_title}   【OCR評価対象外（分類不一致）】"
                    title_cell = ws_detail.cell(row=title_row_idx, column=1, value=title_text)
                    title_cell.fill = cls.PAGE_TITLE_FILL
                    title_cell.font = cls.PAGE_TITLE_FONT
                    title_cell.alignment = Alignment(horizontal="left", vertical="center")

                    current_row += 1
                    continue                                

                # detail CSVが無いページは、OCR採点せずExcelには存在だけ残す
                if is_missing_detail:
                    ws_detail.merge_cells(
                        start_row=current_row,
                        start_column=1,
                        end_row=current_row,
                        end_column=total_cols_count
                    )

                    msg_cell = ws_detail.cell(
                        row=current_row,
                        column=1,
                        value="OCR評価対象外（明細CSVなし）"
                    )
                    msg_cell.fill = cls.HEADER_ROW_FILL
                    msg_cell.font = cls.HEADER_ROW_FONT
                    msg_cell.alignment = Alignment(
                        horizontal="center",
                        vertical="center"
                    )

                    for c_idx in range(1, total_cols_count + 1):
                        ws_detail.cell(
                            row=current_row,
                            column=c_idx
                        ).border = cls.THIN_BORDER

                    title_text = f"📄 {p_title}   【OCR評価対象外（明細CSVなし）】"

                    t_cell = ws_detail.cell(
                        row=title_row_idx,
                        column=1,
                        value=title_text
                    )
                    t_cell.fill = cls.PAGE_TITLE_FILL
                    t_cell.font = cls.PAGE_TITLE_FONT
                    t_cell.alignment = Alignment(
                        horizontal="left",
                        vertical="center"
                    )

                    for c_idx in range(1, total_cols_count + 1):
                        ws_detail.cell(
                            row=title_row_idx,
                            column=c_idx
                        ).border = cls.THIN_BORDER

                    current_row += 1
                    continue

                item_no = 1
                col_item_counts = [0] * max_c_count
                col_match_counts = [0] * max_c_count

                current_section_idx = 0
                for row_pos, (_, row_series) in enumerate(df_page.iterrows()):
                    # 2つ目以降の論理帳票の開始位置に、Excel上の区切り見出しを挿入
                    if row_pos in section_start_map:
                        sec = section_start_map[row_pos]
                        ws_detail.merge_cells(
                            start_row=current_row, start_column=1,
                            end_row=current_row, end_column=total_cols_count
                        )
                        sec_matches, sec_total, sec_acc = section_display_stats[sec["start"]]
                        sec_cell = ws_detail.cell(
                            row=current_row, column=1,
                            value=(
                                f"▶ {sec['label']}   "
                                f"【全 {sec_total} 項目 | 正解: {sec_matches} | 正解率: {sec_acc:.1%}】"
                            )
                        )
                        sec_cell.fill = cls.LIGHT_BLUE_FILL
                        sec_cell.font = cls.SUBTOTAL_FONT
                        sec_cell.alignment = Alignment(horizontal="left", vertical="center")
                        for col_i in range(1, total_cols_count + 1):
                            ws_detail.cell(row=current_row, column=col_i).border = cls.THIN_BORDER
                        current_row += 1
                        # 先頭帳票にも水色ヘッダを出すため、単純な +1 ではなく
                        # 実際の section 番号を設定する。
                        current_section_idx = page_sections.index(sec)

                    row_dict = row_series.to_dict()

                    c0_gt_raw = cls.clean_str(row_dict.get('c0_gt', ''))
                    c0_pd_raw = cls.clean_str(row_dict.get('c0_pd', ''))

                    is_sys_row = cls.is_system_header_row(c0_gt_raw, c0_pd_raw)

                    ws_detail.cell(row=current_row, column=1, value=item_no if not is_sys_row else "-").alignment = Alignment(horizontal="center", vertical="center")

                    row_total_cells = 0
                    row_matched_cells = 0

                    for c_i in range(max_c_count):
                        col_gt_name = f"c{c_i}_gt"
                        col_pd_name = f"c{c_i}_pd"

                        gt_val_raw = cls.clean_str(row_dict.get(col_gt_name, ''))
                        pd_val_raw = cls.clean_str(row_dict.get(col_pd_name, ''))

                        norm_gt = cls.normalize_text(gt_val_raw)
                        norm_pd = cls.normalize_text(pd_val_raw)

                        start_c = 2 + (c_i * 3)

                        if is_sys_row:
                            align_gt = "center"
                            align_pd = "center"
                        else:
                            align_gt = "right" if c_i > 0 and norm_gt.replace('-', '').replace(',', '').isdigit() else "left"
                            align_pd = "right" if c_i > 0 and norm_pd.replace('-', '').replace(',', '').isdigit() else "left"

                        ws_detail.cell(row=current_row, column=start_c, value=gt_val_raw).alignment = Alignment(horizontal=align_gt, vertical="center")
                        ws_detail.cell(row=current_row, column=start_c + 1, value=pd_val_raw).alignment = Alignment(horizontal=align_pd, vertical="center")

                        judge_cell = ws_detail.cell(row=current_row, column=start_c + 2)
                        judge_cell.alignment = Alignment(horizontal="center", vertical="center")

                        if is_sys_row:
                            judge_cell.value = "-"
                        else:
                            if not norm_gt and not norm_pd:
                                judge_cell.value = ""
                            else:
                                is_match = (norm_gt == norm_pd)
                                judge_cell.value = "〇" if is_match else "×"
                                if not is_match:
                                    judge_cell.fill = cls.ALERT_FILL
                                    judge_cell.font = cls.ALERT_FONT

                                if gt_val_raw or pd_val_raw:
                                    row_total_cells += 1
                                    col_item_counts[c_i] += 1
                                    if is_match:
                                        row_matched_cells += 1
                                        col_match_counts[c_i] += 1

                    if not is_sys_row:
                        section_counts[current_section_idx][0] += row_total_cells
                        section_counts[current_section_idx][1] += row_matched_cells

                    acc_c = ws_detail.cell(row=current_row, column=total_cols_count)
                    if is_sys_row:
                        acc_c.value = "-"
                        acc_c.alignment = Alignment(horizontal="center", vertical="center")
                    else:
                        row_acc = (row_matched_cells / row_total_cells) if row_total_cells > 0 else 1.0
                        acc_c.value = row_acc
                        acc_c.number_format = '0.0%'
                        acc_c.alignment = Alignment(horizontal="right", vertical="center")

                    for col_i in range(1, total_cols_count + 1):
                        c = ws_detail.cell(row=current_row, column=col_i)
                        c.font = cls.HEADER_ROW_FONT if is_sys_row else cls.REGULAR_FONT
                        if is_sys_row:
                            c.fill = cls.HEADER_ROW_FILL
                        c.border = cls.THIN_BORDER

                    current_row += 1
                    if not is_sys_row:
                        item_no += 1


                subtotal_row = current_row
                ws_detail.row_dimensions[subtotal_row].height = 22

                ws_detail.cell(row=subtotal_row, column=1, value="小計").alignment = Alignment(horizontal="center", vertical="center")

                total_page_items = sum(col_item_counts)
                total_page_matches = sum(col_match_counts)

                for c_i in range(max_c_count):
                    start_c = 2 + (c_i * 3)
                    
                    ws_detail.cell(row=subtotal_row, column=start_c, value="")
                    ws_detail.cell(row=subtotal_row, column=start_c + 1, value="")

                    c_items = col_item_counts[c_i]
                    c_matches = col_match_counts[c_i]
                    
                    j_text = f"{c_matches} / {c_items}" if c_items > 0 else "-"
                    j_cell = ws_detail.cell(row=subtotal_row, column=start_c + 2, value=j_text)
                    j_cell.alignment = Alignment(horizontal="center", vertical="center")

                p_acc_val = (total_page_matches / total_page_items) if total_page_items > 0 else 1.0
                p_acc_cell = ws_detail.cell(row=subtotal_row, column=total_cols_count, value=p_acc_val)
                p_acc_cell.number_format = '0.0%'
                p_acc_cell.alignment = Alignment(horizontal="right", vertical="center")

                for col_i in range(1, total_cols_count + 1):
                    c = ws_detail.cell(row=subtotal_row, column=col_i)
                    c.fill = cls.SUBTOTAL_FILL
                    c.font = cls.SUBTOTAL_FONT
                    c.border = cls.THIN_BORDER

                current_row += 1

                p_acc_percent = (total_page_matches / total_page_items * 100) if total_page_items > 0 else 100.0

                # ピンク = 物理ページ全体、水色 = ページ内の各論理帳票。
                # 複数帳票ページでも、ピンク側には帳票別成績を重複表示しない。
                if len(page_sections) > 1:
                    logical_labels = " ＋ ".join(sec["label"] for sec in page_sections)
                    title_text = (
                        f"📄 P{page_no} 【ページ全体：{logical_labels}】   "
                        f"【全 {total_page_items} 項目 | 正解: {total_page_matches} | 正解率: {p_acc_percent:.1f}%】"
                    )
                else:
                    title_text = (
                        f"📄 P{page_no} {p_title}   "
                        f"【全 {total_page_items} 項目 | 正解: {total_page_matches} | 正解率: {p_acc_percent:.1f}%】"
                    )

                t_cell = ws_detail.cell(row=title_row_idx, column=1, value=title_text)
                t_cell.fill = cls.PAGE_TITLE_FILL
                t_cell.font = cls.PAGE_TITLE_FONT
                t_cell.alignment = Alignment(horizontal="left", vertical="center")
                for c_idx in range(1, total_cols_count + 1):
                    ws_detail.cell(row=title_row_idx, column=c_idx).border = cls.THIN_BORDER

            ws_detail.column_dimensions['A'].width = 5
            for c_i in range(max_c_count):
                start_c = 2 + (c_i * 3)
                if c_i == 0:
                    ws_detail.column_dimensions[get_column_letter(start_c)].width = 28
                    ws_detail.column_dimensions[get_column_letter(start_c + 1)].width = 28
                else:
                    ws_detail.column_dimensions[get_column_letter(start_c)].width = 18
                    ws_detail.column_dimensions[get_column_letter(start_c + 1)].width = 18
                
                ws_detail.column_dimensions[get_column_letter(start_c + 2)].width = 8

            ws_detail.column_dimensions[last_col_letter].width = 10

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        