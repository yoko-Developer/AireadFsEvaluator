import csv
import os
import webbrowser
import customtkinter as ctk

# local/project imports
from src.main import main as run_evaluation
from src.utils import pathutils

# 画面全体ダークモード
ctk.set_appearance_mode("dark")
current_dir = os.path.dirname(os.path.abspath(__file__))
theme_path = os.path.join(current_dir, "pink_theme.json")
ctk.set_default_color_theme(theme_path)

# アプリのメインウィンドウ
app = ctk.CTk()
app.title("Airead 比較結果")
app.geometry("450x350")

label_text = ctk.CTkLabel(
    app, 
    text="読込完了", 
    font=("Hiragino Sans", 20, "bold")
)
label_text.pack(pady=60)


def button_click():
    label_text.configure(text="評価処理を実行中...")
    app.update()  # 画面表示を更新

    # ----------------------------------------------------
    # 1. 丸付けロジック（main.py）を呼び出して最新のresultsを生成
    # ----------------------------------------------------
    project_root = pathutils.get_project_root_dir()
    
    import sys
    config_path = str(project_root / ".azure-pipelines" / "config.toml")
    
    sys.argv = [
        "main.py",
        "-c", config_path
    ]    
    try:
        run_evaluation()
    except Exception as e:
        print(f"⚠️ 評価実行時の注意: {e}")

    label_text.configure(text="Summaryを表示中...")
    app.update()

    # ----------------------------------------------------
    # 2. 生成された個別比較CSV (full_comparison_*.csv) を探索
    # ----------------------------------------------------
    # 正しいフォルダパス: "individual reports" (スペース区切り)
    results_dir = project_root / "results" / "fs" / "individual reports"
    
    target_csv = None
    if results_dir.exists():
        for root, dirs, files in os.walk(results_dir):
            for file in files:
                if "full_comparison" in file and file.endswith(".csv"):
                    target_csv = os.path.join(root, file)
                    break

    table_rows_html = ""
    total_count = 0
    passed_count = 0

    if target_csv and os.path.exists(target_csv):
        with open(target_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            
            for i, row in enumerate(reader, 1):
                item_gt = row.get("c0_gt", row.get("項目正解", "不明"))
                item_pd = row.get("c0_pd", row.get("項目読み取り", "不明"))
                amt_gt = row.get("c1_gt", "")
                amt_pd = row.get("c1_pd", "")
                
                correct_display = f"{item_gt} ({amt_gt})" if amt_gt else item_gt
                recognized_display = f"{item_pd} ({amt_pd})" if amt_pd else item_pd
                
                accuracy_val = str(row.get("accuracy", row.get("一致", "0")))
                if accuracy_val in ["100", "True", "true", "1"] or (item_gt == item_pd and amt_gt == amt_pd):
                    result_class = "result-ok"
                    result_text = "●"
                    passed_count += 1
                else:
                    result_class = "result-ng"
                    result_text = "✖"
                
                total_count += 1
                
                table_rows_html += f"""
                <tr>
                    <td>{i}</td>
                    <td>{correct_display}</td>
                    <td>{recognized_display}</td>
                    <td class="{result_class}">{result_text}</td>
                </tr>
                """
    else:
        table_rows_html = """
        <tr><td>1</td><td>データ読み込み中</td><td>データ読み込み中</td><td class="result-ng">✖</td></tr>
        """
        total_count = 1
        passed_count = 0

    accuracy = (passed_count / total_count * 100) if total_count > 0 else 0
    
    # ----------------------------------------------------
    # 3. HTMLテンプレートを作成してブラウザ起動
    # ----------------------------------------------------
    output_html_dir = project_root / "results" / "fs"
    output_html_dir.mkdir(parents=True, exist_ok=True)
    html_path = str(output_html_dir / "gui_report.html")
    
    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Airead Evaluation Summary</title>
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
            font-size: 2.5em;
            margin-bottom: 5px;
            letter-spacing: 2px;
        }}
        .subtitle {{
            color: #8E5F69;
            font-size: 1.1em;
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
        table {{
            width: 100%;
            max-width: 800px;
            border-collapse: collapse;
            background: #1a1a1a;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #2d2d2d;
        }}
        th {{
            background-color: #241a1e;
            color: #ff7bd5;
            text-align: left;
            padding: 12px 15px;
            font-size: 0.9em;
            letter-spacing: 1px;
            border-bottom: 2px solid #ff7bd5;
        }}
        td {{
            padding: 12px 15px;
            border-bottom: 1px solid #2d2d2d;
            font-size: 0.95em;
        }}
        tr:hover {{
            background-color: #252525;
        }}
        .result-ok {{
            color: #00ff88;
            font-weight: bold;
        }}
        .result-ng {{
            color: #ff4560;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <h1>Evaluation Summary</h1>
    <div class="subtitle">Airead Round-up Test Report</div>
    
    <div class="summary-box">
        <div class="stat">
            <div class="stat-value">{total_count}</div>
            <div class="stat-label">Total Cases</div>
        </div>
        <div class="stat">
            <div class="stat-value">{passed_count}</div>
            <div class="stat-label">Passed</div>
        </div>
        <div class="stat">
            <div class="stat-value pink">{accuracy:.1f}%</div>
            <div class="stat-label">Accuracy</div>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th style="width: 10%;">No</th>
                <th style="width: 40%;">Correct Answer (正解)</th>
                <th style="width: 40%;">Recognized (読み取り)</th>
                <th style="width: 10%;">Result</th>
            </tr>
        </thead>
        <tbody>
            {table_rows_html}
        </tbody>
    </table>
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
