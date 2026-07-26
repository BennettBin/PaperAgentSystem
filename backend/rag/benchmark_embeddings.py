"""Benchmark Hash and BGE-M3 on one deterministic multilingual corpus."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import threading
import time
from dataclasses import asdict, dataclass

from backend.infrastructure.config import InfrastructureSettings
from backend.rag.embeddings import build_embedding_client, require_embedding_profile

COUNTS = (1, 32, 100, 500, 1000)
DEFAULT_BATCH_SIZES = (1, 8, 16, 32, 64)
SEEDS = (
    "本文提出一种跨语言论文检索方法，并比较稠密向量、BM25 与精确匹配。",
    "We evaluate retrieval-augmented generation on multilingual scientific papers.",
    "实验包含 BGE-M3、Transformer-7B、准确率 92.5% 和 DOI 10.1000/test。",
    "Semantic paraphrases and cross-language queries are evaluated with Recall@K.",
)


@dataclass(frozen=True)
class Result:
    provider: str
    device: str
    count: int
    batch_size: int
    model_load_ms: float
    warm: bool
    total_p50_ms: float
    total_p95_ms: float
    average_item_ms: float
    texts_per_second: float
    peak_rss_mib: float | None
    peak_gpu_mib: float | None
    slower_than_hash: float | None = None


def corpus() -> list[str]:
    return [
        f"{SEEDS[index % len(SEEDS)]} sample={index} model=BGE-M3 number={index * 17}."
        for index in range(max(COUNTS))
    ]


async def benchmark_provider(
    provider: str, device: str, batch_sizes: tuple[int, ...], repeats: int
) -> list[Result]:
    settings = InfrastructureSettings().model_copy(
        update={
            "embedding_provider": provider,
            "embedding_device": device,
            "embedding_fallback_enabled": False,
            "embedding_query_timeout_ms": 10**9,
            "embedding_batch_timeout_seconds": 10**9,
        }
    )
    load_started = time.perf_counter()
    embeddings = build_embedding_client(settings)
    load_ms = (time.perf_counter() - load_started) * 1000
    profile = require_embedding_profile(embeddings)
    texts = corpus()
    await embeddings.embed_batch(texts[:32])
    results: list[Result] = []
    for batch_size in batch_sizes:
        settings_batch = batch_size
        for count in COUNTS:
            totals: list[float] = []
            _reset_gpu_peak()
            rss_sampler = _MemorySampler()
            rss_sampler.start()
            for _ in range(repeats):
                started = time.perf_counter()
                for offset in range(0, count, settings_batch):
                    await embeddings.embed_batch(
                        texts[offset : offset + settings_batch]
                    )
                totals.append((time.perf_counter() - started) * 1000)
            total_p50 = statistics.median(totals)
            results.append(
                Result(
                    provider=profile.provider,
                    device=device,
                    count=count,
                    batch_size=batch_size,
                    model_load_ms=load_ms,
                    warm=True,
                    total_p50_ms=total_p50,
                    total_p95_ms=_percentile(totals, 0.95),
                    average_item_ms=total_p50 / count,
                    texts_per_second=count / max(total_p50 / 1000, 1e-9),
                    peak_rss_mib=rss_sampler.stop(),
                    peak_gpu_mib=_gpu_peak_mib(),
                )
            )
    return results


async def run(args: argparse.Namespace) -> list[Result]:
    providers = tuple(args.providers.split(","))
    devices = tuple(args.devices.split(","))
    batch_sizes = tuple(int(value) for value in args.batch_sizes.split(","))
    all_results: list[Result] = []
    for provider in providers:
        selected_devices = ("cpu",) if provider == "hash" else devices
        for device in selected_devices:
            all_results.extend(
                await benchmark_provider(provider, device, batch_sizes, args.repeats)
            )
    hash_rates = {
        (result.count, result.batch_size): result.texts_per_second
        for result in all_results
        if result.provider == "hash"
    }
    return [
        Result(
            **{
                **asdict(result),
                "slower_than_hash": (
                    hash_rates[(result.count, result.batch_size)]
                    / result.texts_per_second
                    if result.provider != "hash"
                    and (result.count, result.batch_size) in hash_rates
                    else None
                ),
            }
        )
        for result in all_results
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", default="hash,bge_m3")
    parser.add_argument("--devices", default="cpu,cuda")
    parser.add_argument(
        "--batch-sizes", default=",".join(str(value) for value in DEFAULT_BATCH_SIZES)
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output")
    args = parser.parse_args()
    results = asyncio.run(run(args))
    payload = [asdict(result) for result in results]
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered)


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1)]


class _MemorySampler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._peak_mib: float | None = None

    def start(self) -> None:
        try:
            import psutil  # type: ignore[import-untyped]
        except ImportError:
            return
        process = psutil.Process(os.getpid())
        self._peak_mib = float(process.memory_info().rss / 1024 / 1024)

        def sample() -> None:
            while not self._stop.wait(0.01):
                current = float(process.memory_info().rss / 1024 / 1024)
                self._peak_mib = max(self._peak_mib or 0.0, current)

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()

    def stop(self) -> float | None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        return self._peak_mib


def _reset_gpu_peak() -> None:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()


def _gpu_peak_mib() -> float | None:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    return float(torch.cuda.max_memory_allocated() / 1024 / 1024)


if __name__ == "__main__":
    main()
