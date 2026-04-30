import yaml
import time
import os
import zipfile
import shutil
from playwright.sync_api import sync_playwright
from datetime import datetime
from modules import db_manager
import asyncio
import sys

def write_log(message):
    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'system.log')
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}\n"
    
    # 使用 utf-8 確保中文不會亂碼
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(log_line)
    print(log_line.strip()) # 終端機依然保留輸出

def load_config():
    # 讀取根目錄的 config.yaml
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def run_automation():
    # 防呆：同時只允許一個自動偵測執行
    lock_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'automation.lock')
    if os.path.exists(lock_path):
        write_log("⚠️ 已有自動偵測執行中，請勿重複啟動。")
        return
        
    # 建立 lock file
    with open(lock_path, 'w') as f:
        f.write(str(os.getpid()))
        
    try:
        # --- Windows 背景執行緒專屬修復區塊 ---
        if sys.platform == 'win32':
            # 1. 設定 Windows 專用的 Policy (支援開啟子程序)
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            # 2. 為當前這個全新的背景執行緒，建立並綁定一個專屬的事件迴圈
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # 建立一個無限迴圈，直到所有 Pending 任務都跑完
        while True:
            task = db_manager.get_pending_task()
            if not task:
                write_log("ℹ️ 目前沒有待處理的任務。")
                break

            task_id = task['id']
            video_path = task['original_path']
            target_name = task['target_name']
            video_time = task['video_time']

            config = load_config()
            db_manager.update_task_status(task_id, 'Processing')
            write_log(f"🚀 開始處理任務: {target_name} (ID: {task_id})")

            # --- 將單一任務的操作包裝在內層的 try-except 中 ---
            try:
                with sync_playwright() as p:
                    # 啟動瀏覽器 ( headless=False 讓你可以在開發期間看著它動)
                    browser = p.chromium.launch(headless=False, channel="msedge")
                    page = browser.new_page()

                    # 1. 進入內網系統 (請替換為實際網址)
                    page.goto("http://10.10.91.25:3000/")
                    
                    # 2. 選擇 Input Type 為 Video
                    page.locator("button:has-text('Video')").click()
                    # 增加一個等待，確保上傳組件已切換為影片模式
                    page.wait_for_timeout(1000)
                    
                    # 3. 選擇模型 (Model Selection)
                    target_model = config['detection_params']['model']
                    # 尋找帶有 model-btn 且文字符合設定檔的模型按鈕
                    page.locator(f"button.model-btn:has-text('{target_model}')").click()
                    
                    # 4. 設定信心閾值拉桿 (Confidence Slider)
                    conf_val = config['detection_params']['confidence']
                    page.evaluate(f"""
                        const slider = document.getElementById('confidence-slider');
                        if(slider) {{
                            slider.value = {conf_val};
                            // 觸發 input 和 change 事件，讓前端框架(如 React/Vue)能偵測到數值改變
                            slider.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            slider.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        }}
                    """)
                    
                    # 5. 上傳檔案
                    write_log(f"上傳影片中: {video_path}")
                    
                    # 使用更精確的 Selector：只找位在 dropzone 類別底下的 input
                    video_input = page.locator('div.dropzone input[type="file"]')
                    video_input.set_input_files(video_path)
                    
                    # 6. 點擊預測按鈕
                    page.locator('.predict-btn').click()
                    write_log(f"⏳ [{target_name}] 已點擊 Predict，系統運算中 (依影片長度可能需要數分鐘至數小時，請耐心等待)...")

                    # 7. 監聽完成狀態 (等待下載按鈕出現)
                    download_btn = page.locator("button.download-btn:has-text('Download YOLO Dataset')")
                    download_btn.wait_for(state='visible', timeout=0)
                    write_log(f"✅ [{target_name}] 預測完成！出現下載按鈕，準備下載...")
                        
                    # 8. 點擊下載並攔截下載檔案
                    with page.expect_download(timeout=0) as download_info:
                        download_btn.click()
                    download = download_info.value
                    
                    # --- 以下解壓縮與重新命名的邏輯保持不變 ---
                    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'output')
                    os.makedirs(output_dir, exist_ok=True)
                    
                    final_folder_name = f"{target_name}_{video_time}"
                    final_folder_path = os.path.join(output_dir, final_folder_name)
                    
                    temp_zip_path = os.path.join(output_dir, "temp_download.zip")
                    download.save_as(temp_zip_path)
                    
                    with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                        zip_ref.extractall(final_folder_path)
                    
                    os.remove(temp_zip_path)
                    
                    db_manager.update_task_status(task_id, 'Completed')
                    write_log(f"🎉 任務完成，檔案已儲存至: {final_folder_path}")
                    
                    # 成功完成後，關閉本次瀏覽器
                    browser.close()
                    
            except Exception as e:
                error_msg = str(e)
                
                # 定義「斷線」或「伺服器崩潰」的常見 Playwright 關鍵字
                disconnect_keywords = [
                    "net::ERR",              # 網路連線錯誤 (例如 ERR_CONNECTION_REFUSED)
                    "Target closed",         # 網頁或瀏覽器意外關閉
                    "disconnected",          # 連線中斷
                    "closed",                # 通訊埠關閉
                    "Connection"             # 連線相關異常
                ]
                
                # 檢查錯誤訊息中是否包含上述任何一個關鍵字
                if any(keyword in error_msg for keyword in disconnect_keywords):
                    write_log(f"🚨 嚴重異常: 偵測到系統斷線或崩潰！")
                    write_log(f"詳細錯誤: {error_msg}")
                    write_log("🛑 為了保護後續任務，已觸發斷路器。正在終止整批自動化流程...")
                    
                    # 貼心設計：將當前這支跑到一半斷線的影片「退回 Pending」，這樣你下次啟動時它會自動重跑
                    db_manager.update_task_status(task_id, 'Pending')
                    
                    # 直接跳出 while True 迴圈，機器人會立刻收工關機
                    break 
                else:
                    # 如果是一般的錯誤（例如找不到按鈕、某支影片格式壞掉），就只標記這支影片失敗，並繼續跑下一支
                    write_log(f"❌ 任務 [{target_name}] 發生一般錯誤: {error_msg}")
                    db_manager.update_task_status(task_id, 'Failed')

    finally:
        # 最外層的 finally：不論所有任務是跑完、中斷還是出錯，最後一定會刪除 lock_path
        if os.path.exists(lock_path):
            os.remove(lock_path)