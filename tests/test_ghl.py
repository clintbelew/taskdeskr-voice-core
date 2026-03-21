"""
Tests for the GoHighLevel service helpers.
Run with: pytest tests/ -v
"""

import pytest
from src.services.ghl import _normalize_phone


def test_normalize_10_digit():
    assert _normalize_phone("5125551234") == "+15125551234"


def test_normalize_11_digit_with_1():
    assert _normalize_phone("15125551234") == "+15125551234"


def test_normalize_already_e164():
    assert _normalize_phone("+15125551234") == "+15125551234"


def test_normalize_with_dashes():
    assert _normalize_phone("512-555-1234") == "+15125551234"


def test_normalize_with_parens():
    assert _normalize_phone("(512) 555-1234") == "+15125551234"
