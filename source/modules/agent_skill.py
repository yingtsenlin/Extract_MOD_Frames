import importlib
import importlib.util
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from typing import Callable


LogCallback = Callable[[str], None]


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "file"


def _emit_log(message: str, log_callback: LogCallback | None = None) -> None:
    print(message)
    if log_callback:
        log_callback(message)


def _load_name_standardization_from_skill_dir(skill_dir: str):
    script_path = os.path.join(skill_dir, "scripts", "name_standardization.py")
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"找不到命名標準化腳本: {script_path}")

    spec = importlib.util.spec_from_file_location("external_name_standardization", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"無法載入命名標準化腳本: {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "standardize_dataset_stem"):
        raise AttributeError("name_standardization.py 缺少 standardize_dataset_stem(stem) 函式")
    return module


def suggest_folder_rename(folder_path: str, config: dict, log_callback: LogCallback | None = None) -> str:
    raw_name = os.path.basename(os.path.normpath(folder_path))
    module_name = str(config.get("tools", {}).get("agent_skill_module", "")).strip()
    if not module_name:
        _emit_log(f"[AgentSkill][Rename] no skill configured, fallback: {raw_name}", log_callback)
        return raw_name

    try:
        _emit_log(f"[AgentSkill][Rename] resolving by skill: {module_name}, raw={raw_name}", log_callback)
        if os.path.isdir(module_name):
            module = _load_name_standardization_from_skill_dir(module_name)
        elif os.path.isfile(module_name):
            module = _load_module_from_file(module_name)
        else:
            module = importlib.import_module(module_name)

        # 1) Prefer explicit hook if provided by external skill.
        if hasattr(module, "suggest_folder_name"):
            suggested = str(module.suggest_folder_name(folder_path=folder_path, folder_name=raw_name, config=config)).strip()
            if suggested:
                _emit_log(f"[AgentSkill][Rename] suggest_folder_name: {raw_name} -> {suggested}", log_callback)
                return suggested

        # 2) Use skill standardizer directly on raw name.
        if hasattr(module, "standardize_dataset_stem"):
            suggested = str(module.standardize_dataset_stem(raw_name)).strip()
            if suggested:
                _emit_log(f"[AgentSkill][Rename] standardize_dataset_stem(raw): {raw_name} -> {suggested}", log_callback)
                if suggested != raw_name:
                    return suggested

                # 3) If raw output unchanged, adapt CCTV folder name to the skill's APC input format.
                adapted = _build_skill_candidate_from_cctv_name(raw_name)
                if adapted:
                    suggested2 = str(module.standardize_dataset_stem(adapted)).strip()
                    _emit_log(f"[AgentSkill][Rename] standardize_dataset_stem(adapted): {adapted} -> {suggested2}", log_callback)
                    if suggested2 and suggested2 != adapted:
                        return suggested2
                return suggested
    except Exception as exc:
        _emit_log(f"[AgentSkill][Rename] skill failed, fallback: {raw_name}, error={exc}", log_callback)

    _emit_log(f"[AgentSkill][Rename] no rename rule matched, keep: {raw_name}", log_callback)
    return raw_name


def _build_skill_candidate_from_cctv_name(raw_name: str) -> str | None:
    # Example:
    # 11-CCTV-01_2026_4_5 上午 (UTC+08_00) 10_15_20_mod_extracted
    # -> apc_11cctv01_20260405_101520
    cam_match = re.search(r"(?i)(\d{2})-cctv-(\d{2})", raw_name)
    dt_match = re.search(r"(\d{4})_(\d{1,2})_(\d{1,2})", raw_name)
    time_match = re.search(r"(\d{2})_(\d{2})_(\d{2})", raw_name)
    if not cam_match or not dt_match or not time_match:
        return None

    cam_token = f"{cam_match.group(1)}cctv{cam_match.group(2)}".lower()
    y = dt_match.group(1)
    m = dt_match.group(2).zfill(2)
    d = dt_match.group(3).zfill(2)
    hh, mm, ss = time_match.groups()
    return f"apc_{cam_token}_{y}{m}{d}_{hh}{mm}{ss}"


def build_rename_mapping(uploaded_files, prefix: str) -> dict[str, str]:
    safe_prefix = _safe_name(prefix) if prefix else "renamed"
    mapping = {}
    for idx, file in enumerate(uploaded_files, start=1):
        original = file.name
        _, ext = os.path.splitext(original)
        mapping[original] = f"{safe_prefix}_{idx:03d}{ext.lower()}"
    return mapping


def persist_uploaded_files(uploaded_files, rename_mapping: dict[str, str], work_dir: str) -> list[str]:
    os.makedirs(work_dir, exist_ok=True)
    paths = []
    for file in uploaded_files:
        original_name = file.name
        target_name = rename_mapping.get(original_name, original_name)
        target_path = os.path.join(work_dir, target_name)
        with open(target_path, "wb") as f:
            f.write(file.getbuffer())
        paths.append(target_path)
    return paths


def _chunk(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        size = len(items) or 1
    return [items[i : i + size] for i in range(0, len(items), size)]


def prepare_batch_zip_files(
    file_paths: list[str],
    work_dir: str,
    batch_size: int,
    zip_prefix: str,
    log_callback: LogCallback,
) -> list[str]:
    if not file_paths:
        return []

    safe_prefix = _safe_name(zip_prefix) if zip_prefix else "dataset_batch"
    zip_dir = os.path.join(work_dir, "zips")
    os.makedirs(zip_dir, exist_ok=True)

    zip_paths = []
    batches = _chunk(file_paths, batch_size)
    for batch_idx, batch_files in enumerate(batches, start=1):
        zip_name = f"{safe_prefix}_batch_{batch_idx:03d}.zip"
        zip_path = os.path.join(zip_dir, zip_name)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in batch_files:
                zf.write(file_path, arcname=os.path.basename(file_path))
        zip_paths.append(zip_path)
        log_callback(f"[AgentSkill] 建立批次壓縮檔: {zip_name}, 檔案數={len(batch_files)}")

    return zip_paths


def collect_subfolders_from_roots(root_paths: list[str]) -> list[str]:
    subfolders = []
    seen = set()
    for root in root_paths:
        root = os.path.normpath(root.strip())
        if not root or not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            full = os.path.join(root, name)
            if os.path.isdir(full):
                key = full.lower()
                if key not in seen:
                    seen.add(key)
                    subfolders.append(full)
    return subfolders


def zip_each_folder(
    folder_paths: list[str],
    output_dir: str,
    log_callback: LogCallback,
    rename_map: dict[str, str] | None = None,
) -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    zip_paths = []
    used_names = set()
    for idx, folder_path in enumerate(folder_paths, start=1):
        raw_name = os.path.basename(folder_path)
        if rename_map and folder_path in rename_map:
            raw_name = rename_map[folder_path]
        folder_name = _safe_name(raw_name)
        if folder_name.lower() in used_names:
            folder_name = f"{folder_name}_{idx:03d}"
        used_names.add(folder_name.lower())
        zip_name = f"{idx:03d}_{folder_name}.zip"
        zip_path = os.path.join(output_dir, zip_name)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(folder_path):
                for file_name in files:
                    src = os.path.join(root, file_name)
                    arc = os.path.relpath(src, folder_path)
                    zf.write(src, arcname=arc)
        zip_paths.append(zip_path)
        log_callback(f"[AgentSkill] 壓縮完成: {folder_path} -> {zip_name}")
    return zip_paths


def _default_upload(file_paths: list[str], username: str, password: str, output_dir: str, log_callback: LogCallback):
    if not username or not password:
        raise ValueError("預設上傳需要帳號與密碼")

    uploaded_dir = os.path.join(output_dir, "uploaded")
    os.makedirs(uploaded_dir, exist_ok=True)

    moved = 0
    for src in file_paths:
        dst = os.path.join(uploaded_dir, os.path.basename(src))
        with open(src, "rb") as sf, open(dst, "wb") as df:
            df.write(sf.read())
        moved += 1

    log_callback(f"[AgentSkill] 預設上傳完成，搬移檔案數: {moved}")
    return {"success": True, "uploaded_count": moved, "uploaded_batches": moved, "target_dir": uploaded_dir}


def run_agent_skill_upload(
    file_paths: list[str],
    username: str,
    password: str,
    config: dict,
    log_callback: LogCallback,
):
    module_name = config.get("tools", {}).get("agent_skill_module", "").strip()
    if module_name:
        if os.path.isdir(module_name):
            return _run_skill_script_upload(file_paths, username, password, config, module_name, log_callback)
        if os.path.isfile(module_name):
            module = _load_module_from_file(module_name)
        else:
            module = importlib.import_module(module_name)

        if not hasattr(module, "process_upload"):
            raise AttributeError(f"{module_name} 缺少 process_upload 函式")
        log_callback(f"[AgentSkill] 使用外部 skill 模組: {module_name}")
        return module.process_upload(
            file_paths=file_paths,
            username=username,
            password=password,
            config=config,
            log_callback=log_callback,
        )

    output_root = config.get("tools", {}).get("output_dir", os.path.expanduser("~/Desktop/output"))
    return _default_upload(file_paths, username, password, output_root, log_callback)


def create_session_workdir(base_dir: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(base_dir, f"agent_upload_{ts}")


def _load_module_from_file(module_file_path: str):
    module_path = os.path.normpath(module_file_path)
    spec = importlib.util.spec_from_file_location("external_agent_skill_module", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"無法載入模組檔案: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_skill_script_upload(
    file_paths: list[str],
    username: str,
    password: str,
    config: dict,
    skill_dir: str,
    log_callback: LogCallback,
):
    script_path = os.path.join(skill_dir, "scripts", "upload_dataset.py")
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"找不到 skill 上傳腳本: {script_path}")

    if not file_paths:
        return {"success": True, "uploaded_count": 0, "uploaded_batches": 0}

    source_dir = os.path.dirname(file_paths[0])
    base_url = config.get("tools", {}).get("agent_skill_base_url", "").strip()
    if not base_url:
        raise ValueError("缺少 tools.agent_skill_base_url，無法執行 skill 上傳")

    cmd = [
        "python",
        script_path,
        "--base-url",
        base_url,
        "--source",
        source_dir,
        "--username",
        username,
        "--password",
        password,
    ]
    if bool(config.get("tools", {}).get("headless", True)):
        cmd.append("--headless")

    log_callback(f"[AgentSkill] 執行 skill 上傳腳本: {script_path}")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"skill 上傳失敗: {proc.stderr or proc.stdout}")
    return {
        "success": True,
        "uploaded_count": len(file_paths),
        "uploaded_batches": len(file_paths),
        "script": script_path,
    }
