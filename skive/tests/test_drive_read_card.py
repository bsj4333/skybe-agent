from types import SimpleNamespace

from skive.drive_read_card import build_read_card


def test_read_card_keeps_source_locations_and_labels_raw_numbers():
    chunks = [
        SimpleNamespace(location="L10-12", text="목표: 불량 12% 감소\n작업 수: 30건"),
        SimpleNamespace(location="sheet SCM rows 1-2", text="A1: BOM\nB2: 42개"),
        SimpleNamespace(location="p.3 annotation 1", text="수치 7은 확인 필요"),
    ]
    card = build_read_card(chunks, {"supplemental": [{"kind": "pdf_annotations"}]})
    assert card["status"] == "ready"
    assert card["chunk_count"] == 3
    assert card["quote_count"] == 5
    assert [item["location"] for item in card["quote_samples"]] == [
        "L10", "L11", "sheet SCM rows 1-2 · A1", "sheet SCM rows 1-2 · B2",
        "p.3 annotation 1",
    ]
    assert [(item["value"], item["location"]) for item in card["number_samples"]] == [
        ("12%", "L10"), ("30건", "L11"), ("42개", "sheet SCM rows 1-2 · B2"),
        ("7", "p.3 annotation 1"),
    ]


def test_read_card_samples_head_and_tail_but_counts_every_line():
    chunks = [SimpleNamespace(location=f"L{i}-1", text=f"항목 {i}") for i in range(1, 101)]
    card = build_read_card(chunks)
    assert card["quote_count"] == card["number_count"] == 100
    assert len(card["quote_samples"]) == len(card["number_samples"]) == 40
    assert [sample["chunk_index"] for sample in card["quote_samples"]] == list(range(1, 21)) + list(range(81, 101))
