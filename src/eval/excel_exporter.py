from pathlib import Path
from typing import List, Dict, Any, Tuple
import re
import pandas as pd
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

class KessanExcelExporter:
    """
    決算5表評価結果をセル単位比較Excelとして出力するクラス
    """

    # 🎨 スタイル定義
    PASTEL_PINK_FILL = PatternFill(start_color="F875DD", end_color="F875DD", fill_type="solid")  # ヘッダー
    LIGHT_BLUE_FILL = PatternFill(start_color="E1F5FE", end_color="E1F5FE", fill_type="solid")   # 最下行
    ALERT_FILL = PatternFill(start_color="FF6EC7", end_color="FF6EC7", fill_type="solid")        # エラー
    PAGE_TITLE_FILL = PatternFill(start_color="F0C0FE", end_color="F0C0FE", fill_type="solid")   # ページ見出し

    # 🔤 フォント
    TITLE_FONT = Font(name="Yu Gothic", size=14, bold=True, color="000000")
    HEADER_FONT = Font(name="Yu Gothic", size=11, bold=True, color="FFFFFF")
    REGULAR_FONT = Font(name="Yu Gothic", size=10, color="000000")
    TOTAL_FONT = Font(name="Yu Gothic", size=11, bold=True, color="000000")
    PAGE_TITLE_FONT = Font(name="Yu Gothic", size=10, bold=True, color="4A148C")
    ALERT_FONT = Font(name="Yu Gothic", size=10, bold=True, color="FFFFFF") # エラー時白文字

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

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """ノイズ除去比較（【】()（）スペース・記号全消去）"""
        return re.sub(r'[【】\(\)（）※\*＊\s\t,、]', '', str(text or ''))

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
        ws_matrix.views.sheetView[0].showGridLines = True

        ws_matrix.cell(row=1, column=1, value="決算5表 精度評価マトリックスレポート").font = cls.TITLE_FONT

        headers = [
            "No", "PDFファイル名", "総ページ数", "総項目数", "総正解数", "全体正解率",
            "BS", "PL", "販管費", "株主資本", "製造原価"
        ]

        for col_idx, header in enumerate(headers, start=1):
            cell = ws_matrix.cell(row=2, column=col_idx, value=header)
            cell.fill = cls.PASTEL_PINK_FILL
            cell.font = cls.HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = cls.THIN_BORDER

        ws_matrix.row_dimensions[2].height = 28

        # 帳票キー表記ゆれマッピング対応表
        kessan_map = {
            "BS": ["BS", "BS_acc", "貸借対照表", "貸借対照表_acc"],
            "PL": ["PL", "PL_acc", "損益計算書", "損益計算書_acc"],
            "販管費": ["販管費", "販管費_acc", "販売費及び一般管理費明細書", "販売費及び一般管理費明細書_acc", "販売費及び一般管理費", "販売費及び一般管理費_acc"],
            "株主資本": ["株主資本", "株主資本_acc", "株主資本等変動計算書", "株主資本等変動計算書_acc"],
            "製造原価": ["製造原価", "製造原価_acc", "製造原価報告書", "製造原価報告書_acc"]
        }

        row_idx = 3
        for idx, data in enumerate(summary_data, start=1):
            ws_matrix.cell(row=row_idx, column=1, value=idx).alignment = Alignment(horizontal="center", vertical="center")
            ws_matrix.cell(row=row_idx, column=2, value=data.get("filename", "")).alignment = Alignment(horizontal="left", vertical="center")
            
            c3 = ws_matrix.cell(row=row_idx, column=3, value=data.get("total_pages", 0))
            c3.number_format = '#,##0'
            c3.alignment = Alignment(horizontal="center", vertical="center")

            c4 = ws_matrix.cell(row=row_idx, column=4, value=data.get("total_items", 0))
            c4.number_format = '#,##0'
            c4.alignment = Alignment(horizontal="center", vertical="center")

            c5 = ws_matrix.cell(row=row_idx, column=5, value=data.get("total_matches", 0))
            c5.number_format = '#,##0'
            c5.alignment = Alignment(horizontal="center", vertical="center")
            
            acc = data.get("accuracy", 0.0) / 100.0 if data.get("accuracy", 0.0) > 1 else data.get("accuracy", 0.0)
            acc_cell = ws_matrix.cell(row=row_idx, column=6, value=acc)
            acc_cell.number_format = '0.0%'
            acc_cell.alignment = Alignment(horizontal="center", vertical="center")

            kessan_types = ["BS", "PL", "販管費", "株主資本", "製造原価"]
            for c_offset, k_type in enumerate(kessan_types, start=7):
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
                
                # 🌟 上下行で統一感が出るように【センター揃え】にする！
                c.alignment = Alignment(horizontal="center", vertical="center")

            for col in range(1, len(headers) + 1):
                c = ws_matrix.cell(row=row_idx, column=col)
                c.font = cls.REGULAR_FONT
                c.border = cls.THIN_BORDER

            row_idx += 1
            
        # 最下行：累計合計
        total_row = row_idx
        ws_matrix.cell(row=total_row, column=1, value="")
        ws_matrix.cell(row=total_row, column=2, value="【 累計合計/平均 】").alignment = Alignment(horizontal="center", vertical="center")
        
        c3_tot = ws_matrix.cell(row=total_row, column=3, value=f"=SUM(C3:C{total_row-1})")
        c3_tot.number_format = '#,##0'
        c3_tot.alignment = Alignment(horizontal="center", vertical="center")

        c4_tot = ws_matrix.cell(row=total_row, column=4, value=f"=SUM(D3:D{total_row-1})")
        c4_tot.number_format = '#,##0'
        c4_tot.alignment = Alignment(horizontal="center", vertical="center")

        c5_tot = ws_matrix.cell(row=total_row, column=5, value=f"=SUM(E3:E{total_row-1})")
        c5_tot.number_format = '#,##0'
        c5_tot.alignment = Alignment(horizontal="center", vertical="center")
        
        tot_acc_cell = ws_matrix.cell(row=total_row, column=6, value=f"=IF(D{total_row}>0, E{total_row}/D{total_row}, 0)")
        tot_acc_cell.number_format = '0.0%'
        tot_acc_cell.alignment = Alignment(horizontal="center", vertical="center")

        # 各帳票列（G〜K列）の平均正解率計算
        col_letters = ['G', 'H', 'I', 'J', 'K']
        for c_let in col_letters:
            col_cell = ws_matrix.cell(row=total_row, column=openpyxl.utils.column_index_from_string(c_let))
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

        for c_letter in col_letters:
            ws_matrix.column_dimensions[c_letter].width = 16

        # -------------------------------------------------------------
        # シート2以降: 📄 詳細シート（ページごとの小計付き）
        # -------------------------------------------------------------
        for sheet_name, page_df_list in detail_dfs:
            safe_title = re.sub(r'[\\/*?:\[\]]', '', sheet_name)[:28]
            ws_detail = wb.create_sheet(title=safe_title)
            ws_detail.views.sheetView[0].showGridLines = True

            detail_headers = ["No", "科目 (正解)", "科目 (読み取り)", "科目判定", "金額 (正解)", "金額 (読み取り)", "金額判定", "行正解率"]
            
            for col_idx, h_text in enumerate(detail_headers, start=1):
                cell = ws_detail.cell(row=1, column=col_idx, value=h_text)
                cell.fill = cls.PASTEL_PINK_FILL
                cell.font = cls.HEADER_FONT
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = cls.THIN_BORDER

            ws_detail.row_dimensions[1].height = 24

            current_row = 2

            for p_title, df_page in page_df_list:
                page_items = 0
                page_matches = 0

                title_row_idx = current_row
                ws_detail.merge_cells(start_row=title_row_idx, start_column=1, end_row=title_row_idx, end_column=8)
                ws_detail.row_dimensions[title_row_idx].height = 22
                current_row += 1

                item_no = 1
                for row in df_page.itertuples():
                    c0_gt = str(getattr(row, 'c0_gt', '')) if pd.notna(getattr(row, 'c0_gt', '')) else ''
                    c0_pd = str(getattr(row, 'c0_pd', '')) if pd.notna(getattr(row, 'c0_pd', '')) else ''
                    c1_gt = str(getattr(row, 'c1_gt', '')) if pd.notna(getattr(row, 'c1_gt', '')) else ''
                    c1_pd = str(getattr(row, 'c1_pd', '')) if pd.notna(getattr(row, 'c1_pd', '')) else ''

                    norm_c0_gt = cls.normalize_text(c0_gt)
                    norm_c0_pd = cls.normalize_text(c0_pd)
                    norm_c1_gt = cls.normalize_text(c1_gt)
                    norm_c1_pd = cls.normalize_text(c1_pd)

                    c0_match = (norm_c0_gt == norm_c0_pd) if norm_c0_gt else True
                    c1_match = (norm_c1_gt == norm_c1_pd) if norm_c1_gt else True

                    total_cells = (1 if c0_gt else 0) + (1 if c1_gt else 0)
                    matched_cells = (1 if c0_gt and c0_match else 0) + (1 if c1_gt and c1_match else 0)
                    
                    page_items += total_cells
                    page_matches += matched_cells
                    row_acc = (matched_cells / total_cells) if total_cells > 0 else 1.0

                    ws_detail.cell(row=current_row, column=1, value=item_no).alignment = Alignment(horizontal="center", vertical="center")
                    ws_detail.cell(row=current_row, column=2, value=c0_gt).alignment = Alignment(vertical="center")
                    ws_detail.cell(row=current_row, column=3, value=c0_pd).alignment = Alignment(vertical="center")
                    
                    c0_cell = ws_detail.cell(row=current_row, column=4, value="〇" if c0_match else "×")
                    c0_cell.alignment = Alignment(horizontal="center", vertical="center")
                    if not c0_match: 
                        c0_cell.fill = cls.ALERT_FILL
                        c0_cell.font = cls.ALERT_FONT

                    ws_detail.cell(row=current_row, column=5, value=c1_gt).alignment = Alignment(vertical="center")
                    ws_detail.cell(row=current_row, column=6, value=c1_pd).alignment = Alignment(vertical="center")
                    
                    c1_cell = ws_detail.cell(row=current_row, column=7, value="〇" if c1_match else "×")
                    c1_cell.alignment = Alignment(horizontal="center", vertical="center")
                    if not c1_match: 
                        c1_cell.fill = cls.ALERT_FILL
                        c1_cell.font = cls.ALERT_FONT

                    acc_c = ws_detail.cell(row=current_row, column=8, value=row_acc)
                    acc_c.number_format = '0.0%'
                    acc_c.alignment = Alignment(horizontal="right", vertical="center")

                    for col_i in range(1, 9):
                        c = ws_detail.cell(row=current_row, column=col_i)
                        if col_i not in [4, 7] or (col_i == 4 and c0_match) or (col_i == 7 and c1_match):
                            c.font = cls.REGULAR_FONT
                        c.border = cls.THIN_BORDER

                    current_row += 1
                    item_no += 1

                p_acc_val = (page_matches / page_items * 100) if page_items > 0 else 100.0
                t_cell = ws_detail.cell(row=title_row_idx, column=1, value=f"📄 {p_title}   【項目数: {page_items} | 正解数: {page_matches} | ページ正解率: {p_acc_val:.1f}%】")
                t_cell.fill = cls.PAGE_TITLE_FILL
                t_cell.font = cls.PAGE_TITLE_FONT
                t_cell.alignment = Alignment(horizontal="left", vertical="center")
                for c_idx in range(1, 9):
                    ws_detail.cell(row=title_row_idx, column=c_idx).border = cls.THIN_BORDER

            ws_detail.column_dimensions['A'].width = 6
            ws_detail.column_dimensions['B'].width = 28
            ws_detail.column_dimensions['C'].width = 28
            ws_detail.column_dimensions['D'].width = 10
            ws_detail.column_dimensions['E'].width = 18
            ws_detail.column_dimensions['F'].width = 18
            ws_detail.column_dimensions['G'].width = 10
            ws_detail.column_dimensions['H'].width = 12

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        