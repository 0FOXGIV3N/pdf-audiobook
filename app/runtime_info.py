import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List

APP_VERSION = "0.10-gpu-runtime-support"


def _cmd_version(command, args):
    try:
        result = subprocess.run([command, *args], capture_output=True, text=True, timeout=4)
        text = (result.stdout or result.stderr or "").strip().splitlines()
        return text[0].strip() if text else "Installed"
    except Exception:
        return "Not installed"


def _python_package_version(package_name):
    try:
        import importlib.metadata as metadata
        return metadata.version(package_name)
    except Exception:
        return "Unknown"


def _check_import(module_name: str, package_name: str | None = None) -> str:
    try:
        __import__(module_name)
        return _python_package_version(package_name or module_name)
    except Exception:
        return "Not installed"


def _run_nvidia_smi_query(fields: str) -> List[str]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={fields}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def get_gpu_info() -> Dict[str, Any]:
    """Return best-effort GPU and CUDA diagnostics.

    This function is safe on CPU-only machines. It never raises if torch,
    CUDA, or nvidia-smi are unavailable.
    """
    info: Dict[str, Any] = {
        "torch_installed": False,
        "torch_version": "Not installed",
        "cuda_available": False,
        "cuda_version": "Unavailable",
        "device_count": 0,
        "selected_device": "cpu",
        "selected_device_name": "CPU",
        "gpus": [],
        "nvidia_smi": _cmd_version("nvidia-smi", ["--version"]),
        "kokoro_device_env": os.getenv("KOKORO_DEVICE", "auto"),
        "kokoro_gpu_device_env": os.getenv("KOKORO_GPU_DEVICE", "0"),
        "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES", "all/default"),
    }

    smi_rows = _run_nvidia_smi_query("index,name,memory.total")
    for row in smi_rows:
        parts = [p.strip() for p in row.split(",")]
        if len(parts) >= 3:
            info["gpus"].append({
                "index": parts[0],
                "name": parts[1],
                "memory_total_mb": parts[2],
            })

    try:
        import torch

        info["torch_installed"] = True
        info["torch_version"] = getattr(torch, "__version__", "Unknown")
        info["cuda_available"] = bool(torch.cuda.is_available())
        info["cuda_version"] = getattr(torch.version, "cuda", None) or "Unavailable"
        info["device_count"] = int(torch.cuda.device_count()) if info["cuda_available"] else 0

        if info["cuda_available"] and info["device_count"] > 0:
            requested = os.getenv("KOKORO_DEVICE", "auto").strip().lower()
            gpu_index = int(os.getenv("KOKORO_GPU_DEVICE", "0"))
            if requested.startswith("cuda:"):
                try:
                    gpu_index = int(requested.split(":", 1)[1])
                except Exception:
                    gpu_index = 0
            gpu_index = max(0, min(gpu_index, info["device_count"] - 1))
            info["selected_device"] = f"cuda:{gpu_index}"
            try:
                info["selected_device_name"] = torch.cuda.get_device_name(gpu_index)
            except Exception:
                info["selected_device_name"] = f"CUDA device {gpu_index}"
    except Exception:
        pass

    return info


def get_runtime_info(pdf_path=None, output_dir=None) -> Dict[str, Any]:
    try:
        import fitz
        pymupdf_version = getattr(fitz, "version", None)
        if isinstance(pymupdf_version, tuple):
            pymupdf = " / ".join(str(v) for v in pymupdf_version)
        else:
            pymupdf = str(pymupdf_version or _python_package_version("pymupdf"))
    except Exception:
        pymupdf = "Not installed"

    try:
        import kokoro  # noqa: F401
        kokoro_status = _python_package_version("kokoro")
        if kokoro_status == "Unknown":
            kokoro_status = "Installed"
    except Exception:
        kokoro_status = "Not installed"

    return {
        "app_version": APP_VERSION,
        "python": platform.python_version(),
        "platform": f"{platform.system()} ({platform.machine()})",
        "pymupdf": pymupdf,
        "pillow": _check_import("PIL", "Pillow"),
        "tesseract": _cmd_version("tesseract", ["--version"]),
        "ffmpeg": _cmd_version("ffmpeg", ["-version"]),
        "kokoro": kokoro_status,
        "gpu": get_gpu_info(),
        "pdf": Path(pdf_path).name if pdf_path else "None",
        "output": str(output_dir) if output_dir else "None",
    }


def _status_mark(value: str) -> str:
    if value in {"Not installed", "Unavailable", "Unknown"}:
        return "-"
    return "✓"


def print_startup_banner(pdf_path=None, output_dir=None):
    info = get_runtime_info(pdf_path=pdf_path, output_dir=output_dir)
    gpu = info["gpu"]

    print("\n====================================================")
    print("PDF Audiobook Generator")
    print(f"Version {info['app_version']}")
    print("====================================================")
    print("")
    print("Runtime")
    print("----------------------------------------------------")
    print(f"Python           {info['python']} ({info['platform']})")
    print(f"PyMuPDF          {_status_mark(info['pymupdf'])} {info['pymupdf']}")
    print(f"Pillow           {_status_mark(info['pillow'])} {info['pillow']}")
    print(f"Tesseract        {_status_mark(info['tesseract'])} {info['tesseract']}")
    print(f"FFmpeg           {_status_mark(info['ffmpeg'])} {info['ffmpeg']}")
    print(f"Kokoro           {_status_mark(info['kokoro'])} {info['kokoro']}")
    print(f"Torch            {'✓' if gpu['torch_installed'] else '-'} {gpu['torch_version']}")
    print(f"CUDA             {'✓ Available' if gpu['cuda_available'] else '- Not available'}")
    print(f"CUDA Version     {gpu['cuda_version']}")
    print(f"NVIDIA SMI       {gpu['nvidia_smi']}")
    print(f"GPU Count        {gpu['device_count']}")

    if gpu["gpus"]:
        for gpu_item in gpu["gpus"]:
            print(
                f"GPU {gpu_item['index']:<10} {gpu_item['name']} "
                f"({gpu_item['memory_total_mb']} MB)"
            )
    else:
        print("GPU              None detected")

    print(f"Kokoro Device    {gpu['selected_device']} ({gpu['selected_device_name']})")
    print(f"CUDA_VISIBLE     {gpu['cuda_visible_devices']}")
    print("")
    print("Input / Output")
    print("----------------------------------------------------")
    print(f"PDF              {info['pdf']}")
    print(f"Output           {info['output']}")
    print("====================================================\n")
