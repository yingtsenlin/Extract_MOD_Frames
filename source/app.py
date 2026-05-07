import os
import sqlite3
import threading
import time

import pandas as pd
import streamlit as st
import yaml

from modules import db_manager, file_parser, playwright_bot, post_process


db_manager.init_db()

CONFIG_PATH = "config.yaml"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config_data):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)


def load_tasks_to_dataframe():
    conn = sqlite3.connect(os.path.join("database", "tracker.db"))
    df = pd.read_sql_query("SELECT * FROM jobs", conn)
    conn.close()
    return df


def get_output_dir(config):
    configured = config.get("tools", {}).get("output_dir")
    if configured and str(configured).strip():
        return os.path.normpath(str(configured).strip())
    return os.path.join(os.path.expanduser("~"), "Desktop", "output")


def get_mod_output_dir(config):
    configured = config.get("tools", {}).get("mod_output_dir")
    if configured and str(configured).strip():
        return os.path.normpath(str(configured).strip())
    return os.path.join(os.path.expanduser("~"), "Desktop", "mod_output")


def load_system_log_tail(lines=20):
    log_path = os.path.join(os.path.dirname(__file__), "system.log")
    if not os.path.exists(log_path):
        return "(system.log 尚未建立)"
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        data = f.readlines()
    return "".join(data[-lines:])


st.set_page_config(page_title="影片偵測自動化中控台", layout="wide")

st.sidebar.title("系統控制面板")
page = st.sidebar.radio("功能導覽", ["1. 任務總覽與自動化", "2. 匯入資料與設定", "3. 後處理與 Darklabel"])


if page == "1. 任務總覽與自動化":
    st.header("任務狀態總覽")

    if "select_all" not in st.session_state:
        st.session_state.select_all = False

    col_ctrl1, _ = st.columns([1, 5])
    with col_ctrl1:
        if st.button("全選 / 取消全選", use_container_width=True):
            st.session_state.select_all = not st.session_state.select_all
            if "task_editor" in st.session_state:
                del st.session_state["task_editor"]
            st.rerun()

    df = load_tasks_to_dataframe()
    if not df.empty:
        df.insert(0, "選取", st.session_state.select_all)
        edited_df = st.data_editor(
            df,
            width="stretch",
            hide_index=True,
            key="task_editor",
            column_config={
                "選取": st.column_config.CheckboxColumn("選取", help="勾選要操作的任務", default=False)
            },
            disabled=df.columns.drop("選取"),
        )

        selected_ids = edited_df[edited_df["選取"]]["id"].tolist()
        col_btn1, col_btn2 = st.columns(2)

        with col_btn1:
            if st.button("刪除勾選任務"):
                if selected_ids:
                    db_manager.delete_tasks(selected_ids)
                    st.success(f"已刪除 {len(selected_ids)} 筆任務")
                    st.session_state.select_all = False
                    if "task_editor" in st.session_state:
                        del st.session_state["task_editor"]
                    st.rerun()
                else:
                    st.warning("請先勾選任務")

        with col_btn2:
            if st.button("將勾選任務設為 Pending"):
                if selected_ids:
                    db_manager.reset_tasks_to_pending(selected_ids)
                    st.success(f"已重設 {len(selected_ids)} 筆任務")
                    st.session_state.select_all = False
                    if "task_editor" in st.session_state:
                        del st.session_state["task_editor"]
                    st.rerun()
                else:
                    st.warning("請先勾選任務")
    else:
        st.info("目前沒有任務，請先到匯入頁新增。")

    st.divider()

    col_run, col_refresh, col_unlock = st.columns([2, 2, 2])
    with col_run:
        if st.button("開始自動偵測", type="primary"):
            bot_thread = threading.Thread(target=playwright_bot.run_automation)
            bot_thread.start()
            st.success("自動化已在背景啟動")

    with col_refresh:
        if st.button("刷新日誌"):
            st.rerun()

    with col_unlock:
        if st.button("強制解除系統鎖定"):
            lock_path = "automation.lock"
            if os.path.exists(lock_path):
                os.remove(lock_path)
                st.success("已解除系統鎖定")
            else:
                st.info("目前沒有鎖定")

    st.subheader("終端日誌")
    st.caption("顯示 system.log 最近 20 條")
    st.text_area("Automation Log", load_system_log_tail(20), height=500, disabled=True)


elif page == "2. 匯入資料與設定":
    st.header("匯入未偵測母資料夾")
    folder_input = st.text_input(
        "請貼上母資料夾路徑",
        placeholder=r"例如: D:\Exports\匯出 2026-04-30",
    )

    if st.button("解析並加入任務佇列"):
        if os.path.exists(folder_input):
            file_parser.parse_and_register_folder(folder_input)
            st.success("掃描完成，已加入任務")
        else:
            st.error("找不到該資料夾")

    st.divider()
    st.header("偵測系統參數設定")
    config = load_config()
    config.setdefault("tools", {})
    config.setdefault("pipeline", {})
    config.setdefault("detection_params", {})

    with st.form("config_form"):
        st.subheader("Playwright 參數")

        current_interval = str(config["detection_params"].get("frame_interval", "5"))
        interval_options = ["1", "5", "10", "30"]
        default_index = interval_options.index(current_interval) if current_interval in interval_options else 1
        new_interval = st.selectbox("Frame Interval", interval_options, index=default_index)

        current_conf = float(config["detection_params"].get("confidence", 0.65))
        new_conf = st.slider("Confidence Threshold", 0.05, 0.95, current_conf, 0.05)

        current_model = config["detection_params"].get("model", "yolov8_large")
        new_model = st.text_input("Model Selection", current_model)

        st.subheader("外部工具")
        current_dl_path = config["tools"].get("darklabel_path", "")
        new_dl_path = st.text_input("Darklabel 執行檔路徑", current_dl_path)

        current_ffmpeg_path = config["tools"].get("ffmpeg_path", "")
        new_ffmpeg_path = st.text_input("FFmpeg Executable Path", current_ffmpeg_path)

        current_output_dir = get_output_dir(config)
        new_output_dir = st.text_input("Output Folder", current_output_dir)

        current_mod_output_dir = get_mod_output_dir(config)
        new_mod_output_dir = st.text_input("Mod Extract Output Folder", current_mod_output_dir)

        new_headless = st.checkbox("無頭模式 (Headless)", value=bool(config["tools"].get("headless", False)))

        st.subheader("工作流參數")
        new_target_fps = st.number_input(
            "抽幀 FPS", min_value=1, max_value=60, value=int(config["pipeline"].get("target_fps", 10)), step=1
        )
        new_segment_seconds = st.number_input(
            "分割秒數", min_value=5, max_value=600, value=int(config["pipeline"].get("segment_seconds", 30)), step=5
        )

        submitted = st.form_submit_button("儲存設定")
        if submitted:
            config["detection_params"]["frame_interval"] = new_interval
            config["detection_params"]["confidence"] = float(new_conf)
            config["detection_params"]["model"] = new_model
            config["tools"]["darklabel_path"] = new_dl_path
            config["tools"]["ffmpeg_path"] = new_ffmpeg_path
            config["tools"]["output_dir"] = new_output_dir
            config["tools"]["mod_output_dir"] = new_mod_output_dir
            config["tools"]["headless"] = bool(new_headless)
            config["pipeline"]["target_fps"] = int(new_target_fps)
            config["pipeline"]["segment_seconds"] = int(new_segment_seconds)

            save_config(config)
            st.success("設定已儲存")
            time.sleep(0.5)
            st.rerun()


elif page == "3. 後處理與 Darklabel":
    st.header("後處理與 Darklabel")
    st.write("勾選要處理的資料夾")

    config = load_config()
    output_dir = get_output_dir(config)
    os.makedirs(output_dir, exist_ok=True)
    completed_folders = sorted(
        [f for f in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, f))]
    )

    if "post_select_all" not in st.session_state:
        st.session_state.post_select_all = False

    ctrl1, ctrl2, _ = st.columns([2, 2, 6])
    with ctrl1:
        if st.button("全選 / 全不選", use_container_width=True):
            st.session_state.post_select_all = not st.session_state.post_select_all
            if "darklabel_folder_editor" in st.session_state:
                del st.session_state["darklabel_folder_editor"]
            st.rerun()
    with ctrl2:
        if st.button("刷新日誌", use_container_width=True):
            st.rerun()

    if not completed_folders:
        st.warning("output 資料夾內沒有可用資料")
    else:
        folder_df = pd.DataFrame(
            {"選取": [st.session_state.post_select_all] * len(completed_folders), "資料夾": completed_folders}
        )
        edited_folders = st.data_editor(
            folder_df,
            width="stretch",
            hide_index=True,
            key="darklabel_folder_editor",
            column_config={"選取": st.column_config.CheckboxColumn("選取", default=False)},
            disabled=["資料夾"],
        )
        selected_folders = edited_folders[edited_folders["選取"]]["資料夾"].tolist()

        if st.button("批次提取 Mod(4) 並清除標籤", use_container_width=True):
            if not selected_folders:
                st.warning("請先勾選至少一個資料夾")
            else:
                ok_count = 0
                mod_output_dir = get_mod_output_dir(config)
                os.makedirs(mod_output_dir, exist_ok=True)
                for folder in selected_folders:
                    target_folder_path = os.path.join(output_dir, folder)
                    extracted_path = post_process.extract_mod_frames(
                        target_folder_path,
                        output_root=mod_output_dir,
                    )
                    if extracted_path:
                        ok_count += 1
                        st.success(f"{folder} 提取完成: {extracted_path}")
                    else:
                        st.error(f"{folder} 提取失敗或找不到 labels")
                st.info(f"批次完成，成功 {ok_count}/{len(selected_folders)}")

        st.info("Darklabel 啟動功能目前已暫時隱藏（程式碼仍保留）。")

    st.divider()
    st.subheader("終端日誌")
    st.caption("顯示 system.log 最近 20 條")
    st.text_area("Post-process Log", load_system_log_tail(20), height=300, disabled=True)
