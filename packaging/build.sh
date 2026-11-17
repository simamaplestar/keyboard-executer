#!/usr/bin/env bash
# Apple Silicon / macOS 14+；預設 ad-hoc 簽章，CODESIGN_IDENTITY 可指定 Developer ID。
# 前置：原生 arm64 venv 內 python3 -m pip install -e ".[dev,packaging]"。
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON:-python3}"
"$python_bin" "$script_dir/macos_support.py"

for tool in codesign ditto shasum; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "找不到建置工具：$tool" >&2
        exit 1
    fi
done

dist_dir="${KE_DIST_DIR:-$script_dir/dist/macos-arm64}"
work_dir="${KE_WORK_DIR:-$script_dir/build/macos-arm64}"
mkdir -p "$dist_dir" "$work_dir"
dist_dir="$(cd "$dist_dir" && pwd)"
work_dir="$(cd "$work_dir" && pwd)"
export MACOSX_DEPLOYMENT_TARGET=14.0

archive="KeyboardExecutor-macos-arm64.zip"
staging_dir=""
cleanup_archive() {
    local status=$?
    trap - EXIT
    if [[ -n "$staging_dir" ]]; then
        rm -f "$staging_dir/$archive" "$staging_dir/$archive.sha256"
        rmdir "$staging_dir"
    fi
    if [[ $status -ne 0 ]]; then
        rm -f "$dist_dir/$archive" "$dist_dir/$archive.sha256"
        echo "建置失敗，未保留可發布的 ZIP；請修正錯誤後重新建置。" >&2
    fi
    exit "$status"
}
trap cleanup_archive EXIT
# 只清除本腳本管理的兩個發布檔，不刪除其他建置或使用者資料。
rm -f "$dist_dir/$archive" "$dist_dir/$archive.sha256"

if [[ -n "${OCR_SOURCE_DIR:-}" ]]; then
    "$python_bin" "$script_dir/prepare_chat_ocr_models.py" --source-dir "$OCR_SOURCE_DIR"
else
    "$python_bin" "$script_dir/prepare_chat_ocr_models.py"
fi

"$python_bin" -m PyInstaller --clean --noconfirm \
    --distpath "$dist_dir" --workpath "$work_dir" \
    "$script_dir/keyboard-executor.spec"

app="$dist_dir/KeyboardExecutor.app"
codesign --verify --deep --strict --verbose=2 "$app"
QT_QPA_PLATFORM=offscreen "$app/Contents/MacOS/KeyboardExecutor" --self-test

staging_dir="$(mktemp -d "$dist_dir/.archive.XXXXXX")"
ditto -c -k --sequesterRsrc --keepParent "$app" "$staging_dir/$archive"
(
    cd "$staging_dir"
    shasum -a 256 "$archive" > "$archive.sha256"
)
mv "$staging_dir/$archive" "$dist_dir/$archive"
mv "$staging_dir/$archive.sha256" "$dist_dir/$archive.sha256"
rmdir "$staging_dir"
staging_dir=""
echo "完成：$app"
echo "傳送檔案：$dist_dir/${archive}（SHA256：$archive.sha256）"
echo "正式對外發布前，請依 packaging/README.md 完成公證及 Mac 實機驗收。"
