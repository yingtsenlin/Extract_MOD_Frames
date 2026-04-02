import os
import sys
import shutil
from pathlib import Path

def run_extraction():
    # 提示使用者輸入目標資料夾路徑
    while True:
        user_input = input("請輸入包含 'images' 與 'labels' 的目標資料夾路徑 (可直接將資料夾拖曳至此): ").strip().strip('\"\'')
        if not user_input:
            print("⚠️ 未輸入路徑，請重新輸入！\n")
            continue
        
        raw_base = Path(user_input).resolve()
        if not raw_base.is_dir():
            print(f"❌ 找不到該資料夾或路徑無效: {raw_base}，請重新輸入！\n")
            continue
        break
    
    # 處理 Windows 長路徑前綴
    path_str = str(raw_base)
    if os.name == 'nt' and not path_str.startswith('\\\\?\\'):
        base_dir = Path('\\\\?\\' + path_str)
    else:
        base_dir = raw_base

    img_dir = base_dir / 'images'
    lbl_dir = base_dir / 'labels'
    
    output_base = base_dir / 'mod_refinement'
    out_img_dir = output_base / 'images'
    out_lbl_dir = output_base / 'labels'

    print(f"🔎 執行位置: {base_dir}")

    # 檢查必要資料夾
    if not lbl_dir.exists() or not img_dir.exists():
        print("\n❌ 錯誤：找不到資料夾！")
        print(f"請確認您輸入的目錄中包含 'images' 與 'labels' 子資料夾。")
        print(f"目前輸入的路徑: {base_dir}")
        return

    # 建立輸出目錄
    out_img_dir.mkdir(parents=True, exist_ok=True)
    out_lbl_dir.mkdir(parents=True, exist_ok=True)

    valid_extensions = ('.jpg', '.jpeg', '.png', '.bmp')
    count = 0
    target_class_id = "4" 

    print(f"🚀 開始掃描標籤編號 '{target_class_id}'...")

    for lbl_file in lbl_dir.glob('*.txt'):
        if lbl_file.name == 'classes.txt':
            continue
            
        try:
            is_mod_frame = False
            lines_to_keep = []
            for encoding in ['utf-8', 'cp950', 'ansi']:
                try:
                    is_mod_frame = False
                    lines_to_keep = []
                    with open(lbl_file, 'r', encoding=encoding) as f:
                        for line in f:
                            parts = line.strip().split()
                            if parts and parts[0] == target_class_id:
                                is_mod_frame = True
                            else:
                                lines_to_keep.append(line)
                    break 
                except UnicodeDecodeError:
                    continue
            
            if is_mod_frame:
                file_stem = lbl_file.stem
                found_img = False
                for ext in valid_extensions:
                    src_img_path = img_dir / (file_stem + ext)
                    if src_img_path.exists():
                        shutil.copy2(str(src_img_path), str(out_img_dir / (file_stem + ext)))
                        with open(out_lbl_dir / lbl_file.name, 'w', encoding='utf-8') as out_f:
                            out_f.writelines(lines_to_keep)
                        print(f"✅ 提取: {file_stem}")
                        count += 1
                        found_img = True
                        break
        except Exception as e:
            print(f"❌ 錯誤 {lbl_file.name}: {e}")

    # 複製 classes.txt
    classes_src = lbl_dir / 'classes.txt'
    if classes_src.exists():
        shutil.copy2(str(classes_src), str(out_lbl_dir / 'classes.txt'))

    print("\n" + "="*40)
    print(f"✨ 完成！共提取 {count} 個影格。")
    print(f"📂 輸出位置: {output_base}")
    print("="*40)

if __name__ == "__main__":
    while True:
        run_extraction()
        choice = input("\n[輸入 Q 或 q 結束程式，直接按 Enter 繼續處理下一個資料夾]: ").strip().lower()
        if choice == 'q':
            break
        print("\n" + "="*50 + "\n")