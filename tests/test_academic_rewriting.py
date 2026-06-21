from academic_tasks.rewriting import AcademicRewriter, RewriteMode

SOURCE = (
    "我们发现 Model-X 在 Dataset-A 上达到 95.5% [C1]。 "
    "损失定义为 $L=\\sum_i e_i$，该结果支持 calibration improvement。"
)


def test_rewriter_extracts_and_preserves_invariants() -> None:
    result = AcademicRewriter().rewrite(
        SOURCE,
        RewriteMode.POLISH,
        protected_terms=["Model-X", "Dataset-A", "calibration improvement"],
    )

    assert result.invariants.numbers == ["95.5%"]
    assert result.invariants.formulas == ["$L=\\sum_i e_i$"]
    assert result.invariants.citations == ["[C1]"]
    assert result.invariant_preservation == 1
    assert result.regression_passed
    assert result.change_notes


def test_all_rewrite_modes_return_change_notes_and_regression() -> None:
    rewriter = AcademicRewriter()
    for mode in RewriteMode:
        result = rewriter.rewrite(
            SOURCE,
            mode,
            protected_terms=["Model-X", "Dataset-A"],
        )
        assert result.change_notes
        assert result.regression_passed
        assert result.academic_style_score >= 4


def test_rewriting_evaluation_thresholds() -> None:
    rewriter = AcademicRewriter()
    preservation = semantic = style = 0.0
    total = 200
    for index in range(total):
        source = (
            f"我们发现 Model-{index} 在 Dataset-{index} 上达到 {80 + index % 20}% [C{index}]。 "
            f"目标函数为 $L_{index}=x+y$，结果支持 stable improvement。"
        )
        result = rewriter.rewrite(
            source,
            list(RewriteMode)[index % len(RewriteMode)],
            protected_terms=[
                f"Model-{index}",
                f"Dataset-{index}",
                "stable improvement",
            ],
        )
        preservation += result.invariant_preservation
        semantic += result.semantic_score
        style += result.academic_style_score

    assert preservation / total >= 0.99
    assert semantic / total >= 4.5
    assert style / total >= 4
