"""Small health/degradation HTTP services used by Compose."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def deployment_status(service: str, *, model_available: bool) -> dict[str, Any]:
    if service == "model-router":
        if model_available:
            return {"service": service, "status": "ready", "model_available": True}
        return {
            "service": service,
            "status": "degraded",
            "model_available": False,
            "error": {
                "code": "model_not_available",
                "message": "No model server is ready; retry later or use the fake development profile",
                "retryable": True,
            },
        }
    if service.startswith("model-"):
        return {
            "service": service,
            "status": "ready" if model_available else "unavailable",
            "model_available": model_available,
            "error": None
            if model_available
            else {
                "code": "model_not_available",
                "message": "No model weights are mounted for this optional server",
                "retryable": True,
            },
        }
    return {"service": service, "status": "ready"}


class DeploymentHandler(BaseHTTPRequestHandler):
    service = "worker"
    model_available = False

    def do_GET(self) -> None:
        if self.path not in {"/health", "/health/live", "/health/ready"}:
            self._send(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found"}})
            return
        self._send(
            HTTPStatus.OK,
            deployment_status(self.service, model_available=self.model_available),
        )

    def do_POST(self) -> None:
        if self.service != "model-router" or not self.path.startswith("/v1/"):
            self._send(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found"}})
            return
        status = deployment_status(self.service, model_available=self.model_available)
        self._send(HTTPStatus.SERVICE_UNAVAILABLE, status)

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--model-available", action="store_true")
    args = parser.parse_args()

    handler = type(
        "ConfiguredDeploymentHandler",
        (DeploymentHandler,),
        {"service": args.service, "model_available": args.model_available},
    )
    ThreadingHTTPServer(("0.0.0.0", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
