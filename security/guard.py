"""Deterministic guard for document-borne prompt injection."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UntrustedContentDecision:
    allowed_as_evidence: bool
    blocked_instructions: tuple[str, ...]
    sanitized_text: str
    risk_score: float


class PromptInjectionGuard:
    PATTERNS = (
        re.compile(r"ignore (?:all |the )?(?:previous|system) instructions?", re.I),
        re.compile(r"reveal (?:the )?(?:system prompt|secret|api key)", re.I),
        re.compile(r"(?:call|use|invoke) (?:the )?(?:tool|shell|terminal)", re.I),
        re.compile(r"(?:delete|exfiltrate|upload|send) (?:all |the )?(?:files|data|paper)", re.I),
        re.compile(r"你(?:现在)?(?:必须|应该).*(?:忽略|泄露|调用工具|删除)", re.I),
        re.compile(r"忽略(?:之前|系统|所有).*(?:指令|规则|提示)", re.I),
        re.compile(r"(?:system|developer)\s*:\s*", re.I),
    )

    def inspect(self, text: str) -> UntrustedContentDecision:
        matches = []
        sanitized = text
        for pattern in self.PATTERNS:
            for match in pattern.finditer(text):
                matches.append(match.group(0))
            sanitized = pattern.sub("[BLOCKED_UNTRUSTED_INSTRUCTION]", sanitized)
        risk = min(1.0, len(matches) / 2)
        return UntrustedContentDecision(
            allowed_as_evidence=not matches,
            blocked_instructions=tuple(matches),
            sanitized_text=sanitized,
            risk_score=risk,
        )
