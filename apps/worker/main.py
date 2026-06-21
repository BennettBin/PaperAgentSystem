"""
Worker 应用入口

初始化和启动后台任务处理。
"""

from apps.worker.fake_queue import FakeTaskQueue
from apps.worker.handler_registry import HandlerRegistry
from apps.worker.tasks import TaskType


def create_worker():
    """创建 Worker 实例"""
    queue = FakeTaskQueue()
    registry = HandlerRegistry()

    # 注册默认处理器
    def handle_main_agent(task):
        return {"task_id": str(task.task_id), "status": "processed"}

    def handle_sub_agent(task):
        return {"task_id": str(task.task_id), "status": "processed"}

    def handle_document_parse(task):
        return {"task_id": str(task.task_id), "status": "parsed"}

    def handle_memory_summary(task):
        return {"task_id": str(task.task_id), "status": "summarized"}

    registry.register(TaskType.MAIN_AGENT, handle_main_agent)
    registry.register(TaskType.SUB_AGENT, handle_sub_agent)
    registry.register(TaskType.DOCUMENT_PARSE, handle_document_parse)
    registry.register(TaskType.MEMORY_SUMMARY, handle_memory_summary)

    # 注册处理器到队列
    for task_type, handler in registry._handlers.items():
        queue.register_handler(task_type.value, handler)

    return queue, registry
