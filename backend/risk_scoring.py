LIKELIHOOD = {
    "low": 1,
    "medium": 2,
    "high": 3,
}

DANGER = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

CHECK_SAFETY = {
    "high": 1,      # very safe check
    "medium": 2,
    "low": 3,       # risky / invasive / unavailable
}


def normalize_label(value: str | None, default: str) -> str:
    if not value:
        return default
    return value.strip().lower()


def score_differential(item: dict) -> dict:
    likelihood = normalize_label(item.get("likelihood"), "medium")
    danger = normalize_label(item.get("danger_if_missed"), "medium")
    check_safety = normalize_label(item.get("least_risky_check_safety"), "medium")

    likelihood_score = LIKELIHOOD.get(likelihood, 2)
    danger_score = DANGER.get(danger, 2)
    check_cost = CHECK_SAFETY.get(check_safety, 2)

    priority_score = (1.2 * likelihood_score) + (2.0 * danger_score) - (0.7 * check_cost)

    enriched = dict(item)
    enriched["priority_score"] = round(priority_score, 2)

    if danger_score >= 4:
        enriched["priority_category"] = "critical rule-out"
    elif priority_score >= 7:
        enriched["priority_category"] = "high priority"
    elif priority_score >= 5:
        enriched["priority_category"] = "moderate priority"
    else:
        enriched["priority_category"] = "lower priority"

    return enriched


def rank_differentials(differentials: list[dict]) -> list[dict]:
    if not isinstance(differentials, list):
        return []
    scored = [score_differential(item) for item in differentials if isinstance(item, dict)]
    return sorted(scored, key=lambda x: x["priority_score"], reverse=True)