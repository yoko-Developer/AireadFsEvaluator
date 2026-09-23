# standard library
import logging
from pathlib import Path
import subprocess as subproc
import sys


def exec_batch(batch_file: Path, cwd: Path, popen_encoding: str = 'utf-8', stdout_encoding: str = None) -> int:
    """
    Executes a Windows batch file and returns the exit code.
    """
    try:
        logging.info(f"Executing batch ... : {batch_file}")

        print('"""')
        # Popenを使用してプロセスを開始
        process = subproc.Popen(
            [batch_file.name],
            stdin=subproc.PIPE,
            stdout=subproc.PIPE,
            stderr=subproc.STDOUT,
            text=True,
            shell=True,
            cwd=cwd,
            bufsize=1, # 行単位でバッファリング
            encoding=popen_encoding,
            errors='replace'
        )

        # バッチの途中に「pause」がある場合、改行をあらかじめ標準入力に流し込んでおく
        # ※ pauseで出力されるメッセージ末尾には"\n"が入っていないため、process.stdout.readline()では読み取れないので注意
        process.stdin.write("\n" * 10) # バッチファイル内のpause複数回出現に対応
        process.stdin.flush()

        # バッチの出力を標準出力に出すときに、出力不可な文字があってもエラーで落ちないための対策
        sys.stdout.reconfigure(errors='replace')
        sys.stderr.reconfigure(errors='replace')

        # 出力をリアルタイムで読み取って表示
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                if stdout_encoding:
                    sys.stdout.buffer.write(line.encode(stdout_encoding, errors='replace'))
                    sys.stdout.buffer.flush()
                else:
                    sys.stdout.write(line)
                    sys.stdout.flush()
        print('"""')

        logging.info("Batch execution completed!!")

        returncode = process.poll()
        return returncode

    except subproc.CalledProcessError as e:
        logging.error(f"❌ バッチ実行中にエラーが発生しました（Exit Code: {e.returncode}）")
        logging.error(f"エラー内容: {e.stderr}")
        raise

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        raise