"""
Paper Reader Skill - reads and extracts key information from papers
"""

from core.ports.skills import Skill, SkillManifest
from typing import Optional


class PaperReaderSkill(Skill):
    """Skill for reading and extracting information from academic papers"""
    
    @property
    def manifest(self) -> SkillManifest:
        return SkillManifest(
            name="paper_reader",
            version="1.0.0",
            description="Reads academic papers and extracts key information including title, authors, abstract, methodology, results, and conclusions.",
            required_tools=["document_parser", "text_extractor"],
            model_profile="development",
            input_schema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "extract_sections": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["document_id"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "authors": {"type": "array"},
                    "abstract": {"type": "string"},
                    "sections": {"type": "object"},
                },
            },
        )
    
    async def execute(self, input_data: dict) -> dict:
        """Execute paper reading skill"""
        document_id = input_data.get("document_id")
        return {
            "document_id": document_id,
            "title": "Sample Paper Title",
            "authors": ["Author 1", "Author 2"],
            "abstract": "This is a sample abstract...",
            "sections": {
                "introduction": "Introduction content...",
                "methodology": "Methodology content...",
                "results": "Results content...",
            },
        }
    
    def validate_input(self, input_data: dict) -> bool:
        """Validate input against schema"""
        return "document_id" in input_data and isinstance(input_data["document_id"], str)
