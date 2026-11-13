"""
Barehands hand-tracking board plugin for Jarvis.
"""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PLUGIN = {
    "name": "open_barehands",
    "description": (
        "Opens the Barehands hand-tracking dashboard inside Jarvis by default; "
        "do not open a system browser if the embedded viewer is unavailable. "
        "Spanish requests include 'abre Barehands', "
        "'inicia el control por gestos' and 'abre el panel de manos'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
    "behavior": "NON_BLOCKING",
}


def run(parameters: dict, **kwargs) -> str:
    """Triggered when Gemini invokes the open_barehands tool."""
    bare_url = "http://127.0.0.1:8794/stage.html"

    def wait_for_server(url: str, timeout_s: float = 15.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.5):
                    return True
            except Exception:
                time.sleep(0.5)
        return False

    # 1. Verifica se o servidor do Barehands já está em execução
    server_online = False
    try:
        server_online = wait_for_server(bare_url, timeout_s=1.5)
    except Exception:
        server_online = False

    # 2. Se o servidor não responder, inicia o server.py em segundo plano
    if not server_online:
        try:
            script = Path(__file__).resolve().parent / "barehands" / "server.py"
            if script.exists():
                subprocess.Popen(
                    [sys.executable, str(script)],
                    cwd=str(script.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                server_online = wait_for_server(bare_url, timeout_s=15.0)
                if not server_online:
                    return "Falha ao iniciar o servidor Barehands: o serviço não respondeu na URL esperada."
            else:
                return "Erro: o ficheiro server.py do Barehands não foi encontrado."
        except Exception as exc:
            return f"Falha ao iniciar o servidor Barehands: {exc}"

    player = kwargs.get("player")
    opener = getattr(player, "open_plugin_view", None)
    if callable(opener):
        try:
            if opener("Barehands", bare_url):
                return "Barehands está abierto dentro de Jarvis."
        except Exception as exc:
            return f"No se pudo abrir Barehands dentro de Jarvis: {exc}"
    return "El visor integrado de Jarvis no está disponible; no se abrió otro navegador."