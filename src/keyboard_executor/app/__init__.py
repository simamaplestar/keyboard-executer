"""GUI 層（PySide6）。Qt import 只允許出現在本套件與 keyboard_executor.gui；
core/platforms/storage 一律不知道 Qt。每個畫面切成「純 Python controller/model
（無 Qt import，可完整單元測試）＋薄 QWidget（只做版面與 signal/slot 接線）」。"""
