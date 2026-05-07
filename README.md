# Extract MOD Frames

這個專案用來串接「影片偵測自動化 + 後處理」流程，重點是批次、可續跑、可追蹤日誌。

## 目前工作流

1. 匯入任務（SQLite）
2. 自動化流程固定先做「分割 + 抽幀」
3. 逐段上傳到網頁做偵測（支援 Headless）
4. 全部分段完成後自動合併 YOLO 結果
5. 任務完成後僅保留最終合併資料夾（中繼 `origin/`、`segments/` 會清除）

## 主要功能

- 任務管理：新增、刪除、重試（Pending）
- 斷點續跑：
  - 若已存在分割片段，會沿用現有片段
  - 若部分分段已偵測完成，會跳過已完成分段繼續往下
- 參數化設定：
  - 模型、信心值、Frame Interval
  - FFmpeg 路徑
  - Output 路徑
  - Mod 抽取輸出路徑
  - Headless 開關
  - 抽幀 FPS、分割秒數
- 日誌：
  - 任務頁與後處理頁都可顯示 `system.log` 最近 20 條
  - 透過「刷新日誌」手動更新
- 後處理（可勾選批次）：
  - 批次提取含 `mod(4)` 的影像
  - 同步移除輸出標註中的 `4 ` 列

## 專案結構

```text
source/
├── app.py
├── config.yaml
├── requirements.txt
├── system.log
├── database/
│   └── tracker.db
└── modules/
    ├── db_manager.py
    ├── file_parser.py
    ├── playwright_bot.py
    ├── post_process.py
    ├── video_segmenter.py
    └── yolo_merger.py
```

## 安裝與啟動

1. 建立虛擬環境

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip setuptools wheel
```

2. 安裝套件

```bash
pip install -r source/requirements.txt
```

3. 啟動介面（在 `source/` 目錄）

```bash
streamlit run app.py
```

## 設定檔（source/config.yaml）

- `detection_params.confidence`
- `detection_params.frame_interval`
- `detection_params.model`
- `tools.ffmpeg_path`
- `tools.output_dir`（偵測最終輸出）
- `tools.mod_output_dir`（Mod 抽取輸出）
- `tools.headless`
- `tools.darklabel_path`（目前 UI 已暫時隱藏啟動按鈕，但設定仍保留）
- `pipeline.target_fps`
- `pipeline.segment_seconds`

## 使用流程

1. 在「匯入資料與設定」匯入母資料夾並調整參數
2. 到「任務總覽與自動化」啟動偵測
3. 觀察任務頁日誌（最近 20 條）
4. 完成後到「後處理與 Darklabel」勾選資料夾批次提取 Mod
5. 產生的 Mod 結果會輸出到 `tools.mod_output_dir`

## 注意事項

- DB 路徑：`source/database/tracker.db`
- 若自動化流程中斷，可把任務設回 `Pending` 後重跑，系統會嘗試從中斷點續跑
- 若 FFmpeg 失敗，先確認 `tools.ffmpeg_path` 是否正確
