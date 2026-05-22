import json

from firebase_functions import https_fn

CORS_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,X-Webhook-Secret",
}


def json_response(data, status=200):
    return https_fn.Response(
        json.dumps(data, ensure_ascii=False, default=str),
        status=status,
        headers=CORS_HEADERS,
    )


def normalizar_path(req: https_fn.Request) -> str:
    path = req.path or "/"
    if path.startswith("/satie/"):
        path = path.removeprefix("/satie")
    return path.rstrip("/") or "/"
