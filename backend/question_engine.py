def generate_next_questions(differential, missed):
    questions = []

    # From differential
    for d in differential.get("differentials", [])[:2]:
        questions.extend(d.get("least_risky_next_checks", []))

    # From missed signals
    questions.extend(missed.get("questions_to_ask_now", []))

    # Deduplicate
    seen = set()
    deduped = []
    for q in questions:
        if not q or q in seen:
            continue
        seen.add(q)
        deduped.append(q)

    return {
        "next_best_questions": deduped[:5]
    }