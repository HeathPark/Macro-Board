"""공개 계획의 종목 참조·비중과 기존 안전자산 분류를 확인한다."""
import pytest

from src.config import load_config
from src.portfolio import blend_weights, risk_check, universe_map


def test_latest_public_plan_is_valid_for_each_transition():
    plan = load_config("plan")
    known = universe_map(load_config("universe"))
    for account in plan["accounts"].values():
        for k in range(4):
            weights = blend_weights(account, k)
            assert sum(weights.values()) == pytest.approx(100)
            assert set(weights) <= set(known)
            assert not {"SHORT_KTB_DIRECT", "USD_RP"} & set(weights)
    assert "K200" not in plan["accounts"]["isa"]["P2"]
    assert "K200" in plan["accounts"]["brokerage"]["P2"]


def test_retirement_safe_asset_membership_is_preserved():
    configured = set(load_config("universe")["retirement_safe_assets"])
    assert configured == {"DEPOSIT", "USDST", "USTB3M", "KTB3", "KTB30", "UST30", "MMF", "CD"}
    for asset_id in configured:
        assert risk_check({asset_id: 100})["risk_weight"] == 0
    assert risk_check({"SOFR": 100})["exceeded"]
