"""
Phase 1 Tool Dispatcher Tests
Tests the 5 Phase 1 tools using the new dispatcher contract:
  result: str, action: dict (optional)

Run with: pytest tests/ -v
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.tools.dispatcher import dispatch


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_state(contact_id="contact_abc", phone="+15551234567"):
    return {
        "contact_id": contact_id,
        "phone": phone,
        "caller_first_name": "",
        "caller_last_name": "",
        "caller_email": "",
        "opportunity_id": None,
        "booking_link_requested": False,
        "pipeline_stage": "new_lead",
        "qualification": {},
    }


# ── save_caller_info ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_caller_info_success():
    state = make_state()
    with (
        patch("src.tools.dispatcher.ghl.update_contact", new_callable=AsyncMock) as mock_update,
        patch("src.tools.dispatcher.ghl.add_tags", new_callable=AsyncMock) as mock_tags,
    ):
        mock_update.return_value = {}
        mock_tags.return_value = {}
        result = await dispatch(
            tool_name="save_caller_info",
            arguments_json=json.dumps({"first_name": "Jane", "last_name": "Smith"}),
            contact_id="contact_abc",
            call_state=state,
        )
    assert "Jane" in result["result"]
    assert state["caller_first_name"] == "Jane"
    mock_tags.assert_called_once_with("contact_abc", ["voice-bot-lead"])


@pytest.mark.asyncio
async def test_save_caller_info_no_contact():
    state = {"contact_id": None}
    result = await dispatch(
        tool_name="save_caller_info",
        arguments_json=json.dumps({"first_name": "John"}),
        contact_id=None,
        call_state=state,
    )
    assert "result" in result


# ── save_qualification_data ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_qualification_data_success():
    state = make_state()
    with patch("src.tools.dispatcher.ghl.update_qualification_fields", new_callable=AsyncMock) as mock_qual:
        mock_qual.return_value = {}
        result = await dispatch(
            tool_name="save_qualification_data",
            arguments_json=json.dumps({
                "insurance_status": "Yes",
                "insurance_provider": "Blue Cross",
                "chief_complaint": "Back pain",
            }),
            contact_id="contact_abc",
            call_state=state,
        )
    assert "result" in result
    assert state["qualification"].get("insurance_status") == "Yes"


@pytest.mark.asyncio
async def test_save_qualification_data_no_contact():
    state = {"contact_id": None}
    result = await dispatch(
        tool_name="save_qualification_data",
        arguments_json=json.dumps({"insurance_status": "No"}),
        contact_id=None,
        call_state=state,
    )
    assert "result" in result


# ── create_lead_opportunity ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_lead_opportunity_success():
    state = make_state()
    with patch("src.tools.dispatcher.ghl.ensure_opportunity", new_callable=AsyncMock) as mock_opp:
        mock_opp.return_value = ("opp_123", True)
        result = await dispatch(
            tool_name="create_lead_opportunity",
            arguments_json=json.dumps({"opportunity_name": "Voice Bot Lead — Jane Smith"}),
            contact_id="contact_abc",
            call_state=state,
        )
    assert "result" in result
    assert state["opportunity_id"] == "opp_123"


@pytest.mark.asyncio
async def test_create_lead_opportunity_idempotent():
    """Should not create a second opportunity if one already exists in state."""
    state = make_state()
    state["opportunity_id"] = "existing_opp"
    result = await dispatch(
        tool_name="create_lead_opportunity",
        arguments_json=json.dumps({"opportunity_name": "Voice Bot Lead — Jane Smith"}),
        contact_id="contact_abc",
        call_state=state,
    )
    assert "already" in result["result"].lower()


# ── send_booking_link ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_booking_link_success():
    state = make_state()
    state["opportunity_id"] = "opp_123"
    with patch("src.tools.dispatcher.ghl.move_opportunity_stage", new_callable=AsyncMock) as mock_move:
        mock_move.return_value = {}
        result = await dispatch(
            tool_name="send_booking_link",
            arguments_json=json.dumps({"caller_interest_level": "high"}),
            contact_id="contact_abc",
            call_state=state,
        )
    assert "result" in result
    assert state["booking_link_requested"] is True
    assert state["pipeline_stage"] == "booking_link_sent"


@pytest.mark.asyncio
async def test_send_booking_link_creates_opportunity_if_missing():
    """If no opportunity exists yet, send_booking_link should create one first."""
    state = make_state()
    state["opportunity_id"] = None
    with (
        patch("src.tools.dispatcher.ghl.ensure_opportunity", new_callable=AsyncMock) as mock_opp,
        patch("src.tools.dispatcher.ghl.move_opportunity_stage", new_callable=AsyncMock) as mock_move,
    ):
        mock_opp.return_value = ("opp_new", True)
        mock_move.return_value = {}
        result = await dispatch(
            tool_name="send_booking_link",
            arguments_json=json.dumps({"caller_interest_level": "medium"}),
            contact_id="contact_abc",
            call_state=state,
        )
    assert "result" in result
    assert state["opportunity_id"] == "opp_new"


# ── end_call ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_end_call_returns_vapi_action():
    state = make_state()
    result = await dispatch(
        tool_name="end_call",
        arguments_json=json.dumps({"reason": "completed"}),
        contact_id="contact_abc",
        call_state=state,
    )
    assert result.get("action", {}).get("type") == "end-call"
    assert "result" in result
    assert state["end_reason"] == "completed"


# ── Unknown tool ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_tool_graceful():
    state = make_state()
    result = await dispatch(
        tool_name="fly_to_moon",
        arguments_json="{}",
        contact_id="contact_abc",
        call_state=state,
    )
    assert "result" in result


# ── Invalid JSON ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_json_graceful():
    state = make_state()
    result = await dispatch(
        tool_name="save_caller_info",
        arguments_json="not-valid-json",
        contact_id="contact_abc",
        call_state=state,
    )
    assert "result" in result
