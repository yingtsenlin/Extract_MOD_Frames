import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

import yaml

LogCallback = Optional[Callable[[str], None]]


def _log(msg: str, log_callback: LogCallback = None) -> None:
    if log_callback:
        log_callback(msg)
    else:
        print(msg)


def _resolve_ffmpeg(ffmpeg_path: Optional[str] = None) -> str:
    if ffmpeg_path:
        candidate = Path(ffmpeg_path).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"指定的 ffmpeg 不存在: {candidate}")
        return str(candidate)

    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        return which_ffmpeg

    raise FileNotFoundError("找不到 ffmpeg，請安裝後加入 PATH，或明確指定 ffmpeg_path。")


def _load_ffmpeg_path_from_config() -> Optional[str]:
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        tools = config.get("tools", {})
        value = tools.get("ffmpeg_path")
        return str(value).strip() if value else None
    except Exception:
        return None


def convert_to_fps_and_segment(
    input_video: str,
    output_dir: Optional[str] = None,
    target_fps: int = 10,
    segment_time_sec: int = 30,
    ffmpeg_path: Optional[str] = None,
    keep_temp: bool = False,
    log_callback: LogCallback = None,
) -> dict:
    """
    先轉指定 FPS，再用 segment 模式切割影片。
    輸出檔名格式: output_<basename>_001.mp4, output_<basename>_002.mp4...
    """
    input_path = Path(input_video).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"找不到輸入影片: {input_path}")

    if output_dir:
        out_dir = Path(output_dir).expanduser().resolve()
    else:
        out_dir = input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = _resolve_ffmpeg(ffmpeg_path or _load_ffmpeg_path_from_config())
    base_name = input_path.stem
    temp_file = out_dir / f"temp_{target_fps}fps_{base_name}.mp4"
    output_pattern = out_dir / f"output_{base_name}_%03d.mp4"

    _log(f"✓ 接收到影片: {input_path}", log_callback)
    _log(f"✓ 輸出資料夾: {out_dir}", log_callback)
    _log(f"✓ 使用 FFmpeg: {ffmpeg_bin}", log_callback)

    cmd_convert = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        f"fps={target_fps}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "copy",
        str(temp_file),
    ]
    _log("第一步：轉換 FPS...", log_callback)
    _log(" ".join(shlex.quote(x) for x in cmd_convert), log_callback)
    subprocess.run(cmd_convert, check=True)

    cmd_segment = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(temp_file),
        "-c",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        str(segment_time_sec),
        "-segment_start_number",
        "1",
        "-reset_timestamps",
        "1",
        str(output_pattern),
    ]
    _log(f"第二步：每 {segment_time_sec} 秒切割...", log_callback)
    _log(" ".join(shlex.quote(x) for x in cmd_segment), log_callback)
    subprocess.run(cmd_segment, check=True)

    if not keep_temp and temp_file.exists():
        temp_file.unlink()
        _log(f"已刪除暫存檔: {temp_file.name}", log_callback)

    segments = sorted(out_dir.glob(f"output_{base_name}_*.mp4"))
    _log(f"完成，共輸出 {len(segments)} 個片段。", log_callback)

    return {
        "input_video": str(input_path),
        "output_dir": str(out_dir),
        "target_fps": target_fps,
        "segment_time_sec": segment_time_sec,
        "temp_file": str(temp_file),
        "segment_count": len(segments),
        "segments": [str(p) for p in segments],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FFmpeg 轉 FPS + 切割影片工具")
    parser.add_argument("input_video", help="輸入影片路徑")
    parser.add_argument("--output-dir", default=None, help="輸出資料夾，預設為輸入影片同層")
    parser.add_argument("--fps", type=int, default=10, help="目標 FPS (預設: 10)")
    parser.add_argument("--segment-seconds", type=int, default=30, help="切段秒數 (預設: 30)")
    parser.add_argument("--ffmpeg-path", default=None, help="ffmpeg 執行檔路徑")
    parser.add_argument("--keep-temp", action="store_true", help="保留中間暫存影片")
    args = parser.parse_args()

    convert_to_fps_and_segment(
        input_video=args.input_video,
        output_dir=args.output_dir,
        target_fps=args.fps,
        segment_time_sec=args.segment_seconds,
        ffmpeg_path=args.ffmpeg_path,
        keep_temp=args.keep_temp,
    )
