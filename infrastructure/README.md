# Infrastructure

- `docker/compose.yaml`：全部容器编排入口。
- `docker/Dockerfile.python`、`docker/Dockerfile.web`：后端和前端镜像。
- `docker/otel-collector.yaml`：可观测性采集配置。
- `database/alembic.ini`：数据库迁移入口；迁移代码位于 `backend/infrastructure/postgres/migrations/`。
- Redis/Celery 代码位于 `backend/infrastructure/redis/`；PostgreSQL 位于 `backend/infrastructure/postgres/`；MinIO 位于 `backend/infrastructure/minio/`。