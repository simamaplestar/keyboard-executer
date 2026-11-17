# Windows 離線聊天 OCR 實測

日期: 2026-10-02. 使用者已選擇 **RapidOCR + PP-OCRv6 tiny + ONNX Runtime CPU** 作為聊天 OCR 組合. 本文件保留先前隔離環境的實測耗時與原始辨識結果; 正式程式的整合及打包驗證另行記錄.

**更正: 先前的人工轉錄經使用者指出有誤. 由此計算的錯漏數、CER、姓名／方向正確率和準確度排名全部撤回, 以這些分數推薦 small + OpenVINO、否定 tiny 的結論也撤回.** `inputs.json` 的舊標註僅供稽核, 狀態為 `pending_review`; 尚未重新完成人工核對. 不以模型輸出反填正確答案, 也不宣稱 tiny 為 100% 準確.

模型與可用後端參考 [RapidOCR 官方模型列表](https://rapidai.github.io/RapidOCRDocs/main/model_list/) 和 [PaddleOCR 官方 PP-OCRv6 說明](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html). 其他候選與官方數據見 [研究比較](2026-10-02-offline-chat-ocr-options.md).

## 本機結果

每張圖先跑 1 次, 再跑 3 次取中位數. 以下是載入後的 OCR 呼叫時間, 包含偵測、辨識和前後處理, 不含截圖、磁碟讀圖、IPC、AI 回覆或遊戲輸入. 測試過程沒有其他研究 OCR 同時執行; 未關閉使用者其他程式.

| 模型與執行引擎 | 完整聊天框 1059×255 | 新密語截圖 665×93 |
|---|---:|---:|
| 原基準 PP-OCRv5 mobile / Paddle | 6.446s | 2.938s |
| PP-OCRv5 mobile / ONNX Runtime | 1.323s | 0.541s |
| PP-OCRv5 mobile / OpenVINO | 0.900s | 0.257s |
| PP-OCRv6 small / ONNX Runtime | 0.733s | 0.543s |
| PP-OCRv6 small / OpenVINO | 0.578s | 0.310s |
| **PP-OCRv6 tiny / ONNX Runtime（使用者選定）** | **0.163s** | **0.082s** |

tiny 在這批圖片的實測耗時最短. 官方配套 tiny 字典缺「嗎」的檢查紀錄仍保留, 但字典內容不能證明圖片原文是「嗎」, 也不能據此判定這張圖片的 tiny 輸出有誤. [配套字典](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv6/rec/PP-OCRv6_rec_tiny/ppocrv6_tiny_dict.txt)

同 v5 模型換引擎已有明顯速度改善, 所以原基準延遲不全是模型大小造成. 先前對「星星／呈呈」、「認識／靓識」、「嗎／媽」等文字以及漏字的判斷依賴有誤標註, 不再列為已確認的 OCR 錯誤. 原始辨識文字保持不變, 沒有用語言模型或文字替換修正答案. [tiny 原圖與辨識文字](../../packaging/build/diagnostics/offline-ocr/v6-tiny-results.html).

另外嘗試了 v5 mobile det + v5 server rec / ONNX Runtime. 該程序執行超過 139 秒仍沒有完整結果, 因而停止這個研究程序. 它啟動時的測試程式尚未加入階段進度, 無法區分當時停在模型初始化或辨識. 沒有完整結果, **未將它納入速度／準確度排名**, 也不能據此斷言所有 server 部署都慢. 其餘六組均完整完成.

## 全部圖片的中位數

| 組合 | 完整聊天窗 | 地圖+送出密語 | 短密語 | 新密語 | 長送出密語 |
|---|---:|---:|---:|---:|---:|
| 現行 Paddle v5 mobile | 6.446 | 4.154 | 4.166 | 2.938 | 1.514 |
| ONNX v5 mobile | 1.323 | 0.687 | 0.868 | 0.541 | 0.304 |
| OpenVINO v5 mobile | 0.900 | 0.379 | 0.345 | 0.257 | 0.139 |
| ONNX v6 small | 0.733 | 1.045 | 1.078 | 0.543 | 0.572 |
| OpenVINO v6 small | 0.578 | 0.331 | 0.440 | 0.310 | 0.174 |
| ONNX v6 tiny | 0.163 | 0.107 | 0.129 | 0.082 | 0.066 |

單位為秒. 同組合同張圖的四次輸出都一致; raw JSON 另保留每次時間、最大值與完整 OCR 框. 不把三個樣本的最大值當作可靠 p95/p99.

| 組合 | 引擎建構／載入秒數 | 各圖完成後最高取樣 RSS |
|---|---:|---:|
| 現行 Paddle v5 mobile | 13.019 | 354 MiB |
| ONNX v5 mobile | 1.369 | 164 MiB |
| OpenVINO v5 mobile | 2.344 | 510 MiB |
| ONNX v6 small | 0.623 | 170 MiB |
| OpenVINO v6 small | 1.349 | 490 MiB |
| ONNX v6 tiny | 0.709 | 144 MiB |

建構時間不含 Python 啟動與本測試前置 import, 不是 GUI 冷啟動時間. RSS 是圖完成後取樣, 不是整段的精確記憶體峰值. OpenVINO 在本機較快, 但 RSS 比 ONNX Runtime 高.

## 資料、計分與限制

- 5 張保存的真實聊天截圖, 其中 4 張是使用者提供的聊天圖片, 1 張是先前保存的完整聊天框. 沒有使用驗證碼、其他挑戰圖片、螢幕即時操作或雲端 OCR.
- 舊人工標註含 5 行聊天, 涵蓋姓名、CH 編號、收送符號及本文; 內容經使用者指出有誤, 正規化字元總數也不再當作有效分母. 未標註所有公告／廣告文字, 不能稱為整張圖的準確率.
- 原計分方法是在 OCR 前固定每個標註行的垂直位置, 依位置取出結果, 不依答案相似度挑選行. NFKC、忽略空白, 合併合法 `[CH.編號]`/`[CH-編號]` 差異; 其餘用字元 Levenshtein 編輯距離. **方法保留, 但標註未審查完成前不執行準確度計分.**
- 原始 JSON 保留當時 ChatObserver 的顏色、格式、姓名與 confidence 解析結果. 舊標註的收送方向與姓名核對也暫停計分, 不宣稱全部正確或沒有誤判; 這批保存圖片不是自然新訊息端到端收發驗證.
- 各模型切框方式不同: 完整圖 v5 有 19 框, v6 small 15 框, tiny 9 框. 框數較少可能是合併或漏讀, 不直接等同準確度改善.
- 樣本很小、玩家名稱種類少, 還不足以保證任意姓名、縮放、遊戲畫面、收送長句都更準. 未做不同 CPU、長時間排程、打包、停止取消和真實遊戲輸入驗收.
- tiny det + small rec、Tesseract、EasyOCR、Windows OCR 只查官方資料, 沒有列為本機實測勝者.

## 可重現設定與檔案

硬體: Intel Core i9-13900KF, Windows x64, Python 3.13.7, CPU 推論. NumPy 2.3.5、OpenCV 4.10.0 在兩環境對齊. 現行環境 PaddleOCR 3.7.0 / PaddlePaddle 3.3.1; 隔離環境 RapidOCR 3.9.2 / ONNX Runtime 1.30.0 / OpenVINO 2026.4.1.

模型推論 2 threads, ONNX inter-op 1, OpenVINO 1 stream/LATENCY, recognition batch 1, 關閉方向分類. det 為 min/64、維持現行尺度 (模型仍對齊到 32 的倍數), box threshold .6、unclip 1.5、不 dilation; v5 mean/std 按配套模型, v6 使用其 .5/.5. 現行 Paddle 維持 MKLDNN 關閉以符合正在使用的相容性設定. 比較的是可工作的現行設定, 不是宣稱所有 Paddle 部署都有相同速度.

RapidOCR 對照明確停用額外長寬比 padding; 偵測框和裁切實作仍存在引擎間差異, 不能把改善全部歸因於模型 kernel. 所有模型以本機檔案初始化, 下載先驗官方 SHA256, 計時前攔阻 Python socket 網路連線. 這次隔離 benchmark 執行時沒有修改正式 app、原建置 venv、使用者腳本及設定.

- [測試程式](benchmark_offline_chat_ocr.py)
- [計分程式](score_offline_chat_ocr.py)
- [耗時摘要與待審標註狀態](../../packaging/build/diagnostics/offline-ocr/summary.json)
- [輸入檔 SHA256 與待審舊標註](../../packaging/build/diagnostics/offline-ocr/inputs.json)
- [模型來源、大小與 SHA256](../../packaging/build/diagnostics/offline-ocr/models.json)
- 原始個別結果: `packaging/build/diagnostics/offline-ocr/{paddle,v5-mobile-ort,v5-mobile-ov,v6-tiny-ort,v6-small-ort,v6-small-ov}.json`.
- 隔離 Python: `packaging/build/diagnostics/offline-ocr/venv/Scripts/python.exe`.

重跑時, 用隔離 Python 執行 `docs/research/benchmark_offline_chat_ocr.py download` 取得已列出的模型, 然後逐一執行同檔的 `v5-mobile-ort`、`v5-mobile-ov`、`v6-tiny-ort`、`v6-small-ort`、`v6-small-ov` 候選. `paddle` 候選使用原本 `ke-build-venv` Python. 不要讓不同 OCR 候選同時搶 CPU. 最後執行 `docs/research/score_offline_chat_ocr.py` 產生摘要與 tiny 原始文字 HTML/TXT.

只重新產生報告不需重跑 OCR. 計分程式預設將缺少審查狀態的標註視為 `pending_review`; 全部有標註的輸入經人工重新核對、明確設為 `annotation_status: reviewed` 後才會恢復計分. 目前各候選的 `accuracy_status` 為 `unavailable`, CER、錯漏數、分母、逐行核對及路由正確率等欄位均為 `null`, 不產生準確度排名.
