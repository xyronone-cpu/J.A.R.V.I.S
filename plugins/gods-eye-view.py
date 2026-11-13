"""
God's Eye View geospatial visualization plugin for Jarvis.
"""
import subprocess
import time
import urllib.request
from pathlib import Path

PLUGIN = {
    "name": "open_gods_eye_view",
    "description": (
        "Opens the God's Eye View 3D geospatial dashboard inside Jarvis by default; "
        "do not open a system browser if the embedded viewer is unavailable. "
        "Spanish requests include "
        "'abre God's Eye View', 'abre el Ojo de Dios' and 'muéstrame el mapa'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
    "behavior": "NON_BLOCKING",
}


def run(parameters: dict, **kwargs) -> str:
    """Triggered when Gemini invokes the open_gods_eye_view tool."""
    gev_url = "http://127.0.0.1:4173/"

    def wait_for_server(url: str, timeout_s: float = 15.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.5):
                    return True
            except Exception:
                time.sleep(0.5)
        return False
    
    # 1. Comprueba si el servidor ya está activo
    server_online = False
    try:
        server_online = wait_for_server(gev_url, timeout_s=1.5)
    except Exception:
        server_online = False

    # 2. Si no responde, inicia el proceso Vite en segundo plano
    if not server_online:
        try:
            gev_dir = Path(__file__).resolve().parent / "gods-eye-view"
            if (gev_dir / "package.json").exists():
                subprocess.Popen(
                    ["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--port", "4173"],
                    cwd=str(gev_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                server_online = wait_for_server(gev_url, timeout_s=20.0)
                if not server_online:
                    return "Error al iniciar God's Eye View: el servicio no respondió en http://127.0.0.1:4173/."
        except Exception as e:
            return f"Error al intentar iniciar el servidor de God's Eye View: {e}"

    player = kwargs.get("player")
    opener = getattr(player, "open_plugin_view", None)
    if callable(opener):
        try:
            if opener("God's Eye View", gev_url):
                return "God's Eye View está abierto dentro de Jarvis."
        except Exception as exc:
            return f"No se pudo abrir God's Eye View dentro de Jarvis: {exc}"
    return "El visor integrado de Jarvis no está disponible; no se abrió otro navegador."