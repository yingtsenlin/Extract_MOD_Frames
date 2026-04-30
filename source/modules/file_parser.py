import os
import re
from modules import db_manager

def parse_and_register_folder(root_folder_path):
    """
    掃描匯出的母資料夾，找出影片並解析名稱與時間。
    假設結構: 匯出 [日期 時間] -> 媒體播放器格式 -> 我需要的名字_後綴 -> 需要拿來偵測的影片.mp4
    """
    db_manager.init_db()
    video_extensions = ('.mp4', '.avi', '.mkv', '.mov')
    
    for dirpath, dirnames, filenames in os.walk(root_folder_path):
        for file in filenames:
            if file.lower().endswith(video_extensions):
                video_path = os.path.join(dirpath, file)
                
                # 1. 取得「我需要的名字」: 從上一層資料夾名稱提取
                parent_folder_name = os.path.basename(dirpath)
                # 假設你的資料夾叫做 "A廠區_xxx"，我們切出 "_" 前面的字
                target_name = parent_folder_name.split('_')[0] 
                
                # 2. 取得「影片時間」: 從影片檔名提取
                # 這裡使用簡單的正規表達式抓取連續數字 (例如 20260430_112600)
                # 請依照你實際的檔名格式修改 Regex
                # 2. 取得「影片時間」: 抓取檔名中的日期與時間片段
                # 針對格式: 2026_4_5 上午 (UTC+08_00) 10_15_20.mkv
                time_match = re.search(r'(\d{4}_\d{1,2}_\d{1,2}).*?(\d{2}_\d{2}_\d{2})', file)
                
                if time_match:
                    # 組合起來變成乾淨的: 2026_4_5_10_15_20
                    video_time = f"{time_match.group(1)}_{time_match.group(2)}"
                else:
                    # 如果真的格式大變，至少抓檔名本體（去除附檔名）當作時間，避免程式報錯
                    video_time = os.path.splitext(file)[0]
                
                video_time = time_match.group() if time_match else "UnknownTime"
                
                # 3. 註冊到資料庫
                success = db_manager.add_task(video_path, target_name, video_time)
                if success:
                    print(f"✅ 已註冊任務: {target_name} - {video_time}")
                else:
                    print(f"⚠️ 任務已存在或忽略: {video_path}")