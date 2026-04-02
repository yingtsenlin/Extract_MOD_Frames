# YOLO MOD 提取工具 (YOLO MOD Extractor)

這是一個專為 YOLO 影像辨識工作流設計的輔助工具。當你在進行初步標註（如使用 DarkLabel）時，可以將需要後續加強或修改的影格標記為特定類別（預設為 mod，編號 4）。此工具能自動將這些影格及其對應的標籤檔從海量資料中挑選出來，方便進行二次精細修改。

## 🚀 功能亮點

* 直覺式 GUI 介面：提供圖形化視窗，支援路徑瀏覽與手動貼上。

* 全在地化執行：無需聯網，確保資料安全性，不產生多餘的快取紀錄。

## 🛠️ 安裝要求

如果你是直接執行 Python 腳本，請確保環境符合以下條件：
```
Python 3.6+
```
內建 ```tkinter``` 庫（通常 Python 安裝時會內建）

## 📖 使用說明

1. 選擇路徑：點擊「瀏覽...」或直接貼上包含 image 與 label 子資料夾的主路徑。

2. 開始掃描：點擊「開始提取 (Start)」，程式會掃描 label/*.txt。

3. 檢查結果：程式會自動在目標目錄下建立 mod_refinement 資料夾，內含篩選後的影像與標籤。

4. 二次標註：直接使用 DarkLabel 打開 mod_refinement 資料夾進行加強修改。

## 📦 封裝為執行檔 (.exe)

為了在沒有安裝 Python 的環境下使用，你可以使用 PyInstaller 將其封裝。在專案目錄下執行以下指令：
```bash
pyinstaller --onefile --noconsole --clean --name "YOLO_MOD_Extractor" extractor_gui.py
```
```bash
--onefile: 打包成單一執行檔。

--noconsole: 執行時隱藏背景的黑色指令視窗。

--name: 指定生成的軟體名稱。
```

## 📁 資料夾結構範例

執行前，請確保你的資料夾結構如下：
```
你的專案資料夾/
├── image/          # 存放原始影像
└── label/          # 存放 .txt 標籤檔
```

執行後會生成：
```
你的專案資料夾/
└── mod_refinement/
    ├── image/      # 被提取的影像
    └── label/      # 被提取的標籤檔與 classes.txt
```
