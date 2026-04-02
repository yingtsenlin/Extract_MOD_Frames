import os
import sys
import shutil
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

def get_base_dir():
    """取得執行檔或腳本所在的實際目錄"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.resolve()
    else:
        return Path(__file__).parent.resolve()

class ExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YOLO MOD 標籤提取工具 v1.0")
        self.root.geometry("600x450")
        self.root.resizable(False, False)

        # 設定顏色與字體
        self.bg_color = "#f0f0f0"
        self.root.configure(bg=self.bg_color)
        self.font_main = ("Microsoft JhengHei", 10)

        # 介面配置
        self.setup_ui()

    def setup_ui(self):
        # 標題
        tk.Label(self.root, text="YOLO MOD 影格提取小工具", font=("Microsoft JhengHei", 14, "bold"), bg=self.bg_color).pack(pady=10)

        # 路徑輸入區
        path_frame = tk.Frame(self.root, bg=self.bg_color)
        path_frame.pack(fill="x", padx=20, pady=5)
        
        tk.Label(path_frame, text="目標資料夾路徑 (需包含 image 與 label):", font=self.font_main, bg=self.bg_color).pack(side="top", anchor="w")
        
        self.path_entry = tk.Entry(path_frame, font=self.font_main)
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=4, pady=5)
        
        btn_browse = tk.Button(path_frame, text="瀏覽...", command=self.browse_folder, font=self.font_main)
        btn_browse.pack(side="right", padx=5)

        # 日誌顯示區
        tk.Label(self.root, text="執行日誌:", font=self.font_main, bg=self.bg_color).pack(anchor="w", padx=20)
        self.log_area = scrolledtext.ScrolledText(self.root, height=12, font=("Consolas", 9))
        self.log_area.pack(fill="both", padx=20, pady=5)
        self.log_area.config(state="disabled")

        # 按鈕區
        btn_frame = tk.Frame(self.root, bg=self.bg_color)
        btn_frame.pack(fill="x", padx=20, pady=15)

        self.btn_start = tk.Button(btn_frame, text="開始提取 (Start)", bg="#4CAF50", fg="white", 
                                   font=("Microsoft JhengHei", 10, "bold"), width=15, command=self.start_process)
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

    def start_process(self):
        target_path = self.path_entry.get().strip().strip('"').strip("'")
        if not target_path:
            messagebox.showwarning("警告", "請先選擇或貼上目標資料夾路徑！")
            return

        self.btn_start.config(state="disabled")
        # 使用 Thread 避免 UI 卡死
        thread = threading.Thread(target=self.extract_logic, args=(target_path,))
        thread.daemon = True
        thread.start()

    def extract_logic(self, raw_path):
        try:
            base_path = Path(raw_path)
            # 處理 Windows 長路徑
            if os.name == 'nt' and not str(base_path).startswith('\\\\?\\'):
                base_dir = Path('\\\\?\\' + str(base_path.resolve()))
            else:
                base_dir = base_path.resolve()

            img_dir = base_dir / 'images'
            lbl_dir = base_dir / 'labels'
            
            if not lbl_dir.exists() or not img_dir.exists():
                self.log("❌ 錯誤：找不到 'images' 或 'labels' 子資料夾")
                self.btn_start.config(state="normal")
                return

            output_base = base_dir / 'mod_refinement'
            out_img_dir = output_base / 'images'
            out_lbl_dir = output_base / 'labels'

            out_img_dir.mkdir(parents=True, exist_ok=True)
            out_lbl_dir.mkdir(parents=True, exist_ok=True)

            self.log(f"🔎 正在掃描: {base_path.name}")
            
            valid_exts = ('.jpg', '.jpeg', '.png', '.bmp')
            count = 0
            target_id = "4"

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
                    except: continue
                
                if is_mod:
                    found = False
                    for ext in valid_exts:
                        img_path = img_dir / (lbl_file.stem + ext)
                        if img_path.exists():
                            shutil.copy2(str(img_path), str(out_img_dir / (lbl_file.stem + ext)))
                            shutil.copy2(str(lbl_file), str(out_lbl_dir / lbl_file.name))
                            self.log(f"✅ 提取: {lbl_file.stem}")
                            count += 1
                            found = True
                            break
            
            # 複製 classes.txt
            if (lbl_dir / 'classes.txt').exists():
                shutil.copy2(str(lbl_dir / 'classes.txt'), str(out_lbl_dir / 'classes.txt'))

            self.log(f"\n✨ 完成！共提取 {count} 個影格。")
            self.log(f"📂 輸出至: {output_base.name}")
            messagebox.showinfo("完成", f"成功提取 {count} 個影格！")

        except Exception as e:
            self.log(f"❌ 發生未知錯誤: {str(e)}")
        finally:
            self.btn_start.config(state="normal")

if __name__ == "__main__":
    root = tk.Tk()
    app = ExtractorApp(root)
    root.mainloop()