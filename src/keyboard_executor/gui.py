"""GUI 進入點：python -m keyboard_executor.gui"""
from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    import multiprocessing
    multiprocessing.freeze_support()
    import argparse

    parser = argparse.ArgumentParser(description="keyboard-executor GUI")
    parser.add_argument("--dir", default=None,
                        help="資料目錄（預設 ~/.keyboard-executor/scripts）")
    parser.add_argument("--self-test", action="store_true",
                        help="發布前自我檢查：載入所有模組與 OCR 模型、建立主視窗後結束")
    args = parser.parse_args(argv)
    if args.self_test:
        from keyboard_executor.app.self_test import run_self_test
        return run_self_test()

    from keyboard_executor.app.application import build_app

    app, window = build_app(data_dir=args.dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
