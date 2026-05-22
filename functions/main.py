from firebase_functions import https_fn
from runtime import init_runtime

init_runtime()

from handlers import asegurados, casos, health, not_found, procesar_webhook, raiz  # noqa: E402
from http_utils import json_response, normalizar_path  # noqa: E402


@https_fn.on_request(invoker="public")
def satie(req: https_fn.Request) -> https_fn.Response:
    if req.method == "OPTIONS":
        return json_response({})

    path = normalizar_path(req)
    if req.method == "GET" and path == "/":
        return raiz()
    if req.method == "GET" and path == "/health":
        return health()
    if req.method == "GET" and path == "/asegurados":
        return asegurados()
    if req.method == "GET" and path == "/casos":
        return casos()
    if req.method == "POST" and path == "/webhook/emergencia":
        return procesar_webhook(req)

    return not_found(path)
