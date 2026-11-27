extends RefCounted

var origin: String = "http://127.0.0.1:8080"
var transport_kind: String = "websocket"
var websocket_origin: String = ""
var login_host: String = "127.0.0.1"
var login_port: int = 9000
var local_test_only: bool = false
var timeout_seconds: float = 15.0
var ping_seconds: float = 10.0


const DIRECT_WS: String = ""
const DIRECT_PAGES: Array[String] = []
var fallback_ws_origin: String = ""
var direct_seconds: float = 4.0
var direct_off: bool = false

func _init() -> void :
	login_host = str(ProjectSettings.get_setting("bangbang/native_login_host", "127.0.0.1"))
	login_port = int(ProjectSettings.get_setting("bangbang/native_login_port", 9000))
	var app: String = str(ProjectSettings.get_setting("bangbang/android_origin", origin)).trim_suffix("/")
	if not app.is_empty():
		origin = app
	pick_websocket_route()

func pick_websocket_route() -> void :
	websocket_origin = origin.replace("https://", "wss://").replace("http://", "ws://")
	fallback_ws_origin = ""
	if origin in DIRECT_PAGES:
		fallback_ws_origin = websocket_origin
		websocket_origin = DIRECT_WS


func direct_ready() -> bool:
	return not fallback_ws_origin.is_empty() and not direct_off

func endpoint(role: String, region: Dictionary = {}) -> Dictionary:
	if role not in ["login", "gate", "comm"]:
		return {}
	if transport_kind == "websocket":
		if not websocket_origin.begins_with("ws://") and not websocket_origin.begins_with("wss://"):
			return {}
		var base: String = fallback_ws_origin if direct_off and not fallback_ws_origin.is_empty() else websocket_origin
		return {"url": base + "/ws/" + role, "origin": origin}
	var host: String = login_host if role == "login" else str(region.get(role + "_realm", "127.0.0.1"))
	var port: int = login_port if role == "login" else int(region.get(role + "_port", 9001))
	if host.is_empty() or port < 1 or port > 65535:
		return {}
	if local_test_only and (host != "127.0.0.1" or port in [9000, 9001, 41843]):
		return {}
	return {"host": host, "port": port}

func server_entry() -> Dictionary:

	return {"sid": 299001, "name": "BangBang", "ip": login_host, "port": login_port, 
		"isDefault": 1, "isMaintaining": 0, "cantCreate": 0, "openDesc": ""}
