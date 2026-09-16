from app.ai.memory.service import extract_candidates


def test_extracts_high_priority_allergy_memory():
    result = extract_candidates([{"role": "user", "content": "我对花生过敏"}])

    assert result == [{
        "type": "constraint",
        "subject": "user",
        "predicate": "allergic_to",
        "value": "花生",
        "importance": 100,
        "confidence": 0.9,
        "source_message": "我对花生过敏",
    }]


def test_ignores_assistant_guess_and_extracts_preference():
    result = extract_candidates([
        {"role": "assistant", "content": "你可能喜欢泰国菜"},
        {"role": "user", "content": "我喜欢泰国菜"},
    ])

    assert len(result) == 1
    assert result[0]["predicate"] == "prefers"
    assert result[0]["value"] == "泰国菜"
