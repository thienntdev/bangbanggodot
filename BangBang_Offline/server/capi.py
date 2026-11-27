"""Replay netzone /capi HTTP bootstrap. Combat is still TCP :49119."""
from __future__ import annotations

import json
import time
from urllib.parse import parse_qs, urlparse
from storage import capture_payload


def _read_capture(*names: str) -> bytes | None:
    for name in names:
        payload = capture_payload(name)
        if payload:
            return payload
    return None


def _json(obj: dict) -> tuple[bytes, str]:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), "application/json; charset=UTF-8"


def handle(path_qs: str) -> tuple[bytes, str] | None:
    parsed = urlparse(path_qs)
    path = parsed.path
    name = path.rsplit("/", 1)[-1].lower()
    qs = parse_qs(parsed.query)

    from character_info import http as character_http
    character_response = character_http(name, qs)
    if character_response is not None:
        return character_response

    from guild_protocol import http as guild_http
    guild_response = guild_http(name, qs)
    if guild_response is not None:
        return guild_response

    # The native ShopHttpManager uses queryUrl at the site root, not /capi.
    # Expose only the two implemented cosmetic categories at that alias.
    if not path.startswith("/capi") and not (
        path == '/goodsshopquery.php' and qs.get('gt', [''])[0] in ('3', '9')
    ):
        return None

    if name in ('goodsshopquery.php', 'cshopquery.php') and qs.get('gt', [''])[0] in ('3', '9'):
        from cosmetic_shop import shop_query
        return shop_query(qs), 'application/xml; charset=utf-8'

    if path == "/capi/normalshopquery.php":
        from normal_shop import public_catalog
        return _json(public_catalog())

    if name in ("ongamestart.php", "ongamestart"):
        return _json({"state": 1, "servertime": int(time.time()), "opentime": 0})

    if name in ("getplayerlogins.php", "svrlinelist.php"):
        return _json({"state": 1, "success": 1, "code": 0, "ret": 0, "msg": "ok", "data": [], "result": []})

    if name == "cgetopbulletininfo.php":
        return b"ok", "text/html; charset=utf-8"

    if name == "getuseraward.php":
        return _json({"state": 1, "success": 1, "code": 0, "data": [], "result": []})

    if name == "cshopquery.php":
        raw = _read_capture(
            "live_netzone.id.vn_capi_cShopQuery.php_",
            "live_netzone.id.vn_8080_capi_cShopQuery.php_",
        )
        if raw:
            return raw, "application/xml; charset=utf-8"

    if name == "ctankrentlist.php":
        raw = _read_capture(
            "live_netzone.id.vn_capi_cTankRentList.php_noCache=1",
            "live_netzone.id.vn_8080_capi_cTankRentList.php_noCache=1",
        )
        if raw:
            return raw, "application/json; charset=UTF-8"

    if name == "cleaguelist.php":
        return (
            b'<?xml version="1.0" encoding="utf-8"?><query state="1" success="1"></query>',
            "application/xml; charset=utf-8",
        )

    if name.endswith(".php") or name == "capi":
        return _json({"state": 1, "success": 1, "code": 0, "ret": 0, "msg": "ok", "data": [], "result": []})

    return None
