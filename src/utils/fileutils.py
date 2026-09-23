import chardet

def detect_encoding(file_path):
    with open(file_path, 'rb') as f:
        result: dict = chardet.detect(f.read())
    return result['encoding']