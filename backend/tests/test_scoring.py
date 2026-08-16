"""§19 scoring formula tests."""

from app.modules.analysis.service import compute_overall_score


def test_weighted_formula() -> None:
    # 100*0.25 + 90*0.20 + 80*0.15 + 70*0.10 + 60*0.15 + 50*0.15
    score = compute_overall_score(100, 90, 80, 70, 60, 50)
    assert score == 78  # 25+18+12+7+9+7.5 = 78.5 → round 78? Python round(78.5)=78 (banker's) — see below


def test_weights_exact() -> None:
    assert compute_overall_score(100, 100, 100, 100, 100, 100) == 100
    assert compute_overall_score(0, 0, 0, 0, 0, 0) == 0


def test_hook_weight_dominates() -> None:
    # Hook carries 25%: 84 vs 24 hook changes the overall by exactly 15.
    # (Values chosen to avoid banker's-rounding half-cases.)
    strong = compute_overall_score(84, 72, 72, 72, 72, 72)
    weak = compute_overall_score(24, 72, 72, 72, 72, 72)
    assert strong == 75
    assert weak == 60
    assert strong - weak == 15
