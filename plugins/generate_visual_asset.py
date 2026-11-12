"""Generate and stage images with Gemini for Barehands."""
from __future__ import annotations

import base64
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import requests

PLUGIN = {
    "name": "generate_visual_asset",
    "description": (
        "Generate a photo, illustration, or poster with Gemini and show it in "
        "Barehands. Use this tool only for flat images. For a manipulable 3D "
        "object use generate_3d_object instead. Spanish examples: 'genera una "
        "foto de un jaguar', 'crea una ilustración', 'haz un póster'. The image "
        "is saved locally and summoned into the Barehands stage."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {
                "type": "STRING",
                "description": "Detailed description of the image.",
            },
            "title": {
                "type": "STRING",
                "description": "Optional short name shown on the Barehands object.",
            },
            "aspect_ratio": {
                "type": "STRING",
                "enum": ["1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"],
                "description": "Optional image shape; ignored for 3D models.",
            },
            "image_size": {
                "type": "STRING",
                "enum": ["1K", "2K", "4K"],
                "description": "Optional image resolution. 1K is fastest and most economical.",
            },
        },
        "required": ["prompt"],
    },
    "behavior": "NON_BLOCKING",
}

_IMAGE_MODEL = "gemini-3.1-flash-image"


def _base_dir() -> Path:
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _media_root() -> Path:
    barehands_dir = _base_dir() / "plugins" / "barehands"
    config_path = barehands_dir / "barehands.json"
    try:
        import json

        config = json.loads(config_path.read_text(encoding="utf-8"))
        for orb in config.get("orbs", []):
            if orb.get("kind") == "media":
                configured = Path(str(orb.get("path") or "media")).expanduser()
                if not configured.is_absolute():
                    configured = barehands_dir / configured
                return configured.resolve()
    except (OSError, ValueError, TypeError):
        pass
    return (barehands_dir / "media").resolve()


def _slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()
    return (slug[:48] or "creation").rstrip("_")


def _new_output_path(prompt: str, extension: str) -> Path:
    folder = _media_root() / "generated"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return folder / f"{stamp}_{_slug(prompt)}.{extension}"


def _log(player, message: str) -> None:
    writer = getattr(player, "write_log", None)
    if callable(writer):
        try:
            writer(message)
        except Exception:
            pass


def _generate_image(prompt: str, image_size: str, aspect_ratio: str) -> bytes:
    from google import genai
    from memory.config_manager import get_gemini_key

    api_key = get_gemini_key()
    if not api_key:
        raise RuntimeError("No hay una clave Gemini configurada en Jarvis.")
    client = genai.Client(api_key=api_key)
    interaction = client.interactions.create(
        model=_IMAGE_MODEL,
        input=prompt,
        response_format={
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        },
    )
    image = getattr(interaction, "output_image", None)
    encoded = getattr(image, "data", None)
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("Gemini no devolvió una imagen. Prueba con otra descripción.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Gemini devolvió datos de imagen inválidos.") from exc
    if not data.startswith(b"\xff\xd8\xff"):
        raise RuntimeError("Gemini devolvió un archivo que no es JPEG.")
    return data


def _stage_in_barehands(path: Path, title: str, player) -> str:
    opener = getattr(player, "run_plugin", None)
    if not callable(opener):
        raise RuntimeError("Jarvis no tiene conectado el lanzador de Barehands.")
    result = opener("open_barehands", {}, player=player, session_memory=None)
    if not result or "falha" in str(result).lower() or "error" in str(result).lower():
        raise RuntimeError(f"No pude abrir Barehands: {result or 'sin respuesta'}")

    relative = path.resolve().relative_to(_media_root()).as_posix()
    response = requests.post(
        "http://127.0.0.1:8794/cmd",
        json={"a": "add_img", "src": relative, "title": title[:80]},
        timeout=(3, 8),
    )
    if response.status_code != 204:
        raise RuntimeError(f"Barehands rechazó el recurso (HTTP {response.status_code}).")
    return str(result)


def run(parameters: dict, player=None, session_memory=None) -> str:
    prompt = str(parameters.get("prompt") or "").strip()
    if not prompt:
        return "Necesito una descripción de la imagen."
    if len(prompt) > 800:
        return "La descripción puede tener como máximo 800 caracteres."

    title = str(parameters.get("title") or prompt).strip()[:80]
    aspect_ratio = str(parameters.get("aspect_ratio") or "1:1")
    if aspect_ratio not in {"1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"}:
        aspect_ratio = "1:1"
    image_size = str(parameters.get("image_size") or "1K").upper()
    if image_size not in {"1K", "2K", "4K"}:
        image_size = "1K"
    try:
        data = _generate_image(prompt, image_size, aspect_ratio)
        path = _new_output_path(prompt, "jpg")
        path.write_bytes(data)
    except Exception as exc:
        return f"No pude generar la imagen: {exc}"

    if player:
        try:
            _stage_in_barehands(path, title, player)
        except Exception as exc:
            return (
                f"Generé y guardé la imagen en {path}, pero no pude "
                f"ponerla en Barehands: {exc}"
            )
    else:
        return f"Generé la imagen '{title}' y la guardé en {path}."
    return f"Generé la imagen '{title}' y la puse en Barehands: {path.name}."
