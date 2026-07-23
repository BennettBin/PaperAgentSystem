"""Select a validated Skill from the single production registry."""

from dataclasses import dataclass

from backend.skills.loader import LoadedSkill, SkillRegistry


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    name: str
    description: str
    score: float


@dataclass(frozen=True, slots=True)
class SkillSelection:
    selected: LoadedSkill
    candidates: tuple[SkillCandidate, ...]
    used_fallback: bool


class SkillSelector:
    def __init__(self, registry: SkillRegistry, *, fallback_skill: str) -> None:
        self._registry = registry
        self._fallback = fallback_skill
        self.loaded_instruction_names: set[str] = set()

    async def select(self, requirement: str) -> SkillSelection:
        normalized = requirement.casefold()
        ranked = []
        for skill in self._registry.list_all():
            hits = sum(keyword.casefold() in normalized for keyword in skill.routing_keywords)
            ranked.append(
                SkillCandidate(
                    skill.name,
                    skill.description,
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

    def _load_selected(self, name: str) -> LoadedSkill:
        skill = self._registry.get(name)
        if skill is None:
            raise ValueError(f"Skill not found: {name}")
        self.loaded_instruction_names.add(name)
        return skill
