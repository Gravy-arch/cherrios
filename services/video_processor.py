"""
Video processing service.

convert_to_y4m() is the pre-defined conversion function.
All the bot needs to do is pass the raw video bytes (or file path) to it
and receive back the path of the finished .y4m file.
"""

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Pre-defined conversion function (provided externally) ─────────────────────

def convert_to_y4m(input_path: str, output_path: str) -> str:
    """
    PRE-DEFINED FUNCTION — do not modify the signature.

    Converts the video at *input_path* to Y4M format with a specialised
    encoding pipeline and writes the result to *output_path*.

    Parameters
    ----------
    input_path  : absolute path to the source video file
    output_path : absolute path where the .y4m file should be written

    Returns
    -------
    str – the output_path on success, raises on failure.

    NOTE: Replace the body below with the real implementation when integrating.
    """
    # ------------------------------------------------------------------ #
    #  ↓↓↓  REPLACE THIS STUB WITH THE REAL ENCODING LOGIC  ↓↓↓          #
    # ------------------------------------------------------------------ #
    import subprocess  # noqa: PLC0415

    command = [
    "C:\\Users\\julia\\Downloads\\files (1)\\ffmpeg\\bin\\ffmpeg.exe",
    "-t", "10",
    "-i", input_path,
    "-vf", "scale=1280:720,fps=30",
      "-pix_fmt", "yuv420p",
    "-f", "yuv4mpegpipe",
    output_path,
]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg conversion failed:\n{result.stderr}"
        )

    return output_path
    # ------------------------------------------------------------------ #


# ── Async wrapper used by the bot ─────────────────────────────────────────────

async def process_video(input_path: str, media_dir: str) -> str:
    """
    Async wrapper around convert_to_y4m().

    Downloads nothing — expects the raw video already saved at *input_path*.
    Runs the blocking conversion in a thread-pool executor so it doesn't
    block the event loop.

    Returns the path of the finished .y4m file.
    """
    Path(media_dir).mkdir(parents=True, exist_ok=True)

    base_name = Path(input_path).stem
    output_path = str(Path(media_dir) / f"{base_name}_converted.y4m")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,                           # default ThreadPoolExecutor
        convert_to_y4m,
        input_path,
        output_path,
    )

    logger.info("Video converted → %s", output_path)
    return output_path


