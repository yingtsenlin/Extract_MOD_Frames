import os
import sys
import shutil
import threading
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

def get_base_dir():
    """取得執行檔或腳本所在的實際目錄，確保封裝後路徑正確"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.resolve()
    else:
        return Path(__file__).parent.resolve()

class ExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YOLO MOD 標籤提取工具 v2.0")
        self.root.geometry("650x550")
        self.root.resizable(False, False)

        # 設定顏色與字體
        self.bg_color = "#f0f0f0"
        self.root.configure(bg=self.bg_color)
        self.font_main = ("Microsoft JhengHei", 10)
        
        # 氣體對應表
        self.gas_mapping = {
            "氯乙烯 (Vinyl Chloride) -> CGTD01": "CGTD01",
            "丁二烯 (Butadiene) -> CGTD02": "CGTD02"
        }

        # 介面配置
        self.setup_ui()

    def setup_ui(self):
        # 標題
        tk.Label(self.root, text="YOLO MOD 影格提取與自動命名工具", font=("Microsoft JhengHei", 14, "bold"), bg=self.bg_color).pack(pady=10)

        # 參數配置區
        config_frame = tk.LabelFrame(self.root, text=" 參數設定 ", font=self.font_main, bg=self.bg_color, padx=10, pady=10)
        config_frame.pack(fill="x", padx=20, pady=5)

        # 1. 氣體分類選取
        tk.Label(config_frame, text="選擇氣體分類:", font=self.font_main, bg=self.bg_color).grid(row=0, column=0, sticky="w", pady=5)
        self.gas_var = tk.StringVar()
        self.gas_combo = ttk.Combobox(config_frame, textvariable=self.gas_var, values=list(self.gas_mapping.keys()), state="readonly", width=35)
        self.gas_combo.grid(row=0, column=1, padx=10, sticky="w")
        self.gas_combo.current(0)

        # 2. 路徑輸入
        tk.Label(config_frame, text="目標資料夾路徑:", font=self.font_main, bg=self.bg_color).grid(row=1, column=0, sticky="w", pady=5)
        self.path_entry = tk.Entry(config_frame, font=self.font_main, width=33)
        self.path_entry.grid(row=1, column=1, padx=10, sticky="w")
        
        btn_browse = tk.Button(config_frame, text="瀏覽...", command=self.browse_folder, font=self.font_main)
        btn_browse.grid(row=1, column=1, sticky="e")

        # 日誌顯示區
        tk.Label(self.root, text="執行日誌:", font=self.font_main, bg=self.bg_color).pack(anchor="w", padx=20)
        self.log_area = scrolledtext.ScrolledText(self.root, height=12, font=("Consolas", 9))
        self.log_area.pack(fill="both", padx=20, pady=5)
        self.log_area.config(state="disabled")

        # 按鈕區
        btn_frame = tk.Frame(self.root, bg=self.bg_color)
        btn_frame.pack(fill="x", padx=20, pady=15)

        self.btn_start = tk.Button(btn_frame, text="開始解析與提取", bg="#4CAF50", fg="white", 
                                   font=("Microsoft JhengHei", 10, "bold"), width=20, command=self.start_process)
        self.btn_start.pack(side="left", padx=5)

        btn_exit = tk.Button(btn_frame, text="離開 (Exit)", bg="#f44336", fg="white", 
                             font=("Microsoft JhengHei", 10, "bold"), width=15, command=self.root.quit)
        btn_exit.pack(side="right", padx=5)

    def browse_folder(self):
        selected = filedialog.askdirectory()
        if selected:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, selected)

    def log(self, message):
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")

    def parse_folder_name(self, folder_name):
        """解析資料夾名稱以符合特定格式 YYMMDD_HHMMSS_Part"""
        try:
            # 提取日期 (YYYY_M_D)
            date_match = re.search(r'(\d{4})_(\d{1,2})_(\d{1,2})', folder_name)
            # 提取時間 (HH_MM_SS)
            time_match = re.search(r'(\d{2})_(\d{2})_(\d{2})', folder_name)
            
            if not date_match or not time_match:
                return None

            year, month, day = date_match.groups()
            hh, mm, ss = time_match.groups()
            
            # 格式化日期時間 YYMMDD_HHMMSS
            formatted_dt = f"{year[2:]}{int(month):02d}{int(day):02d}_{hh}{mm}{ss}"

            # 提取 Part
            part_name = "0"
            # 形式一: 找 part013 -> 取 13
            part_match1 = re.search(r'part(\d+)', folder_name)
            # 形式二: 找時間後的 _001_ 格式
            part_match2 = re.search(rf'{hh}_{mm}_{ss}_(\d{{3}})', folder_name)

            if part_match1:
                part_name = str(int(part_match1.group(1))) # 013 -> 13
            elif part_match2:
                part_name = part_match2.group(1) # 001 -> 001
            
            return f"{formatted_dt}_{part_name}"
        except Exception:
            return None

    def start_process(self):
        target_path = self.path_entry.get().strip().strip('"').strip("'")
        gas_key = self.gas_var.get()
        
        if not target_path:
            messagebox.showwarning("警告", "請先選擇或貼上目標資料夾路徑！")
            return

        gas_code = self.gas_mapping.get(gas_key, "UNKNOWN")
        
        self.btn_start.config(state="disabled")
        thread = threading.Thread(target=self.extract_logic, args=(target_path, gas_code))
        thread.daemon = True
        thread.start()

    def extract_logic(self, raw_path, gas_code):
        try:
            base_path = Path(raw_path)
            orig_name = base_path.name
            
            # 1. 命名解析
            parsed_info = self.parse_folder_name(orig_name)
            if parsed_info:
                output_name = f"{gas_code}_{parsed_info}"
            else:
                self.log(f"⚠️ 無法自動解析日期格式，將沿用部分原始名稱。")
                output_name = f"{gas_code}_{orig_name}"

            # 2. 處理 Windows 長路徑
            if os.name == 'nt' and not str(base_path).startswith('\\\\?\\'):
                base_dir = Path('\\\\?\\' + str(base_path.resolve()))
            else:
                base_dir = base_path.resolve()

            # 3. 檢查子資料夾 (依據您的程式碼使用 images/labels)
            img_dir = base_dir / 'images'
            lbl_dir = base_dir / 'labels'
            
            if not lbl_dir.exists() or not img_dir.exists():
                self.log(f"❌ 錯誤：在路徑下找不到 'images' 或 'labels' 子資料夾")
                self.btn_start.config(state="normal")
                return

            # 4. 設定輸出位置
            output_base = base_dir / output_name
            out_img_dir = output_base / 'images'
            out_lbl_dir = output_base / 'labels'

            out_img_dir.mkdir(parents=True, exist_ok=True)
            out_lbl_dir.mkdir(parents=True, exist_ok=True)

            self.log(f"📁 輸出資料夾定名為: {output_name}")
            self.log(f"🚀 開始掃描 Class ID 為 '4' 的標籤...")
            
            valid_exts = ('.jpg', '.jpeg', '.png', '.bmp')
            count = 0
            target_id = "4"

            # 5. 執行提取邏輯
            for lbl_file in lbl_dir.glob('*.txt'):
                if lbl_file.name == 'classes.txt': continue
                
                is_mod = False
                for enc in ['utf-8', 'cp950', 'ansi']:
                    try:
                        with open(lbl_file, 'r', encoding=enc) as f:
                            for line in f:
                                if line.split() and line.split()[0] == target_id:
                                    is_mod = True
                                    break
                        break
                    except Exception: continue
                
                if is_mod:
                    found = False
                    for ext in valid_exts:
                        img_path = img_dir / (lbl_file.stem + ext)
                        if img_path.exists():
                            shutil.copy2(str(img_path), str(out_img_dir / (lbl_file.stem + ext)))
                            shutil.copy2(str(lbl_file), str(out_lbl_dir / lbl_file.name))
                            self.log(f"✅ 提取成功: {lbl_file.stem}")
                            count += 1
                            found = True
                            break
            
            # 6. 複製 classes.txt
            classes_src = base_dir / 'classes.txt'
            
            if classes_src.exists():
                shutil.copy2(str(classes_src), str(output_base / 'classes.txt'))
            else:
                self.log("⚠️ 注意: 找不到 'classes.txt'。")

            self.log(f"\n✨ 完成！")
            self.log(f"📊 總計提取: {count} 個影格")
            self.log(f"📂 儲存路徑: {output_base}")
            messagebox.showinfo("完成", f"提取完成！\n資料夾：{output_name}\n影格數：{count}")

        except Exception as e:
            self.log(f"❌ 發生錯誤: {str(e)}")
        finally:
            self.btn_start.config(state="normal")

if __name__ == "__main__":
    root = tk.Tk()
    app = ExtractorApp(root)
    root.mainloop()