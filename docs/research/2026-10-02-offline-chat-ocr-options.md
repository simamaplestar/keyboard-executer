# Windows 離線繁體中文聊天 OCR 候選

查核日期: 2026-10-02. 範圍是遊戲聊天列的姓名、頻道、方向符號與本文. 本文件是官方資料比較和字典檢查; **下列官方速度、準確率都不是這台電腦的聊天實測**. 本機的隔離環境比較另見 [聊天截圖實測](2026-10-02-offline-chat-ocr-benchmark.md).

使用者已選擇 **PP-OCRv6 tiny + ONNX Runtime**. 先前本機報告的人工標註經使用者指出有誤, 相關準確度分數及 small + OpenVINO 推薦已撤回; 本機標註待重新核對. 下列官方數據和字典檢查保留作候選背景, 不用來判定使用者圖片中的實際文字對錯.

## 比較候選背景

1. **RapidOCR + ONNX Runtime + PP-OCRv5 mobile**: 先保留目前模型系列, 比較推理引擎是否能消除主要 CPU 開銷. RapidOCR 將 PaddleOCR 模型轉成 ONNX, 支援 Windows 及離線本機模型. 這是較容易區分「模型改變」與「引擎改變」的方法. [RapidOCR 官方介紹](https://rapidai.github.io/RapidOCRDocs/main/)
2. **PP-OCRv6 tiny / small**, 以及 **v6 tiny 偵測 + small 辨識**: v6 有 tiny/small/medium, small 支援繁體中文且官方綜合及繁中分項成績比 v5 mobile 高. tiny 的精簡字典與 small 不同; 實際適用程度仍須以可靠的聊天圖片標註核對. tiny + ONNX Runtime 是使用者本次選定的組合. [PaddleOCR v6 官方介紹及比較](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html)
3. **同模型換 OpenVINO**, 或 **v5 mobile 偵測 + v5 server 辨識**: 前者比較引擎, 後者檢查姓名和本文準確度是否值得增加耗時. RapidOCR 已支援 ONNX Runtime 和 OpenVINO 使用 v5/v6. [RapidOCR 模型表](https://rapidai.github.io/RapidOCRDocs/main/model_list/)

以上保留研究時的候選比較理由, 實測耗時另見本機報告, 不構成聊天準確度排名.

## 候選及部署差異

| 候選 | 繁中與模型大小 | Windows CPU 與本任務取捨 |
|---|---|---|
| PP-OCRv5 mobile | 支援繁中; 官方模型儲存大小 det 4.7 MB / rec 16 MB | 現有基準模型; 可保留模型換成 ONNX Runtime/OpenVINO |
| PP-OCRv5 server rec | 支援繁中; rec 81 MB | 可沿用 mobile det, 單獨評估更大的辨識模型 |
| PP-OCRv6 small | 官方列繁中; det 9.6 MB / rec 20.4 MB | 主要新模型候選 |
| PP-OCRv6 tiny | 官方列多語支援; det 1.9 MB / rec 4.4 MB | 本次選定搭配 ONNX Runtime; 字典精簡, 字典內容檢查另列於下方 |
| chinese_cht_PP-OCRv3_mobile_rec | 繁中專用; rec 10.8 MB | 備選辨識模型; 必須另驗英文玩家名、CH 與符號 |
| Tesseract chi_tra | 官方繁中模型; fast 約 2.37 MB, best 約 12.99 MB | 本機執行; fast/best 是速度與準確度取捨, 尚未在聊天樣本比較 |
| EasyOCR ch_tra + en | 繁中採 zh_tra_g1; 模型 Hub 未列完整部署體積 | CPU 可用, Windows 需 PyTorch/torchvision; 本輪未安裝、未測速 |
| Windows.Media.Ocr | 語言由系統 OCR 語言包決定 | 可用系統 API 讀取文字與座標; 需先確認本機有繁中辨識器, 未測速 |

Paddle 大小是官方 Paddle 模型儲存欄位, **不是** ONNX 檔案實測大小或整個安裝大小. [辨識模型表](https://www.paddleocr.ai/main/en/version3.x/module_usage/text_recognition.html), [偵測模型表](https://www.paddleocr.ai/main/en/version3.x/module_usage/text_detection.html)

Tesseract 大小是當天官方檔案 HTTP Content-Length, fast 2,366,642 bytes、best 12,985,735 bytes, 不含引擎及英文模型. fast 與 best 只能用 LSTM (`--oem 1`); Windows 安裝方式由官方文件列出. [官方模型說明](https://tesseract-ocr.github.io/tessdoc/Data-Files.html), [fast chi_tra](https://github.com/tesseract-ocr/tessdata_fast/blob/main/chi_tra.traineddata), [best chi_tra](https://github.com/tesseract-ocr/tessdata_best/blob/main/chi_tra.traineddata), [Windows 安裝](https://tesseract-ocr.github.io/tessdoc/Installation.html)

EasyOCR 可用 `Reader(['ch_tra', 'en'], gpu=False)`; 模型事先下載後可離線使用. 繁中仍列在第一代模型, 不能把第二代英文/簡中模型的改善直接視為繁中改善. [官方程式庫](https://github.com/JaidedAI/EasyOCR), [官方模型 Hub](https://www.jaided.ai/easyocr/modelhub/)

Windows OCR 可呼叫 `RecognizeAsync` 取得行與單字座標; `AvailableRecognizerLanguages` 只列出已安裝語言. 本輪未查使用者系統語言清單, 不假設已有繁中包或可直接打包分發模型. [Microsoft OcrEngine](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine), [已安裝語言](https://learn.microsoft.com/zh-tw/uwp/api/windows.media.ocr.ocrengine.availablerecognizerlanguages)

## 官方比較數字如何解讀

以下取自 v6 同一份官方比較, CPU 是 **Intel Xeon 8350C**, 測速是 200 張一般/文件圖的整體平均, 含影像 I/O、前後處理與模型. TC 是該份內部評估集的繁中辨識分項. 這些數字可選候選, 不能換算為本機每張遊戲截圖延遲. [原表與條件](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html#3-key-metrics)

| 模型組合 | ONNX Runtime 秒/圖 | OpenVINO 秒/圖 | TC 辨識準確率 |
|---|---:|---:|---:|
| v5 mobile | 0.61 | 0.78 | 72.0% |
| v6 tiny | 0.22 | 0.20 | 65.0% |
| v6 small | 0.61 | 0.59 | 77.0% |
| v6 medium | 3.31 | 1.40 | 78.6% |

官方提到的 5.2 倍是 **v6 medium 對 v5 server、OpenVINO** 的比較; 不能解讀為本機目前 v5 mobile 將普遍快 5.2 倍. v6 tiny 在同一表也不是繁中最準. 不混用其他世代文件的不同資料集百分比作跨表排名.

## 字典檢查: tiny 的實際限制

直接讀取 RapidAI v3.9.2 模型配套文字字典, 以 UTF-8-SIG 解碼並計算 `splitlines()`. 這是字典內容檢查, **不是 OCR 準確度實測**, 也不能證明使用者截圖中出現的字是「嗎」或將「媽」判為 OCR 錯誤.

| 字典 | 列數 | 是否包含「嗎」 |
|---|---:|---|
| v5 mobile | 18,383 | 有 |
| v6 small | 18,708 | 有 |
| v6 tiny | 6,904 | 無 |
| 繁中 v3 | 8,421 | 有 |

來源: [v5 字典](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile/ppocrv5_dict.txt), [v6 small 字典](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv6/rec/PP-OCRv6_rec_small/ppocrv6_dict.txt), [v6 tiny 字典](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv6/rec/PP-OCRv6_rec_tiny/ppocrv6_tiny_dict.txt), [繁中 v3 字典](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/paddle/PP-OCRv4/rec/chinese_cht_PP-OCRv3_rec_mobile/chinese_cht_dict.txt)

RapidOCR 的 ONNX 模型可內嵌字元字典, 應優先使用模型配套字典. v6 的 `lang_type` 選擇並不換另一套模型, 所以單改成繁中語言代號不能補 tiny 的缺字. 推論: 固定分類字典沒有某個字時, 該辨識模型無法原樣輸出該字; 不應事後猜測玩家姓名來補救. [RapidOCR 字典載入原始碼](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/ch_ppocr_rec/main.py), [模型選擇規則](https://rapidai.github.io/RapidOCRDocs/main/model_list/)

## 可重現的候選配置

當天套件查核: RapidOCR 3.9.2 要求 Python >=3.8,<4; ONNX Runtime 1.30.0 有 CPython 3.13 Windows x64 wheel. 這只證明候選套件分發相容, 仍需以隔離環境確認實際執行. [RapidOCR PyPI](https://pypi.org/project/rapidocr/3.9.2/), [ONNX Runtime PyPI](https://pypi.org/project/onnxruntime/1.30.0/)

```text
python -m pip install rapidocr==3.9.2 onnxruntime==1.30.0
```

測試應明確指定模型, 不依賴 RapidOCR 新版預設 v6 small. 下面只示意 v5 mobile 對照配置, 不代表最優參數:

```python
from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR

engine = RapidOCR(params={
    "Global.use_cls": False,
    "Det.engine_type": EngineType.ONNXRUNTIME,
    "Det.lang_type": LangDet.CH,
    "Det.ocr_version": OCRVersion.PPOCRV5,
    "Det.model_type": ModelType.MOBILE,
    "Rec.engine_type": EngineType.ONNXRUNTIME,
    "Rec.lang_type": LangRec.CH,
    "Rec.ocr_version": OCRVersion.PPOCRV5,
    "Rec.model_type": ModelType.MOBILE,
    "EngineConfig.onnxruntime.intra_op_num_threads": 2,
    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    "Rec.rec_batch_num": 1,
    "Det.limit_type": "min",
    "Det.limit_side_len": 64,
    "Det.mean": [0.485, 0.456, 0.406],
    "Det.std": [0.229, 0.224, 0.225],
})
```

RapidOCR 預設 det `min/736`, 與本應用現有 `min/64` 不同. 若用預設, 高度 255 的聊天圖可能先放大, 使「引擎比較」混入影像大小差異. 本機比較應記錄並對齊設定, 再另測需要放大才能提高準確度的情況. [RapidOCR 參數原始碼](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/config.yaml)

v5 偵測模型的 mean/std 也須指定: 上述數值取自本機官方 `PP-OCRv5_mobile_det/inference.yml`; 不能在切換回 v5 時直接沿用 RapidOCR 3.9.2 的 v6 預設 0.5. 完整本機參數與關閉方向分類、填補、後處理設定見 [測試程式](benchmark_offline_chat_ocr.py).

首用自動下載不是完全離線初始化. 部署時應預先保存模型, 再用 `Det.model_path` / `Rec.model_path` 明確指定檔案; 模型 SHA256 列在 RapidAI 官方配置中. [離線使用方式](https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/how_to_use_offline_model/), [模型 URL 與 SHA256](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml)

## 執行環境與授權

- ONNX Runtime CPU 不需 CUDA; Windows 需要 Visual C++ runtime. OpenVINO 官方列 Windows 10/11 與 Python 3.10-3.14, 可另測 CPU 後端. [ONNX Runtime 安裝](https://onnxruntime.ai/docs/install/), [OpenVINO 系統需求](https://docs.openvino.ai/2026/about-openvino/release-notes-openvino/system-requirements.html)
- RapidOCR、PaddleOCR、EasyOCR、Tesseract 專案採 Apache-2.0; RapidOCR 明示 OCR 模型歸原模型提供者. ONNX Runtime 採 MIT, OpenVINO 採 Apache-2.0. 分發時保留各依賴與模型的授權/來源, Windows OCR 則是系統 API 與語言包. [RapidOCR 授權](https://github.com/RapidAI/RapidOCR/blob/main/LICENSE), [PaddleOCR 授權](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE), [EasyOCR 授權](https://github.com/JaidedAI/EasyOCR/blob/master/LICENSE), [Tesseract 授權](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE), [ONNX Runtime 授權](https://github.com/microsoft/onnxruntime/blob/main/LICENSE), [OpenVINO 授權](https://github.com/openvinotoolkit/openvino/blob/master/LICENSE)

## 本機評估需分開記錄

每個候選記錄: 冷啟動、暖機後中位數與最慢值、CPU threads、det/rec 模型 SHA256、辨識尺寸與 batch. 準確度要以人工轉錄的同一組聊天圖比較完整姓名、CH 編號、`>>`/`<<`、本文及漏行數, 不只看引擎自己的 confidence. 速度比較至少包含完整聊天窗與單則新密語. 圖片保留本機, 不需要送雲端 OCR.

本研究未在本機執行 Tesseract、EasyOCR 或 Windows OCR. Paddle/Rapid 候選的實際試跑結果應另附同圖測試紀錄, 不以以上官方表格代替.
