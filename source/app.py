import streamlit as st
import pandas as pd
import sqlite3
import yaml
import os
import threading
from modules import db_manager, file_parser, playwright_bot, post_process

# 初始化資料庫
db_manager.init_db()

# 讀取與寫入設定檔的輔助函式
CONFIG_PATH = 'config.yaml'
def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def save_config(config_data):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

# 讀取資料庫狀態為 Pandas DataFrame (為了在 UI 上畫出漂亮的表格)
def load_tasks_to_dataframe():
    conn = sqlite3.connect(os.path.join('database', 'tracker.db'))
    df = pd.read_sql_query("SELECT * FROM jobs", conn)
    conn.close()
    return df

# 設定網頁基本資訊
st.set_page_config(page_title="影片偵測自動化中控台", layout="wide")

# 側邊欄導覽
st.sidebar.title("🤖 系統控制面板")
page = st.sidebar.radio("功能導覽", ["1. 任務總覽與自動化", "2. 匯入資料與設定", "3. 後處理與 Darklabel"])

# ==========================================
# 頁面 1: 任務總覽與自動化
# ==========================================
if page == "1. 任務總覽與自動化":
    st.header("📊 任務狀態總覽")
    
    # 1. 初始化全選的狀態 (預設為 False)
    if "select_all" not in st.session_state:
        st.session_state.select_all = False
        
    # 2. 建立一個獨立的區塊放全選按鈕
    col_ctrl1, col_ctrl2 = st.columns([1, 5])
    with col_ctrl1:
        if st.button("☑️ 全選 / 取消全選", use_container_width=True):
            # 切換狀態
            st.session_state.select_all = not st.session_state.select_all
            # 清除表格的編輯記憶，強迫表格依照新的 select_all 狀態重新繪製
            if "task_editor" in st.session_state:
                del st.session_state["task_editor"]
            st.rerun() # 立刻重新整理畫面
            
    df = load_tasks_to_dataframe()
    if not df.empty:
        # 3. 表格預設的勾選狀態，直接綁定我們的 session_state
        df.insert(0, "選取", st.session_state.select_all)
        
        # 4. 加上 key="task_editor"，讓 Streamlit 能夠追蹤並清除它的狀態
        edited_df = st.data_editor(
            df,
            width="stretch",
            hide_index=True,
            key="task_editor", 
            column_config={
                "選取": st.column_config.CheckboxColumn("選取", help="勾選你要操作的任務", default=False)
            },
            disabled=df.columns.drop("選取") 
        )
        
        selected_ids = edited_df[edited_df["選取"]]["id"].tolist()
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🗑️ 刪除勾選的任務"):
                if selected_ids:
                    db_manager.delete_tasks(selected_ids)
                    st.success(f"已刪除 {len(selected_ids)} 筆任務！")
                    # 執行完畢後把全選按鈕重置
                    st.session_state.select_all = False
                    if "task_editor" in st.session_state:
                        del st.session_state["task_editor"]
                    st.rerun()
                else:
                    st.warning("請先在表格中勾選要刪除的任務。")
                    
        with col_btn2:
            if st.button("🔄 將勾選任務設為 Pending (再試一次)"):
                if selected_ids:
                    db_manager.reset_tasks_to_pending(selected_ids)
                    st.success(f"已將 {len(selected_ids)} 筆任務重設為待處理！")
                    # 執行完畢後把全選按鈕重置
                    st.session_state.select_all = False
                    if "task_editor" in st.session_state:
                        del st.session_state["task_editor"]
                    st.rerun()
                else:
                    st.warning("請先在表格中勾選要重試的任務。")
                    
    else:
        st.info("目前沒有任何任務，請至「匯入資料」頁面新增。")
        
    st.divider()
    
    # 建立三個按鈕的排版
    col_run, col_refresh, col_unlock = st.columns([2, 2, 2])
    
    with col_run:
        if st.button("▶️ 開始自動偵測", type="primary"):
            bot_thread = threading.Thread(target=playwright_bot.run_automation)
            bot_thread.start()
            st.success("🤖 機器人已在背景啟動！")
            
    with col_refresh:
        if st.button("🔄 刷新日誌"):
            pass # 單純重整畫面
            
    with col_unlock:
        # 新增這個強制解鎖按鈕
        if st.button("🔓 強制解除系統鎖定"):
            lock_path = "automation.lock" # 請確保路徑正確，如果是在根目錄就這樣寫
            if os.path.exists(lock_path):
                os.remove(lock_path)
                st.success("✅ 已強制解除系統防呆鎖！你可以重新啟動機器人了。")
            else:
                st.info("ℹ️ 目前系統沒有被鎖定。")
    

# ==========================================
# 頁面 2: 匯入資料與設定
# ==========================================
elif page == "2. 匯入資料與設定":
    st.header("📂 匯入未偵測的母資料夾")
    folder_input = st.text_input("請貼上「匯出 [日期 時間]」的母資料夾絕對路徑：", 
                                 placeholder="例如: D:\\Exports\\匯出 2026-04-30")
    
    if st.button("📥 解析並加入任務佇列"):
        if os.path.exists(folder_input):
            file_parser.parse_and_register_folder(folder_input)
            st.success("✅ 掃描完成！已將符合的影片加入資料庫 (請至任務總覽查看)。")
        else:
            st.error("❌ 找不到該資料夾，請檢查路徑是否正確。")
            
    st.divider()
    
    st.header("⚙️ 偵測系統參數設定")
    # 每次進來這頁或重新整理時，讀取最新的 config.yaml
    config = load_config()
    
    with st.form("config_form"):
        st.subheader("Playwright 填表參數")
        
        # 1. 安全讀取 Frame Interval (強制轉為字串避免型別錯誤)
        current_interval = str(config['detection_params'].get('frame_interval', '5'))
        interval_options = ["1", "5", "10", "30"]
        default_index = interval_options.index(current_interval) if current_interval in interval_options else 1
        new_interval = st.selectbox("Frame Interval", interval_options, index=default_index)
        
        # 2. 安全讀取 Confidence (強制轉為浮點數)
        current_conf = float(config['detection_params'].get('confidence', 0.65))
        new_conf = st.slider("Confidence Threshold", 0.05, 0.95, current_conf, 0.05)
        
        # 3. 讀取 Model
        current_model = config['detection_params'].get('model', 'yolov8_large')
        new_model = st.text_input("Model Selection", current_model)
        
        st.subheader("外部工具")
        current_dl_path = config['tools'].get('darklabel_path', '')
        new_dl_path = st.text_input("Darklabel 執行檔路徑", current_dl_path)
        
        # 提交按鈕
        submitted = st.form_submit_button("💾 儲存設定")
        
        if submitted:
            # 更新字典內容
            config['detection_params']['frame_interval'] = new_interval
            config['detection_params']['confidence'] = float(new_conf) # 確保寫入數字
            config['detection_params']['model'] = new_model
            config['tools']['darklabel_path'] = new_dl_path
            
            # 存入 yaml
            save_config(config)
            st.success("✅ 設定已成功儲存！正在套用...")
            
            # 給使用者看 1 秒鐘的成功訊息，然後強制重整畫面
            import time
            time.sleep(1)
            st.rerun()

# ==========================================
# 頁面 3: 後處理與 Darklabel
# ==========================================
elif page == "3. 後處理與 Darklabel":
    st.header("🛠️ Mod 標籤提取與精修")
    st.write("針對狀態為 Completed 的資料夾進行處理。")
    
    # 讓使用者選擇要處理哪一個已完成的資料夾 (從 output/ 抓取)
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    completed_folders = [f for f in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, f))]
    
    if not completed_folders:
        st.warning("目前 `output/` 資料夾內沒有已完成的專案。")
    else:
        selected_folder = st.selectbox("選擇要處理的資料夾：", completed_folders)
        target_folder_path = os.path.join(output_dir, selected_folder)
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("✂️ 提取 Mod (4) 影像並清除標籤", width="stretch"):
                extracted_path = post_process.extract_mod_frames(target_folder_path)
                if extracted_path:
                    st.success(f"✅ 提取成功！已同步清除提取結果中的 Mod(4) 標籤。\n輸出路徑：\n`{extracted_path}`")
                else:
                    st.error("❌ 提取失敗或找不到 labels 資料夾。")
                    
        with col2:
            if st.button("🖌️ 在此資料夾啟動 Darklabel", use_container_width=True, type="primary"):
                # 接收 post_process 回傳的訊息字串
                result_msg = post_process.launch_darklabel(target_folder_path)
                
                # 直接在網頁上印出結果！如果是 ❌ 開頭就用 error，否則用 success
                if result_msg.startswith("❌"):
                    st.error(result_msg)
                else:
                    st.success(result_msg)
                    # 💡 溫馨提示
                    st.info("💡 提示：請在彈出的 Darklabel 視窗中，按下「Ctrl + O」(或點選 Open) 然後直接按「Enter」即可載入！")
