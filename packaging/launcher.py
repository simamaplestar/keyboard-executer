"""PyInstaller 進入點：打包後的可執行檔從這裡啟動 GUI。

保持極薄：所有組裝在 keyboard_executor.gui.main——pip 安裝的
[project.gui-scripts] 與打包後的執行檔共用同一進入點，行為一致。"""
import sys
import multiprocessing

from keyboard_executor.gui import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
