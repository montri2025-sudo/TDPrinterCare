# -*- coding: utf-8 -*-
"""Google Routes API proxy for the field-service Demo (server-side key, read-only, fictional points).

GET /field-service/google/matrix?ids=HQ,C1,C2      -> driving km/minutes between every pair (Route Matrix)
GET /field-service/google/route?seq=HQ,C1,C3,HQ    -> legs + encoded polyline for one ordered trip (Compute Routes)

Privacy/cost rules:
- The browser sends only Demo point IDs. Coordinates come from DEMO_POINTS below (fictional customers placed
  on public roads around the service centre). No customer name, phone, address or serial is sent to Google.
- Essentials SKU only: travelMode DRIVE, routingPreference TRAFFIC_UNAWARE, <= 10 intermediates, no
  waypoint optimisation, no departure time. Results are cached in memory (traffic-unaware => stable).
- Per-user rate limit + daily outbound call cap; failures return a sanitized JSON error and the page falls
  back to the simulated estimate (clearly labelled).
- GOOGLE_ROUTES_API_KEY stays on the server (env, never in Git or the page).
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
TIMEOUT_S = 8
CACHE_TTL_S = 24 * 3600
MAX_POINTS = 9            # HQ + 8 stops -> matrix <= 81 elements
MAX_INTERMEDIATES = 10    # Essentials limit
USER_RATE_PER_MIN = 20

# Fictional Demo points. HQ is approximate for the service centre (override with FIELD_SERVICE_HQ_LATLNG).
# Customers are fictional companies placed on public roads nearby — NOT real company locations.
DEMO_POINTS = {
    "HQ": (13.8270, 100.6680),
    "C1": (13.8530, 100.7130),
    "C2": (13.8460, 100.6040),
    "C3": (13.7990, 100.7510),
    "C4": (13.7790, 100.6670),
    "C5": (13.8960, 100.6560),
}

_lock = threading.Lock()
_cache = {}          # key -> (expires, payload)
_user_calls = {}     # user_id -> [timestamps]
_day = {"date": None, "count": 0}


def settings():
    hq = os.environ.get("FIELD_SERVICE_HQ_LATLNG", "").strip()
    points = dict(DEMO_POINTS)
    if hq:
        try:
            lat, lng = (float(v) for v in hq.split(","))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                points["HQ"] = (lat, lng)
        except ValueError:
            pass
    try:
        cap = max(0, int(os.environ.get("FIELD_SERVICE_GOOGLE_DAILY_CAP", "200")))
    except ValueError:
        cap = 200
    return {
        "routes_key": os.environ.get("GOOGLE_ROUTES_API_KEY", "").strip(),
        "maps_key": os.environ.get("GOOGLE_MAPS_BROWSER_KEY", "").strip(),
        "map_id": os.environ.get("GOOGLE_MAPS_MAP_ID", "").strip() or "DEMO_MAP_ID",
        "daily_cap": cap,
        "points": points,
    }


def page_config():
    """Non-secret settings for the page. The routes key is never included."""
    s = settings()
    return {
        "routing": bool(s["routes_key"]),
        "mapsKey": s["maps_key"] or None,      # browser key: must be HTTP-referrer restricted in Google Cloud
        "mapId": s["map_id"],
        "points": {k: {"lat": v[0], "lng": v[1]} for k, v in s["points"].items()},
    }


class ApiError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code


def _respond(start_response, status, payload):
    reasons = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
               429: "Too Many Requests", 502: "Bad Gateway", 503: "Service Unavailable"}
    start_response(f"{status} {reasons.get(status, 'Error')}", [
        ("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff")])
    return [json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")]


def _ids(raw, points, allow_repeat_end=False):
    ids = [p for p in (raw or "").split(",") if p]
    if not ids or any(p not in points for p in ids):
        raise ApiError(400, "invalid_points")
    body = ids[:-1] if allow_repeat_end and len(ids) > 1 and ids[-1] == ids[0] else ids
    if len(set(body)) != len(body):
        raise ApiError(400, "invalid_points")
    return ids


def _check_limits(user_id, cap):
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    with _lock:
        stamps = [t for t in _user_calls.get(user_id, []) if now - t < 60]
        if len(stamps) >= USER_RATE_PER_MIN:
            raise ApiError(429, "rate_limited")
        if _day["date"] != today:
            _day.update(date=today, count=0)
        if _day["count"] >= cap:
            raise ApiError(429, "daily_cap_reached")
        stamps.append(now)
        _user_calls[user_id] = stamps
        _day["count"] += 1


def _cached(key):
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
    return None


def _store(key, payload):
    with _lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (time.time() + CACHE_TTL_S, payload)


def _post(url, body, key, field_mask):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": field_mask})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"[field_service_google] upstream HTTP {exc.code}")
        raise ApiError(502, "upstream_error")
    except Exception as exc:  # noqa: BLE001 — never echo upstream/key details
        print(f"[field_service_google] upstream {type(exc).__name__}")
        raise ApiError(503, "upstream_unavailable")


def _wp(point):
    return {"location": {"latLng": {"latitude": point[0], "longitude": point[1]}}}


def _seconds(value):
    return float(str(value or "0s").rstrip("s") or 0)


def matrix(ids, s, fetch=_post):
    key = ("matrix", tuple(sorted(ids)), tuple(s["points"][i] for i in sorted(ids)))
    hit = _cached(key)
    if hit:
        return dict(hit, cached=True)
    pts = [s["points"][i] for i in ids]
    body = {"origins": [{"waypoint": _wp(p)} for p in pts], "destinations": [{"waypoint": _wp(p)} for p in pts],
            "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE"}
    rows = fetch(MATRIX_URL, body, s["routes_key"], "originIndex,destinationIndex,distanceMeters,duration,condition")
    pairs = {}
    for row in rows if isinstance(rows, list) else []:
        o, d = row.get("originIndex", 0), row.get("destinationIndex", 0)
        if o == d or row.get("condition") != "ROUTE_EXISTS":
            continue
        pairs[ids[o] + ">" + ids[d]] = {"km": round(row.get("distanceMeters", 0) / 1000, 1),
                                        "minutes": round(_seconds(row.get("duration")) / 60)}
    if len(pairs) != len(ids) * (len(ids) - 1):
        raise ApiError(502, "incomplete_matrix")
    payload = {"ok": True, "source": "google_routes_matrix_traffic_unaware", "pairs": pairs}
    _store(key, payload)
    return dict(payload, cached=False)


def route(seq, s, fetch=_post):
    key = ("route", tuple(seq), tuple(s["points"][i] for i in seq))
    hit = _cached(key)
    if hit:
        return dict(hit, cached=True)
    pts = [s["points"][i] for i in seq]
    body = {"origin": _wp(pts[0]), "destination": _wp(pts[-1]),
            "intermediates": [_wp(p) for p in pts[1:-1]],
            "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE", "polylineQuality": "OVERVIEW"}
    data = fetch(ROUTES_URL, body, s["routes_key"],
                 "routes.distanceMeters,routes.duration,routes.legs.distanceMeters,routes.legs.duration,routes.polyline.encodedPolyline")
    routes = (data or {}).get("routes") or []
    if not routes:
        raise ApiError(502, "no_route")
    r = routes[0]
    legs = [{"km": round(l.get("distanceMeters", 0) / 1000, 1), "minutes": round(_seconds(l.get("duration")) / 60)} for l in r.get("legs", [])]
    if len(legs) != len(seq) - 1:
        raise ApiError(502, "incomplete_route")
    payload = {"ok": True, "source": "google_routes_traffic_unaware", "legs": legs,
               "polyline": (r.get("polyline") or {}).get("encodedPolyline", "")}
    _store(key, payload)
    return dict(payload, cached=False)


def handle(path, environ, user, start_response, allowed_roles, fetch=_post):
    from urllib.parse import parse_qs
    try:
        if not user:
            raise ApiError(401, "login_required")
        if user["role"] not in allowed_roles:
            raise ApiError(403, "forbidden")
        s = settings()
        if not s["routes_key"]:
            raise ApiError(503, "not_configured")
        qs = parse_qs(environ.get("QUERY_STRING", ""))
        if path == "/field-service/google/matrix":
            ids = _ids(qs.get("ids", [""])[0], s["points"])
            if not 2 <= len(ids) <= MAX_POINTS:
                raise ApiError(400, "invalid_points")
            if _cached(("matrix", tuple(sorted(ids)), tuple(s["points"][i] for i in sorted(ids)))) is None:
                _check_limits(user["user_id"], s["daily_cap"])
            return _respond(start_response, 200, matrix(ids, s, fetch))
        if path == "/field-service/google/route":
            seq = _ids(qs.get("seq", [""])[0], s["points"], allow_repeat_end=True)
            if not 2 <= len(seq) <= MAX_INTERMEDIATES + 2:
                raise ApiError(400, "invalid_points")
            if _cached(("route", tuple(seq), tuple(s["points"][i] for i in seq))) is None:
                _check_limits(user["user_id"], s["daily_cap"])
            return _respond(start_response, 200, route(seq, s, fetch))
        raise ApiError(404, "not_found")
    except ApiError as err:
        return _respond(start_response, err.status, {"ok": False, "error": err.code})


def reset_state():
    """Test helper."""
    with _lock:
        _cache.clear(); _user_calls.clear(); _day.update(date=None, count=0)
