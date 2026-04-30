import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml


def extract_mod_frames(completed_folder_path):
    """
    Extract frames that contain class `4` into `<folder>_mod_extracted`.
    In extracted labels, class `4` rows are removed automatically.
    """
    labels_dir = os.path.join(completed_folder_path, "labels")
    images_dir = os.path.join(completed_folder_path, "images")

    extracted_dir = completed_folder_path + "_mod_extracted"
    ext_labels = os.path.join(extracted_dir, "labels")
    ext_images = os.path.join(extracted_dir, "images")

    os.makedirs(ext_labels, exist_ok=True)
    os.makedirs(ext_images, exist_ok=True)

    if not os.path.exists(labels_dir):
        print(f"找不到 labels 資料夾: {labels_dir}")
        return None

    extracted_count = 0
    removed_mod_rows = 0
    for txt_file in os.listdir(labels_dir):
        if not txt_file.endswith(".txt"):
            continue

        txt_path = os.path.join(labels_dir, txt_file)
        has_mod = False
        kept_lines = []

        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("4 "):
                    has_mod = True
                    removed_mod_rows += 1
                    continue
                kept_lines.append(line)

        if has_mod:
            with open(os.path.join(ext_labels, txt_file), "w", encoding="utf-8") as f:
                f.writelines(kept_lines)

            base_name = os.path.splitext(txt_file)[0]
            for ext in [".jpg", ".png", ".jpeg"]:
                img_path = os.path.join(images_dir, base_name + ext)
                if os.path.exists(img_path):
                    shutil.copy(img_path, os.path.join(ext_images, base_name + ext))
                    break

            extracted_count += 1

    yaml_path = os.path.join(completed_folder_path, "data.yaml")
    if os.path.exists(yaml_path):
        shutil.copy(yaml_path, os.path.join(extracted_dir, "data.yaml"))

    print(f"提取完成，共 {extracted_count} 筆含 mod(4) 標註；已移除 {removed_mod_rows} 列 mod(4) 標籤")
    return extracted_dir


def remove_mod_labels(completed_folder_path):
    """
    Create `<folder>_mod_removed` and remove class `4` rows from all label txt files.
    Keep original folder untouched.
    """
    source_dir = Path(completed_folder_path).resolve()
    output_dir = Path(str(source_dir) + "_mod_removed")

    if not source_dir.exists():
        return None

    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(source_dir, output_dir)

    labels_dir = output_dir / "labels"
    if not labels_dir.is_dir():
        return None

    processed_files = 0
    removed_rows = 0
    for txt_path in labels_dir.glob("*.txt"):
        with open(txt_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        kept_lines = []
        for line in lines:
            if line.startswith("4 "):
                removed_rows += 1
                continue
            kept_lines.append(line)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.writelines(kept_lines)
        processed_files += 1

    return {
        "output_dir": str(output_dir),
        "processed_files": processed_files,
        "removed_rows": removed_rows,
    }


def load_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _escape_for_darklabel(path_text: str) -> str:
    """DarkLabel yml uses double quoted strings, so backslashes must be escaped."""
    return path_text.replace("\\", "\\\\")


def _resolve_darklabel_dataset_dirs(base_folder: str):
    """Resolve best images/labels dirs for DarkLabel (supports nested train/valid folders)."""
    base = Path(base_folder).resolve()

    direct_images = base / "images"
    direct_labels = base / "labels"
    if direct_images.is_dir():
        return str(direct_images), str(direct_labels if direct_labels.is_dir() else direct_images)

    for images_dir in base.rglob("images"):
        if not images_dir.is_dir():
            continue

        parent = images_dir.parent
        sibling_labels = parent / "labels"
        if sibling_labels.is_dir():
            return str(images_dir), str(sibling_labels)

    return str(base), str(base)


def _upsert_darklabel_key(content: str, key: str, value_literal: str) -> str:
    """Update an existing top-level key; append it if missing."""
    pattern = rf"(?m)^(\s*{re.escape(key)}\s*:\s*).*$"
    if re.search(pattern, content):
        return re.sub(pattern, lambda m: f"{m.group(1)}{value_literal}", content, count=1)
    return content.rstrip() + f"\n{key}: {value_literal}\n"


def launch_darklabel(folder_path, legacy_path=None):
    """Launch DarkLabel and pre-fill media/gt roots in darklabel.yml."""
    try:
        config = load_config()
        darklabel_exe_path = config["tools"]["darklabel_path"]
        darklabel_exe_path = os.path.normpath(darklabel_exe_path.strip("\"'"))

        if not os.path.exists(darklabel_exe_path):
            return f"找不到 DarkLabel 執行檔: {darklabel_exe_path}"

        darklabel_dir = os.path.dirname(darklabel_exe_path)
        yml_path = os.path.join(darklabel_dir, "darklabel.yml")

        images_dir, labels_dir = _resolve_darklabel_dataset_dirs(folder_path)
        safe_images_dir = _escape_for_darklabel(images_dir)
        safe_labels_dir = _escape_for_darklabel(labels_dir)

        msg_parts = []

        if os.path.exists(yml_path):
            with open(yml_path, "r", encoding="utf-8") as f:
                content = f.read()

            content = _upsert_darklabel_key(content, "media_path_root", f'"{safe_images_dir}"')
            content = _upsert_darklabel_key(content, "gt_path_root", f'"{safe_labels_dir}"')
            content = _upsert_darklabel_key(content, "auto_gt_load", "1")
            content = _upsert_darklabel_key(content, "gt_file_ext", '"txt"')

            # Atomic write: avoid partial writes that can break DarkLabel startup.
            with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=darklabel_dir) as tf:
                tf.write(content)
                temp_yml_path = tf.name
            os.replace(temp_yml_path, yml_path)

            msg_parts.append(f"已設定 DarkLabel 預設影像路徑: `{images_dir}`")
            msg_parts.append(f"已設定 DarkLabel 預設標註路徑: `{labels_dir}`")
        else:
            msg_parts.append("找不到 darklabel.yml，已直接啟動 DarkLabel（未寫入預設路徑）。")

        try:
            # Always launch with DarkLabel folder as CWD so it can find darklabel.yml.
            subprocess.Popen([darklabel_exe_path], cwd=darklabel_dir)
            msg_parts.append("DarkLabel 已啟動。")
            return "\n".join(msg_parts)
        except Exception as e:
            return f"DarkLabel 啟動失敗: {e}"

    except Exception as e:
        return f"啟動 DarkLabel 失敗: {e}"
