"""Let JARVIS control the embedded God's Eye View with its own model tools."""
import json


_ACTIONS = {
    "fly_to_location": ("query", "location_id", "latitude", "longitude", "view_mode", "range_m", "wait_for_arrival"),
    "select_nearest_aircraft": ("layer_id", "location_id", "location_query", "latitude", "longitude"),
    "adjust_camera_zoom": ("direction", "amount"),
    "zoom_to_globe": (),
    "set_layer_visibility": ("layer_id", "enabled"),
    "show_data_layers_menu": ("layer_id",),
    "set_panel_open": ("panel_id", "open"),
    "set_context_mode": ("mode",),
    "control_cockpit": ("cockpit_action", "target_layer", "aircraft_class"),
    "set_visual_style": ("style",),
    "set_map_stack": ("stack",),
    "get_entity_context": ("scope", "layer_id", "limit"),
    "get_current_view_state": (),
}

_CAMEL_CASE = {
    "location_id": "locationId",
    "location_query": "locationQuery",
    "view_mode": "viewMode",
    "range_m": "rangeM",
    "wait_for_arrival": "waitForArrival",
    "layer_id": "layerId",
    "panel_id": "panelId",
    "cockpit_action": "action",
    "target_layer": "targetLayer",
    "aircraft_class": "aircraftClass",
}

PLUGIN = {
    "name": "control_gods_eye_view",
    "description": (
        "Use this tool whenever the user asks JARVIS to move, navigate, zoom, "
        "inspect, or control the God's Eye View map. JARVIS controls the embedded "
        "viewer directly; this does not need the GEV OpenAI microphone or an "
        "OpenAI API key. Use fly_to_location for places, adjust_camera_zoom for "
        "relative zoom, set_layer_visibility for map layers, and get_current_view_state "
        "or get_entity_context to answer questions about the displayed map. "
        "Spanish examples: 'lleva el mapa a Tokio', 'acerca la cámara', "
        "'muestra los vuelos', '¿qué hay en el mapa?'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "map_action": {
                "type": "STRING",
                "enum": list(_ACTIONS),
                "description": "The God's Eye View action that best matches the request.",
            },
            "query": {"type": "STRING", "description": "Place, city, or landmark to fly to."},
            "location_id": {
                "type": "STRING",
                "enum": ["austin", "sf", "nyc", "tokyo", "london", "paris", "dubai", "dc"],
            },
            "location_query": {"type": "STRING", "description": "Destination for nearest-aircraft selection."},
            "latitude": {"type": "NUMBER", "minimum": -90, "maximum": 90},
            "longitude": {"type": "NUMBER", "minimum": -180, "maximum": 180},
            "view_mode": {"type": "STRING", "enum": ["close", "overview"]},
            "range_m": {"type": "NUMBER", "minimum": 100, "maximum": 20000000},
            "wait_for_arrival": {"type": "BOOLEAN"},
            "direction": {"type": "STRING", "enum": ["in", "out"]},
            "amount": {"type": "STRING", "enum": ["little", "medium", "lot"]},
            "layer_id": {
                "type": "STRING",
                "enum": [
                    "flights", "military", "earthquakes", "satellites",
                    "rocket-launches", "traffic", "cctv", "radio", "bikeshare",
                    "ais-live-vessels", "local-datacenters", "local-dams",
                    "telegeography-submarine-cables", "local-firms", "alpr-cameras",
                ],
            },
            "enabled": {"type": "BOOLEAN"},
            "panel_id": {
                "type": "STRING",
                "enum": [
                    "data-panel", "location-bar", "control-panel", "cctv-panel",
                    "radio-panel", "scene-panel", "pp-toggles", "global-context-panel",
                ],
            },
            "open": {"type": "BOOLEAN"},
            "mode": {"type": "STRING", "enum": ["off", "contacts", "flights", "space-missions", "missions"]},
            "cockpit_action": {"type": "STRING", "enum": ["enter", "exit", "previous", "next", "prev", "status"]},
            "target_layer": {"type": "STRING", "enum": ["flights", "military", "ais-live-vessels", "military-installations"]},
            "aircraft_class": {"type": "STRING"},
            "style": {"type": "STRING", "enum": ["normal", "retro", "surveillance", "thermal", "anime", "noir", "snow"]},
            "stack": {"type": "STRING"},
            "scope": {"type": "STRING", "enum": ["auto", "selected", "in_view"]},
            "limit": {"type": "NUMBER", "minimum": 1, "maximum": 12},
        },
        "required": ["map_action"],
    },
    "behavior": "BLOCKING",
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("map_action") or "").strip()
    accepted_arguments = _ACTIONS.get(action)
    if accepted_arguments is None:
        return f"Acción de God's Eye View no admitida: {action or 'vacía'}."
    if player is None:
        return "No hay una interfaz de Jarvis disponible para controlar God's Eye View."

    plugin_runner = getattr(player, "run_plugin", None)
    if not callable(plugin_runner):
        return "El lanzador de God's Eye View no está conectado a Jarvis."
    try:
        opened = plugin_runner(
            "open_gods_eye_view", {}, player=player, session_memory=session_memory
        )
    except Exception as exc:
        return f"No pude abrir God's Eye View: {exc}"
    if not opened or "failed" in str(opened).lower() or "error" in str(opened).lower():
        return f"No pude preparar God's Eye View: {opened or 'sin respuesta'}"

    dispatch = getattr(player, "run_gods_eye_action", None)
    if not callable(dispatch):
        return "Jarvis no tiene conectado el control directo de God's Eye View."

    arguments = {}
    for key in accepted_arguments:
        value = parameters.get(key)
        if value is not None:
            arguments[_CAMEL_CASE.get(key, key)] = value
    try:
        response = dispatch(action, arguments)
    except Exception as exc:
        return f"Falló la comunicación con God's Eye View: {exc}"
    if not isinstance(response, dict) or response.get("ok") is not True:
        detail = response.get("error", "resultado inesperado") if isinstance(response, dict) else response
        return f"God's Eye View no pudo completar {action}: {detail}"

    result = response.get("result")
    if isinstance(result, dict) and result.get("ok") is False:
        detail = result.get("error") or result.get("stage") or "acción rechazada"
        return f"God's Eye View no pudo completar {action}: {detail}"
    try:
        summary = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        summary = str(result)
    return f"God's Eye View ejecutó {action}: {summary[:2400]}"