from pathlib import Path
from typing import List, Dict, Any, Tuple
import re
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
        "01_050_02": "株主資本等変動計算書"
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
    def export_kessan_report(
        cls, 
        output_path: Path, 
        summary_data: List[Dict[str, Any]], 
        detail_dfs: List[Tuple[str, List[Tuple[str, pd.DataFrame]]]]
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
            "OCR総項目数", "OCR正解数", "OCR正解率",
            "BS", "PL", "製造原価", "販管費", "株主資本"
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

        row_idx = 3
        for idx, data in enumerate(summary_data, start=1):
            ws_matrix.cell(row=row_idx, column=1, value=idx).alignment = Alignment(horizontal="center", vertical="center")
            ws_matrix.cell(row=row_idx, column=2, value=data.get("filename", "")).alignment = Alignment(horizontal="left", vertical="center")
            
            c3 = ws_matrix.cell(row=row_idx, column=3, value=data.get("total_pages", 0))
            c3.number_format = '#,##0'
            c3.alignment = Alignment(horizontal="center", vertical="center")

            # 分類
            c4 = ws_matrix.cell(row=row_idx, column=4, value=data.get("classification_matches", 0))
            c4.number_format = '#,##0'
            c4.alignment = Alignment(horizontal="center", vertical="center")

            c5 = ws_matrix.cell(row=row_idx, column=5, value=data.get("classification_total", 0))
            c5.number_format = '#,##0'
            c5.alignment = Alignment(horizontal="center", vertical="center")

            classification_total = data.get("classification_total", 0)
            classification_matches = data.get("classification_matches", 0)
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
            for c_offset, k_type in enumerate(kessan_types, start=10):
                status_val = "-"
                for alt_key in kessan_map[k_type]:
                    if alt_key in data:
                        status_val = data[alt_key]
                        break

                c = ws_matrix.cell(row=row_idx, column=c_offset)
                if isinstance(status_val, (int, float)):
                    c.value = status_val / 100.0 if status_val > 1 else status_val
                    c.number_format = '0.0%'
                else:
                    c.value = str(status_val)
                
                c.alignment = Alignment(horizontal="center", vertical="center")

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
        col_letters = ['J', 'K', 'L', 'M', 'N']

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

        # -------------------------------------------------------------
        # シート2以降: 📄 詳細シート
        # -------------------------------------------------------------
        for sheet_name, page_df_list in detail_dfs:
            safe_title = re.sub(r'[\\/*?:\[\]]', '', sheet_name)[:28]
            ws_detail = wb.create_sheet(title=safe_title)
            ws_detail.views.sheetView[0].showGridLines = False

            max_c_count = 1
            for _, df_p in page_df_list:
                gt_cols = [c for c in df_p.columns if re.match(r'^c\d+_gt$', c)]
                max_c_count = max(max_c_count, len(gt_cols))

            total_cols_count = 1 + (max_c_count * 3) + 1

            ws_detail.row_dimensions[1].height = 22
            ws_detail.row_dimensions[2].height = 22

            ws_detail.merge_cells("A1:A2")
            ws_detail.cell(row=1, column=1, value="No")

            last_col_letter = get_column_letter(total_cols_count)
            ws_detail.merge_cells(f"{last_col_letter}1:{last_col_letter}2")
            ws_detail.cell(row=1, column=total_cols_count, value="行正解率")

            for c_i in range(max_c_count):
                start_c = 2 + (c_i * 3)
                end_c = start_c + 2
                start_let = get_column_letter(start_c)
                end_let = get_column_letter(end_c)

                grp_title = "科目" if c_i == 0 else f"金額{c_i}" if max_c_count > 2 else "金額"
                ws_detail.merge_cells(f"{start_let}1:{end_let}1")
                ws_detail.cell(row=1, column=start_c, value=grp_title)

                ws_detail.cell(row=2, column=start_c, value="マスタ")
                ws_detail.cell(row=2, column=start_c + 1, value="読み取り")
                ws_detail.cell(row=2, column=start_c + 2, value="判定")

            for r in [1, 2]:
                for c in range(1, total_cols_count + 1):
                    cell = ws_detail.cell(row=r, column=c)
                    cell.fill = cls.PASTEL_PINK_FILL
                    cell.font = cls.HEADER_FONT
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.border = cls.THIN_BORDER

            current_row = 3

            for raw_p_title, df_page in page_df_list:
                # ★formidから正解の帳票タイトルを動的に決定★
                p_title = cls.get_title_from_df(df_page, raw_p_title)

                title_row_idx = current_row
                ws_detail.merge_cells(start_row=title_row_idx, start_column=1, end_row=title_row_idx, end_column=total_cols_count)
                ws_detail.row_dimensions[title_row_idx].height = 22
                current_row += 1

                item_no = 1
                col_item_counts = [0] * max_c_count
                col_match_counts = [0] * max_c_count

                for _, row_series in df_page.iterrows():
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
                title_text = f"📄 {p_title}   【全 {total_page_items} 項目 | 正解: {total_page_matches} | ページ総合正解率: {p_acc_percent:.1f}%】"

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
        