import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml


def load_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _default_mod_output_dir() -> str:
    return os.path.join(str(Path.home()), "Desktop", "mod_output")


def _get_mod_output_dir_from_config() -> str:
    try:
        config = load_config()
        value = config.get("tools", {}).get("mod_output_dir")
        if value and str(value).strip():
            return os.path.normpath(str(value).strip())
    except Exception:
        pass
    return _default_mod_output_dir()


def extract_mod_frames(completed_folder_path, output_root=None, log_callback=None):
    """
    Extract frames containing class '4' into a configurable output folder.
    Output folder name format: <source_folder_name>_mod_extracted
    """

    def log(msg: str):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    source_dir = Path(completed_folder_path).resolve()
    if output_root:
        root_dir = Path(output_root).expanduser().resolve()
    else:
        root_dir = Path(_get_mod_output_dir_from_config()).expanduser().resolve()
    root_dir.mkdir(parents=True, exist_ok=True)

    labels_dir = source_dir / "labels"
    images_dir = source_dir / "images"

    extracted_dir = root_dir / f"{source_dir.name}_mod_extracted"
    ext_labels = extracted_dir / "labels"
    ext_images = extracted_dir / "images"

    ext_labels.mkdir(parents=True, exist_ok=True)
    ext_images.mkdir(parents=True, exist_ok=True)

    if not labels_dir.exists():
        log(f"找不到 labels 資料夾: {labels_dir}")
        return None

    extracted_count = 0
    removed_mod_rows = 0

    for txt_file in os.listdir(labels_dir):
        if not txt_file.endswith(".txt"):
            continue

        txt_path = labels_dir / txt_file
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
            with open(ext_labels / txt_file, "w", encoding="utf-8") as f:
                f.writelines(kept_lines)

            base_name = os.path.splitext(txt_file)[0]
            for ext in [".jpg", ".png", ".jpeg"]:
                img_path = images_dir / f"{base_name}{ext}"
                if img_path.exists():
                    shutil.copy(img_path, ext_images / img_path.name)
                    break

            extracted_count += 1

    yaml_path = source_dir / "data.yaml"
    if yaml_path.exists():
        shutil.copy(yaml_path, extracted_dir / "data.yaml")

    log(f"提取完成，共 {extracted_count} 筆含 mod(4) 標註；已移除 {removed_mod_rows} 列 mod(4) 標籤")
    return str(extracted_dir)


def remove_mod_labels(completed_folder_path):
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


def _escape_for_darklabel(path_text: str) -> str:
    return path_text.replace("\\", "\\\\")


def _resolve_darklabel_dataset_dirs(base_folder: str):
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
    pattern = rf"(?m)^(\s*{re.escape(key)}\s*:\s*).*$"
    if re.search(pattern, content):
        return re.sub(pattern, lambda m: f"{m.group(1)}{value_literal}", content, count=1)
    return content.rstrip() + f"\n{key}: {value_literal}\n"


def launch_darklabel(folder_path, legacy_path=None):
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

            with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=darklabel_dir) as tf:
                tf.write(content)
                temp_yml_path = tf.name
            os.replace(temp_yml_path, yml_path)

            msg_parts.append(f"已設定 DarkLabel 預設影像路徑: `{images_dir}`")
            msg_parts.append(f"已設定 DarkLabel 預設標註路徑: `{labels_dir}`")
        else:
            msg_parts.append("找不到 darklabel.yml，已直接啟動 DarkLabel（未寫入預設路徑）。")

        try:
            subprocess.Popen([darklabel_exe_path], cwd=darklabel_dir)
            msg_parts.append("DarkLabel 已啟動。")
            return "\n".join(msg_parts)
        except Exception as e:
            return f"DarkLabel 啟動失敗: {e}"

    except Exception as e:
        return f"啟動 DarkLabel 失敗: {e}"
