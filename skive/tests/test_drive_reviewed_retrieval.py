"""Facts a person confirmed must reach writing even when search words do not match."""

from skive.drive_reviewed_retrieval import reviewed_facts


class FakeConnection:
    def __init__(self):
        self.queries = []

    def execute(self, query, params):
        self.queries.append(query)
        rows = [] if "ilike" in query else [{"id": 1, "content": "F1 0.2254"}]
        return type("Result", (), {"fetchall": lambda _: rows})()


def test_writing_falls_back_to_confirmed_facts_across_languages():
    facts = reviewed_facts(FakeConnection(), ["성능", "수치"], all_if_unmatched=True)
    assert [fact["content"] for fact in facts] == ["F1 0.2254"]


def test_search_stays_narrow_by_default():
    assert reviewed_facts(FakeConnection(), ["성능", "수치"]) == []
