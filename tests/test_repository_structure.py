from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repository_has_clear_top_level_boundaries() -> None:
    required = {
        "backend", "frontend", "infrastructure", "runtime",
        "docs", "training", "tests", "scripts",
    }
    assert required <= {path.name for path in ROOT.iterdir() if path.is_dir()}


def test_legacy_scattered_directories_are_removed() -> None:
    obsolete = {
        "academic_tasks", "agent_runtime", "apps", "conversations", "core",
        "document_processing", "memory", "models", "observability", "rag",
        "security", "skills", "subagents", "tool_runtime", "workspace",
        "agent_logs", "rag_diagnostics", "scratch", "documents", "infra",
        "packages", "retrieval", "storage", "tasks", "tmp", "verification",
        "writing",
    }
    assert not {name for name in obsolete if (ROOT / name).exists()}


def test_memory_and_infrastructure_are_easy_to_locate() -> None:
    assert (ROOT / "backend" / "memory" / "short_term.py").is_file()
    assert (ROOT / "backend" / "memory" / "long_term.py").is_file()
    assert (ROOT / "backend" / "infrastructure" / "redis").is_dir()
    assert (ROOT / "backend" / "infrastructure" / "postgres").is_dir()
    assert (ROOT / "infrastructure" / "docker" / "compose.yaml").is_file()
