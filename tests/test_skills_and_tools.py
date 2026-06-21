import pytest
from core.ports.skills import SkillManifest, Skill, SkillRegistry, get_skill_registry
from core.ports.tools import ToolParameter, Tool, ToolRegistry, get_tool_registry
from core.ports.subagents import SubAgentDefinition, SubAgentRegistry, get_subagent_registry
from skills.paper_reader import PaperReaderSkill
from skills.document_parser import DocumentParserSkill
from skills.claim_extractor import ClaimExtractorSkill


class TestToolDefinition:
    """Test Tool definitions"""

    def test_tool_parameter_creation(self):
        """Test creating tool parameters"""
        param = ToolParameter(
            name="input_file",
            type="string",
            description="Input file path",
            required=True,
        )
        assert param.name == "input_file"
        assert param.type == "string"
        assert param.required is True

    async def test_tool_creation(self):
        """Test creating tools"""
        async def dummy_execute(**kwargs):
            return {"result": "success"}

        tool = Tool(
            name="test_tool",
            description="Test tool",
            parameters=[ToolParameter("input", "string", "Input", required=True)],
            execute_fn=dummy_execute,
        )
        assert tool.name == "test_tool"
        result = await tool.execute(input="test")
        assert result["result"] == "success"


class TestToolRegistry:
    """Test Tool Registry"""

    def test_tool_registry_creation(self):
        """Test creating tool registry"""
        registry = ToolRegistry()
        assert len(registry.list_all()) == 0

    async def test_register_and_get_tool(self):
        """Test registering and getting tools"""
        registry = ToolRegistry()

        async def dummy_execute(**kwargs):
            return {"status": "ok"}

        tool = Tool(
            name="test_tool",
            description="Test",
            parameters=[],
            execute_fn=dummy_execute,
        )
        registry.register(tool)
        found = registry.get("test_tool")
        assert found is not None
        assert found.name == "test_tool"

    async def test_execute_tool(self):
        """Test executing tool from registry"""
        registry = ToolRegistry()

        async def dummy_execute(**kwargs):
            return {"param": kwargs.get("test_param")}

        tool = Tool(
            name="test_tool",
            description="Test",
            parameters=[],
            execute_fn=dummy_execute,
        )
        registry.register(tool)
        result = await registry.execute("test_tool", test_param="value")
        assert result["param"] == "value"


class TestSkillManifest:
    """Test Skill Manifests"""

    def test_manifest_creation(self):
        """Test creating skill manifest"""
        manifest = SkillManifest(
            name="test_skill",
            version="1.0.0",
            description="Test skill",
            required_tools=["tool1"],
            model_profile="development",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )
        assert manifest.name == "test_skill"
        assert manifest.version == "1.0.0"


@pytest.mark.asyncio
class TestSkills:
    """Test Skill implementations"""

    async def test_paper_reader_skill(self):
        """Test PaperReaderSkill"""
        skill = PaperReaderSkill()
        manifest = skill.manifest
        assert manifest.name == "paper_reader"
        assert manifest.version == "1.0.0"

        result = await skill.execute({"document_id": "doc-1"})
        assert "title" in result
        assert "authors" in result

    async def test_document_parser_skill(self):
        """Test DocumentParserSkill"""
        skill = DocumentParserSkill()
        manifest = skill.manifest
        assert manifest.name == "document_parser"

        result = await skill.execute({"file_id": "file-1"})
        assert "content" in result

    async def test_claim_extractor_skill(self):
        """Test ClaimExtractorSkill"""
        skill = ClaimExtractorSkill()
        manifest = skill.manifest
        assert manifest.name == "claim_extractor"

        result = await skill.execute({"content": "Some claim here"})
        assert "claims" in result

    async def test_skill_validation(self):
        """Test skill input validation"""
        skill = PaperReaderSkill()
        assert skill.validate_input({"document_id": "doc-1"})
        assert not skill.validate_input({"other_key": "value"})


class TestSkillRegistry:
    """Test Skill Registry"""

    def test_skill_registry_creation(self):
        """Test creating skill registry"""
        registry = SkillRegistry()
        assert len(registry.list_all()) == 0

    async def test_register_skill(self):
        """Test registering skill"""
        registry = SkillRegistry()
        skill = PaperReaderSkill()
        registry.register(skill)

        found = registry.get("paper_reader")
        assert found is not None
        assert found.manifest.name == "paper_reader"

    async def test_get_manifest(self):
        """Test getting skill manifest"""
        registry = SkillRegistry()
        skill = PaperReaderSkill()
        registry.register(skill)

        manifest = registry.get_manifest("paper_reader")
        assert manifest is not None
        assert manifest.name == "paper_reader"

    async def test_execute_skill(self):
        """Test executing skill from registry"""
        registry = SkillRegistry()
        skill = PaperReaderSkill()
        registry.register(skill)

        result = await registry.execute("paper_reader", {"document_id": "doc-1"})
        assert "title" in result

    async def test_skill_execution_with_invalid_input(self):
        """Test skill execution with invalid input"""
        registry = SkillRegistry()
        skill = PaperReaderSkill()
        registry.register(skill)

        with pytest.raises(ValueError):
            await registry.execute("paper_reader", {"invalid": "input"})


class TestSubAgentRegistry:
    """Test SubAgent Registry"""

    def test_subagent_registry_creation(self):
        """Test creating subagent registry"""
        registry = SubAgentRegistry()
        assert len(registry.list_all()) == 0

    def test_subagent_definition(self):
        """Test subagent definition"""
        definition = SubAgentDefinition(
            name="paper_reader_agent",
            version="1.0.0",
            description="Agent for reading papers",
            parent_skills=["paper_reader"],
            model_profile="development",
        )
        assert definition.name == "paper_reader_agent"
        assert "paper_reader" in definition.parent_skills


class TestGlobalRegistries:
    """Test global registries"""

    def test_get_global_skill_registry(self):
        """Test getting global skill registry"""
        registry = get_skill_registry()
        assert isinstance(registry, SkillRegistry)

    def test_get_global_tool_registry(self):
        """Test getting global tool registry"""
        registry = get_tool_registry()
        assert isinstance(registry, ToolRegistry)

    def test_get_global_subagent_registry(self):
        """Test getting global subagent registry"""
        registry = get_subagent_registry()
        assert isinstance(registry, SubAgentRegistry)


@pytest.mark.asyncio
class TestIntegration:
    """Integration tests"""

    async def test_multiple_skills_registration(self):
        """Test registering multiple skills"""
        registry = SkillRegistry()
        skills = [PaperReaderSkill(), DocumentParserSkill(), ClaimExtractorSkill()]
        for skill in skills:
            registry.register(skill)

        assert len(registry.list_all()) == 3
        manifests = registry.list_manifests()
        assert len(manifests) == 3

    async def test_skill_chain_execution(self):
        """Test executing skills in chain"""
        registry = SkillRegistry()
        registry.register(DocumentParserSkill())
        registry.register(ClaimExtractorSkill())

        # Execute first skill
        result1 = await registry.execute("document_parser", {"file_id": "file-1"})
        assert "content" in result1

        # Execute second skill with output from first
        result2 = await registry.execute("claim_extractor", {"content": result1["content"]})
        assert "claims" in result2
