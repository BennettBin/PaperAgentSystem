"""Two-stage, manifest-first Skill selection."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    name: str
    description: str
    score: float


@dataclass(frozen=True, slots=True)
class SelectedSkill:
    name: str
    model_profile: str
    allowed_tools: tuple[str, ...]
    output_schema_path: Path
    instructions: str


@dataclass(frozen=True, slots=True)
class SkillSelection:
    selected: SelectedSkill
    candidates: tuple[SkillCandidate, ...]
    used_fallback: bool


class SkillSelector:
    KEYWORDS = {
        "citation_manager": ("引用", "参考文献", "citation"),
        "claim_extractor": ("提取主张", "抽取事实", "事实性结论", "claim extract"),
        "claim_verifier": ("验证", "核验", "verify", "证据"),
        "comparison_analyzer": ("比较", "对比", "compare"),
        "document_parser": ("解析", "章节", "parse", "pdf 文档"),
        "insight_extractor": ("洞见", "启示", "insight"),
        "limitation_analyst": ("局限", "限制", "limitation"),
        "literature_synthesizer": ("综合", "综述", "synthesi"),
        "methodology_reviewer": ("方法", "methodology", "实验方法"),
        "paper_reader": ("阅读", "paper card", "单篇"),
        "summary_generator": ("总结", "摘要", "summar"),
    }

    def __init__(self, skills_root: Path, *, fallback_skill: str) -> None:
        self._root = skills_root
        self._fallback = fallback_skill
        self._manifests = self._discover_manifests()
        self.loaded_instruction_names: set[str] = set()

    async def select(self, requirement: str) -> SkillSelection:
        normalized = requirement.casefold()
        ranked = []
        for name, manifest in self._manifests.items():
            hits = sum(keyword in normalized for keyword in self.KEYWORDS.get(name, ()))
            ranked.append(
                SkillCandidate(
                    name,
                    str(manifest["description"]),
                    float(hits),
                )
            )
        ranked.sort(key=lambda item: (-item.score, item.name))
        top = tuple(ranked[:3])
        used_fallback = not top or top[0].score == 0
        selected_name = self._fallback if used_fallback else top[0].name
        return SkillSelection(
            selected=self._load_selected(selected_name),
            candidates=top,
            used_fallback=used_fallback,
        )

    def _discover_manifests(self) -> dict[str, dict]:
        manifests = {}
        for path in sorted(self._root.glob("*/manifest.yaml")):
            manifest = yaml.safe_load(path.read_text("utf-8"))
            manifest["_directory"] = path.parent
            manifests[str(manifest["name"])] = manifest
        return manifests

    def _load_selected(self, name: str) -> SelectedSkill:
        manifest = self._manifests[name]
        directory = Path(manifest["_directory"])
        self.loaded_instruction_names.add(name)
        return SelectedSkill(
            name=name,
            model_profile=str(manifest["model_profile"]),
            allowed_tools=tuple(manifest["allowed_tools"]),
            output_schema_path=directory / str(manifest["output_schema"]),
            instructions=(directory / "SKILL.md").read_text("utf-8"),
        )
