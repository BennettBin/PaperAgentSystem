from dataclasses import dataclass

from backend.rag.section_resolver import SectionRecord


@dataclass(frozen=True, slots=True)
class ResolverCase:
    query: str
    expected_status: str
    expected_section_id: str | None
    category: str


def _section(section_id: str, number: str | None, title: str, ordinal: int) -> SectionRecord:
    return SectionRecord(
        section_id=section_id,
        document_id="evaluation-document",
        file_id="evaluation-paper",
        number=number,
        title=title,
        normalized_title="",
        section_path=[f"{number} {title}".strip() if number else title],
        parent_section_id=None,
        ordinal=ordinal,
    )


EVALUATION_SECTIONS = [
    _section("abstract", None, "Abstract", 0),
    _section("introduction", "1", "Introduction", 1),
    _section("related-work", "2", "Related Work", 2),
    _section("methods", "3", "Materials and Methods", 3),
    _section("dataset", "3.1", "Dataset", 4),
    _section("model-architecture", "3.2", "Model Architecture", 5),
    _section("training-strategy", "3.3", "Training Strategy", 6),
    _section("experiments", "4", "Experiments", 7),
    _section("experimental-setup", "4.1", "Experimental Setup", 8),
    _section("results", "5", "Results and Findings", 9),
    _section("discussion", "6", "Discussion", 10),
    _section("conclusion", "7", "Conclusions", 11),
    _section("references", None, "References", 12),
    _section("appendix", "A", "Supplementary Material", 13),
    _section("appendix-a1", "A.1", "Additional Results", 14),
    _section("analysis-one", "3.4", "Analysis", 15),
    _section("analysis-two", "5.1", "Analysis", 16),
]


def _cases() -> list[ResolverCase]:
    cases: list[ResolverCase] = []
    numbered = [
        ("1", "introduction"),
        ("2", "related-work"),
        ("3", "methods"),
        ("3.1", "dataset"),
        ("3.2", "model-architecture"),
        ("3.3", "training-strategy"),
        ("4", "experiments"),
        ("4.1", "experimental-setup"),
        ("5", "results"),
        ("A.1", "appendix-a1"),
    ]
    for number, section_id in numbered:
        cases.extend(
            [
                ResolverCase(
                    f"请解释第 {number} 节", "resolved", section_id, "number"
                ),
                ResolverCase(
                    f"Summarize section {number}", "resolved", section_id, "number"
                ),
            ]
        )

    exact_titles = [
        ("Abstract", "abstract"),
        ("Introduction", "introduction"),
        ("Related Work", "related-work"),
        ("Materials and Methods", "methods"),
        ("Dataset", "dataset"),
        ("Model Architecture", "model-architecture"),
        ("Training Strategy", "training-strategy"),
        ("Experimental Setup", "experimental-setup"),
        ("Discussion", "discussion"),
        ("References", "references"),
    ]
    for title, section_id in exact_titles:
        cases.extend(
            [
                ResolverCase(
                    f"Explain the {title} section", "resolved", section_id, "title"
                ),
                ResolverCase(f"总结 {title}", "resolved", section_id, "title"),
            ]
        )

    aliases = [
        ("摘要部分讲了什么", "abstract"),
        ("overview of the abstract", "abstract"),
        ("引言部分", "introduction"),
        ("paper introduction", "introduction"),
        ("相关工作有哪些", "related-work"),
        ("literature review section", "related-work"),
        ("方法部分用了什么", "methods"),
        ("methodology section", "methods"),
        ("研究方法是什么", "methods"),
        ("数据集部分", "dataset"),
        ("data section", "dataset"),
        ("model design section", "model-architecture"),
        ("模型架构部分", "model-architecture"),
        ("训练策略部分", "training-strategy"),
        ("training procedure section", "training-strategy"),
        ("实验部分", "experiments"),
        ("experiments section", "experiments"),
        ("实验设置部分", "experimental-setup"),
        ("evaluation setup section", "experimental-setup"),
        ("结果部分", "results"),
        ("findings section", "results"),
        ("主要发现是什么", "results"),
        ("讨论部分", "discussion"),
        ("discussion section", "discussion"),
        ("结论部分", "conclusion"),
        ("conclusion section", "conclusion"),
        ("参考文献部分", "references"),
        ("bibliography section", "references"),
        ("附录部分", "appendix"),
        ("supplement section", "appendix"),
    ]
    cases.extend(
        ResolverCase(query, "resolved", section_id, "alias")
        for query, section_id in aliases
    )

    fuzzy = [
        ("abstrct section", "abstract"),
        ("introducion section", "introduction"),
        ("relatd work section", "related-work"),
        ("materials & method section", "methods"),
        ("datasett section", "dataset"),
        ("model archtecture section", "model-architecture"),
        ("trainng strategy section", "training-strategy"),
        ("expermental setup section", "experimental-setup"),
        ("reslts and findings section", "results"),
        ("discusion section", "discussion"),
        ("conclusons section", "conclusion"),
        ("referenes section", "references"),
        ("supplementry material section", "appendix"),
        ("aditional results section", "appendix-a1"),
        ("model-architecture section", "model-architecture"),
        ("training_strategy section", "training-strategy"),
        ("experimental/setup section", "experimental-setup"),
        ("results & findings section", "results"),
        ("related-work section", "related-work"),
        ("materials-and-methods section", "methods"),
    ]
    cases.extend(
        ResolverCase(query, "resolved", section_id, "fuzzy")
        for query, section_id in fuzzy
    )

    cases.extend(
        [
            ResolverCase("Experimental Ethics section", "unresolved", None, "unresolved"),
            ResolverCase("第 9.9 节", "unresolved", None, "unresolved"),
            ResolverCase("Hardware Procurement section", "unresolved", None, "unresolved"),
            ResolverCase("法律声明部分", "unresolved", None, "unresolved"),
            ResolverCase("section Z.9", "unresolved", None, "unresolved"),
        ]
    )
    cases.extend(
        ResolverCase("总结 Analysis section", "ambiguous", None, "ambiguous")
        for _ in range(5)
    )
    assert len(cases) == 100
    return cases


EVALUATION_CASES = _cases()
