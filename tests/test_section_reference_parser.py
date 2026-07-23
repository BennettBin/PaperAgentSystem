from backend.rag.section_resolver import SectionReferenceParser


def test_parser_extracts_chinese_and_english_section_numbers() -> None:
    parser = SectionReferenceParser()

    assert parser.parse("请解释第 4.5 节的三个管理启示").number == "4.5"
    assert parser.parse("总结第4章").number == "4"
    assert parser.parse("Explain section 3.2 training strategy").number == "3.2"
    assert parser.parse("What is in Sec. A.2?").number == "A.2"
    assert parser.parse("概括 2.1节").number == "2.1"
    assert parser.parse("Summarize Section IV").number == "IV"
    assert parser.parse("解释附录 A.1").number == "A.1"


def test_parser_separates_number_title_and_requested_mode() -> None:
    parser = SectionReferenceParser()

    reference = parser.parse("总结 3.2 Model Architecture")

    assert reference.kind == "number"
    assert reference.number == "3.2"
    assert reference.title == "Model Architecture"
    assert reference.requested_mode == "summary"
    assert reference.raw_text == "3.2 Model Architecture"


def test_parser_extracts_titles_aliases_and_ordinary_queries() -> None:
    parser = SectionReferenceParser()

    assert parser.parse("Methods section 用了什么数据集？").title == "Methods"
    assert parser.parse("结果部分有哪些发现？").title == "结果"
    assert parser.parse("请解释 literature review").title == "literature review"
    assert parser.parse("作者使用了什么数据集？").kind == "none"
    assert parser.parse("告诉我这篇文章用了哪些数据集进行验证").kind == "none"
    assert parser.parse("这篇文章的结果是什么？").kind == "none"
    assert parser.parse("概括这篇文章使用的数据集").kind == "none"
    assert parser.parse("Paper uses which dataset?").kind == "none"


def test_parser_marks_deictic_references_without_inventing_section_ids() -> None:
    parser = SectionReferenceParser()

    current = parser.parse("总结这一节")
    previous = parser.parse("上一节讲了什么？")

    assert current.kind == "deictic"
    assert current.deictic == "current"
    assert current.requested_mode == "summary"
    assert previous.kind == "deictic"
    assert previous.deictic == "previous"
    assert current.number is None
    assert current.title is None
