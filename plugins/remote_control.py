"""Remote dashboard connectivity helper."""

import socket

from dashboard.server import PORT, _local_ip


PLUGIN = {
    "name": "remote_control",
    "description": (
        "Diagnose the JARVIS remote control connection and tell the user the correct URL. "
        "Use when the phone cannot open the QR code, the remote dashboard does not load, "
        "or the user asks how to connect the phone from another network. Do not use for ordinary computer control."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
        "required": [],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Return a short, actionable diagnosis without starting a second server."""
    try:
        ip = _local_ip()
        url = f"http://{ip}:{PORT}/login"
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        reachable = sock.connect_ex((ip, PORT)) == 0
        sock.close()

        dashboard = getattr(player, "_dashboard", None) if player else None
        public_url = dashboard.get_url() if dashboard else None
        if public_url and "trycloudflare.com" in public_url:
            result = (
                f"Public remote access is active. Open {public_url}/login from any network. "
                "The phone does not need to be on the same Wi-Fi; use the QR code from JARVIS."
            )
        elif reachable:
            result = (
                f"The remote dashboard is running. Open {url} on the phone. "
                "This local address requires the phone and PC to be on the same Wi-Fi. "
                "Install cloudflared to enable access from other networks."
            )
        else:
            result = (
                f"The remote dashboard is not listening on port {PORT}. "
                "Restart JARVIS, then open a new QR code. "
                f"The expected phone address is {url}."
            )
    except Exception as exc:
        result = f"Remote dashboard diagnosis failed: {exc}"

    if player:
        try:
            player.write_log(f"JARVIS: {result}")
        except Exception:
            pass
    return result
