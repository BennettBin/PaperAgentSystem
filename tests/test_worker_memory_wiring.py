from backend.apps.worker.runtime import register_worker_handlers


class RecordingQueue:
    def __init__(self) -> None:
        self.handlers = {}

    def register_handler(self, task_type, handler) -> None:
        self.handlers[task_type] = handler


class Processor:
    async def parse(self, payload):
        return {"status": "parsed", "payload": payload}

    async def answer(self, payload):
        return {"status": "completed", "payload": payload}


class MemoryCoordinator:
    async def summarize(self, workspace_id, conversation_id):
        return {
            "status": "completed",
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
        }


def test_default_worker_registers_real_memory_summary_handler() -> None:
    queue = RecordingQueue()

    register_worker_handlers(queue, Processor(), MemoryCoordinator())

    assert set(queue.handlers) == {
        "document_parse",
        "main_agent",
        "memory_summary",
    }
    result = queue.handlers["memory_summary"](
        {
            "workspace_id": "local-workspace",
            "conversation_id": "conversation-1",
        }
    )
    assert result == {
        "status": "completed",
        "workspace_id": "local-workspace",
        "conversation_id": "conversation-1",
    }
