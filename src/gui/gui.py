import os
import csv
import webbrowser
import customtkinter as ctk

# 画面全体ダークモード
ctk.set_appearance_mode("dark")
current_dir = os.path.dirname(os.path.abspath(__file__))
theme_path = os.path.join(current_dir, "pink_theme.json")
ctk.set_default_color_theme(theme_path)

# アプリのメインウィンドウ
app = ctk.CTk()
app.title("Airead 比較結果")
app.geometry("450x350")

# ==========================================
# テキスト表示エリア
# ==========================================
label_text = ctk.CTkLabel(
    app, 
    text="読込完了", 
    font=("Hiragino Sans", 20, "bold")
)
label_text.pack(pady=60)

# ==========================================
# CSVを読み込んで「Summary」HTMLを生成して開く
# ==========================================
def button_click():
    label_text.configure(text="Summaryを表示中...")
    
    # 1. 読み込むCSVのパスを解決する
    # ※プロジェクトルート直下の results/whole_summary_report.csv を狙い撃ち！
    project_root = os.path.dirname(os.path.dirname(current_dir))
    csv_path = os.path.join(project_root, "results", "whole_summary_report.csv")
    
    # CSVからHTMLのテーブル行（tr）を自動生成する
    table_rows_html = ""
    total_count = 0
    passed_count = 0
    
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            
            for i, row in enumerate(reader, 1):
                # CSVのカラム名に合わせて取得
                correct = row.get("correct", row.get("正解", "不明"))
                recognized = row.get("recognized", row.get("読み取り", "不明"))
                result = row.get("result", row.get("結果", "✖"))
                
                # 結果に応じてクラス（色）を変える
                if result in ["●", "○", "OK", "Passed", "1"]:
                    result_class = "result-ok"
                    result_text = "●"
                    passed_count += 1
                else:
                    result_class = "result-ng"
                    result_text = "✖"
                
                total_count += 1
                
                # HTMLの1行分を組み立てるのん！
                table_rows_html += f"""
                <tr>
                    <td>{i}</td>
                    <td>{correct}</td>
                    <td>{recognized}</td>
                    <td class="{result_class}">{result_text}</td>
                </tr>
                """
    else:
        # CSVが見つからない場合のフォールバック（テスト用ダミーデータ）
        table_rows_html = """
        <tr><td>1</td><td>宇都宮</td><td>宇都宮</td><td class="result-ok">●</td></tr>
        <tr><td>2</td><td>餃子</td><td>校舎</td><td class="result-ng">✖</td></tr>
        """
        total_count = 2
        passed_count = 1

    # 正解率を計算
    accuracy = (passed_count / total_count * 100) if total_count > 0 else 0
    
    # 2. 生成するHTMLファイルのパス（src/gui/result.html）
    html_path = os.path.join(current_dir, "result.html")
    
    # 3. HTMLテンプレート
    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Airead Evaluation Summary 🌸</title>
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
    
    # HTMLファイルを出力
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    # ブラウザで自動起動
    webbrowser.open(html_path)

# テスト実行ボタン
button = ctk.CTkButton(
    app, 
    text="テスト実行", 
    font=("Hiragino Sans", 14, "bold"),
    command=button_click
)
button.pack(pady=20)

# 画面を起動する
app.mainloop()
