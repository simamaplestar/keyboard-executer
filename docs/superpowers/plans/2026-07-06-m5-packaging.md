# M5 打包與發布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 M5：PyInstaller 產出兩平台可執行檔的完整建置設定（spec §13-M5），macOS 權限引導補完（主動請求 `CGRequestScreenCaptureAccess`/`CGRequestListenEventAccess`＋`x-apple.systempreferences:` 直達系統設定 deep link，spec §10）；logging 收斂（stderr print → 滾動日誌檔＋GUI 日誌面板，spec §10 末段）；版本單一來源與 CLI `--version`；GUI 刪除入口（腳本/規則/模板）接上 M4 已建好的 delete seams。同時吸收 M4 最終審查「M5 計畫必須吸收的待辦」全部 10 項（各任務內明列，未做者在文末對應表註明延後理由）。

**Architecture:** M5 把每個任務切成「可自動化的支撐邏輯」與「原生建置／實機」兩半：logging 設定、版本中繼資料、deep-link URL 組裝、權限請求包裝、刪除編排全部沿用既有「純 Python ＋ 注入」模式，pytest 測到底；PyInstaller 建置、codesign/notarytool 簽章公證、TCC 權限對話框則是腳本化＋文件化的人工步驟（原生呼叫一律 `# pragma: no cover`），絕不以假測試冒充建置驗證。Qt 依然只准出現在 `app/` 與 `gui.py`——新的 `core/logging_config.py` 是純 Python，GUI 橋接（`QtLogHandler`）住在 `app/qt_log_handler.py`。

**Tech Stack:** 既有（Python 3.11+、PySide6 6.11、pynput/pywinctl/mss/opencv-python-headless/numpy/pyobjc、pytest）＋標準庫 `logging`（`RotatingFileHandler`）與 `tomllib`；建置期新增 PyInstaller（`>=6.16`，僅入 `[project.optional-dependencies] packaging` extra，不進 runtime 依賴）。

**對應 spec:** `docs/superpowers/specs/2026-07-06-keyboard-executor-design.md` §13-M5（「PyInstaller 產出兩平台可執行檔；macOS 權限引導完整」→ Task 5 ＋ Task 3；Windows 建置腳本備妥但實機驗證需 Windows 機器，如實列 backlog）、§10（「所有事件寫入 GUI 日誌面板與滾動日誌檔」→ Task 1；「引導畫面（附直達系統設定的連結）」→ Task 3）、§5（settings.json 的 log_level 接進 logging → Task 1）、§14（簽章、打包體積 50–100MB、防毒誤報 → Task 5 README）、§15（v2 範圍外確認不做 → 文末）。吸收 `docs/superpowers/notes/2026-07-06-m4-final-review.md`「M5 計畫必須吸收的待辦」1–10（對應表見文末）；Windows backlog（M1/M2b/M3/M4 跨里程碑累積）明列文末，需 Windows 實機，本計畫不假裝清償。

## Global Constraints

- Python `>=3.11`；src layout：程式碼一律在 `src/keyboard_executor/` 下（spec §4）
- 專案 venv 為 `.venv`（Python 3.14.6）；下列所有 `python` 指令都在啟用 venv 後於 repo 根目錄執行（`source .venv/bin/activate` 或以 `.venv/bin/python` 代替）
- 判斷作業系統（`sys.platform`）只允許出現在 `platforms/` 層；既有已核准例外：`cli._check_darwin_permissions`、`app/application.py` 權限檢查函式群（本計畫在同函式群新增 `request_missing_permissions`，沿用同一例外）、`app/region_picker.py.drag_scale`。**`packaging/*.spec` 與 build 腳本是建置期腳本、不進 runtime 的 `src/`，其中的 `sys.platform` 分派不受此 runtime 約束**（spec 檔內註明）
- **Qt import 只允許出現在 `src/keyboard_executor/app/` 與 `src/keyboard_executor/gui.py`**；core/、platforms/、storage/ 一律不得 import PySide6——特別地：`core/logging_config.py` 純 Python，`QtLogHandler` 在 `app/`
- 所有面向使用者的訊息（錯誤、GUI 文字、日誌、docstring 內操作說明）一律繁體中文（台灣用語）
- 外部依賴一律建構子/參數注入，預設為真實實作（spec §12）；原生呼叫（`CGRequest*`、PyInstaller、codesign）的 lazy import 行加 `# pragma: no cover - 需原生環境`，並在人工驗收清單留驗證項——**不寫假測試冒充建置或原生行為驗證**
- 不新增 runtime 依賴；PyInstaller 只進 `packaging` extra，僅建置機安裝
- Commit 訊息用 conventional commits；直接在 main 工作，不開分支（用戶既定選擇）
- TDD：RED 一律用計畫指定的 pytest 指令執行，報告需貼 `rtk proxy python -m pytest ...` 的**原始 transcript**（本機 RTK hook 會壓縮 pytest 輸出，需用 `rtk proxy` 取原始格式）；全套件回歸在 repo 根目錄跑 `python -m pytest -q`
- YAGNI：只實作本計畫列出的行為。模板影像預覽（M4 待辦 #5）、run/watch worker helper 抽共用（M4 待辦 #6）、多螢幕框選（M4 待辦 #7）皆明列延後（理由見文末對應表），不「順手」做
- 全套件基準（計畫撰寫時已實測於 macOS）：**461 passed, 1 skipped**（`test_win32_input` 的 1 個 win32-gated skip）。各任務結束的精確累計總數列在該任務回歸步驟

### M5 可測／人工切分（每任務共同遵循）

| 任務 | 可自動化（pytest） | 人工／腳本（`# pragma: no cover` 或建置步驟） |
|------|-------------------|---------------------------------------------|
| 1 logging 收斂 | `setup_logging`（滾動檔、冪等、等級）、`QtLogHandler` record→字串 payload、print→logger 行為（caplog）、build_app/cli 接線 | 打包後日誌實際落在資料目錄（人工驗收 #6） |
| 2 版本 | `__version__` ↔ pyproject 一致（tomllib）、CLI `--version` 輸出與 exit 0 | —（無原生面） |
| 3 macOS 權限 | `system_settings_url` 精確字串、`request_*` 注入包裝、缺失權限→URL 映射、橫幅按鈕接線（url_opener 注入） | `CGRequest*` 原生呼叫、系統設定實際跳轉、TCC 對話框（人工驗收 #4） |
| 4 GUI 刪除＋清理 | 刪除編排（confirm 注入）、模板管理清單/刪除、rule_editor 注入、訊息格式統一 | QMessageBox 實機外觀、qtbase 繁中翻譯生效（人工驗收 #7/#9） |
| 5 PyInstaller | entry point 解析為可呼叫、launcher 可載入、spec 檔文字 sanity | `pyinstaller` 建置、codesign/notarytool/staple、.app 實機端到端（人工驗收全清單） |

### 跨任務型別契約（先鎖定，後續任務一致消費）

| 名稱 | 位置 | 簽名／形狀 | 引入任務 |
|------|------|-----------|---------|
| `PACKAGE_LOGGER` | `core/logging_config.py` | `"keyboard_executor"`；各模組一律 `logging.getLogger(__name__)` 進此階層 | Task 1 |
| `setup_logging` | `core/logging_config.py` | `(log_dir: str \| Path, level: str = "INFO") -> logging.Logger`；`<log_dir>/app.log` RotatingFileHandler（1MB × 3 備份，utf-8）＋ StreamHandler(stderr)；冪等（重呼叫先拆舊 handler）；propagate 維持 True（caplog 免設定） | Task 1 |
| `QtLogHandler` / `LogBridge` | `app/qt_log_handler.py` | `LogBridge.line = Signal(str)`；`QtLogHandler().bridge.line` 每筆 record 發一次格式化字串（`"%H:%M:%S [LEVEL] message"`） | Task 1 |
| `attach_gui_handler` / `detach_gui_handler` | `app/qt_log_handler.py` | `(sink: Callable[[str], None], *, level: str = "INFO") -> QtLogHandler`；`(handler \| None) -> None` | Task 1 |
| print→logger 行為 | `core/player.py`、`core/rule_engine.py`、`app/run_controller.py`、`app/watch_controller.py` | `_poll_until` 輪內失敗→`logger.warning`；`_log_failure`→warning、`_log_fire_failure`→error、`_fire` run_script 失敗→error；guard 警告→warning。**訊息原文一字不改；on_error/notifier 回呼原樣保留（logging 是 additive）** | Task 1 |
| `MainWindow.gui_log_handler` | `app/application.py` 設定 | build_app 掛上後存於 window 公開屬性；closeEvent `detach_gui_handler` 收尾 | Task 1 |
| `__version__` 0.5.0 | `__init__.py` ↔ `pyproject.toml` | 單一來源測試鎖定（tomllib） | Task 2 |
| CLI `--version` | `cli.py` | `argparse action="version"`，輸出 `keyboard-executor 0.5.0`，exit 0 | Task 2 |
| `system_settings_url` | `platforms/darwin/permissions.py` | `(pane: str) -> str`；pane ∈ accessibility / screen-recording / input-monitoring；未知拋 `ValueError`（繁中） | Task 3 |
| `request_screen_recording` / `request_input_monitoring` | `platforms/darwin/permissions.py` | `(_request=None) -> bool`；lazy import `CGRequest*`（pragma no cover），注入供測試 | Task 3 |
| `settings_urls_for_missing` | `app/application.py` | `(checks=None) -> list[str]`（缺失權限的 deep-link URL，順序同 checks；未知權限名稱略過） | Task 3 |
| `request_missing_permissions` | `app/application.py` | `(requesters=None) -> None`；darwin 預設 `(request_screen_recording, request_input_monitoring)`、非 darwin no-op；個別失敗吞掉不阻斷啟動 | Task 3 |
| `build_app(..., request_permissions=None)` | `app/application.py` | None → `request_missing_permissions`；**測試一律注入 no-op 避免真實 TCC 呼叫** | Task 3 |
| `MainWindow(..., url_opener=None)` ＋ `open_settings_button` | `app/main_window.py` | 橫幅下「開啟系統設定」鈕；無警告時隱藏 | Task 3 |
| `confirm_delete` | `app/confirm.py` | `(parent, message: str) -> bool`；自建繁中「刪除／取消」按鈕（不用 Qt 內建英文 Yes/No） | Task 4 |
| `MainWindow(..., confirm=None)` ＋ `script_delete_button` / `rule_delete_button` / `template_manage_button` | `app/main_window.py` | confirm 注入供測試，預設 `confirm_delete` | Task 4 |
| `TemplateManagerDialog` | `app/template_manager.py` | `(store, confirm=None, parent=None)`；`template_list` / `delete_button` / `status_label` / `refresh()` | Task 4 |
| `RuleEditorDialog(..., get_platform=None, capture_factory=None)` ＋ `_ask_template_name()` seam | `app/rule_editor.py` | None → 真實 `get_platform` / `MssScreenCapture`（lazy import） | Task 4 |
| `default_permission_checks` | `app/application.py` | `_default_permission_checks` 更名公開（M4 待辦 #8 後半） | Task 4 |
| 規則數字欄位錯誤格式 | `core/models.py` ↔ `app/rule_editor_model.py` | 統一 `規則欄位 {name} 必須是數字: {value!r}`（>0 / >=0 同樣帶值） | Task 4 |
| `[project.scripts]` / `[project.gui-scripts]` | `pyproject.toml` | `keyboard-executor = "keyboard_executor.cli:main"`、`keyboard-executor-gui = "keyboard_executor.gui:main"` | Task 5 |
| `packaging/` | 新目錄 | `launcher.py`、`keyboard-executor.spec`、`entitlements.plist`、`build.sh`、`build.ps1`、`README.md` | Task 5 |

### 全套件累計數（各任務回歸步驟的預期值）

| 任務 | 新增測試 | `python -m pytest -q` 預期 |
|------|---------|---------------------------|
| 基準 | — | 461 passed, 1 skipped |
| Task 1 | +10 | **471 passed, 1 skipped** |
| Task 2 | +2 | **473 passed, 1 skipped** |
| Task 3 | +9 | **482 passed, 1 skipped** |
| Task 4 | +9 | **491 passed, 1 skipped** |
| Task 5 | +3 | **494 passed, 1 skipped** |

（Task 5 的 PyInstaller 建置、簽章、.app 啟動為人工/腳本步驟，**新增 0 個自動化測試**——僅 3 個設定檔 sanity 測試。）

---

### Task 1: logging 收斂——滾動日誌檔＋GUI 日誌橋（M4 待辦 #2）

打包成 .app/.exe 後沒有終端機，現有三處 stderr print（`player._poll_until` 輪內失敗、`rule_engine` 的 `_fire`/`_matches` 失敗、run/watch controller 的 guard 警告）完全不可見——違反 spec §10「所有事件寫入 GUI 日誌面板與滾動日誌檔」。本任務：(1) 新增 `core/logging_config.py`（純 Python）：`setup_logging` 掛 RotatingFileHandler（`<資料目錄>/logs/app.log`，預設資料目錄下即 `~/.keyboard-executor/scripts/logs/app.log`）＋ StreamHandler；(2) 把上述 print 全數改為 `logger.warning/error`，**訊息原文不變、on_error/notifier 回呼原樣保留**（logging 是 additive，GUI progress 記錄不受影響）；(3) `app/qt_log_handler.py` 薄橋：`QtLogHandler` 每筆 record 經 `LogBridge.line` signal 投遞（Worker QThread 裡的記錄跨執行緒 queued 送達 GUI 執行緒），build_app 接到 `MainWindow.append_log`；(4) cli.main 與 build_app 接上 `setup_logging`（GUI 用 settings.log_level 當等級）。

**刻意不改的 print（記錄於此，非遺漏）：** `app/settings.py` SettingsStore.load 失敗警告——它發生在 `setup_logging` 之前（log_level 來自 settings，雞生蛋），維持 stderr；`storage/rules.py` load_enabled 跳過損毀檔——GUI 已有可見面（規則清單顯示「（載入失敗）」）、CLI watch 有 stderr；CLI 的使用者互動輸出（print/echo）本來就是介面，不動。

**切分：** 可測＝setup_logging 行為、QtLogHandler record→payload、logger 取代 print（caplog）、接線；人工＝打包後日誌實際落地（Task 5 人工驗收 #6）。

**Files:**
- Create: `src/keyboard_executor/core/logging_config.py`
- Create: `src/keyboard_executor/app/qt_log_handler.py`
- Create: `tests/conftest.py`（autouse：每測後重置套件 logger handlers）
- Create: `tests/core/test_logging_config.py`（4 個）
- Create: `tests/app/test_qt_log_handler.py`（3 個）
- Modify: `src/keyboard_executor/core/player.py`（`_poll_until` print→logger；移除 `import sys`）
- Modify: `src/keyboard_executor/core/rule_engine.py`（三處 print→logger；移除 `import sys`；docstring 措辭）
- Modify: `src/keyboard_executor/app/run_controller.py`、`app/watch_controller.py`（guard 警告 print→logger；移除 `import sys`）
- Modify: `src/keyboard_executor/app/application.py`（build_app 接 setup_logging＋attach_gui_handler）
- Modify: `src/keyboard_executor/app/main_window.py`（closeEvent detach_gui_handler）
- Modify: `src/keyboard_executor/cli.py`（main 接 setup_logging）
- Test(更新既有): `tests/core/test_player_wait.py`（1 個 capsys→caplog）、`tests/core/test_rule_engine.py`（4 個 capsys→caplog）、`tests/app/test_run_controller.py`（1 個）、`tests/app/test_watch_controller.py`（1 個）、`tests/app/test_application.py`（4 個 build_app 測試補 `data_dir=tmp_path`，追加 2 個新測試）、`tests/test_cli_main.py`（追加 1 個）

**Interfaces:**
- Consumes: 既有 `Player._poll_until`、`RuleEngine._log_failure/_log_fire_failure/_fire`、`RunController._start_guard`、`WatchController._start_guard`、`build_app`、`MainWindow.append_log/closeEvent`、`Settings.log_level`、`cli.main`
- Produces（形狀見跨任務契約表）: `PACKAGE_LOGGER`、`setup_logging`、`QtLogHandler`/`LogBridge`、`attach_gui_handler`/`detach_gui_handler`、`MainWindow.gui_log_handler`

- [ ] **Step 1: 寫失敗測試**

`tests/conftest.py`（新檔——不是測試，是全套件基座，先建）：

```python
"""全套件共用基座：每測後重置套件根 logger 的 handlers。

setup_logging / attach_gui_handler 掛在全域 logging 狀態上（跨測試存活），
不清理會讓 handler 累積：後續測試把記錄寫進已刪除 tmp 目錄的檔案、或投遞給
已銷毀的 widget。autouse 每測後拆除，測試彼此隔離。本檔不得 import PySide6
（非 GUI 測試不碰 Qt）。"""
import logging

import pytest


@pytest.fixture(autouse=True)
def _reset_package_logger():
    yield
    logger = logging.getLogger("keyboard_executor")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
```

`tests/core/test_logging_config.py`（新檔）：

```python
"""集中式日誌設定（M4 待辦 #2：stderr 打包後不可見 → logging 收斂，spec §10）。"""
import logging
from logging.handlers import RotatingFileHandler

from keyboard_executor.core.logging_config import PACKAGE_LOGGER, setup_logging


def test_setup_logging_writes_rotating_file(tmp_path):
    logger = setup_logging(tmp_path / "logs")
    logger.warning("測試訊息：%s", "甲")
    log_file = tmp_path / "logs" / "app.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "測試訊息：甲" in content
    assert "[WARNING]" in content
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 1_000_000
    assert file_handlers[0].backupCount == 3


def test_setup_logging_idempotent(tmp_path):
    setup_logging(tmp_path / "logs")
    logger = setup_logging(tmp_path / "logs")   # 重複呼叫不得累積 handler
    assert len(logger.handlers) == 2            # RotatingFileHandler + StreamHandler
    logger.warning("只出現一次")
    content = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert content.count("只出現一次") == 1


def test_setup_logging_respects_level(tmp_path):
    logger = setup_logging(tmp_path / "logs", level="WARNING")
    logger.info("不該寫入")
    logger.warning("該寫入")
    content = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "不該寫入" not in content
    assert "該寫入" in content


def test_module_loggers_propagate_into_package_log(tmp_path):
    """各模組 logging.getLogger(__name__) 屬 keyboard_executor.* 階層，
    記錄必須流進 setup_logging 掛的檔案 handler（階層契約）。"""
    setup_logging(tmp_path / "logs")
    logging.getLogger(f"{PACKAGE_LOGGER}.core.player").warning("子模組訊息")
    content = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "子模組訊息" in content
    assert "keyboard_executor.core.player" in content
```

`tests/app/test_qt_log_handler.py`（新檔）：

```python
"""logging → Qt signal 橋（app 薄件）：record→字串 payload、等級過濾、掛載/拆除。"""
import logging

from keyboard_executor.app.qt_log_handler import (
    QtLogHandler,
    attach_gui_handler,
    detach_gui_handler,
)


def make_record(level, message):
    return logging.LogRecord(name="keyboard_executor.core.player", level=level,
                             pathname=__file__, lineno=1, msg=message,
                             args=(), exc_info=None)


def test_handler_formats_record_and_emits_line(qapp):
    lines = []
    handler = QtLogHandler()
    handler.bridge.line.connect(lines.append)
    handler.emit(make_record(logging.WARNING, "規則失敗：甲"))
    assert len(lines) == 1
    assert "[WARNING] 規則失敗：甲" in lines[0]   # HH:MM:SS 前綴由 formatter 提供


def test_handler_level_filters_records(qapp):
    lines = []
    handler = QtLogHandler()
    handler.setLevel(logging.ERROR)
    handler.bridge.line.connect(lines.append)
    handler.handle(make_record(logging.WARNING, "低於等級"))
    handler.handle(make_record(logging.ERROR, "達到等級"))
    assert len(lines) == 1 and "達到等級" in lines[0]


def test_attach_and_detach_gui_handler(qapp):
    lines = []
    handler = attach_gui_handler(lines.append, level="WARNING")
    try:
        logging.getLogger("keyboard_executor.app.somewhere").warning("橋接訊息")
        assert any("橋接訊息" in line for line in lines)
    finally:
        detach_gui_handler(handler)
    logging.getLogger("keyboard_executor.app.somewhere").warning("拆除後")
    assert not any("拆除後" in line for line in lines)
```

`tests/app/test_application.py`——**既有 4 個 build_app 測試改為傳 `data_dir=tmp_path`**（build_app 將呼叫 setup_logging，不得寫進真實家目錄）：`test_build_app_constructs_window_with_title`、`test_main_window_has_core_panels`、`test_permission_banner_visible_with_warnings`、`test_permission_banner_hidden_without_warnings` 四個的簽名加 `tmp_path`、呼叫改 `build_app(data_dir=tmp_path, permission_checks=…)`（斷言不變）。檔尾追加：

```python
def test_build_app_sets_up_logging_in_data_dir(qapp, tmp_path):
    build_app(data_dir=tmp_path, permission_checks={})
    assert (tmp_path / "logs" / "app.log").exists()


def test_build_app_bridges_logger_records_to_log_view(qapp, tmp_path):
    import logging

    _, window = build_app(data_dir=tmp_path, permission_checks={})
    logging.getLogger("keyboard_executor.core.rule_engine").error("規則甲觸發失敗")
    qapp.processEvents()
    assert "規則甲觸發失敗" in window.log_view.toPlainText()
```

`tests/test_cli_main.py` 檔尾追加：

```python
def test_main_sets_up_rolling_log_under_data_dir(tmp_path):
    main(["list", "--dir", str(tmp_path)])
    assert (tmp_path / "logs" / "app.log").exists()
```

Run: `rtk proxy python -m pytest tests/core/test_logging_config.py tests/app/test_qt_log_handler.py tests/app/test_application.py tests/test_cli_main.py -v`
Expected: `test_logging_config` 與 `test_qt_log_handler` 全數 `ModuleNotFoundError: No module named 'keyboard_executor.core.logging_config'`（等）；`test_build_app_sets_up_logging_in_data_dir`、`test_build_app_bridges_logger_records_to_log_view`、`test_main_sets_up_rolling_log_under_data_dir` FAILED（logs/app.log 不存在）；既有測試仍綠。

- [ ] **Step 2: 既有 stderr 斷言測試改 caplog（與實作同步的 RED 前置）**

以下 7 個既有測試把 `capsys` 換成 `caplog`（訊息斷言字串不變）。**改完後這些測試會先 FAIL（實作仍是 print），Step 3 實作後轉綠**——這是本任務「破壞既有測試的點」的同步修正。

(a) `tests/core/test_player_wait.py` 整個函式替換：

```python
def test_wait_poll_exception_logged_in_traditional_chinese(caplog):
    import logging

    cap = FlakyCapture(scale=1.0)
    ocr = FakeOcrEngine(boxes=[box("完成")])
    platform, _, _ = make_platform(capture=cap, ocr=ocr)
    script = make_script([{"type": "wait_text", "pattern": "完成", "timeout_ms": 100000}])
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        result = Player(platform, sleep=lambda s: None).play(script)
    assert result.ok
    assert "已跳過" in caplog.text and "擷取暫時失敗" in caplog.text
```

(b) `tests/core/test_rule_engine.py` 四個函式替換（其餘行不動；模組頂已有的 import 沿用，函式內補 `import logging` 不必——統一在檔頂加一行 `import logging`）：

```python
def test_capture_failure_logged_in_traditional_chinese(caplog):
    """擷取例外必須「記錄」（spec §10），不能只是吞掉；訊息含規則名稱，繁中。
    M5 起經 logging（GUI 日誌面板與滾動日誌檔皆可見），不再 print 到 stderr。"""
    class BoomCapture(FakeScreenCapture):
        def capture(self, region):
            raise RuntimeError("截圖失敗")

    engine = RuleEngine(make_platform(BoomCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), clock=Clock())
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        engine.evaluate_once([text_rule(name="斷線監控")])
    assert "斷線監控" in caplog.text
    assert "跳過" in caplog.text
```

```python
def test_fire_missing_script_isolated_and_logged_without_crashing(caplog):
    """觸發 run_script 時腳本不存在（storage.load 拋例外）：_fire 的例外必須被隔離
    （與 _matches 一樣），watch 不可因此崩潰；同一輪其他規則仍須評估與觸發。"""
    notes = []
    broken = text_rule(name="缺腳本規則",
                       trigger={"type": "run_script", "script_name": "不存在的腳本"})
    healthy = text_rule(name="正常規則", trigger={"type": "notify", "message": "正常觸發"})
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append,
                        player_factory=FakePlayer, clock=Clock())
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        engine.evaluate_once([broken, healthy])   # 不得拋例外
    assert "缺腳本規則" in caplog.text
    assert "跳過" in caplog.text
    assert notes == ["正常觸發"]
```

```python
def test_fire_run_script_failure_result_is_logged_not_discarded(caplog):
    """run_script 觸發的 Player 回傳 ok=False：PlayResult 過去被完全丟棄，
    現在必須記錄規則名稱、腳本名稱與 result.error，不可悄悄無痕跡。"""
    from keyboard_executor.core.models import script_from_dict

    class FailingPlayer:
        def __init__(self, platform, storage=None, templates=None, **k):
            pass

        def play(self, script):
            return PlayResult(ok=False, actions_run=1, error="目標視窗已關閉")

    sub = script_from_dict({"name": "重連", "target_window": {"title_pattern": "遊戲"},
                            "actions": [{"type": "key_press", "key": "a"}]})
    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage({"重連": sub}),
                        player_factory=FailingPlayer, clock=Clock())
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        engine.evaluate_once([text_rule(trigger={"type": "run_script",
                                                 "script_name": "重連"})])
    assert "重連" in caplog.text
    assert "目標視窗已關閉" in caplog.text
```

```python
def test_on_fire_exception_isolated_like_fire_failures(caplog):
    notes = []

    def boom(name, ttype):
        raise RuntimeError("GUI 回呼壞掉")

    engine = RuleEngine(make_platform(FakeScreenCapture(), FakeOcrEngine([tbox("連線中斷")])),
                        storage=DictStorage(), notifier=notes.append, clock=Clock(),
                        on_fire=boom)
    first = text_rule(name="規則甲", trigger={"type": "notify", "message": "甲"})
    second = text_rule(name="規則乙", trigger={"type": "notify", "message": "乙"})
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        engine.evaluate_once([first, second])   # 不得拋例外（on_fire 例外由 _fire 隔離吸收）
    assert "規則甲" in caplog.text and "規則乙" in caplog.text and "跳過" in caplog.text
    assert notes == []   # on_fire 於觸發前失敗，兩條規則的 notify 都未執行、皆被記錄
```

(c) `tests/app/test_run_controller.py`（檔頂加 `import logging`）函式替換：

```python
def test_guard_best_effort_started_stopped_and_failure_ignored(tmp_path, caplog):
    SpyGuard.instances = []
    controller, *_ = make_controller(tmp_path, stop_key="f8")
    controller.build_job("甲")(lambda r: None)
    guard = SpyGuard.instances[-1]
    assert guard.started == 1 and guard.stopped == 1
    assert guard.stop_key == "f8"                       # 設定頁自訂熱鍵的掛點
    assert guard.stop_event is SpyPlayer.last.stop_event  # 與 Player 共用同一顆

    def exploding_guard(*a, **k):
        raise RuntimeError("缺輸入監控權限")

    controller2, *_ = make_controller(tmp_path, guard_factory=exploding_guard)
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        result = controller2.build_job("甲")(lambda r: None)
    assert result.ok                                     # 守護失敗不阻斷回放
    assert "緊急停止熱鍵無法啟用" in caplog.text
```

(d) `tests/app/test_watch_controller.py`（檔頂加 `import logging`）函式替換：

```python
def test_guard_best_effort_with_configured_stop_key(tmp_path, caplog):
    SpyGuard.instances = []
    controller = make_controller(tmp_path, stop_key="f8")
    controller.build_job()(lambda r: None)
    guard = SpyGuard.instances[-1]
    assert guard.started == 1 and guard.stopped == 1 and guard.stop_key == "f8"

    def exploding(*a, **k):
        raise RuntimeError("缺權限")

    controller2 = make_controller(tmp_path, guard_factory=exploding)
    with caplog.at_level(logging.WARNING, logger="keyboard_executor"):
        result = controller2.build_job()(lambda r: None)
    assert result.startswith("已停止監看")            # 守護失敗不阻斷監看
    assert "緊急停止熱鍵無法啟用" in caplog.text
```

Run: `rtk proxy python -m pytest tests/core/test_player_wait.py tests/core/test_rule_engine.py tests/app/test_run_controller.py tests/app/test_watch_controller.py -v`
Expected: 上述 7 個改寫測試 FAILED（caplog 空、訊息仍走 stderr），其餘綠。

- [ ] **Step 3: 實作**

(a) `src/keyboard_executor/core/logging_config.py`（新檔，全文）：

```python
"""集中式日誌設定（spec §10：所有事件寫入 GUI 日誌面板與滾動日誌檔）。

純 Python、無 Qt——GUI 端橋接（app/qt_log_handler.py 的 QtLogHandler）只負責
把 LogRecord 轉成 Qt signal。各模組一律 logging.getLogger(__name__) 取
keyboard_executor.* 階層 logger；setup_logging 只掛在套件根 logger 上，
propagate 維持預設 True——記錄照樣流向 root，pytest caplog 免設定即可斷言，
一般執行時 root 無 handler、不會重複輸出。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

PACKAGE_LOGGER = "keyboard_executor"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 1_000_000   # 單檔 1MB
_BACKUP_COUNT = 3        # app.log.1 ~ app.log.3


def setup_logging(log_dir: str | Path, level: str = "INFO") -> logging.Logger:
    """設定套件根 logger：<log_dir>/app.log 滾動檔＋ stderr 串流。

    冪等：重複呼叫（GUI 重啟、測試）會先拆除既有 handlers 再重掛，不會重複
    輸出；GUI 橋（QtLogHandler）由 build_app 在本函式之後另掛。回傳套件根
    logger 供進一步掛載。level 用 settings.json 的 log_level 值
    （DEBUG/INFO/WARNING/ERROR，與 logging 等級名一致）。"""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(PACKAGE_LOGGER)
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    file_handler = RotatingFileHandler(log_dir / "app.log", maxBytes=_MAX_BYTES,
                                       backupCount=_BACKUP_COUNT, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger
```

(b) `src/keyboard_executor/app/qt_log_handler.py`（新檔，全文）：

```python
"""logging → Qt signal 橋（app 層薄件）：把 LogRecord 格式化後投遞給 GUI 日誌面板。

QtLogHandler 可能在任意執行緒被呼叫（Worker QThread 裡的 Player/RuleEngine
logger 也流到這裡），因此不直接碰 widget，一律經 LogBridge 的 signal——
跨執行緒 emit 由 Qt queued connection 安全投遞到 GUI 執行緒（與 Worker
progress signal 同一治理，M4 既定模式）。"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from keyboard_executor.core.logging_config import PACKAGE_LOGGER

GUI_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
GUI_DATE_FORMAT = "%H:%M:%S"


class LogBridge(QObject):
    line = Signal(str)


class QtLogHandler(logging.Handler):
    """format 後經 bridge.line signal 投遞；emit 例外交給 handleError
    （logging 慣例——日誌本身故障不可拖垮回放/監看）。"""

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self.bridge = LogBridge()
        self.setFormatter(logging.Formatter(GUI_LOG_FORMAT, datefmt=GUI_DATE_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.line.emit(self.format(record))
        except Exception:
            self.handleError(record)


def attach_gui_handler(sink, *, level: str = "INFO") -> QtLogHandler:
    """建 QtLogHandler、connect 到 sink（如 MainWindow.append_log）、掛上
    套件根 logger；回傳 handler 供 detach_gui_handler 收尾。"""
    handler = QtLogHandler()
    handler.setLevel(level)
    handler.bridge.line.connect(sink)
    logging.getLogger(PACKAGE_LOGGER).addHandler(handler)
    return handler


def detach_gui_handler(handler: QtLogHandler | None) -> None:
    """自套件根 logger 拆除 GUI 橋（關窗收尾；None 安全 no-op）。"""
    if handler is None:
        return
    logging.getLogger(PACKAGE_LOGGER).removeHandler(handler)
    handler.close()
```

(c) `src/keyboard_executor/core/player.py`：
- 檔頂 `import sys` 刪除，改加 `import logging`；import 區塊後加模組級 `logger = logging.getLogger(__name__)`
- `_poll_until` 的 except 區塊替換：

```python
            except Exception as e:
                logger.warning("wait 動作本輪擷取或辨識失敗，已跳過：%s", e)
                hit = None
```

（docstring「記錄並跳過該輪」語義不變，不用改。）

(d) `src/keyboard_executor/core/rule_engine.py`：
- 檔頂 `import sys` 刪除，改加 `import logging`；import 區塊後加 `logger = logging.getLogger(__name__)`
- 模組 docstring 第 5 行「錯誤訊息印到 stderr（繁中），不吃掉不留痕跡」改為「錯誤經 logging 記錄（繁中；GUI 日誌面板與滾動日誌檔皆可見），不吃掉不留痕跡」
- 三處替換：

```python
    def _log_failure(self, rule: Rule, error: Exception) -> None:
        logger.warning("規則 %r 本輪擷取或比對失敗，已跳過：%s", rule.name, error)
        self._emit_error(rule, f"本輪擷取或比對失敗，已跳過：{error}")

    def _log_fire_failure(self, rule: Rule, error: Exception) -> None:
        logger.error("規則 %r 觸發失敗，已跳過：%s", rule.name, error)
        self._emit_error(rule, f"觸發失敗，已跳過：{error}")
```

`_fire` 內 `if not result.ok:` 區塊替換：

```python
            if not result.ok:
                # PlayResult 不可靜默丟棄（spec §10）：記錄規則、腳本與錯誤，
                # 同時經 on_error 進 GUI 日誌（M4 修正批次既定行為，logging 為 additive）。
                logger.error("規則 %r 觸發腳本 %r 中止：%s",
                             rule.name, trig.script_name, result.error)
                self._emit_error(rule, f"觸發腳本 {trig.script_name!r} 中止：{result.error}")
```

(e) `src/keyboard_executor/app/run_controller.py`：檔頂 `import sys` 刪除、加 `import logging` 與 `logger = logging.getLogger(__name__)`；`_start_guard` 的 except 替換：

```python
        except Exception:
            logger.warning("緊急停止熱鍵無法啟用（可能缺輸入監控權限），仍可用停止按鈕")
            return None
```

(f) `src/keyboard_executor/app/watch_controller.py`：同 (e)（訊息尾為「仍可用停止監看按鈕」）：

```python
        except Exception:
            logger.warning("緊急停止熱鍵無法啟用（可能缺輸入監控權限），仍可用停止監看按鈕")
            return None
```

(g) `src/keyboard_executor/app/application.py`——`build_app` 整個函式替換：

```python
def build_app(argv=None, *, data_dir=None, permission_checks=None):
    """建立（或重用）QApplication 與主視窗：載入設定、日誌、權限檢查、全接線。"""
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from keyboard_executor.app.main_window import MainWindow
    from keyboard_executor.app.qt_log_handler import attach_gui_handler
    from keyboard_executor.app.settings import SettingsStore
    from keyboard_executor.cli import default_scripts_dir
    from keyboard_executor.core.logging_config import setup_logging

    app = QApplication.instance() or QApplication(list(argv) if argv else [])
    directory = Path(data_dir) if data_dir is not None else default_scripts_dir()
    settings = SettingsStore(directory).load()
    setup_logging(directory / "logs", level=settings.log_level)
    window = MainWindow(
        directory, settings=settings,
        permission_warnings=collect_permission_warnings(permission_checks),
        permission_checks=permission_checks)
    # GUI 日誌橋：logger 記錄（含 Worker QThread 內的）同步進日誌面板（spec §10）。
    # 存為公開屬性，closeEvent 收尾時 detach，避免對已銷毀 widget 投遞。
    window.gui_log_handler = attach_gui_handler(window.append_log,
                                                level=settings.log_level)
    return app, window
```

(h) `src/keyboard_executor/app/main_window.py`——`closeEvent` 整個方法替換：

```python
    def closeEvent(self, event):
        # 關窗前先停掉進行中的回放/監看，並等 QThread 真正結束，避免 teardown 時
        # 「QThread: Destroyed while thread is still running」與背景仍送輸入；
        # 最後拆除 GUI 日誌橋（build_app 掛上的），避免後續記錄投遞給已銷毀 widget。
        self._run_controller.stop()
        self._watch_controller.stop()
        self._cleanup_worker()
        self._cleanup_watch_worker()
        from keyboard_executor.app.qt_log_handler import detach_gui_handler

        detach_gui_handler(getattr(self, "gui_log_handler", None))
        event.accept()
```

(i) `src/keyboard_executor/cli.py`：import 區塊加 `from keyboard_executor.core.logging_config import setup_logging`；`main` 開頭三行替換（`storage = ScriptStorage(args.dir or default_scripts_dir())` 改為）：

```python
    args = build_parser().parse_args(argv)
    data_root = Path(args.dir) if args.dir else default_scripts_dir()
    setup_logging(data_root / "logs")
    storage = ScriptStorage(data_root)
```

並把 `main` 內兩處 `data_dir = args.dir or default_scripts_dir()`（watch 與 play 分支）改為 `data_dir = data_root`。

- [ ] **Step 4: 跑測試確認通過**

Run: `rtk proxy python -m pytest tests/core/test_logging_config.py tests/app/test_qt_log_handler.py tests/core/test_player_wait.py tests/core/test_rule_engine.py tests/app/test_run_controller.py tests/app/test_watch_controller.py tests/app/test_application.py tests/test_cli_main.py -v`
Expected: 全數 passed（含 7 個改寫測試與 10 個新測試）。

- [ ] **Step 5: 全套件回歸**

Run: `python -m pytest -q`
Expected: **471 passed, 1 skipped**（461 + 10）

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/core/logging_config.py src/keyboard_executor/app/qt_log_handler.py src/keyboard_executor/core/player.py src/keyboard_executor/core/rule_engine.py src/keyboard_executor/app/run_controller.py src/keyboard_executor/app/watch_controller.py src/keyboard_executor/app/application.py src/keyboard_executor/app/main_window.py src/keyboard_executor/cli.py tests/conftest.py tests/core/test_logging_config.py tests/app/test_qt_log_handler.py tests/core/test_player_wait.py tests/core/test_rule_engine.py tests/app/test_run_controller.py tests/app/test_watch_controller.py tests/app/test_application.py tests/test_cli_main.py
git commit -m "feat: logging 收斂——滾動日誌檔與 GUI 日誌橋取代 stderr print（M5 Task 1）"
```

---

### Task 2: 版本單一來源與 CLI --version

版本目前寫在兩處（`pyproject.toml` 與 `__init__.__version__`），M4 曾因不同步吃過修正批次（0.1.0→0.4.0）。本任務：以 tomllib 測試鎖住兩處一致；CLI 加 `--version`（`argparse action="version"`，印 `keyboard-executor <版本>` 後 exit 0）；版本 bump 0.4.0 → **0.5.0**（M5 里程碑）。M4 待辦 #1 的 build-metadata dict 依「optionally」裁定 **不做**（YAGNI：`--version` 一行輸出已滿足發布識別；平台資訊入 dict 需要 sys.platform，會擴大例外面）。

**切分：** 全部可測；無人工面。

**Files:**
- Create: `tests/test_version.py`（2 個）
- Modify: `pyproject.toml`（version 0.4.0→0.5.0）
- Modify: `src/keyboard_executor/__init__.py`（0.4.0→0.5.0）
- Modify: `src/keyboard_executor/cli.py`（build_parser 加 `--version`）
- Test(更新既有): `tests/test_sanity.py`（"0.4.0"→"0.5.0"）

**Interfaces:**
- Consumes: `keyboard_executor.__version__`、`cli.build_parser`
- Produces: `__version__ == "0.5.0"`（pyproject 同步）；`keyboard-executor --version` → stdout `keyboard-executor 0.5.0`、exit 0

- [ ] **Step 1: 寫失敗測試**

`tests/test_version.py`（新檔）：

```python
"""版本單一來源（pyproject ↔ __init__）與 CLI --version（M5 發布識別）。"""
import tomllib
from pathlib import Path

import pytest

import keyboard_executor
from keyboard_executor.cli import main


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == keyboard_executor.__version__
    assert keyboard_executor.__version__ == "0.5.0"   # M5 里程碑版本


def test_cli_version_prints_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"keyboard-executor {keyboard_executor.__version__}" in out
```

同步更新 `tests/test_sanity.py`（整檔替換）：

```python
import keyboard_executor


def test_package_importable():
    assert keyboard_executor.__version__ == "0.5.0"
```

Run: `rtk proxy python -m pytest tests/test_version.py tests/test_sanity.py -v`
Expected: `test_version_matches_pyproject` FAILED（0.4.0 ≠ 0.5.0）、`test_cli_version_prints_and_exits_zero` FAILED（argparse：unrecognized arguments: --version，exit code 2）、`test_package_importable` FAILED（仍 0.4.0）。

- [ ] **Step 2: 實作**

(a) `pyproject.toml`：`version = "0.4.0"` → `version = "0.5.0"`
(b) `src/keyboard_executor/__init__.py`（整檔）：

```python
__version__ = "0.5.0"
```

(c) `src/keyboard_executor/cli.py`：import 區塊加 `from keyboard_executor import __version__`；`build_parser` 的 `parser = argparse.ArgumentParser(...)` 之後、`sub = parser.add_subparsers(...)` 之前插入：

```python
    parser.add_argument("--version", action="version",
                        version=f"keyboard-executor {__version__}")
```

- [ ] **Step 3: 跑測試確認通過**

Run: `rtk proxy python -m pytest tests/test_version.py tests/test_sanity.py tests/test_cli_main.py -v`
Expected: 全數 passed。

- [ ] **Step 4: 全套件回歸**

Run: `python -m pytest -q`
Expected: **473 passed, 1 skipped**（471 + 2）

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/keyboard_executor/__init__.py src/keyboard_executor/cli.py tests/test_version.py tests/test_sanity.py
git commit -m "feat: 版本單一來源鎖定與 CLI --version，bump 0.5.0（M5 Task 2）"
```

---

### Task 3: macOS 權限主動請求與系統設定 deep link（M4 待辦 #3 可測半）

spec §10 要求權限引導「附直達系統設定的連結」——M4 只做了檢查與文字引導。本任務補完可測半：(1) `platforms/darwin/permissions.py` 加 `request_screen_recording()` / `request_input_monitoring()`（包 `CGRequestScreenCaptureAccess` / `CGRequestListenEventAccess`，lazy import ＋ pragma no cover，注入供測試）與 `system_settings_url(pane)`（純函式，回傳 `x-apple.systempreferences:com.apple.preference.security?Privacy_*` 精確字串）；(2) `app/application.py` 加 `settings_urls_for_missing`（缺失權限→URL 清單）與 `request_missing_permissions`（啟動時 best-effort 觸發 TCC 對話框；打包後的 .app 首次啟動即出現在系統設定清單），`build_app` 增 `request_permissions` 注入參數；(3) `MainWindow` 權限橫幅下加「開啟系統設定」按鈕（`url_opener` 注入，預設 `QDesktopServices.openUrl`），開啟第一個缺失權限的分頁。

「輔助使用」沒有對應的 `CGRequest*` API（其對話框由首次輸入模擬觸發），deep-link 分頁涵蓋它即可——與 M4 審查列的兩個 request API 一致。簽章/公證/Info.plist 屬 Task 5。

**⚠ 測試安全紅線：** `build_app` 預設會呼叫真實 `request_missing_permissions`（darwin 上會打原生 `CGRequest*`、可能彈 TCC 對話框）——**所有測試（含既有 6 個 build_app 測試與煙霧指令）一律傳 `request_permissions=lambda: None`**，本步驟同步更新。

**切分：** 可測＝URL 字串、注入的 request 包裝、缺失→URL 映射、按鈕接線；人工＝原生 CGRequest 呼叫、系統設定實際跳轉、TCC 對話框（Task 5 人工驗收 #4）。

**Files:**
- Modify: `src/keyboard_executor/platforms/darwin/permissions.py`（`system_settings_url`、`request_screen_recording`、`request_input_monitoring`）
- Modify: `src/keyboard_executor/app/application.py`（`_PANE_BY_PERMISSION`、`settings_urls_for_missing`、`request_missing_permissions`、`build_app` 加參數）
- Modify: `src/keyboard_executor/app/main_window.py`（`open_settings_button`、`url_opener` 注入、`_on_open_system_settings`/`_open_url`）
- Test: `tests/platforms/test_darwin_permissions.py`（追加 4）
- Test: `tests/app/test_application.py`（追加 4；既有 6 個 build_app 測試補 `request_permissions=lambda: None`）
- Test: `tests/app/test_main_window.py`（追加 1）

**Interfaces:**
- Consumes: 既有 `check_*` 三函式與 GUIDE 常數、`collect_permission_warnings`、`MainWindow` 橫幅、`build_app`
- Produces（形狀見跨任務契約表）: `system_settings_url(pane)`、`request_screen_recording(_request=None)`、`request_input_monitoring(_request=None)`、`settings_urls_for_missing(checks=None)`、`request_missing_permissions(requesters=None)`、`build_app(..., request_permissions=None)`、`MainWindow(..., url_opener=None)` + `open_settings_button`

- [ ] **Step 1: 寫失敗測試**

`tests/platforms/test_darwin_permissions.py`——檔頂加 `import pytest`，檔尾追加：

```python
def test_system_settings_url_exact_strings():
    """spec §10「直達系統設定的連結」：三分頁的 deep link 精確字串。"""
    from keyboard_executor.platforms.darwin.permissions import system_settings_url
    assert system_settings_url("accessibility") == (
        "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_Accessibility")
    assert system_settings_url("screen-recording") == (
        "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_ScreenCapture")
    assert system_settings_url("input-monitoring") == (
        "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_ListenEvent")


def test_system_settings_url_rejects_unknown_pane():
    from keyboard_executor.platforms.darwin.permissions import system_settings_url
    with pytest.raises(ValueError, match="未知的權限分頁"):
        system_settings_url("camera")


def test_request_screen_recording_uses_injected_request():
    from keyboard_executor.platforms.darwin.permissions import request_screen_recording
    assert request_screen_recording(_request=lambda: 1) is True
    assert request_screen_recording(_request=lambda: 0) is False


def test_request_input_monitoring_uses_injected_request():
    from keyboard_executor.platforms.darwin.permissions import request_input_monitoring
    assert request_input_monitoring(_request=lambda: True) is True
    assert request_input_monitoring(_request=lambda: False) is False
```

`tests/app/test_application.py`——import 行改為：

```python
from keyboard_executor.app.application import (
    build_app,
    collect_permission_warnings,
    request_missing_permissions,
    settings_urls_for_missing,
)
```

**既有 6 個 build_app 相關測試**（Task 1 更新過的 4 個＋Task 1 新增的 2 個）的 `build_app(...)` 呼叫全部補上 `request_permissions=lambda: None`。檔尾追加：

```python
def test_request_missing_permissions_calls_all_requesters():
    calls = []
    request_missing_permissions(requesters=(lambda: calls.append("a") or True,
                                            lambda: calls.append("b") or True))
    assert calls == ["a", "b"]


def test_request_missing_permissions_swallows_requester_exceptions():
    calls = []

    def boom():
        raise RuntimeError("原生呼叫失敗")

    request_missing_permissions(requesters=(boom, lambda: calls.append("b")))
    assert calls == ["b"]   # 前一個失敗不阻斷後續請求（spec §10 啟動不崩潰）


def test_settings_urls_for_missing_maps_panes():
    checks = {"螢幕錄製": (lambda: False, "guide"),
              "輔助使用": (lambda: True, "guide"),
              "輸入監控": (lambda: False, "guide"),
              "未知權限": (lambda: False, "guide")}
    assert settings_urls_for_missing(checks) == [
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    ]


def test_build_app_requests_permissions_on_startup(qapp, tmp_path):
    calls = []
    build_app(data_dir=tmp_path, permission_checks={},
              request_permissions=lambda: calls.append(1))
    assert calls == [1]
```

`tests/app/test_main_window.py` 檔尾追加：

```python
def test_open_settings_button_opens_first_missing_pane(qapp, tmp_path):
    opened = []
    checks = {"螢幕錄製": (lambda: False, "請授予螢幕錄製權限")}
    window = MainWindow(tmp_path, permission_warnings=["請授予螢幕錄製權限"],
                        permission_checks=checks, url_opener=opened.append)
    assert not window.open_settings_button.isHidden()
    window.open_settings_button.click()
    assert opened == ["x-apple.systempreferences:com.apple.preference.security"
                      "?Privacy_ScreenCapture"]
    window_ok = MainWindow(tmp_path, permission_warnings=[], permission_checks={})
    assert window_ok.open_settings_button.isHidden()
```

Run: `rtk proxy python -m pytest tests/platforms/test_darwin_permissions.py tests/app/test_application.py tests/app/test_main_window.py -v`
Expected: 新測試 ImportError/AttributeError（`system_settings_url`、`request_missing_permissions` 等不存在；`open_settings_button` 缺）FAILED；既有測試因 import 行改動也會 ImportError——先確認 RED 後立即進 Step 2。

- [ ] **Step 2: 實作**

(a) `src/keyboard_executor/platforms/darwin/permissions.py` 檔尾追加：

```python
_SETTINGS_PANES = {
    "accessibility": "Privacy_Accessibility",
    "screen-recording": "Privacy_ScreenCapture",
    "input-monitoring": "Privacy_ListenEvent",
}


def system_settings_url(pane: str) -> str:
    """「系統設定 → 隱私權與安全性」對應分頁的 deep link（spec §10 直達連結）。
    pane ∈ accessibility / screen-recording / input-monitoring。"""
    if pane not in _SETTINGS_PANES:
        raise ValueError(f"未知的權限分頁: {pane!r}")
    return ("x-apple.systempreferences:com.apple.preference.security"
            f"?{_SETTINGS_PANES[pane]}")


def request_screen_recording(_request=None) -> bool:
    """主動觸發「螢幕錄製」授權對話框——簽章打包後的 .app 首次啟動呼叫，
    讓本程式出現在系統設定清單。回傳當下是否已授權（未授權時系統只提示，
    授權後需重新啟動程式才生效）。"""
    if _request is None:
        from Quartz import CGRequestScreenCaptureAccess as _request  # pragma: no cover - 需原生環境
    return bool(_request())


def request_input_monitoring(_request=None) -> bool:
    """主動觸發「輸入監控」授權對話框。行為同 request_screen_recording。
    「輔助使用」沒有對應的 CGRequest API：其系統對話框由首次模擬輸入觸發，
    引導改走 system_settings_url("accessibility") 直達分頁。"""
    if _request is None:
        from Quartz import CGRequestListenEventAccess as _request  # pragma: no cover - 需原生環境
    return bool(_request())
```

(b) `src/keyboard_executor/app/application.py`——`collect_permission_warnings` 之後追加兩個函式：

```python
_PANE_BY_PERMISSION = {"輔助使用": "accessibility",
                       "螢幕錄製": "screen-recording",
                       "輸入監控": "input-monitoring"}


def settings_urls_for_missing(checks=None) -> list[str]:
    """缺失權限 → 直達系統設定的 deep-link URL 清單（spec §10「附直達系統設定
    的連結」）。checks 注入供測試；darwin 權限模組頂層無 pyobjc import，
    跨平台可安全 import。未知權限名稱略過；check 拋例外視同缺失。"""
    from keyboard_executor.platforms.darwin.permissions import system_settings_url

    checks = checks if checks is not None else _default_permission_checks()
    urls = []
    for name, (check, _guide) in checks.items():
        try:
            ok = check()
        except Exception:
            ok = False
        if not ok and name in _PANE_BY_PERMISSION:
            urls.append(system_settings_url(_PANE_BY_PERMISSION[name]))
    return urls


def request_missing_permissions(requesters=None) -> None:
    """啟動時主動觸發 macOS 授權對話框（M4 待辦 #3：打包後的 .app 藉此出現在
    系統設定清單）。requesters 注入供測試；預設 darwin 為兩個 CGRequest 包裝、
    非 darwin no-op（sys.platform 沿用 cli._check_darwin_permissions 已核准
    例外模式）。個別請求失敗不阻斷啟動（spec §10 報錯不崩潰）。"""
    if requesters is None:
        if sys.platform != "darwin":
            return
        from keyboard_executor.platforms.darwin.permissions import (
            request_input_monitoring,
            request_screen_recording,
        )

        requesters = (request_screen_recording, request_input_monitoring)
    for request in requesters:
        try:
            request()
        except Exception:
            pass  # 權限請求失敗只影響引導體驗，不可讓啟動崩潰
```

(c) `build_app` 簽名改為 `def build_app(argv=None, *, data_dir=None, permission_checks=None, request_permissions=None):`，函式體在 `app = QApplication.instance() or ...` 之後、`settings = ...` 之前插入：

```python
    if request_permissions is None:
        request_permissions = request_missing_permissions
    request_permissions()   # 先請求（觸發 TCC 對話框），再檢查、顯示引導橫幅
```

（docstring 首行改為「建立（或重用）QApplication 與主視窗：權限請求、載入設定、日誌、權限檢查、全接線。」）

(d) `src/keyboard_executor/app/main_window.py`：
- import 區塊加 `from keyboard_executor.app.application import settings_urls_for_missing`
- ctor 簽名加 `url_opener=None`（放在 `permission_checks=Worker` 前後皆可，統一放最後：`worker_factory=Worker, permission_checks=None, url_opener=None`）；`self._permission_checks = permission_checks` 之後加：

```python
        self._url_opener = url_opener if url_opener is not None else self._open_url
```

- `_build_ui` 的橫幅段整段替換：

```python
        self.permission_banner = QLabel()
        self.permission_banner.setWordWrap(True)
        self.permission_banner.setStyleSheet(
            "background: #8b0000; color: white; padding: 6px;")
        self.open_settings_button = QPushButton("開啟系統設定")
        if warnings:
            self.permission_banner.setText("\n\n".join(warnings))
        else:
            self.permission_banner.hide()
            self.open_settings_button.hide()
        root.addWidget(self.permission_banner)
        root.addWidget(self.open_settings_button)
```

- `_wire` 追加一行：

```python
        self.open_settings_button.clicked.connect(self._on_open_system_settings)
```

- 類別內追加兩個方法（放在 `_on_open_settings` 之後）：

```python
    def _on_open_system_settings(self) -> None:
        urls = settings_urls_for_missing(self._permission_checks)
        if not urls:
            self.append_log("目前沒有缺失的權限")
            return
        # 系統設定一次只顯示一個分頁：開第一個缺失的；其餘依橫幅引導文字逐一處理
        self._url_opener(urls[0])

    def _open_url(self, url: str) -> None:
        """thin：真實開啟 deep link（人工驗收）。"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(url))
```

- [ ] **Step 3: 跑測試確認通過**

Run: `rtk proxy python -m pytest tests/platforms/test_darwin_permissions.py tests/app/test_application.py tests/app/test_main_window.py -v`
Expected: 全數 passed（darwin_permissions 9、application 12、main_window 7）。

- [ ] **Step 4: 全套件回歸**

Run: `python -m pytest -q`
Expected: **482 passed, 1 skipped**（473 + 9）

- [ ] **Step 5: Commit**

```bash
git add src/keyboard_executor/platforms/darwin/permissions.py src/keyboard_executor/app/application.py src/keyboard_executor/app/main_window.py tests/platforms/test_darwin_permissions.py tests/app/test_application.py tests/app/test_main_window.py
git commit -m "feat: macOS 權限主動請求與系統設定 deep link（M5 Task 3）"
```

---

### Task 4: GUI 刪除入口接線＋M4 清理小項（待辦 #4/#8/#9/#10）

M4 已建好 `ScriptListController.delete_selected`、`RuleListController.delete`、`TemplateStore.delete/list_names` 三組 seam 但 GUI 無按鈕（待辦 #4）。本任務：(1) 主視窗加「刪除腳本」「刪除規則」「模板管理…」按鈕，繁中確認對話框（`confirm` 注入供測試；自建「刪除／取消」按鈕，不依賴 Qt 內建英文 Yes/No）；(2) `TemplateManagerDialog`（薄件）列出模板＋刪除；(3) 清理批次：`rule_editor.py` 注入 `get_platform`/`capture_factory`（待辦 #8 前半）＋`_ask_template_name` seam、`_default_permission_checks` 更名公開 `default_permission_checks`（待辦 #8 後半）、`build_app` 載入 qtbase 繁中 translator（待辦 #9，thin＋人工驗收）、`_parse_number` 與 `_get_positive_number` 錯誤訊息格式統一為「規則欄位 {name} 必須是數字: {value!r}」（待辦 #10）。

**明列不做（理由）：** 待辦 #6（run/watch worker 處理器抽共用＋wait 5s）——M4 審查自身條件是「若打包後有第三種背景工作再抽」，M5 未新增背景工作，維持延後；待辦 #5（模板擷取影像預覽）——列 backlog（M4 審查允許「補或記 backlog」；v1 以檔名回填＋規則試跑驗證，預覽需 numpy→QImage 橋接屬純視覺、無單元測試價值）。

**切分：** 可測＝刪除編排（confirm/storage 注入）、模板管理清單/刪除、rule_editor 注入路徑、訊息格式；人工＝QMessageBox 實機外觀、qtbase_zh_TW 翻譯生效（人工驗收 #7/#9）。

**Files:**
- Create: `src/keyboard_executor/app/confirm.py`
- Create: `src/keyboard_executor/app/template_manager.py`
- Create: `tests/app/test_template_manager.py`（3 個）
- Modify: `src/keyboard_executor/app/main_window.py`（三按鈕＋confirm 注入＋handlers）
- Modify: `src/keyboard_executor/app/rule_editor.py`（ctor 注入、`_ask_template_name`、兩 handler 改用注入）
- Modify: `src/keyboard_executor/app/application.py`（`_default_permission_checks`→`default_permission_checks`；build_app 載 qtbase 翻譯）
- Modify: `src/keyboard_executor/app/settings_page.py`（import 更名跟進）
- Modify: `src/keyboard_executor/core/models.py`（`_get_positive_number` 訊息帶值）
- Test: `tests/app/test_main_window.py`（追加 3）、`tests/app/test_rule_editor_widget.py`（追加 2）、`tests/core/test_models_rule.py`（追加 1）

**Interfaces:**
- Consumes: `ScriptListController.delete_selected`、`RuleListController.delete`、`TemplateStore.list_names/delete`（皆 M4 Task 1 已建）、`RuleEditorDialog`、`_get_positive_number`
- Produces（形狀見跨任務契約表）: `confirm_delete(parent, message)`、`MainWindow(..., confirm=None)` + 三按鈕、`TemplateManagerDialog`、`RuleEditorDialog(..., get_platform=None, capture_factory=None)`、`default_permission_checks`、統一數字欄位錯誤格式

- [ ] **Step 1: 寫失敗測試**

`tests/app/test_main_window.py` 檔尾追加（檔頂 import 若缺則補 `from keyboard_executor.core.models import rule_from_dict, script_from_dict`、`from keyboard_executor.storage.rules import RuleStorage`、`from keyboard_executor.storage.scripts import ScriptStorage`）：

```python
def _save_script(tmp_path, name):
    ScriptStorage(tmp_path).save(script_from_dict({
        "name": name, "target_window": {"title_pattern": "記事本"},
        "actions": [{"type": "key_press", "key": "a"}]}))


def test_delete_script_button_confirmed_deletes_and_logs(qapp, tmp_path):
    _save_script(tmp_path, "甲")
    messages = []
    window = MainWindow(tmp_path, permission_warnings=[], permission_checks={},
                        confirm=lambda m: messages.append(m) or True)
    window.script_list.setCurrentRow(0)   # currentTextChanged → 控制器 select("甲")
    window.script_delete_button.click()
    assert "甲" in messages[0]                       # 確認訊息含名稱
    assert ScriptStorage(tmp_path).list_names() == []
    assert window.script_list.count() == 0
    assert "已刪除腳本「甲」" in window.log_view.toPlainText()


def test_delete_script_cancelled_keeps_file(qapp, tmp_path):
    _save_script(tmp_path, "甲")
    window = MainWindow(tmp_path, permission_warnings=[], permission_checks={},
                        confirm=lambda m: False)
    window.script_list.setCurrentRow(0)
    window.script_delete_button.click()
    assert ScriptStorage(tmp_path).list_names() == ["甲"]
    assert "已刪除" not in window.log_view.toPlainText()


def test_delete_rule_button_confirmed_deletes(qapp, tmp_path):
    RuleStorage(tmp_path).save(rule_from_dict({
        "name": "斷線", "target_window": {"title_pattern": "遊戲"},
        "condition": {"type": "text", "pattern": "中斷", "mode": "contains"},
        "trigger": {"type": "stop_all"}}))
    window = MainWindow(tmp_path, permission_warnings=[], permission_checks={},
                        confirm=lambda m: True)
    window.rule_list.setCurrentRow(0)
    window.rule_delete_button.click()
    assert RuleStorage(tmp_path).list_names() == []
    assert "已刪除規則「斷線」" in window.log_view.toPlainText()
```

`tests/app/test_template_manager.py`（新檔）：

```python
"""模板管理對話框（M4 待辦 #4：TemplateStore delete seam 的 GUI 入口）。"""
from keyboard_executor.app.template_manager import TemplateManagerDialog
from keyboard_executor.core.models import ScriptValidationError


class FakeStore:
    def __init__(self, names):
        self.names = list(names)
        self.deleted = []

    def list_names(self):
        return list(self.names)

    def delete(self, name):
        if name not in self.names:
            raise ScriptValidationError(f"找不到模板 {name!r}")
        self.names.remove(name)
        self.deleted.append(name)


def test_dialog_lists_templates(qapp):
    dialog = TemplateManagerDialog(FakeStore(["乙鈕", "甲鈕"]))
    items = [dialog.template_list.item(i).text()
             for i in range(dialog.template_list.count())]
    assert items == ["乙鈕", "甲鈕"]


def test_delete_confirmed_removes_and_refreshes(qapp):
    store = FakeStore(["甲鈕", "乙鈕"])
    messages = []
    dialog = TemplateManagerDialog(store, confirm=lambda m: messages.append(m) or True)
    dialog.template_list.setCurrentRow(0)
    dialog.delete_button.click()
    assert store.deleted == ["甲鈕"]
    assert "甲鈕" in messages[0]
    assert dialog.template_list.count() == 1
    assert "已刪除模板「甲鈕」" in dialog.status_label.text()


def test_delete_cancelled_keeps_template(qapp):
    store = FakeStore(["甲鈕"])
    dialog = TemplateManagerDialog(store, confirm=lambda m: False)
    dialog.template_list.setCurrentRow(0)
    dialog.delete_button.click()
    assert store.deleted == []
    assert dialog.template_list.count() == 1
```

`tests/app/test_rule_editor_widget.py` 檔尾追加（檔頂 import 若缺則補 `from keyboard_executor.storage.rules import RuleStorage`、`from keyboard_executor.storage.templates import TemplateStore`、`from keyboard_executor.app.rule_editor import RuleEditorDialog`、`from keyboard_executor.app.rule_editor_model import RuleEditorModel`）：

```python
def test_pick_region_uses_injected_get_platform(qapp, tmp_path):
    class FakeWM:
        def find_windows(self, title_pattern=None, app_name=None):
            return []

    class FakePlatform:
        window_manager = FakeWM()

    calls = []

    def fake_get_platform(**kwargs):
        calls.append(kwargs)
        return FakePlatform()

    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              get_platform=fake_get_platform)
    dialog.title_edit.setText("記事本")
    dialog._on_pick_region()
    assert calls, "應使用注入的 get_platform，而非真實平台（M4 待辦 #8）"
    assert "找不到符合" in dialog.status_label.text()


def test_capture_template_uses_injected_capture_factory(qapp, tmp_path):
    import numpy as np

    class FakeCapture:
        def scale_factor(self):
            return 1.0

        def capture(self, rect):
            return np.zeros((rect.height, rect.width, 3), dtype=np.uint8)

    store = TemplateStore(tmp_path)
    dialog = RuleEditorDialog(RuleEditorModel(), RuleStorage(tmp_path),
                              template_store=store, capture_factory=FakeCapture)
    dialog._ask_template_name = lambda: "鈕"     # thin seam：跳過 QInputDialog
    dialog._on_capture_template()
    dialog._overlay._begin(10, 10)
    dialog._overlay._finish(30, 40)              # normalize → Rect(10, 10, 20, 30)
    assert store.list_names() == ["鈕"]
    assert dialog.template_edit.text() == "鈕"
    assert "已儲存模板" in dialog.status_label.text()
```

`tests/core/test_models_rule.py` 檔尾追加（沿用該檔既有 import；若無 `pytest`/`rule_from_dict`/`ScriptValidationError` import 則補）：

```python
def test_rule_number_field_errors_include_offending_value():
    """M4 待辦 #10：models 與 rule_editor_model 的數字欄位錯誤格式統一——
    「規則欄位 {name} 必須是數字: {value!r}」（>0 / >=0 同樣帶值）。"""
    def data(**overrides):
        base = {"name": "r", "target_window": {"title_pattern": "遊戲"},
                "condition": {"type": "text", "pattern": "x", "mode": "contains"},
                "trigger": {"type": "stop_all"}}
        base.update(overrides)
        return base

    with pytest.raises(ScriptValidationError, match="interval_sec 必須是數字: 'x'"):
        rule_from_dict(data(interval_sec="x"))
    with pytest.raises(ScriptValidationError, match="interval_sec 必須 > 0: 0"):
        rule_from_dict(data(interval_sec=0))
    with pytest.raises(ScriptValidationError, match="cooldown_sec 必須 >= 0: -1"):
        rule_from_dict(data(cooldown_sec=-1))
```

Run: `rtk proxy python -m pytest tests/app/test_main_window.py tests/app/test_template_manager.py tests/app/test_rule_editor_widget.py tests/core/test_models_rule.py -v`
Expected: 新測試 FAILED（`script_delete_button` 缺、`template_manager` 模組不存在、`RuleEditorDialog` 不收 `get_platform` kwarg、models 訊息不帶值）；既有測試綠。

- [ ] **Step 2: 實作**

(a) `src/keyboard_executor/app/confirm.py`（新檔，全文）：

```python
"""繁中刪除確認對話框（共用薄件）。Qt 內建 StandardButton（Yes/No）在未載
qtbase 翻譯時是英文（M4 待辦 #9）——刪除確認直接自建繁中按鈕，雙保險；
qtbase_zh_TW translator 另於 build_app 載入，涵蓋其餘內建對話框。"""
from __future__ import annotations


def confirm_delete(parent, message: str) -> bool:
    """回傳使用者是否按下「刪除」。thin：實機外觀列人工驗收。"""
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setWindowTitle("確認刪除")
    box.setText(message)
    delete_button = box.addButton("刪除", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is delete_button
```

(b) `src/keyboard_executor/app/template_manager.py`（新檔，全文）：

```python
"""模板管理對話框（M4 待辦 #4）：列出 templates/、刪除（附繁中確認）。

薄件：清單與刪除直接走 TemplateStore（list_names/delete 為 M4 已建 seam），
confirm 注入供測試，預設 confirm_delete。刪除引用中的模板不做連動檢查
（規則/腳本執行時會以「找不到模板」如實回報，spec §10）。"""
from __future__ import annotations

from functools import partial

from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QPushButton, QVBoxLayout

from keyboard_executor.app.confirm import confirm_delete
from keyboard_executor.core.models import ScriptValidationError


class TemplateManagerDialog(QDialog):
    def __init__(self, store, confirm=None, parent=None):
        super().__init__(parent)
        self._store = store
        self._confirm = confirm if confirm is not None else partial(confirm_delete, self)
        self.setWindowTitle("模板管理")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("模板（PNG，供 *_image 動作與 image 規則引用）"))
        self.template_list = QListWidget()
        layout.addWidget(self.template_list)
        self.delete_button = QPushButton("刪除")
        layout.addWidget(self.delete_button)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.delete_button.clicked.connect(self._on_delete)
        self.refresh()

    def refresh(self) -> None:
        self.template_list.clear()
        self.template_list.addItems(self._store.list_names())

    def _on_delete(self) -> None:
        item = self.template_list.currentItem()
        if item is None:
            self.status_label.setText("請先選取要刪除的模板")
            return
        name = item.text()
        if not self._confirm(f"確定刪除模板「{name}」？引用它的規則與腳本將失效。"):
            return
        try:
            self._store.delete(name)
        except ScriptValidationError as e:
            self.status_label.setText(f"模板刪除失敗：{e}")
            return
        self.status_label.setText(f"已刪除模板「{name}」")
        self.refresh()
```

(c) `src/keyboard_executor/app/main_window.py`：
- import 區塊加 `from keyboard_executor.app.confirm import confirm_delete`
- ctor 簽名加 `confirm=None`（放在 `url_opener=None` 之後）；`self._url_opener = ...` 之後加：

```python
        self._confirm = (confirm if confirm is not None
                         else (lambda message: confirm_delete(self, message)))
```

- `_build_ui` 右側按鈕段整段替換：

```python
        self.run_button = QPushButton("執行")
        self.stop_button = QPushButton("停止")
        self.watch_button = QPushButton("開始監看")
        self.watch_stop_button = QPushButton("停止監看")
        self.record_button = QPushButton("錄製面板…")
        self.edit_button = QPushButton("編輯腳本…")
        self.script_delete_button = QPushButton("刪除腳本")
        self.rule_edit_button = QPushButton("編輯規則…")
        self.rule_delete_button = QPushButton("刪除規則")
        self.template_manage_button = QPushButton("模板管理…")
        self.settings_button = QPushButton("設定…")
        for button in (self.run_button, self.stop_button, self.watch_button,
                       self.watch_stop_button, self.record_button,
                       self.edit_button, self.script_delete_button,
                       self.rule_edit_button, self.rule_delete_button,
                       self.template_manage_button, self.settings_button):
            right.addWidget(button)
```

- `_wire` 追加：

```python
        self.script_delete_button.clicked.connect(self._on_delete_script)
        self.rule_delete_button.clicked.connect(self._on_delete_rule)
        self.template_manage_button.clicked.connect(self._on_manage_templates)
```

- 類別內追加三個方法（放在 `_on_edit_rule` 之後）：

```python
    def _on_delete_script(self) -> None:
        name = self._scripts.selected
        if name is None:
            self.append_log("請先選取要刪除的腳本")
            return
        if not self._confirm(f"確定刪除腳本「{name}」？此操作無法復原。"):
            return
        try:
            self._scripts.delete_selected()
        except (ScriptValidationError, ValueError) as e:
            self.append_log(f"腳本刪除失敗：{e}")
            return
        self.append_log(f"已刪除腳本「{name}」")
        self.refresh_scripts()
        self.summary_label.setText("尚未選取腳本")

    def _on_delete_rule(self) -> None:
        index = self.rule_list.currentRow()
        if index < 0 or index >= len(self._rules.names):
            self.append_log("請先選取要刪除的規則")
            return
        name = self._rules.names[index]
        if not self._confirm(f"確定刪除規則「{name}」？此操作無法復原。"):
            return
        try:
            self._rules.delete(name)
        except ScriptValidationError as e:
            self.append_log(f"規則刪除失敗：{e}")
            return
        self.append_log(f"已刪除規則「{name}」")
        self.refresh_rules()

    def _on_manage_templates(self) -> None:
        from keyboard_executor.app.template_manager import TemplateManagerDialog

        TemplateManagerDialog(self._template_store, parent=self).exec()
```

(d) `src/keyboard_executor/app/rule_editor.py`：
- ctor 簽名改為 `def __init__(self, model, rule_storage, template_store=None, parent=None, get_platform=None, capture_factory=None):`；`self._overlay = None` 之後加：

```python
        if get_platform is None:
            from keyboard_executor.platforms.factory import get_platform as _real_get_platform
            get_platform = _real_get_platform
        if capture_factory is None:
            from keyboard_executor.platforms.common.capture_mss import MssScreenCapture
            capture_factory = MssScreenCapture
        self._get_platform = get_platform          # M4 待辦 #8：注入取代直接建構
        self._capture_factory = capture_factory
```

- `_on_pick_region` 整個方法替換（改用 `self._get_platform`，移除函式內 `from keyboard_executor.platforms.factory import get_platform`）：

```python
    def _on_pick_region(self) -> None:
        """框選螢幕區域 → 換算目標視窗相對 region 填入欄位（人工驗收）。"""
        from keyboard_executor.app.region_math import screen_rect_to_window_region
        from keyboard_executor.app.region_picker import RegionPickerOverlay, drag_scale
        from keyboard_executor.core.geometry import Point

        title = self.title_edit.text().strip()
        if not title:
            self.status_label.setText("請先填視窗標題（regex）再框選")
            return
        windows = self._get_platform().window_manager.find_windows(title_pattern=title)
        if not windows:
            self.status_label.setText(f"找不到符合 {title!r} 的視窗")
            return
        win = windows[0]
        overlay = RegionPickerOverlay()
        self._overlay = overlay                       # 保留引用避免被 GC

        def on_selected(rect) -> None:
            scale = drag_scale(overlay.devicePixelRatio())
            try:
                region = screen_rect_to_window_region(rect, Point(win.x, win.y),
                                                      scale)
            except ValueError as e:
                self.status_label.setText(str(e))
                return
            self.region_edit.setText(", ".join(str(v) for v in region))
            self.status_label.setText("已填入框選區域")

        overlay.region_selected.connect(on_selected)
        overlay.open_fullscreen()
```

- `_on_capture_template` 整個方法替換＋新增 `_ask_template_name`（改用 `self._capture_factory`，QInputDialog 收進 seam）：

```python
    def _ask_template_name(self) -> str | None:
        """thin：實機 QInputDialog（人工驗收）；取消或空白回 None。"""
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "模板名稱", "輸入模板名稱")
        if not ok or not name.strip():
            return None
        return name.strip()

    def _on_capture_template(self) -> None:
        """框選並擷取模板 PNG 存入 TemplateStore（人工驗收）。"""
        from keyboard_executor.app.region_picker import RegionPickerOverlay, drag_scale
        from keyboard_executor.app.template_capture import capture_template
        from keyboard_executor.core.geometry import Rect

        if self._template_store is None:
            self.status_label.setText("未提供模板儲存位置，無法擷取")
            return
        overlay = RegionPickerOverlay()
        self._overlay = overlay

        def on_selected(rect) -> None:
            name = self._ask_template_name()
            if name is None:
                return
            scale = drag_scale(overlay.devicePixelRatio())
            points = Rect(round(rect.x * scale), round(rect.y * scale),
                          round(rect.width * scale), round(rect.height * scale))
            try:
                path = capture_template(self._capture_factory(), self._template_store,
                                        name, points)
            except ScriptValidationError as e:
                self.status_label.setText(f"模板儲存失敗：{e}")
                return
            self.template_edit.setText(name)
            self.status_label.setText(f"已儲存模板：{path}")

        overlay.region_selected.connect(on_selected)
        overlay.open_fullscreen()
```

(e) `src/keyboard_executor/app/application.py`：`_default_permission_checks` 更名 `default_permission_checks`（docstring 不變），檔內兩處呼叫（`collect_permission_warnings`、`settings_urls_for_missing`）跟進；`src/keyboard_executor/app/settings_page.py` 的 import 與呼叫改為 `default_permission_checks`（M4 待辦 #8 後半：不再跨模組 import 私名）。

(f) `src/keyboard_executor/app/application.py` `build_app`：`app = QApplication.instance() or ...` 之後插入 qtbase 繁中翻譯（M4 待辦 #9；thin，載入失敗安靜略過、按鈕維持英文）：

```python
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    translator = QTranslator(app)
    if translator.load(QLocale("zh_TW"), "qtbase", "_",
                       QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)   # 內建對話框（開檔、訊息框標準鈕）轉繁中
```

(g) `src/keyboard_executor/core/models.py` `_get_positive_number` 三處 `_err` 改為帶值（M4 待辦 #10）：

```python
def _get_positive_number(data: dict, name: str, default: float, *, allow_zero: bool) -> float:
    value = data.get(name, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _err(f"規則欄位 {name} 必須是數字: {value!r}")
    if allow_zero and value < 0:
        _err(f"規則欄位 {name} 必須 >= 0: {value!r}")
    if not allow_zero and value <= 0:
        _err(f"規則欄位 {name} 必須 > 0: {value!r}")
    return float(value)
```

（`app/rule_editor_model.py._parse_number` 已是「規則欄位 {name} 必須是數字: {raw!r}」格式，統一後兩邊一致，不需改；既有測試以 `match` 子字串斷言，帶值後綴不破壞。）

- [ ] **Step 3: 跑測試確認通過**

Run: `rtk proxy python -m pytest tests/app tests/core/test_models_rule.py -v`
Expected: 全數 passed（tests/app 新增 8、models 新增 1；既有全綠——特別確認 `test_rule_editor_model.py` 與 `test_models_rule.py` 的既有 match 斷言未被帶值後綴破壞）。

- [ ] **Step 4: 全套件回歸**

Run: `python -m pytest -q`
Expected: **491 passed, 1 skipped**（482 + 9）

- [ ] **Step 5: 啟動煙霧驗證（自動化部分）**

Run: `QT_QPA_PLATFORM=offscreen python -c "
from keyboard_executor.app.application import build_app
app, window = build_app(data_dir='/tmp/ke-m5-smoke', permission_checks={},
                        request_permissions=lambda: None)
window.show()
print('gui ok:', window.windowTitle(),
      window.script_delete_button.text(), window.rule_delete_button.text(),
      window.template_manage_button.text())
"`
Expected: 印出 `gui ok: Keyboard Executor 刪除腳本 刪除規則 模板管理…`。

- [ ] **Step 6: Commit**

```bash
git add src/keyboard_executor/app/confirm.py src/keyboard_executor/app/template_manager.py src/keyboard_executor/app/main_window.py src/keyboard_executor/app/rule_editor.py src/keyboard_executor/app/application.py src/keyboard_executor/app/settings_page.py src/keyboard_executor/core/models.py tests/app/test_main_window.py tests/app/test_template_manager.py tests/app/test_rule_editor_widget.py tests/core/test_models_rule.py
git commit -m "feat: GUI 刪除入口與 M4 清理批次——確認對話框、模板管理、注入與訊息統一（M5 Task 4）"
```

---

### Task 5: PyInstaller spec、建置腳本與發布文件（大部分人工/腳本）

M5 收官：(1) pyproject 加 `[project.scripts]`/`[project.gui-scripts]`（M4 待辦 #1）與 `packaging` extra；(2) `packaging/` 目錄：`launcher.py`（打包進入點，與 pip 入口共用 `gui.main`）、`keyboard-executor.spec`（兩平台共用；darwin 產 `.app` 含 Info.plist、win32 產 onedir exe；pynput/mss 動態後端 hiddenimports、winsdk/pyobjc 平台依賴）、`entitlements.plist`（hardened runtime 用）、`build.sh`/`build.ps1`、`README.md`（完整簽章/公證/自簽/驗收文件）；(3) 3 個設定檔 sanity 測試（entry point 可解析、launcher 可載入、spec 關鍵內容存在）；(4) 完整人工驗收清單（本沙箱**無法**執行簽章與 .app 啟動——build 可嘗試但不是門檻，簽章/公證/實機端到端一律交人工）。

**風險（如實記錄）：** venv 為 Python 3.14.6——PyInstaller 對 3.14 的支援需在建置機以 `pip install "pyinstaller>=6.16" && pyinstaller --version` 驗證；若不支援，README 指示以 Python 3.12/3.13 另建打包 venv（runtime 相容 `>=3.11`）。「輔助使用／螢幕錄製／輸入監控」三權限是系統管理的 TCC 對話框、**沒有** Info.plist usage-description 鍵；能穩定出現在系統設定清單靠固定 bundle identifier＋正式簽章；`NSAppleEventsUsageDescription`（pywinctl 以 AppleScript 查應用程式名稱所需的 Automation 權限）則必須提供——spec 內已含。ad-hoc 簽章（無憑證降級）每次重建 TCC 視為新 app、需重新授權——README 明載。

**切分：** 可測＝entry point 解析、launcher 載入、spec 文字 sanity（3 個測試，僅此而已）；人工/腳本＝`pyinstaller` 建置、codesign/notarytool/staple、.app 實機端到端（人工驗收清單）。**不寫任何「假裝有 build」的 CI 測試。**

**Files:**
- Create: `packaging/launcher.py`
- Create: `packaging/keyboard-executor.spec`
- Create: `packaging/entitlements.plist`
- Create: `packaging/build.sh`（chmod +x）
- Create: `packaging/build.ps1`
- Create: `packaging/README.md`
- Create: `tests/test_packaging.py`（3 個）
- Modify: `pyproject.toml`（entry points＋packaging extra）

**Interfaces:**
- Consumes: `keyboard_executor.gui:main`、`keyboard_executor.cli:main`、`keyboard_executor.__version__`（spec 內單一版本來源）
- Produces: `[project.scripts] keyboard-executor`、`[project.gui-scripts] keyboard-executor-gui`、`packaging/` 全套建置資產（形狀見跨任務契約表）
- 註：`.gitignore` 既有 `dist/`、`build/` 樣式已涵蓋 `packaging/dist`、`packaging/build`（gitignore 無斜線前綴＝任意深度），不需改

- [ ] **Step 1: 寫失敗測試**

`tests/test_packaging.py`（新檔）：

```python
"""打包設定 sanity（M5 Task 5 可測半）。真正的 pyinstaller 建置、簽章、
.app 啟動屬人工驗收（見 packaging/README.md），不在自動化測試假裝驗證。"""
import importlib
import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_entry_points_resolve_to_callables():
    """M4 待辦 #1：pyproject 進入點宣告存在，且指向可 import 的 callable。"""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entries = {**data["project"]["scripts"], **data["project"]["gui-scripts"]}
    assert entries == {"keyboard-executor": "keyboard_executor.cli:main",
                       "keyboard-executor-gui": "keyboard_executor.gui:main"}
    for target in entries.values():
        module_name, func_name = target.split(":")
        module = importlib.import_module(module_name)
        assert callable(getattr(module, func_name))


def test_launcher_module_loads_and_references_gui_main():
    """PyInstaller 進入點與 pip gui-scripts 共用同一個 gui.main。"""
    spec = importlib.util.spec_from_file_location(
        "ke_packaging_launcher", ROOT / "packaging" / "launcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)   # __name__ != "__main__"，不會啟動 GUI
    from keyboard_executor.gui import main
    assert module.main is main


def test_pyinstaller_spec_sanity():
    """spec 檔關鍵內容：進入點、名稱、版本單一來源、bundle id、Automation 用途字串。"""
    text = (ROOT / "packaging" / "keyboard-executor.spec").read_text(encoding="utf-8")
    assert "launcher.py" in text
    assert 'APP_NAME = "KeyboardExecutor"' in text
    assert "from keyboard_executor import __version__" in text
    assert 'BUNDLE_ID = "io.github.simamaplestar.keyboardexecutor"' in text
    assert "NSAppleEventsUsageDescription" in text
    assert "pynput.keyboard._darwin" in text and "pynput.keyboard._win32" in text
```

Run: `rtk proxy python -m pytest tests/test_packaging.py -v`
Expected: 3 FAILED（pyproject 無 scripts 段 KeyError；packaging/ 檔案不存在 FileNotFoundError）。

- [ ] **Step 2: 實作——pyproject 與 packaging/ 資產**

(a) `pyproject.toml`：`[project]` 段之後插入兩段、`[project.optional-dependencies]` 替換：

```toml
[project.scripts]
keyboard-executor = "keyboard_executor.cli:main"

[project.gui-scripts]
keyboard-executor-gui = "keyboard_executor.gui:main"

[project.optional-dependencies]
dev = ["pytest>=8.0"]
packaging = ["pyinstaller>=6.16"]
```

(b) `packaging/launcher.py`（新檔，全文）：

```python
"""PyInstaller 進入點：打包後的可執行檔從這裡啟動 GUI。

保持極薄：所有組裝在 keyboard_executor.gui.main——pip 安裝的
[project.gui-scripts] 與打包後的執行檔共用同一進入點，行為一致。"""
import sys

from keyboard_executor.gui import main

if __name__ == "__main__":
    sys.exit(main())
```

(c) `packaging/keyboard-executor.spec`（新檔，全文）：

```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 建置設定（兩平台共用；spec §13-M5）。

執行方式見 build.sh / build.ps1：
    cd packaging && python -m PyInstaller --clean --noconfirm keyboard-executor.spec

本檔是建置期腳本、不進 runtime 的 src/——此處的 sys.platform 分派不受
「僅 platforms/ 判斷 OS」的 runtime 約束（該約束針對 src/ 內程式碼）。
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent            # SPECPATH 由 PyInstaller 注入＝本檔所在目錄
sys.path.insert(0, str(ROOT / "src"))
from keyboard_executor import __version__  # noqa: E402  版本單一來源（與 pyproject 同步）

APP_NAME = "KeyboardExecutor"
BUNDLE_ID = "io.github.simamaplestar.keyboardexecutor"

# pynput / mss 以動態 import 載入平台後端，PyInstaller 靜態分析看不到，需明列。
# （測試 sanity 斷言兩平台鍵名都在本檔：pynput.keyboard._darwin / pynput.keyboard._win32）
if sys.platform == "darwin":
    platform_hiddenimports = [
        "pynput.keyboard._darwin", "pynput.mouse._darwin",
        "mss.darwin",
    ]
else:  # win32
    platform_hiddenimports = [
        "pynput.keyboard._win32", "pynput.mouse._win32",
        "mss.windows",
        "pydirectinput",
        "winsdk.windows.media.ocr", "winsdk.windows.graphics.imaging",
        "winsdk.windows.storage.streams", "winsdk.windows.globalization",
    ]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=platform_hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,        # UPX 會提高防毒誤報率（spec §14 風險），不使用
    console=False,    # GUI 程式：Windows 不開主控台、macOS 進 .app
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "Keyboard Executor",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.utilities",
            # 「輔助使用／螢幕錄製／輸入監控」三權限屬系統管理的 TCC 對話框，
            # 沒有 Info.plist usage-description 鍵；能穩定出現在系統設定清單，
            # 靠的是固定 bundle identifier ＋ 正式簽章（見 README.md）。
            # Automation（pywinctl 以 AppleScript 查應用程式名稱）則必須提供：
            "NSAppleEventsUsageDescription":
                "Keyboard Executor 需要控制「系統事件」以查詢與切換目標視窗。",
        },
    )
```

(d) `packaging/entitlements.plist`（新檔，全文；hardened runtime 簽章＋公證用）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- PyInstaller 打包的 Python 程式在 hardened runtime 下需要以下豁免 -->
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
    <!-- pywinctl 以 AppleScript（Apple Events）查詢視窗的應用程式名稱 -->
    <key>com.apple.security.automation.apple-events</key>
    <true/>
</dict>
</plist>
```

(e) `packaging/build.sh`（新檔，全文；建立後 `chmod +x packaging/build.sh`）：

```bash
#!/usr/bin/env bash
# macOS 打包：產出 packaging/dist/KeyboardExecutor.app（未簽章）。
# 前置：venv 內 pip install -e ".[packaging]"（PyInstaller 僅建置機需要）。
# 簽章、公證、驗收步驟見 packaging/README.md。
set -euo pipefail
cd "$(dirname "$0")"
python -m PyInstaller --clean --noconfirm keyboard-executor.spec
echo "完成：$(pwd)/dist/KeyboardExecutor.app"
echo "下一步：依 README.md 簽章（codesign）→ 公證（notarytool）→ 實機驗收"
```

(f) `packaging/build.ps1`（新檔，全文）：

```powershell
# Windows 打包：產出 packaging\dist\KeyboardExecutor\KeyboardExecutor.exe。
# 前置：Windows 機器、venv 內 pip install -e ".[packaging]"。
# 自簽與驗收步驟見 README.md。本腳本尚未實機驗證（Windows backlog，M5 如實記錄）。
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m PyInstaller --clean --noconfirm keyboard-executor.spec
Write-Host "完成：$PSScriptRoot\dist\KeyboardExecutor\KeyboardExecutor.exe"
```

(g) `packaging/README.md`（新檔，全文）：

```markdown
# Keyboard Executor 打包與發布（M5）

## 前置

- 建置機 venv：`pip install -e ".[packaging]"`（PyInstaller >= 6.16 僅建置期需要，不進 runtime 依賴）
- **Python 版本相容性**：先驗證 `python -m PyInstaller --version` 可在本 venv（Python 3.14）執行；
  若 PyInstaller 尚未支援 3.14，以 Python 3.12/3.13 另建打包 venv（本專案 runtime 相容 `>=3.11`）
- 預期體積：50–100MB（PySide6 ＋ OpenCV；spec §14 已接受）；不使用 UPX（防毒誤報）

## macOS

### 建置

    ./build.sh          # → dist/KeyboardExecutor.app

### 簽章

正式簽章（Developer ID，公證必要）：

    codesign --deep --force --options runtime \
      --entitlements entitlements.plist \
      --sign "Developer ID Application: <名稱> (<TEAMID>)" \
      dist/KeyboardExecutor.app

無憑證降級（ad-hoc）：

    codesign --deep --force --sign - dist/KeyboardExecutor.app

⚠ ad-hoc 簽章下 TCC 權限綁定不穩定：**每次重建都被系統視為新 App，三權限需重新授權**；
Gatekeeper 會攔右鍵開啟。正式發布必須用 Developer ID ＋ 公證。

### 公證（僅 Developer ID）

    ditto -c -k --keepParent dist/KeyboardExecutor.app dist/KeyboardExecutor.zip
    xcrun notarytool submit dist/KeyboardExecutor.zip \
      --keychain-profile ke-notary --wait          # 事先 notarytool store-credentials
    xcrun stapler staple dist/KeyboardExecutor.app

### 權限（首次啟動）

App 啟動即主動請求「螢幕錄製」「輸入監控」（`CGRequest*`）；「輔助使用」對話框由
首次模擬輸入觸發。權限橫幅的「開啟系統設定」按鈕直達對應分頁
（`x-apple.systempreferences:com.apple.preference.security?Privacy_*`）。
授權後**必須重新啟動 App** 才生效。三權限沒有 Info.plist usage-description 鍵
（系統管理的 TCC 類別）；穩定出現在系統設定清單靠固定 bundle id ＋ 正式簽章。

## Windows（backlog——需 Windows 實機，尚未驗證）

    powershell -ExecutionPolicy Bypass -File build.ps1

自簽（測試機信任用；正式憑證另議）：

    New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=KeyboardExecutor" `
      -CertStoreLocation Cert:\CurrentUser\My
    Set-AuthenticodeSignature -FilePath dist\KeyboardExecutor\KeyboardExecutor.exe `
      -Certificate (Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert)[0]

未簽章的 exe 會觸發 SmartScreen 警告（spec §14 已知風險，如實告知使用者）。
Windows 驗收項目（winsdk OCR、pydirectinput、DPI 縮放、多螢幕）見主計畫
「Windows backlog」一節。

## 驗收清單

見 `docs/superpowers/plans/2026-07-06-m5-packaging.md` Task 5 Step 5 的
「人工總驗收清單」（打包 App 內執行，同時清償 M4 累積的 GUI 實機驗收）。
```

- [ ] **Step 3: 跑測試確認通過＋entry point 刷新**

```bash
python -m pip install -e . --no-deps   # 刷新 console/gui scripts 進入點
chmod +x packaging/build.sh
```

Run: `rtk proxy python -m pytest tests/test_packaging.py -v`
Expected: 3 passed。
Run: `keyboard-executor --version`
Expected: `keyboard-executor 0.5.0`（pip 入口與 Task 2 版本一致）。

- [ ] **Step 4: 全套件回歸**

Run: `python -m pytest -q`
Expected: **494 passed, 1 skipped**（491 + 3）

- [ ] **Step 4b:（可選，非驗收門檻）本機嘗試建置**

沙箱／開發機若可安裝 PyInstaller，best-effort 跑一次 `pip install "pyinstaller>=6.16" && bash packaging/build.sh` 並記錄結果（成功→記錄 .app 體積；失敗→記錄原因，最常見為 PyInstaller 對 Python 3.14 支援落差，依 README 降級指引處理）。**本步驟結果如實寫入報告，不得以「測試通過」措辭混充建置成功；簽章與 .app 啟動一律留給人工驗收。**

- [ ] **Step 5: 人工總驗收清單（macOS 實機，由人執行——會建置、簽章、彈權限對話框、送輸入）**

依用戶既定安排，**人工驗收累積到最後一次做**：本清單在打包 App 內執行 M4 清單的核心流程，可同時清償 M4 待驗收項（M4 plan Task 8 Step 8 的 1–13 若要逐項驗，先以 `python -m keyboard_executor.gui` 開發模式跑一輪再驗打包版）。

  1. **建置環境**：`pip install -e ".[packaging]"`；`python -m PyInstaller --version` 確認可用（Python 3.14 不支援時依 README 以 3.12/3.13 打包 venv 重建）
  2. **建置**：`./packaging/build.sh` → `packaging/dist/KeyboardExecutor.app` 產出；記錄體積（預期 50–100MB，spec §14）
  3. **簽章**：有 Developer ID → 正式簽章＋notarytool 公證＋staple；無 → ad-hoc 降級（README 注意事項）
  4. **權限引導（spec §10/§13-M5「macOS 權限引導完整」）**：全新授權狀態下首次啟動 .app → 出現「螢幕錄製」「輸入監控」系統請求對話框（Task 3 主動請求）；主視窗紅色橫幅列出缺失權限繁中引導；點「開啟系統設定」→ 系統設定直達正確的隱私權分頁；逐一授權（輔助使用經 deep link 手動加入）→ 重啟 App → 橫幅與按鈕消失；設定頁三權限列顯示「已授權」
  5. **端到端（打包 App 內）**：錄製面板選窗 → F9 錄一段打字＋點擊 → 停止 → 命名儲存；回放該腳本（日誌逐步 `[n/N]`、F10 與滑鼠甩左上角可中斷）；建一條 text 規則（框選 region）＋一條 image 規則（框選並擷取模板）→ 開始監看 → 讓畫面出現關鍵字 → 觸發、冷卻、停止監看正常
  6. **日誌落地（Task 1，spec §10）**：`~/.keyboard-executor/scripts/logs/app.log` 存在且含啟動與回放記錄；故意讓一條規則觸發失敗（指向不存在的腳本）→ GUI 日誌面板與 app.log **同時**出現「觸發失敗」繁中訊息；`logs/` 滾動檔設定生效（app.log 未爆量）
  7. **刪除入口（Task 4）**：刪除腳本／刪除規則／模板管理刪除各操作一次——確認對話框為繁中「刪除／取消」，取消不動作、確認後清單即時刷新
  8. **--version（Task 2）**：`keyboard-executor --version` → `keyboard-executor 0.5.0`
  9. **qtbase 繁中（Task 4 待辦 #9）**：開啟任一含內建標準鈕的 Qt 對話框確認按鈕為繁中；若 PySide6 未帶 zh_TW 翻譯檔則如實記錄（刪除確認已自建繁中鈕，不受影響）
  10. **關窗收尾（M4 followthrough）**：回放/監看進行中關閉主視窗 → 無 QThread 警告、無殘留背景輸入、無日誌橋投遞錯誤
  11. **Windows（backlog，不在本驗收）**：`build.ps1`＋自簽＋smoke、winsdk OCR、pydirectinput、DPI/多螢幕——需 Windows 機器，列文末 backlog

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml packaging/launcher.py packaging/keyboard-executor.spec packaging/entitlements.plist packaging/build.sh packaging/build.ps1 packaging/README.md tests/test_packaging.py
git commit -m "feat: PyInstaller 打包設定、建置腳本與發布文件（M5 Task 5）"
```

---

## M4／前里程碑待辦對應表（10 項全數對應）

| # | M4 審查待辦 | 去向 |
|---|------------|------|
| 1 | pyproject 進入點（gui-scripts/scripts） | ✓ Task 5 |
| 2 | logging 收斂（stderr 三源→日誌檔＋GUI 面板） | ✓ Task 1 |
| 3 | macOS 打包：主動請求＋deep link＋Info.plist＋簽章/公證 | ✓ Task 3（請求/deep link，可測半）＋ Task 5（Info.plist/簽章/公證，人工半） |
| 4 | GUI 缺 delete 入口 | ✓ Task 4（腳本/規則/模板三入口） |
| 5 | 模板擷取無影像預覽 | **Backlog**（M4 審查允許「補或記 backlog」；v1 以檔名回填＋規則試跑驗證，預覽為純視覺 numpy→QImage 橋接，無單元測試價值） |
| 6 | run/watch worker helper 重複＋wait 5s | **延後**（M4 審查自身條件「若打包後有第三種背景工作再抽」；M5 無新背景工作） |
| 7 | 多螢幕 RegionPicker／drag_scale devicePixelRatio | **Windows backlog**（維持 M4 裁定；macOS 單螢幕人工驗收涵蓋現行為） |
| 8 | rule_editor 直接建構未注入＋settings_page import 私名 | ✓ Task 4（get_platform/capture_factory 注入；default_permission_checks 公開） |
| 9 | Qt 內建對話框英文按鈕（qtbase_zh_TW） | ✓ Task 4（build_app 載 translator＋刪除確認自建繁中鈕雙保險；人工驗收 #9） |
| 10 | _parse_number vs _get_positive_number 格式統一 | ✓ Task 4 |

## Windows backlog（跨里程碑累積，需 Windows 實機——M5 如實移交，不假裝清償）

- winsdk OCR 實作實機驗證（win32/ocr.py 薄適配；M3 起）＋ spec 的 winsdk hiddenimports 實測
- pydirectinput 實機（game_input_mode 端到端、未知按鍵行為；M1/M2 起）
- I4：watch 觸發腳本忽略 `settings.game_input_mode`（per-script platform；M3 裁定延 M5-prep）
- mss 多螢幕／DPI（125%/150% 縮放座標、RegionPickerOverlay primaryScreen 限制；M1/M4）
- `drag_scale` devicePixelRatio 實測（M4）
- Windows PyInstaller 建置＋自簽＋smoke（Task 5 的 build.ps1／spec win32 分支已備妥，未實機執行）
- M1 既有：Windows smoke 清單（錄製→回放→OCR→模板→規則觸發 端到端）

## spec §15 v2 範圍外確認（本版不做，M5 不越界）

背景視窗輸入（PostMessage/事件注入）、Linux 支援、腳本市集／匯入匯出打包格式、條件運算式（AND/OR 組合）、cron 式排程器——全數不做；本計畫亦不加自動更新、安裝器（DMG/MSI）、系統匣等「發布順手」項（YAGNI）。

## 完成定義（M5）

- [ ] `python -m pytest -q` 全綠：**494 passed, 1 skipped**
- [ ] 支撐邏輯全數有單元覆蓋：`setup_logging`/`QtLogHandler`（含 print→logger 的 caplog 行為）、版本單一來源＋`--version`、`system_settings_url` 精確字串＋`request_*` 注入包裝＋缺失→URL 映射、刪除編排（confirm 注入）＋模板管理＋rule_editor 注入＋訊息統一、entry point／launcher／spec sanity
- [ ] 原生／建置面零假測試：`CGRequest*` lazy import 行有 `# pragma: no cover`；PyInstaller 建置、codesign/notarytool、.app 啟動只出現在腳本與人工驗收清單
- [ ] Qt 隔離不變：`grep -rn "PySide6" src/keyboard_executor --include="*.py" | grep -v "/app/" | grep -v "gui.py"` 為空（`core/logging_config.py` 純 Python）
- [ ] macOS 實機人工驗收（Task 5 Step 5 全清單）通過：build → 簽章 → 首次啟動權限請求與 deep link → 打包 App 內 record/play/watch 端到端 → 日誌落地 `logs/app.log` → 刪除入口 → `--version`
- [ ] M4 待辦 10 項全對應（上表）；Windows backlog 與 spec §15 範圍外明列；`packaging/README.md` 含簽章/公證/降級完整文件
