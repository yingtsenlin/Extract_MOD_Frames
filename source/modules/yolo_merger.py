import os
import re
import shutil
from pathlib import Path
from typing import Callable, Optional


LogCallback = Optional[Callable[[str], None]]
ConfirmCallback = Optional[Callable[[list[int]], bool]]


def _log(msg: str, log_callback: LogCallback = None) -> None:
    if log_callback:
        log_callback(msg)
    else:
        print(msg)


def merge_yolo_folders(
    base_path: str,
    folder_prefix: str,
    origin_folder_name: str = "origin",
    results_folder_name: str = "results",
    copy_classes_once: bool = True,
    log_callback: LogCallback = None,
    confirm_callback: ConfirmCallback = None,
) -> dict:
    """
    合併 `origin/<prefix>_<數字>/` 下的 YOLO 資料夾至 `results/<prefix>_MERGED/`。
    """
    base_dir = Path(base_path).expanduser().resolve()
    origin_dir = base_dir / origin_folder_name

    if not origin_dir.exists():
        raise FileNotFoundError(f"找不到 origin 資料夾: {origin_dir}")

    pattern = re.compile(rf"^{re.escape(folder_prefix)}_(\d+)$")
    folders = []
    for entry in os.listdir(origin_dir):
        match = pattern.match(entry)
        if match:
            folders.append({"name": entry, "index": int(match.group(1))})

    if not folders:
        raise ValueError(f"找不到符合前綴 '{folder_prefix}' 的資料夾。")

    folders.sort(key=lambda x: x["index"])
    indices = [f["index"] for f in folders]
    missing = [i for i in range(min(indices), max(indices) + 1) if i not in indices]

    if missing:
        _log(f"⚠️ 發現資料夾編號缺漏: {missing}", log_callback)
        if confirm_callback is not None and not confirm_callback(missing):
            raise RuntimeError("使用者取消合併作業。")
    else:
        _log("✅ 資料夾編號連續，未發現缺漏。", log_callback)

    output_dir = base_dir / results_folder_name / f"{folder_prefix}_MERGED"
    output_images = output_dir / "images"
    output_labels = output_dir / "labels"
    output_images.mkdir(parents=True, exist_ok=True)
    output_labels.mkdir(parents=True, exist_ok=True)

    _log(f"🚀 開始合併到: {output_dir}", log_callback)
    copied_images = 0
    copied_labels = 0
    classes_copied = False

    for folder in folders:
        folder_name = folder["name"]
        folder_idx = folder["index"]
        src_path = origin_dir / folder_name

        if copy_classes_once and not classes_copied:
            src_classes = src_path / "classes.txt"
            if src_classes.exists():
                shutil.copy2(src_classes, output_dir / "classes.txt")
                classes_copied = True

        for sub_type in ["images", "labels"]:
            src_sub = src_path / sub_type
            if not src_sub.exists():
                continue

            for filename in os.listdir(src_sub):
                src_file = src_sub / filename
                if not src_file.is_file():
                    continue

                name, ext = os.path.splitext(filename)
                new_filename = f"{folder_idx}_{name}{ext}"
                dst_file = output_dir / sub_type / new_filename
                shutil.copy2(src_file, dst_file)
                if sub_type == "images":
                    copied_images += 1
                else:
                    copied_labels += 1

        _log(f"--- 已完成資料夾: {folder_name}", log_callback)

    _log("✨ 合併完成！", log_callback)
    return {
        "base_path": str(base_dir),
        "origin_dir": str(origin_dir),
        "output_dir": str(output_dir),
        "folder_prefix": folder_prefix,
        "folder_count": len(folders),
        "missing_indices": missing,
        "copied_images": copied_images,
        "copied_labels": copied_labels,
        "classes_copied": classes_copied,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="YOLO 分段資料夾合併工具")
    parser.add_argument("base_path", help="資料集根路徑（底下需有 origin）")
    parser.add_argument("folder_prefix", help="資料夾前綴，例如 CGTD01_260310_075343")
    parser.add_argument("--origin-name", default="origin", help="origin 資料夾名稱")
    parser.add_argument("--results-name", default="results", help="results 資料夾名稱")
    args = parser.parse_args()

    merge_yolo_folders(
        base_path=args.base_path,
        folder_prefix=args.folder_prefix,
        origin_folder_name=args.origin_name,
        results_folder_name=args.results_name,
    )
