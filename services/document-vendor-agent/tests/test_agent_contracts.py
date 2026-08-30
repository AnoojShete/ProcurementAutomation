from app.services.agent_contracts import AgentResult, record_agent_result


class TestAgentContracts:
    def test_record_agent_result_appends_to_trail(self):
        envelope = {"document_id": "doc-1"}
        result = record_agent_result(envelope, "parsing_agent", confidence=0.9)
        assert isinstance(result, AgentResult)
        assert envelope["_agent_trail"] == [result]
        assert result.agent_name == "parsing_agent"
        assert result.input_reference == "doc-1"
        assert result.validation_status == "valid"

    def test_record_agent_result_defaults(self):
        envelope = {"document_id": "doc-1"}
        result = record_agent_result(envelope, "confidence_agent")
        assert result.confidence is None
        assert result.errors == []
        assert result.warnings == []
        assert result.next_action == "continue"
        assert result.agent_version

    def test_task_id_unique_per_stage(self):
        envelope = {"document_id": "doc-1"}
        first = record_agent_result(envelope, "parsing_agent")
        second = record_agent_result(envelope, "classification_agent")
        assert first.task_id != second.task_id
        assert len(envelope["_agent_trail"]) == 2

    def test_invalid_stage_marks_validation_status_and_errors(self):
        envelope = {"document_id": "doc-1"}
        result = record_agent_result(
            envelope, "parsing_agent", validation_status="invalid", errors=["empty extraction"]
        )
        assert result.validation_status == "invalid"
        assert result.errors == ["empty extraction"]
