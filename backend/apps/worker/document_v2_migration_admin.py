"""Inspect or cancel old document-parse jobs before a V2-only deployment."""

from __future__ import annotations

import argparse
import asyncio
import json

from redis import Redis

from backend.apps.worker.document_v2_migration import LegacyDocumentTaskDrainService
from backend.infrastructure.config import InfrastructureSettings
from backend.infrastructure.postgres.database import Database
from backend.infrastructure.redis.queue import RedisTaskQueue


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "cancel-queued-legacy"))
    parser.add_argument("--confirm-intake-frozen", action="store_true")
    args = parser.parse_args()
    settings = InfrastructureSettings()
    database = Database(settings.database_url)
    service = LegacyDocumentTaskDrainService(database.session_factory)
    if args.action == "inspect":
        result = service.inspect(intake_frozen=args.confirm_intake_frozen)
    else:
        if not args.confirm_intake_frozen:
            parser.error("cancel requires --confirm-intake-frozen")
        redis = Redis.from_url(settings.redis_url)
        result = asyncio.run(
            service.cancel_queued_legacy(
                RedisTaskQueue(redis, database.session_factory),
                intake_frozen=True,
            )
        )
    print(json.dumps(result.model_dump(mode="json"), sort_keys=True))


if __name__ == "__main__":
    main()
