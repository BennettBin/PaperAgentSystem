from pathlib import Path


def test_portfolio_deliverables_exist_and_readme_links_versioned_evidence() -> None:
    root = Path(__file__).resolve().parents[1]
    required = [
        "docs/adr/0011-evidence-gated-agent-promotion.md",
        "docs/MODEL_CARD.md",
        "evaluation/datasets/DATASET_CARD.md",
        "evaluation/reports/p04_final_v1/report.json",
        "evaluation/reports/p04_final_v1/report.md",
        "docs/FAILURE_POSTMORTEMS.md",
        "docs/DEMO_RUNBOOK.md",
        "docs/INTERVIEW_GUIDE.md",
        "docs/RESUME_PROJECT.md",
        "evaluation/reports/p05_demo_v1/demo.json",
        "evaluation/reports/p05_demo_v1/demo.md",
    ]
    assert all((root / path).exists() for path in required)

    readme = (root / "README.md").read_text("utf-8")
    assert "python -m evaluation.p05_demo" in readme
    assert "evaluation/reports/p04_final_v1/report.md" in readme
    assert "M06" in readme and "N05" in readme
    assert "NO-GO" in readme
    assert "不可用" in readme


def test_resume_and_postmortems_keep_negative_results_and_no_sft_claim() -> None:
    root = Path(__file__).resolve().parents[1]
    resume = (root / "docs" / "RESUME_PROJECT.md").read_text("utf-8")
    failures = (root / "docs" / "FAILURE_POSTMORTEMS.md").read_text("utf-8")
    model_card = (root / "docs" / "MODEL_CARD.md").read_text("utf-8")

    assert resume.count("- ") >= 5
    assert "1,800" in resume
    assert "96.84%" in resume
    assert "+398.03%" in resume
    assert "6.33%–8.0%" in resume
    assert failures.count("## ") == 3
    assert "NO-GO" in model_card
    assert "No project SFT/RL Adapter is claimed" in model_card
