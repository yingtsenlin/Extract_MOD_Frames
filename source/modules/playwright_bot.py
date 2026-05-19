import asyncio
import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from modules import db_manager
from modules.video_segmenter import convert_to_fps_and_segment
from modules.yolo_merger import merge_yolo_folders

DISCONNECTED_SELECTOR = "header div.connection-status.disconnected"
DISCONNECTED_TEXT = "Disconnected - Check backend"


def write_log(message):
    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "system.log")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")
    print(log_line)


def load_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _default_output_dir() -> str:
    return os.path.join(str(Path.home() / "Desktop"), "output")


def _get_output_dir(config: dict) -> str:
    value = config.get("tools", {}).get("output_dir")
    if value and str(value).strip():
        return os.path.normpath(str(value).strip())
    return _default_output_dir()


def _cleanup_intermediate_dirs(task_root: str) -> None:
    for name in ["origin", "segments"]:
        path = os.path.join(task_root, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _collect_existing_segments(segments_dir: str) -> list[str]:
    if not os.path.isdir(segments_dir):
        return []
    return sorted(
        [
            os.path.join(segments_dir, name)
            for name in os.listdir(segments_dir)
            if name.lower().endswith(".mp4")
        ]
    )


def _collect_completed_segment_indices(origin_dir: str, task_prefix: str) -> set[int]:
    if not os.path.isdir(origin_dir):
        return set()

    completed = set()
    for name in os.listdir(origin_dir):
        full_path = os.path.join(origin_dir, name)
        if not os.path.isdir(full_path):
            continue
        if not name.startswith(f"{task_prefix}_"):
            continue
        try:
            idx = int(name.rsplit("_", 1)[-1])
        except ValueError:
            continue

        if os.path.isdir(os.path.join(full_path, "images")) or os.path.isdir(os.path.join(full_path, "labels")):
            completed.add(idx)
    return completed


def ensure_backend_connected(page):
    disconnected_locator = page.locator(DISCONNECTED_SELECTOR)
    if disconnected_locator.count() > 0:
        status_text = disconnected_locator.first.inner_text().strip()
        if DISCONNECTED_TEXT in status_text:
            raise RuntimeError(f"disconnected: {status_text}")


def apply_detection_options(page, config):
    detection_params = config.get("detection_params", {})

    conf_val = float(detection_params.get("confidence", 0.35))
    conf_val = max(0.05, min(0.95, conf_val))
    slider = page.locator("#confidence-slider")
    slider.wait_for(state="visible", timeout=10000)
    page.evaluate(
        """
        (val) => {
            const slider = document.getElementById('confidence-slider');
            if (!slider) return false;
            slider.value = String(val);
            slider.dispatchEvent(new Event('input', { bubbles: true }));
            slider.dispatchEvent(new Event('change', { bubbles: true }));
            slider.dispatchEvent(new Event('mouseup', { bubbles: true }));
            return true;
        }
        """,
        conf_val,
    )
    applied_conf = slider.input_value()
    write_log(f"[Detection Options] confidence 已設定為 {applied_conf}")

    frame_interval = str(detection_params.get("frame_interval", "1")).strip()
    frame_applied = page.evaluate(
        """
        (targetInterval) => {
            const normalize = (s) => (s || '').toString().trim().toLowerCase();
            const target = normalize(targetInterval);
            const labelNodes = Array.from(document.querySelectorAll('label, span, div'));
            const frameLabel = labelNodes.find(el => normalize(el.textContent).includes('frame interval'));
            if (!frameLabel) return { ok: false, reason: 'frame label not found' };
            let container = frameLabel.parentElement;
            for (let i = 0; i < 5 && container; i++) {
                const sel = container.querySelector('select');
                if (!sel) { container = container.parentElement; continue; }
                const options = Array.from(sel.options || []);
                let targetOption = options.find(o => normalize(o.value) === target)
                    || options.find(o => {
                        const txt = normalize(o.textContent);
                        return txt === target || txt.includes(target);
                    });
                if (!targetOption && target === '1') {
                    targetOption = options.find(o => normalize(o.textContent).includes('every frame'));
                }
                if (!targetOption) {
                    return { ok: false, reason: 'target option not found' };
                }
                sel.value = targetOption.value;
                sel.dispatchEvent(new Event('input', { bubbles: true }));
                sel.dispatchEvent(new Event('change', { bubbles: true }));
                return { ok: true, value: sel.value, text: (targetOption.textContent || '').trim() };
            }
            return { ok: false, reason: 'frame select not found' };
        }
        """,
        frame_interval,
    )
    if frame_applied.get("ok"):
        write_log(
            f"[Detection Options] frame_interval 已設定為 value={frame_applied.get('value')} "
            f"text='{frame_applied.get('text')}'"
        )
    else:
        write_log(f"[Detection Options] frame_interval 套用失敗: {frame_applied}")


def run_automation():
    lock_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "automation.lock")
    if os.path.exists(lock_path):
        stale_lock = False
        lock_pid = None
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if raw.isdigit():
                lock_pid = int(raw)
                try:
                    os.kill(lock_pid, 0)
                except OSError:
                    stale_lock = True
            else:
                stale_lock = True
        except Exception:
            stale_lock = True

        if stale_lock:
            try:
                os.remove(lock_path)
                write_log(f"[Lock] 偵測到過期鎖定，已自動清除: {lock_path}, pid={lock_pid}")
            except Exception as e:
                write_log(f"[Lock] 發現過期鎖定但清除失敗，改為直接覆寫: {lock_path}, error={e}")
        else:
            write_log("偵測到自動化流程已在執行中，這次請求略過")
            return

    with open(lock_path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        while True:
            task = db_manager.get_pending_task()
            if not task:
                write_log("沒有待處理任務，結束自動化流程")
                break

            task_id = task["id"]
            video_path = task["original_path"]
            target_name = task["target_name"]
            video_time = task["video_time"]
            task_prefix = f"{target_name}_{video_time}"
            config = load_config()
            db_manager.update_task_status(task_id, "Processing")
            write_log(f"開始處理任務: {target_name} (ID: {task_id})")

            try:
                output_root = _get_output_dir(config)
                os.makedirs(output_root, exist_ok=True)
                task_root = os.path.join(output_root, task_prefix)
                segments_dir = os.path.join(task_root, "segments")
                origin_dir = os.path.join(task_root, "origin")
                os.makedirs(origin_dir, exist_ok=True)

                segment_time = int(config.get("pipeline", {}).get("segment_seconds", 30))
                target_fps = int(config.get("pipeline", {}).get("target_fps", 10))
                ffmpeg_path = config.get("tools", {}).get("ffmpeg_path")

                write_log(f"[Pipeline] 輸出根目錄: {output_root}")
                write_log(f"[Pipeline] 任務工作目錄: {task_root}")

                segments = _collect_existing_segments(segments_dir)
                if not segments:
                    write_log(f"[Pipeline] 先進行分割與抽幀 (fps={target_fps}, segment={segment_time}s)")
                    segment_result = convert_to_fps_and_segment(
                        input_video=video_path,
                        output_dir=segments_dir,
                        target_fps=target_fps,
                        segment_time_sec=segment_time,
                        ffmpeg_path=ffmpeg_path,
                        keep_temp=False,
                        log_callback=write_log,
                    )
                    segments = segment_result.get("segments", [])
                    if not segments:
                        raise RuntimeError("分割完成但沒有產生任何片段。")
                else:
                    write_log(f"[Resume] 偵測到既有分割片段 {len(segments)} 個，沿用現有片段續跑。")

                headless_mode = bool(config.get("tools", {}).get("headless", False))
                completed_indices = _collect_completed_segment_indices(origin_dir, task_prefix)
                if completed_indices:
                    write_log(f"[Resume] 偵測到已完成分段 {len(completed_indices)} 個，將從下一段接續。")

                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=headless_mode, channel="msedge")
                    write_log(f"[Pipeline] Browser 啟動模式: {'headless' if headless_mode else 'headed'}")
                    target_model = config["detection_params"]["model"]

                    for seg_idx, seg_path in enumerate(segments, start=1):
                        if seg_idx in completed_indices:
                            write_log(f"[Resume] 跳過已完成分段: {seg_idx}")
                            continue

                        page = browser.new_page()
                        write_log(f"[Segment {seg_idx}] 開始處理: {seg_path}")
                        page.goto("http://10.10.91.25:3000/")
                        ensure_backend_connected(page)
                        page.locator("button:has-text('Video')").click()
                        page.wait_for_timeout(1000)
                        page.locator(f"button.model-btn:has-text('{target_model}')").click()
                        apply_detection_options(page, config)

                        video_input = page.locator('div.dropzone input[type="file"]')
                        video_input.set_input_files(seg_path)
                        page.locator(".predict-btn").click()
                        write_log(f"[Segment {seg_idx}] 已按 Predict，等待完成")

                        download_btn = page.locator("button.download-btn:has-text('Download YOLO Dataset')")
                        download_btn.wait_for(state="visible", timeout=0)
                        with page.expect_download(timeout=0) as download_info:
                            download_btn.click()
                        download = download_info.value

                        seg_output_dir = os.path.join(origin_dir, f"{task_prefix}_{seg_idx}")
                        os.makedirs(seg_output_dir, exist_ok=True)
                        temp_zip_path = os.path.join(seg_output_dir, "temp_download.zip")
                        download.save_as(temp_zip_path)
                        with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                            zip_ref.extractall(seg_output_dir)
                        os.remove(temp_zip_path)
                        write_log(f"[Segment {seg_idx}] 偵測輸出已下載到: {seg_output_dir}")
                        page.close()

                    merge_result = merge_yolo_folders(
                        base_path=task_root,
                        folder_prefix=task_prefix,
                        origin_folder_name="origin",
                        results_folder_name="results",
                        log_callback=write_log,
                    )
                    merged_dir = merge_result["output_dir"]
                    final_dir = os.path.join(output_root, f"{task_prefix}_MERGED")
                    if os.path.isdir(final_dir):
                        shutil.rmtree(final_dir, ignore_errors=True)
                    shutil.move(merged_dir, final_dir)
                    _cleanup_intermediate_dirs(task_root)
                    results_dir = os.path.join(task_root, "results")
                    if os.path.isdir(results_dir) and not os.listdir(results_dir):
                        shutil.rmtree(results_dir, ignore_errors=True)
                    if os.path.isdir(task_root) and not os.listdir(task_root):
                        os.rmdir(task_root)
                        write_log(f"[Cleanup] 已移除空白任務資料夾: {task_root}")

                    db_manager.update_task_status(task_id, "Completed")
                    write_log(f"任務完成，合併結果已輸出到: {final_dir}")
                    browser.close()

            except Exception as e:
                error_msg = str(e)
                disconnect_keywords = ["net::ERR", "Target closed", "disconnected", "closed", "Connection"]
                if any(keyword in error_msg for keyword in disconnect_keywords):
                    write_log("偵測到連線異常，觸發斷路器並中止本次自動化")
                    write_log(f"連線異常訊息: {error_msg}")
                    write_log("當前任務會回到 Pending，待連線恢復後可重試")
                    db_manager.update_task_status(task_id, "Pending")
                    break
                write_log(f"任務 [{target_name}] 發生錯誤: {error_msg}")
                db_manager.update_task_status(task_id, "Failed")

    finally:
        if os.path.exists(lock_path):
            os.remove(lock_path)
