"""Evidence-bounded academic analysis and writing services."""

from academic_tasks.comparison import MultiPaperComparator
from academic_tasks.drafting import AcademicDrafter
from academic_tasks.literature_review import LiteratureReviewService
from academic_tasks.paper_analysis import PaperCardExtractor
from academic_tasks.rewriting import AcademicRewriter
from academic_tasks.writing_brief import WritingBriefBuilder

__all__ = [
    "AcademicDrafter",
    "AcademicRewriter",
    "LiteratureReviewService",
    "MultiPaperComparator",
    "PaperCardExtractor",
    "WritingBriefBuilder",
]
