import csv
import os
import re
import sys
import webbrowser
import customtkinter as ctk

# local/project imports
from src.main import main as run_evaluation
from src.utils import pathutils

# 画面全体ダークモード
ctk.set_appearance_mode("dark")
current_dir = os.path.dirname(os.path.abspath(__file__))
theme_path = os.path.join(current_dir, "pink_theme.json")
if os.path.exists(theme_path):
    ctk.set_default_color_theme(theme_path)

# アプリのメインウィンドウ
app = ctk.CTk()
app.title("Airead 精度評価アプリ（ファイル別サマリー＆折りたたみ詳細）")
app.geometry("480x360")

label_text = ctk.CTkLabel(
    app, 
    text="読込完了", 
    font=("Hiragino Sans", 20, "bold")
)
label_text.pack(pady=60)

def clean_text(val):
    """ノイズ（全角・半角スペース、カンマ、カッコなど）を除去する"""
    text = str(val).replace(' ', '').replace(' ', '')
    return re.sub(r'[【】\(\)（）※\*＊\s\t,、]', '', text)

def detect_sheet_name(csv_path):
    """CSVの中身やファイル名から帳票タイトルを判定する"""
    file_name = os.path.basename(csv_path).lower()
    
    # ページ番号によるデフォルト判定（_0: BS, _1: PL, _2: 販管費, _3: SS）
    default_title = ""
    if "_0.csv" in file_name:
        default_title = "貸借対照表"
    elif "_1.csv" in file_name:
        default_title = "損益計算書"
    elif "_2.csv" in file_name:
        default_title = "販売費及び一般管理費明細書"
    elif "_3.csv" in file_name:
        default_title = "株主資本等変動計算書"

    # CSVの中身から判定
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            content = f.read(1500)
            if "流動資産" in content or "固定資産" in content:
                return "貸借対照表"
            elif "売上高" in content or "営業利益" in content:
                return "損益計算書"
            elif "役員報酬" in content or "福利厚生費" in content:
                return "販売費及び一般管理費明細書"
            elif "当期変動額" in content or "資本金" in content:
                return "株主資本等変動計算書"
    except Exception:
        pass
        
    return default_title if default_title else "決算書帳票"

def button_click():
    label_text.configure(text="評価処理を実行中...")
    app.update()

    # 1. 丸付けロジック（main.py）を呼び出して最新のresultsを生成
    project_root = pathutils.get_project_root_dir()
    config_path = str(project_root / ".azure-pipelines" / "config.toml")
    
    sys.argv = ["main.py", "-c", config_path]    
    try:
        run_evaluation()
    except Exception as e:
        print(f"⚠️ 評価実行時の注意: {e}")

    label_text.configure(text="ファイル別レポートを作成中...")
    app.update()

    # 2. 全結果ファイル (full_comparison_*.csv) を探索してPDF（ファイル）ごとにグループ化
    results_dir = project_root / "results" / "fs" / "individual reports"
    
    pdf_groups = {}  # { PDF基本名: [ページごとのデータ] }
    
    total_cumulative_items = 0
    passed_cumulative_items = 0

    if results_dir.exists():
        for root, dirs, files in os.walk(results_dir):
            csv_files = sorted([f for f in files if "full_comparison" in f and f.endswith(".csv")])
            for file in csv_files:
                target_csv = os.path.join(root, file)
                sheet_title = detect_sheet_name(target_csv)
                
                # ファイル名からPDF名とページ番号（_0, _1など）を分解
                file_stem = file.replace("full_comparison_", "").replace(".csv", "")
                
                # ページ番号の抽出（末尾の _0, _1 などからページを計算）
                page_idx_match = re.search(r'_(\d+)$', file_stem)
                if page_idx_match:
                    page_num = int(page_idx_match.group(1)) + 1  # 0始まりなら1を足す
                    pdf_base_name = re.sub(r'_\d+$', '', file_stem)
                else:
                    page_num = 1
                    pdf_base_name = file_stem

                page_items = []
                page_total = 0
                page_passed = 0
                
                with open(target_csv, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader, 1):
                        item_gt = row.get("c0_gt", row.get("項目正解", "不明"))
                        item_pd = row.get("c0_pd", row.get("項目読み取り", "不明"))
                        amt_gt = row.get("c1_gt", "")
                        amt_pd = row.get("c1_pd", "")
                        
                        correct_disp = f"{item_gt} ({amt_gt})" if amt_gt else item_gt
                        recognized_disp = f"{item_pd} ({amt_pd})" if amt_pd else item_pd
                        
                        item_gt_clean = clean_text(item_gt)
                        item_pd_clean = clean_text(item_pd)
                        amt_gt_clean = clean_text(amt_gt)
                        amt_pd_clean = clean_text(amt_pd)

                        accuracy_val = str(row.get("accuracy", row.get("一致", "0")))
                        
                        if (
                            accuracy_val in ["100", "100.0", "True", "true", "1"] 
                            or (item_gt_clean == item_pd_clean and amt_gt_clean == amt_pd_clean)
                        ):
                            is_ok = True
                            page_passed += 1
                        else:
                            is_ok = False
                        
                        page_total += 1
                        
                        page_items.append({
                            "no": idx,
                            "correct": correct_disp,
                            "recognized": recognized_disp,
                            "is_ok": is_ok
                        })

                page_acc = (page_passed / page_total * 100) if page_total > 0 else 0
                
                total_cumulative_items += page_total
                passed_cumulative_items += page_passed

                if pdf_base_name not in pdf_groups:
                    pdf_groups[pdf_base_name] = []

                pdf_groups[pdf_base_name].append({
                    "page_num": page_num,
                    "sheet_title": sheet_title,
                    "page_total": page_total,
                    "page_passed": page_passed,
                    "page_acc": page_acc,
                    "items": page_items
                })

    # 累計精度
    total_acc = (passed_cumulative_items / total_cumulative_items * 100) if total_cumulative_items > 0 else 0

    # 3. PDF（ファイル）ごとにまとめたHTMLとExcel用データの生成
    pdf_cards_html = ""
    
    excel_export_path = project_root / "results" / "fs" / "全ページ詳細明細_Excel用.csv"
    with open(excel_export_path, "w", encoding="utf-8-sig", newline="") as ef:
        writer = csv.writer(ef)
        writer.writerow(["PDFファイル名", "ページ番号", "帳票タイトル", "No", "正解データ", "AIRead読み取り結果", "判定(1/0)"])

        for pdf_idx, (pdf_name, pages) in enumerate(pdf_groups.items(), 1):
            # ページ順にソート
            pages = sorted(pages, key=lambda x: x["page_num"])
            
            pdf_total = sum(p["page_total"] for p in pages)
            pdf_passed = sum(p["page_passed"] for p in pages)
            pdf_acc = (pdf_passed / pdf_total * 100) if pdf_total > 0 else 0
            
            pdf_acc_class = "result-ok" if pdf_acc >= 90 else "result-ng"
            
            pages_summary_rows = ""
            pages_detail_blocks = ""

            for p in pages:
                p_acc_class = "result-ok" if p["page_acc"] >= 90 else "result-ng"
                
                # 簡易サマリーテーブル用
                pages_summary_rows += f"""
                <tr>
                    <td>ページ {p['page_num']}</td>
                    <td style="font-weight:bold; color:#ff7bd5;">{p['sheet_title']}</td>
                    <td>{p['page_passed']} / {p['page_total']} 項目</td>
                    <td class="{p_acc_class}">{p['page_acc']:.1f}%</td>
                </tr>
                """

                # 項目ごとの明細
                item_rows_html = ""
                for item in p["items"]:
                    r_class = "result-ok" if item["is_ok"] else "result-ng"
                    r_mark = "●" if item["is_ok"] else "✖"
                    item_rows_html += f"""
                    <tr>
                        <td style="text-align:center;">{item['no']}</td>
                        <td>{item['correct']}</td>
                        <td>{item['recognized']}</td>
                        <td class="{r_class}" style="text-align:center;">{r_mark}</td>
                    </tr>
                    """
                    
                    # Excel書き込み
                    writer.writerow([
                        pdf_name,
                        f"ページ {p['page_num']}",
                        p['sheet_title'],
                        item['no'],
                        item['correct'],
                        item['recognized'],
                        "1" if item['is_ok'] else "0"
                    ])

                pages_detail_blocks += f"""
                <div class="page-detail-box">
                    <div class="page-detail-header">
                        <span>📄 ページ {p['page_num']}：{p['sheet_title']}</span>
                        <span class="{p_acc_class}">正解率: {p['page_acc']:.1f}% ({p['page_passed']}/{p['page_total']})</span>
                    </div>
                    <table class="detail-table">
                        <thead>
                            <tr>
                                <th style="width: 8%; text-align:center;">No</th>
                                <th style="width: 42%;">正解データ (Ground Truth)</th>
                                <th style="width: 42%;">AIRead 読み取り結果</th>
                                <th style="width: 8%; text-align:center;">判定</th>
                            </tr>
                        </thead>
                        <tbody>
                            {item_rows_html}
                        </tbody>
                    </table>
                </div>
                """

            # PDFごとの枠（カード）
            pdf_cards_html += f"""
            <div class="pdf-card">
                <div class="pdf-header" onclick="toggleDetails('pdf_detail_{pdf_idx}')">
                    <div>
                        <span class="pdf-title">📁 PDF {pdf_idx} : {pdf_name}</span>
                        <span class="pdf-sub">({len(pages)} ページ構成)</span>
                    </div>
                    <div class="pdf-score">
                        全体の正解率: <span class="{pdf_acc_class}">{pdf_acc:.1f}%</span> ({pdf_passed}/{pdf_total})
                        <span class="arrow-icon">▼ クリックで詳細</span>
                    </div>
                </div>
                
                <div id="pdf_detail_{pdf_idx}" class="pdf-body" style="display: block;">
                    <div class="page-summary-table-box">
                        <h4>【ページ別サマリー】</h4>
                        <table class="summary-table">
                            <thead>
                                <tr>
                                    <th>ページ</th>
                                    <th>帳票タイトル</th>
                                    <th>正解数 / 項目数</th>
                                    <th>正解率</th>
                                </tr>
                            </thead>
                            <tbody>
                                {pages_summary_rows}
                            </tbody>
                        </table>
                    </div>
                    
                    <h4 style="color:#ff7bd5; margin-top:20px;">【全ページ・全項目 明細照合】</h4>
                    {pages_detail_blocks}
                </div>
            </div>
            """

    # 4. HTMLレポートの組み立てと生成
    output_html_dir = project_root / "results" / "fs"
    output_html_dir.mkdir(parents=True, exist_ok=True)
    html_path = str(output_html_dir / "gui_pdf_summary_report.html")

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Airead 精度評価 総合分析サマリー</title>
    <style>
        body {{
            background-color: #121212;
            color: #ffffff;
            font-family: 'Helvetica Neue', Arial, 'Hiragino Sans', sans-serif;
            margin: 0;
            padding: 40px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        h1 {{
            color: #ff7bd5;
            font-size: 2.2em;
            margin-bottom: 5px;
        }}
        .subtitle {{
            color: #8E5F69;
            font-size: 1.0em;
            margin-bottom: 30px;
        }}
        .summary-box {{
            background: #1e1e1e;
            padding: 20px 40px;
            border-radius: 12px;
            border: 2px solid #ff7bd5;
            box-shadow: 0 4px 20px rgba(255, 123, 213, 0.15);
            margin-bottom: 30px;
            display: flex;
            gap: 40px;
        }}
        .stat {{
            text-align: center;
        }}
        .stat-value {{
            font-size: 1.8em;
            font-weight: bold;
            color: #ffffff;
        }}
        .stat-value.pink {{
            color: #ff7bd5;
        }}
        .stat-label {{
            font-size: 0.8em;
            color: #8E5F69;
            text-transform: uppercase;
            margin-top: 5px;
        }}
        .pdf-card {{
            width: 100%;
            max-width: 950px;
            background: #1a1a1a;
            border-radius: 10px;
            border: 1px solid #333;
            margin-bottom: 25px;
            overflow: hidden;
        }}
        .pdf-header {{
            background: #241a1e;
            padding: 18px 25px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            border-bottom: 1px solid #ff7bd5;
        }}
        .pdf-title {{
            font-size: 1.2em;
            font-weight: bold;
            color: #ffffff;
        }}
        .pdf-sub {{
            font-size: 0.9em;
            color: #8E5F69;
            margin-left: 10px;
        }}
        .pdf-score {{
            font-size: 1.1em;
            font-weight: bold;
        }}
        .arrow-icon {{
            font-size: 0.8em;
            color: #ff7bd5;
            margin-left: 15px;
        }}
        .pdf-body {{
            padding: 25px;
            background: #161616;
        }}
        .summary-table {{
            width: 100%;
            border-collapse: collapse;
            background: #1e1e1e;
            border-radius: 6px;
            overflow: hidden;
        }}
        .summary-table th, .summary-table td {{
            padding: 10px 15px;
            border-bottom: 1px solid #2a2a2a;
            font-size: 0.9em;
            text-align: left;
        }}
        .summary-table th {{
            background: #2c2226;
            color: #ff7bd5;
        }}
        .page-detail-box {{
            margin-top: 20px;
            background: #1e1e1e;
            border-radius: 8px;
            padding: 15px;
            border: 1px solid #2d2d2d;
        }}
        .page-detail-header {{
            font-size: 1.0em;
            font-weight: bold;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            color: #ff7bd5;
        }}
        .detail-table {{
            width: 100%;
            border-collapse: collapse;
            background: #141414;
        }}
        .detail-table th {{
            background-color: #281e22;
            color: #ff7bd5;
            padding: 8px 12px;
            font-size: 0.85em;
            border-bottom: 1px solid #ff7bd5;
            text-align: left;
        }}
        .detail-table td {{
            padding: 8px 12px;
            border-bottom: 1px solid #252525;
            font-size: 0.9em;
        }}
        .result-ok {{
            color: #00ff88;
            font-weight: bold;
        }}
        .result-ng {{
            color: #ff4560;
            font-weight: bold;
        }}
        .export-note {{
            color: #8E5F69;
            font-size: 0.9em;
            margin-bottom: 20px;
        }}
    </style>
    <script>
        function toggleDetails(id) {{
            var el = document.getElementById(id);
            if (el.style.display === "none") {{
                el.style.display = "block";
            }} else {{
                el.style.display = "none";
            }}
        }}
    </script>
</head>
<body>
    <h1>Airead Evaluation Summary</h1>
    <div class="subtitle">PDFファイル別 ＆ ページ別詳細 総合判定レポート</div>
    
    <div class="summary-box">
        <div class="stat">
            <div class="stat-value">{len(pdf_groups)}</div>
            <div class="stat-label">Total PDFs (ファイル数)</div>
        </div>
        <div class="stat">
            <div class="stat-value">{total_cumulative_items}</div>
            <div class="stat-label">Total Items (総項目数)</div>
        </div>
        <div class="stat">
            <div class="stat-value">{passed_cumulative_items}</div>
            <div class="stat-label">Passed Items (正解数)</div>
        </div>
        <div class="stat">
            <div class="stat-value pink">{total_acc:.1f}%</div>
            <div class="stat-label">Cumulative Accuracy (全体累計)</div>
        </div>
    </div>

    <div class="export-note">
        📊 Excel用データ（CSV）を出力しました: <code>{excel_export_path}</code>
    </div>

    {pdf_cards_html}

</body>
</html>
"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    webbrowser.open(html_path)

button = ctk.CTkButton(
    app, 
    text="テスト実行", 
    font=("Hiragino Sans", 14, "bold"),
    command=button_click
)
button.pack(pady=20)

app.mainloop()
