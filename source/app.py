import os
import sqlite3
import threading
import time
from datetime import datetime

import pandas as pd
import streamlit as st
import yaml

from modules import agent_skill, db_manager, file_parser, playwright_bot, post_process


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

def write_system_log(message):
    log_path = os.path.join(os.path.dirname(__file__), "system.log")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


st.set_page_config(page_title="影片偵測自動化中控台", layout="wide")

st.sidebar.title("系統控制面板")
page = st.sidebar.radio(
    "功能導覽",
    ["1. 任務總覽與自動化", "2. 匯入資料與設定", "3. 後處理與 Darklabel", "4. Agent Skill 上傳與改名"],
)


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
            lock_path = os.path.join(os.path.dirname(__file__), "automation.lock")
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
    completed_folders = [f for f in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, f))]

    sort_mode = st.selectbox(
        "資料夾排序方式",
        ["建立時間（新到舊）", "建立時間（舊到新）", "名稱（A-Z）", "名稱（Z-A）"],
        index=0,
    )
    if sort_mode == "建立時間（新到舊）":
        completed_folders = sorted(
            completed_folders,
            key=lambda f: os.path.getctime(os.path.join(output_dir, f)),
            reverse=True,
        )
    elif sort_mode == "建立時間（舊到新）":
        completed_folders = sorted(
            completed_folders,
            key=lambda f: os.path.getctime(os.path.join(output_dir, f)),
        )
    elif sort_mode == "名稱（Z-A）":
        completed_folders = sorted(completed_folders, reverse=True)
    else:
        completed_folders = sorted(completed_folders)

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




elif page == "4. Agent Skill 上傳與改名":
    st.header("Agent Skill 上傳與改名")
    st.caption("貼上目標路徑後，會抓該路徑下所有資料夾，各自壓縮成 zip 再上傳。")

    config = load_config()
    config.setdefault("tools", {})
    root_paths_input = st.text_area(
        "目標資料夾路徑（每行一個）",
        placeholder="例如:\nD:\\Data\\BatchA\nD:\\Data\\BatchB",
        key="agent_root_paths_input",
        height=120,
    )
    root_paths = [line.strip() for line in root_paths_input.splitlines() if line.strip()]
    target_subfolders = agent_skill.collect_subfolders_from_roots(root_paths)
    st.session_state["agent_target_subfolders"] = target_subfolders

    st.subheader("待壓縮資料夾")
    if target_subfolders:
        st.dataframe(pd.DataFrame({"資料夾路徑": target_subfolders}), width="stretch", hide_index=True)
    else:
        st.info("尚未找到可壓縮子資料夾（請確認路徑存在，且目錄下有資料夾）。")

    if "agent_rename_rows" not in st.session_state:
        st.session_state["agent_rename_rows"] = []

    if st.button("改名", use_container_width=True):
        if not target_subfolders:
            st.warning("請先提供有效路徑")
        else:
            write_system_log(f"[AgentSkill][Rename] start, folders={len(target_subfolders)}")
            rename_rows = []
            skill_applied = 0
            for p in target_subfolders:
                fallback_name = os.path.basename(p)
                suggested_name = agent_skill.suggest_folder_rename(
                    folder_path=p,
                    config=config,
                    log_callback=write_system_log,
                )
                if suggested_name != fallback_name:
                    skill_applied += 1
                rename_rows.append({"原資料夾路徑": p, "新名稱": suggested_name})
            st.session_state["agent_rename_rows"] = rename_rows
            write_system_log(f"[AgentSkill][Rename] done, folders={len(target_subfolders)}, skill_applied={skill_applied}")
            st.success(f"已產生 {len(target_subfolders)} 筆改名資料")
            st.caption(f"SKILL 建議名稱套用 {skill_applied} 筆")

    rename_rows = st.session_state.get("agent_rename_rows", [])
    st.subheader("改名結果(表格可修改)")
    if rename_rows:
        rename_df = pd.DataFrame(rename_rows)
        edited_df = st.data_editor(
            rename_df,
            width="stretch",
            hide_index=True,
            key="agent_rename_editor",
            column_config={
                "原資料夾路徑": st.column_config.TextColumn("原資料夾路徑"),
                "新名稱": st.column_config.TextColumn("新名稱"),
            },
            disabled=["原資料夾路徑"],
        )
        st.session_state["agent_rename_rows"] = edited_df.to_dict(orient="records")
    else:
        st.info("尚未產生改名資料，請先按「改名」。")

    if st.button("儲存", use_container_width=True):
        rows = st.session_state.get("agent_rename_rows", [])
        if not rows:
            st.warning("沒有可儲存的改名資料")
        else:
            rename_map = {}
            used = set()
            valid = True
            for row in rows:
                folder_path = str(row.get("原資料夾路徑", "")).strip()
                new_name = str(row.get("新名稱", "")).strip()
                if not folder_path or not new_name:
                    valid = False
                    break
                key = new_name.lower()
                if key in used:
                    valid = False
                    break
                used.add(key)
                rename_map[folder_path] = new_name
            if not valid:
                st.error("儲存失敗：新名稱不可空白且不可重複")
            else:
                st.session_state["agent_folder_rename_map"] = rename_map
                st.success(f"已儲存 {len(rename_map)} 筆改名結果")

    @st.dialog("上傳驗證")
    def upload_auth_dialog():
        st.write("請輸入帳號密碼後開始上傳")
        username = st.text_input("帳號", key="agent_upload_username")
        password = st.text_input("密碼", type="password", key="agent_upload_password")
        if st.button("確認上傳", type="primary", use_container_width=True):
            folders = st.session_state.get("agent_target_subfolders", [])
            if not folders:
                st.error("目前沒有可壓縮的子資料夾")
                return

            session_dir = agent_skill.create_session_workdir(os.path.join(os.path.dirname(__file__), "output"))
            zip_paths = agent_skill.zip_each_folder(
                folder_paths=folders,
                output_dir=os.path.join(session_dir, "zips"),
                log_callback=write_system_log,
                rename_map=st.session_state.get("agent_folder_rename_map", {}),
            )
            result = agent_skill.run_agent_skill_upload(
                file_paths=zip_paths,
                username=username,
                password=password,
                config=config,
                log_callback=write_system_log,
            )
            st.session_state["agent_last_upload_result"] = result
            st.success(
                f"上傳完成，共壓縮 {len(zip_paths)} 個資料夾，成功 {result.get('uploaded_count', result.get('uploaded_batches', 0))} 筆"
            )
            st.rerun()

    if st.button("上傳", type="primary", use_container_width=True):
        if not target_subfolders:
            st.warning("請先提供有效路徑")
        else:
            upload_auth_dialog()

    last_result = st.session_state.get("agent_last_upload_result")
    if last_result:
        st.divider()
        st.subheader("最近一次上傳結果")
        st.json(last_result)



