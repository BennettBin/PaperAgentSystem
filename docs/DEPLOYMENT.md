# 部署说明

## 本地 Compose

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

默认启动 `web`、`api`、`worker`、`postgres`、`redis`、`minio`、
`model-router` 和 `observability`。1.7B/4B 服务是可选 Profile：

```bash
docker compose --profile models up --build -d
```

所有服务都定义了健康检查。API readiness 位于 `/health/ready`。未挂载真实模型权重时，
系统仍可使用 development Fake Profile；模型路由对真实推理请求返回 HTTP 503 和
`model_not_available`，不会伪装为成功。

## 数据与停止

PostgreSQL、Redis 和 MinIO 使用命名卷。普通停止不会删除数据：

```bash
docker compose down
```

只有明确需要清空本地数据时才使用 `docker compose down -v`。
