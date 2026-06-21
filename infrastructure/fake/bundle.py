from dataclasses import dataclass
from typing import Optional

from apps.worker.fake_queue import FakeTaskQueue
from core.domain.ids import UserId
from core.domain.user import User
from infrastructure.fake.adapters import (
    FakeClaimVerifier,
    FakeDocumentParser,
    FakeEventPublisher,
    FakeModelRegistry,
    FakeObjectStore,
    FakeRetriever,
    FakeSandboxExecutor,
    FakeSkillRegistry,
    FakeToolRegistry,
)
from infrastructure.fake.control import FakeControl
from infrastructure.fake.data_repositories import FakeMemoryRepository
from infrastructure.fake.llm_clients import (
    FakeEmbeddingClient,
    FakeLLMClient,
    FakeRerankerClient,
)
from infrastructure.fake.observability import FakeTraceWriter
from infrastructure.fake.repositories import (
    FakeConversationRepository,
    FakeFileRepository,
    FakeMessageRepository,
    FakeTaskRepository,
    FakeWorkspaceRepository,
)


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[str, User] = {}

    async def save(self, user: User) -> None:
        self.users[str(user.id)] = user

    async def find_by_id(self, user_id: UserId) -> Optional[User]:
        return self.users.get(str(user_id))

    async def find_by_email(self, email: str) -> Optional[User]:
        return next((user for user in self.users.values() if user.email == email), None)


@dataclass
class FakeAdapterBundle:
    """Single deterministic composition root for every external Port in stage B."""

    control: FakeControl
    conversations: FakeConversationRepository
    messages: FakeMessageRepository
    tasks: FakeTaskRepository
    files: FakeFileRepository
    users: FakeUserRepository
    workspaces: FakeWorkspaceRepository
    memory: FakeMemoryRepository
    object_store: FakeObjectStore
    task_queue: FakeTaskQueue
    events: FakeEventPublisher
    llm: FakeLLMClient
    embeddings: FakeEmbeddingClient
    reranker: FakeRerankerClient
    parser: FakeDocumentParser
    retriever: FakeRetriever
    claim_verifier: FakeClaimVerifier
    sandbox: FakeSandboxExecutor
    tools: FakeToolRegistry
    skills: FakeSkillRegistry
    models: FakeModelRegistry
    traces: FakeTraceWriter

    @classmethod
    def create(cls, control: FakeControl | None = None) -> "FakeAdapterBundle":
        selected_control = control or FakeControl()
        return cls(
            control=selected_control,
            conversations=FakeConversationRepository(),
            messages=FakeMessageRepository(),
            tasks=FakeTaskRepository(),
            files=FakeFileRepository(),
            users=FakeUserRepository(),
            workspaces=FakeWorkspaceRepository(),
            memory=FakeMemoryRepository(),
            object_store=FakeObjectStore(),
            task_queue=FakeTaskQueue(),
            events=FakeEventPublisher(),
            llm=FakeLLMClient(),
            embeddings=FakeEmbeddingClient(),
            reranker=FakeRerankerClient(),
            parser=FakeDocumentParser(),
            retriever=FakeRetriever(),
            claim_verifier=FakeClaimVerifier(),
            sandbox=FakeSandboxExecutor(),
            tools=FakeToolRegistry(),
            skills=FakeSkillRegistry(),
            models=FakeModelRegistry(),
            traces=FakeTraceWriter(),
        )
