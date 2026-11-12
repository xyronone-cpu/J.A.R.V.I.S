"""Free/open-source image-to-3D generation for Barehands.

Cloud mode uses public Hugging Face Gradio Spaces (FLUX.1-schnell + TripoSR).
Local mode uses a local Diffusers preview model and the official TripoSR CLI.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import requests

PLUGIN = {
    "name": "generate_3d_object",
    "description": (
        "Generate a real GLB 3D object and summon it into Barehands using open-source models. "
        "The configured mode is Hugging "
        "Face cloud or local CUDA/PyTorch. Describe the object in 'prompt'. If "
        "the user says to use the uploaded/current image, set use_current_image=true; "
        "otherwise a neutral, centered preview image is created automatically. "
        "Spanish examples: 'crea un modelo 3D de un dragón', 'convierte esta "
        "imagen en un objeto 3D', 'haz una figura 3D de un robot y ponla en Barehands'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {
                "type": "STRING",
                "description": "Detailed description of a single 3D object, in the user's language.",
            },
            "title": {
                "type": "STRING",
                "description": "Optional short title shown in Barehands.",
            },
            "use_current_image": {
                "type": "BOOLEAN",
                "description": "Use the currently uploaded image as the 3D reference instead of generating a preview.",
            },
            "reference_image": {
                "type": "STRING",
                "description": "Optional local image file path to use as the 3D reference.",
            },
        },
        "required": ["prompt"],
    },
    "behavior": "NON_BLOCKING",
}

PLUGIN_SETTINGS = {
    "namespace": "generator_3d",
    "title": "OPEN-SOURCE 3D GENERATION",
    "fields": [
        {
            "key": "backend",
            "label": "Generation mode",
            "type": "choice",
            "options": ["cloud", "local"],
            "default": "cloud",
        },
        {
            "key": "text_to_image_space",
            "label": "Hugging Face text-to-image Space",
            "type": "text",
            "default": "black-forest-labs/FLUX.1-schnell",
        },
        {
            "key": "image_to_3d_space",
            "label": "Hugging Face image-to-3D Space",
            "type": "text",
            "default": "Jose16062007/TripoSR",
        },
        {
            "key": "hf_token",
            "label": "Optional Hugging Face token (public Spaces need none)",
            "type": "password",
            "placeholder": "Optional; only for private or gated Spaces",
        },
        {
            "key": "local_python",
            "label": "Python executable with CUDA/PyTorch and Diffusers",
            "type": "text",
            "placeholder": "Example: C:\\TripoSR\\.venv\\Scripts\\python.exe",
        },
        {
            "key": "local_triposr_repo",
            "label": "Local VAST-AI-Research/TripoSR repository path",
            "type": "text",
            "placeholder": "Folder containing run.py",
        },
        {
            "key": "local_image_model",
            "label": "Local Diffusers preview model",
            "type": "text",
            "default": "stabilityai/sdxl-turbo",
        },
    ],
}

_DEFAULT_T2I_SPACE = "black-forest-labs/FLUX.1-schnell"
_DEFAULT_I2M_SPACE = "Jose16062007/TripoSR"
_T2I_API = "/infer"
_I2M_API = "/professor"
_TASK_TIMEOUT_SECONDS = 15 * 60
_LOCAL_TIMEOUT_SECONDS = 25 * 60
_SPACE_FILE_LIMIT = 120 * 1024 * 1024
_LOCAL_FILE_LIMIT = 300 * 1024 * 1024
_OUTPUT_LOCK = threading.Lock()
_JOB_ACTIVE = False


def _base_dir() -> Path:
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _setting(key: str, default: str = "") -> str:
    from memory.config_manager import get_plugin_setting

    value = get_plugin_setting("generator_3d", key, default)
    return str(value or default).strip()


def _media_root() -> Path:
    barehands_dir = _base_dir() / "plugins" / "barehands"
    try:
        config = json.loads((barehands_dir / "barehands.json").read_text(encoding="utf-8"))
        for orb in config.get("orbs", []):
            if orb.get("kind") == "media":
                path = Path(str(orb.get("path") or "media")).expanduser()
                return (path if path.is_absolute() else barehands_dir / path).resolve()
    except (OSError, ValueError, TypeError):
        pass
    return (barehands_dir / "media").resolve()


def _slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return (re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()[:48] or "object")


def _output_path(prompt: str) -> Path:
    folder = _media_root() / "generated" / "models"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return folder / f"{stamp}_{_slug(prompt)}.glb"


def _log(player, message: str) -> None:
    writer = getattr(player, "write_log", None)
    if callable(writer):
        try:
            writer(message)
        except Exception:
            pass


def _speak(player, message: str) -> None:
    speak = getattr(player, "request_say", None)
    if callable(speak):
        try:
            speak(f"Tell the user in their language: {message}")
        except Exception:
            pass


def _neutral_preview_prompt(prompt: str) -> str:
    return (
        "Create one clean image to reconstruct a 3D object from a single view. "
        "Show exactly one complete object: " + prompt.strip() + ". "
        "Centered, large in frame with all parts visible, three-quarter front view, "
        "neutral light-gray seamless studio background, soft even studio lighting, "
        "realistic material detail, no people, no extra objects, no text, no logo, "
        "no border, no collage, no cast shadow obscuring the silhouette."
    )


def _wait_for_job(job, timeout: int, label: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if job.done():
            return job.result()
        time.sleep(0.5)
    try:
        job.cancel()
    except Exception:
        pass
    raise TimeoutError(f"La tarea de {label} superó el límite de {timeout // 60} minutos.")


def _result_file(result) -> str:
    """Extract a Gradio file output from path, FileData, or tuple-shaped results."""
    if isinstance(result, (list, tuple)):
        for item in result:
            try:
                return _result_file(item)
            except (TypeError, ValueError):
                continue
    if isinstance(result, dict):
        for key in ("path", "url", "name"):
            value = result.get(key)
            if isinstance(value, str) and value:
                return value
    for key in ("path", "url", "name"):
        value = getattr(result, key, None)
        if isinstance(value, str) and value:
            return value
    if isinstance(result, str) and result:
        return result
    raise TypeError("El Space no devolvió un archivo.")


def _copy_space_file(result, destination: Path, max_bytes: int) -> Path:
    value = _result_file(result)
    destination.parent.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        response = requests.get(value, stream=True, timeout=(10, 90))
        response.raise_for_status()
        total = 0
        with destination.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError("El archivo del Space supera el límite de descarga.")
                output.write(chunk)
    else:
        source = Path(value).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"Gradio devolvió una ruta que no existe: {value}")
        if source.stat().st_size > max_bytes:
            raise RuntimeError("El archivo del Space supera el límite de descarga.")
        shutil.copyfile(source, destination)
    return destination


def _gradio_client(space_id: str, token: str):
    try:
        from gradio_client import Client
    except ImportError as exc:
        raise RuntimeError(
            "Falta gradio_client. Instala las dependencias del proyecto con "
            "python -m pip install -r requirements.txt."
        ) from exc
    return Client(space_id, token=token or None, verbose=False)


def _cloud_preview(prompt: str, folder: Path, token: str) -> Path:
    from gradio_client import Client

    space_id = _setting("text_to_image_space", _DEFAULT_T2I_SPACE)
    client = Client(space_id, token=token or None, verbose=False)
    preview_prompt = _neutral_preview_prompt(prompt)
    job = client.submit(
        preview_prompt,
        0,
        True,
        512,
        512,
        4,
        api_name=_T2I_API,
    )
    result = _wait_for_job(job, _TASK_TIMEOUT_SECONDS, "imagen previa")
    preview_path = folder / "preview.png"
    return _copy_space_file(result, preview_path, _SPACE_FILE_LIMIT)


def _local_python() -> Path:
    configured = _setting("local_python")
    if not configured:
        raise RuntimeError(
            "Configura la ruta de Python del entorno TripoSR en Plugin Settings. "
            "Se recomienda Python 3.10 con CUDA/PyTorch."
        )
    executable = Path(configured).expanduser()
    if not executable.is_file():
        raise FileNotFoundError(f"No existe el Python local configurado: {executable}")
    return executable.resolve()


def _local_preview(prompt: str, folder: Path) -> Path:
    python = _local_python()
    model = _setting("local_image_model", "stabilityai/sdxl-turbo")
    preview_path = folder / "preview.png"
    script = (
        "import sys, torch; from diffusers import AutoPipelineForText2Image; "
        "from PIL import Image; "
        "model, prompt, output = sys.argv[1:4]; "
        "assert torch.cuda.is_available(), 'CUDA no está disponible en este entorno'; "
        "pipe = AutoPipelineForText2Image.from_pretrained(model, torch_dtype=torch.float16, variant='fp16').to('cuda'); "
        "image = pipe(prompt, width=512, height=512, num_inference_steps=4, guidance_scale=0.0).images[0]; "
        "image.save(output)"
    )
    command = [str(python), "-c", script, model, _neutral_preview_prompt(prompt), str(preview_path)]
    result = subprocess.run(
        command,
        cwd=str(_base_dir()),
        capture_output=True,
        text=True,
        timeout=_LOCAL_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()[-1600:]
        raise RuntimeError(f"Falló el modelo local de vista previa: {detail}")
    if not preview_path.is_file():
        raise RuntimeError("El modelo local terminó sin crear la imagen previa.")
    return preview_path


def _cloud_model(preview: Path, folder: Path, token: str) -> Path:
    from gradio_client import handle_file

    space_id = _setting("image_to_3d_space", _DEFAULT_I2M_SPACE)
    client = _gradio_client(space_id, token)
    job = client.submit(
        handle_file(str(preview)),
        256,
        0.85,
        api_name=_I2M_API,
    )
    result = _wait_for_job(job, _TASK_TIMEOUT_SECONDS, "reconstrucción 3D en Hugging Face")
    model_path = folder / "space-output.glb"
    return _copy_space_file(result, model_path, _SPACE_FILE_LIMIT)


def _local_model(preview: Path, folder: Path) -> Path:
    repo = Path(_setting("local_triposr_repo")).expanduser()
    if not repo.is_dir() or not (repo / "run.py").is_file():
        raise FileNotFoundError(
            "Configura la carpeta del repositorio TripoSR local (debe contener run.py)."
        )
    python = _local_python()
    cuda_check = subprocess.run(
        [str(python), "-c", "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 3)"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if cuda_check.returncode:
        raise RuntimeError(
            "El Python de TripoSR no detecta CUDA. Revisa la instalación PyTorch/CUDA "
            "o usa el modo cloud gratuito."
        )
    output_dir = folder / "triposr-output"
    command = [
        str(python), str((repo / "run.py").resolve()), str(preview.resolve()),
        "--output-dir", str(output_dir),
        "--device", "cuda:0",
        "--chunk-size", "4096",
        "--mc-resolution", "256",
        "--foreground-ratio", "0.85",
        "--model-save-format", "glb",
    ]
    result = subprocess.run(
        command,
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=_LOCAL_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()[-1600:]
        raise RuntimeError(f"Falló TripoSR local: {detail}")
    model_path = output_dir / "0" / "mesh.glb"
    if not model_path.is_file():
        raise RuntimeError("TripoSR terminó sin crear 0/mesh.glb.")
    return model_path


def _validate_glb(path: Path) -> None:
    if path.stat().st_size < 12:
        raise RuntimeError("El resultado no es un archivo GLB válido.")
    with path.open("rb") as model_file:
        header = model_file.read(12)
    if header[:4] != b"glTF":
        raise RuntimeError("El resultado no es un archivo GLB válido.")


def _stage_in_barehands(path: Path, title: str, player) -> None:
    opener = getattr(player, "run_plugin", None)
    if not callable(opener):
        raise RuntimeError("Jarvis no tiene conectado el lanzador de Barehands.")
    result = opener("open_barehands", {}, player=player, session_memory=None)
    if not result or "error" in str(result).lower():
        raise RuntimeError(f"No pude abrir Barehands: {result or 'sin respuesta'}")
    relative = path.resolve().relative_to(_media_root()).as_posix()
    response = requests.post(
        "http://127.0.0.1:8794/cmd",
        json={"a": "add_img", "src": relative, "title": title[:80]},
        timeout=(3, 8),
    )
    if response.status_code != 204:
        raise RuntimeError(f"Barehands rechazó el modelo (HTTP {response.status_code}).")


def _generate_job(prompt: str, title: str, reference_image: Path | None, player) -> None:
    global _JOB_ACTIVE
    try:
        mode = _setting("backend", "cloud").lower()
        if mode not in {"cloud", "local"}:
            raise ValueError("El modo debe ser cloud o local.")
        token = _setting("hf_token")
        with tempfile.TemporaryDirectory(prefix="jarvis_3d_") as temp:
            workdir = Path(temp)
            if reference_image:
                preview = reference_image
                _log(player, f"SYS: Usando imagen de referencia: {preview.name}.")
            elif mode == "cloud":
                _log(player, "SYS: Creando vista previa aislada con FLUX.1-schnell…")
                preview = _cloud_preview(prompt, workdir, token)
            else:
                _log(player, "SYS: Creando vista previa aislada con SDXL Turbo local…")
                preview = _local_preview(prompt, workdir)

            if mode == "cloud":
                _log(player, "SYS: Reconstruyendo el modelo con TripoSR en Hugging Face…")
                generated = _cloud_model(preview, workdir, token)
                destination = _output_path(prompt)
                shutil.copyfile(generated, destination)
            else:
                _log(player, "SYS: Ejecutando TripoSR local en CUDA…")
                generated = _local_model(preview, workdir)
                destination = _output_path(prompt)
                shutil.copyfile(generated, destination)
            _validate_glb(destination)
            if player:
                _stage_in_barehands(destination, title, player)
        message = f"Terminé el modelo 3D '{title}' y lo coloqué en Barehands: {destination.name}."
        _log(player, f"SYS: {message}")
        _speak(player, message)
    except Exception as exc:
        message = f"No pude generar el modelo 3D '{title}': {exc}"
        _log(player, f"ERR: {message}")
        _speak(player, message)
    finally:
        with _OUTPUT_LOCK:
            _JOB_ACTIVE = False


def run(parameters: dict, player=None, session_memory=None) -> str:
    prompt = str(parameters.get("prompt") or "").strip()
    if not prompt:
        return "Describe el objeto 3D que quieres crear."
    if len(prompt) > 800:
        return "La descripción puede tener como máximo 800 caracteres."

    reference = str(parameters.get("reference_image") or "").strip()
    if not reference and parameters.get("use_current_image"):
        reference = str(getattr(player, "current_file", None) or "").strip()
    reference_path = Path(reference).expanduser().resolve() if reference else None
    if reference_path and (not reference_path.is_file() or reference_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}):
        return "La imagen de referencia debe ser un archivo PNG, JPG o WebP existente."

    global _JOB_ACTIVE
    with _OUTPUT_LOCK:
        if _JOB_ACTIVE:
            return "Ya hay una generación 3D en curso; Jarvis te avisará cuando termine."
        _JOB_ACTIVE = True
    title = str(parameters.get("title") or prompt).strip()[:80]
    try:
        Thread(
            target=_generate_job,
            args=(prompt, title, reference_path, player),
            name="open-source-3d-generation",
            daemon=True,
        ).start()
    except Exception as exc:
        with _OUTPUT_LOCK:
            _JOB_ACTIVE = False
        return f"No pude iniciar la generación 3D: {exc}"
    return f"Empecé a crear '{title}' en 3D. Jarvis te avisará cuando aparezca en Barehands."
