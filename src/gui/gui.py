import os
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
# 📝 テキスト表示エリア
# ==========================================
label_text = ctk.CTkLabel(
    app, 
    text="読込完了", 
    font=("Hiragino Sans", 20, "bold")
)
label_text.pack(pady=60)


# ==========================================
# 🚀 ボタンの設定（ブラウザ自動起動の魔法！）
# ==========================================
def button_click():
    label_text.configure(text="テスト結果を表示中...")
    
    # 1. 保存するHTMLファイルのパスを作る（src/gui/result.html に保存）
    html_path = os.path.join(current_dir, "result.html")
    
    # 2. HTMLコードを自動書き出し
    html_content = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Airead 比較結果</title>
    <style>
        body {
            background-color: #121212;
            color: #ffffff;
            font-family: 'Helvetica Neue', Arial, sans-serif;
            text-align: center;
            padding: 50px;
        }
        h1 {
            color: #ff7bd5;
            font-size: 3em;
            margin-bottom: 20px;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
            background: #1e1e1e;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 4px 15px rgba(255, 123, 213, 0.2);
            border: 2px solid #ff7bd5;
        }
        .badge {
            display: inline-block;
            background-color: #ff7bd5;
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 1.2em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>読込完了</h1>
        <p>テスト結果表示</p>
        <div class="badge">正解率 100%</div>
    </div>
</body>
</html>
"""
    
    # ファイルに書き込む
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    # 3. 既定のブラウザを自動起動してHTMLを表示
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
