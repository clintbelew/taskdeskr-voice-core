"""
Tests for the tool dispatcher.
Run with: pytest tests/ -v
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.tools.dispatcher import dispatch


@pytest.mark.asyncio
async def test_book_appointment_missing_start_time():
    result = await dispatch(
        tool_name="book_appointment",
        arguments_json=json.dumps({"title": "Test"}),
        contact_id="contact_123",
    )
    assert result["success"] is False
    assert "start_time" in result["error"]


@pytest.mark.asyncio
async def test_book_appointment_no_contact():
    result = await dispatch(
        tool_name="book_appointment",
        arguments_json=json.dumps({"start_time": "2026-04-01T14:00:00"}),
        contact_id=None,
        phone=None,
    )
    assert result["success"] is False


@pytest.mark.asyncio
async def test_add_tag_success():
    with patch("src.tools.dispatcher.ghl.add_tags", new_callable=AsyncMock) as mock_add:
        mock_add.return_value = {}
        result = await dispatch(
            tool_name="add_contact_tag",
            arguments_json=json.dumps({"tags": ["hot-lead"]}),
            contact_id="contact_123",
        )
    assert result["success"] is True
    assert "hot-lead" in result["message"]


@pytest.mark.asyncio
async def test_send_sms_empty_message():
    result = await dispatch(
        tool_name="send_sms",
        arguments_json=json.dumps({"message": ""}),
        contact_id="contact_123",
    )
    assert result["success"] is False


@pytest.mark.asyncio
async def test_escalate_no_phone_configured():
    with patch("src.tools.dispatcher.settings") as mock_settings:
        mock_settings.ESCALATION_PHONE_NUMBER = ""
        result = await dispatch(
            tool_name="escalate_to_human",
            arguments_json=json.dumps({"reason": "Caller is upset"}),
            contact_id="contact_123",
        )
    assert result["success"] is False


@pytest.mark.asyncio
async def test_end_call_returns_farewell():
    result = await dispatch(
        tool_name="end_call",
        arguments_json=json.dumps({"farewell_message": "Goodbye and have a great day!"}),
        contact_id=None,
    )
    assert result["success"] is True
    assert result["action"] == "end_call"
    assert "Goodbye" in result["farewell_message"]


@pytest.mark.asyncio
async def test_unknown_tool():
    result = await dispatch(
        tool_name="do_something_unknown",
        arguments_json="{}",
        contact_id="contact_123",
    )
    assert result["success"] is False
    assert "Unknown tool" in result["error"]


@pytest.mark.asyncio
async def test_invalid_json_arguments():
    result = await dispatch(
        tool_name="add_contact_tag",
        arguments_json="not-valid-json",
        contact_id="contact_123",
    )
    assert result["success"] is False
