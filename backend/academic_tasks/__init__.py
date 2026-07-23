"""Evidence-bounded academic analysis and writing services."""

from backend.academic_tasks.comparison import MultiPaperComparator
from backend.academic_tasks.drafting import AcademicDrafter
from backend.academic_tasks.literature_review import LiteratureReviewService
from backend.academic_tasks.paper_analysis import PaperCardExtractor
from backend.academic_tasks.rewriting import AcademicRewriter
from backend.academic_tasks.writing_brief import WritingBriefBuilder

__all__ = [
    "AcademicDrafter",
    "AcademicRewriter",
    "LiteratureReviewService",
    "MultiPaperComparator",
    "PaperCardExtractor",
    "WritingBriefBuilder",
]
