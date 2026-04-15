from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline import llm_budget


def test_estimate_cost_haiku_basic():
    # 1M input + 1M output on Haiku = $1 + $5 = $6
    cost = llm_budget.estimate_cost_usd(
        "claude-haiku-4-5-20251001",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert math.isclose(cost, 6.0, rel_tol=1e-9)


def test_estimate_cost_sonnet_basic():
    # 1M input + 1M output on Sonnet = $3 + $15 = $18
    cost = llm_budget.estimate_cost_usd(
        "claude-sonnet-4-20250514",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert math.isclose(cost, 18.0, rel_tol=1e-9)


def test_estimate_cost_with_cached_tokens_haiku():
    # 800K regular + 200K cached input + 500K output, Haiku:
    #   regular: 0.8 * 1   = 0.80
    #   cached : 0.2 * 0.10 = 0.02
    #   output : 0.5 * 5   = 2.50
    #   total  : 3.32
    cost = llm_budget.estimate_cost_usd(
        "claude-haiku-4-5-20251001",
        input_tokens=1_000_000,
        output_tokens=500_000,
        cached_input_tokens=200_000,
    )
    assert math.isclose(cost, 3.32, rel_tol=1e-9)


def test_estimate_cost_batch_discount():
    # Batch API = 50% off. Sonnet 1M/1M normally $18 -> $9 with batch.
    cost = llm_budget.estimate_cost_usd(
        "claude-sonnet-4-20250514",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        batch=True,
    )
    assert math.isclose(cost, 9.0, rel_tol=1e-9)


def test_estimate_cost_unknown_model_falls_back_to_sonnet():
    cost_unknown = llm_budget.estimate_cost_usd(
        "not-a-real-model",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    cost_sonnet = llm_budget.estimate_cost_usd(
        "claude-sonnet-4-20250514",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert cost_unknown == cost_sonnet


@pytest.mark.asyncio
async def test_check_budget_under_hard_stop(monkeypatch):
    monkeypatch.setattr(llm_budget.settings, "LLM_BUDGET_HARD_STOP_USD", 20.0)
    with patch.object(llm_budget, "current_total_usd", AsyncMock(return_value=5.0)):
        under, total = await llm_budget.check_budget()
        assert under is True
        assert total == 5.0


@pytest.mark.asyncio
async def test_check_budget_blocks_at_hard_stop(monkeypatch):
    monkeypatch.setattr(llm_budget.settings, "LLM_BUDGET_HARD_STOP_USD", 20.0)
    with patch.object(llm_budget, "current_total_usd", AsyncMock(return_value=20.01)):
        under, total = await llm_budget.check_budget()
        assert under is False
        assert total == 20.01
