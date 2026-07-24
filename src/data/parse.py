import os
import re
import csv

def parse_ai_read_tsv(tsv_path):
    """
    AIReadのTSVを解析して、「項目名」と「金額」を順番に取り出す
    """
    components = []
    
    with open(tsv_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    in_components = False
    for line in lines:
        if "<Components>" in line:
            in_components = True
            continue
        if "<Lines>" in line or "</Components>" in line:
            in_components = False
            
        if in_components:
            cols = line.strip().split("\t")
            if not cols or cols[0] == "" or "ID" in cols[0]:
                continue
            
            # Value(インデックス6) を取得
            if len(cols) > 6:
                value = cols[6].strip()
                components.append(value)
    return components

def convert_to_raw_csv(tsv_folder, output_csv_path):
    """
    TSVファイルを走査して、生の読み取り結果CSVを作成する
    """
    raw_rows = []
    
    if not os.path.exists(tsv_folder):
        print(f"TSVフォルダが見つからない: {tsv_folder}")
        return

    for filename in sorted(os.listdir(tsv_folder)):
        if filename.endswith(".tsv"):
            tsv_path = os.path.join(tsv_folder, filename)
            # ファイル名から拡張子を削除
            file_base = filename.replace(".tsv", "")
            
            values = parse_ai_read_tsv(tsv_path)
            
            current_item = ""
            row_num = 1
            
            for val in values:
                if not val or val in ["科目", "金額", "資産の部", "負債の部", "貸借対照表"]:
                    continue
                
                # 金額クレンジング（カンマ、円、カッコを消す）
                clean_val = re.sub(r"[)円「,（）]", "", val).strip()
                
                # 数字（マイナス含む）かどうか判定
                if re.match(r"^-?\d+$", clean_val) and clean_val != "":
                    if current_item:
                        raw_rows.append({
                            "file_name": file_base,
                            "sheet_name": "貸借対照表",
                            "page_num": "1",
                            "row_num": row_num,
                            "ocr_text": current_item,
                            "ocr_amount": clean_val
                        })
                        row_num += 1
                        current_item = ""
                else:
                    current_item = val

    # CSV出力
    os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)
    headers = ["file_name", "sheet_name", "page_num", "row_num", "ocr_text", "ocr_amount"]
    with open(output_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(raw_rows)
        
    print(f"生データCSVを作成 ➡️ {output_csv_path}")

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    
    # フォルダのパスを設定
    tsv_dir = os.path.join(project_root, "data", "tsv")
    output_path = os.path.join(project_root, "results", "detail_raw.csv")
    
    convert_to_raw_csv(tsv_dir, output_path)
    