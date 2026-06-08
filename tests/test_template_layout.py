from app.components.template_form import _cols_from_peeked_labels, _header_row_chunks


def test_cols_all_short() -> None:
    assert _cols_from_peeked_labels(["a"] * 10) == 11


def test_cols_over_10_chars() -> None:
    assert _cols_from_peeked_labels(["a"] * 9 + ["Container Seal No."]) == 9


def test_cols_over_20_chars() -> None:
    label_21 = "Product Description X"
    assert _cols_from_peeked_labels(["a"] * 9 + [label_21]) == 7


def test_cols_over_30_chars() -> None:
    label_31 = "A" * 31
    assert _cols_from_peeked_labels(["a"] * 9 + [label_31]) == 5


def test_sequential_peek_advances_position() -> None:
    headers = [f"f{i}" for i in range(10)] + ["Container Seal No."] + [f"g{i}" for i in range(6)] + [
        "Product Description X"
    ] + ["tail0", "tail1"]
    assert len(headers) == 20
    rows = _header_row_chunks(headers)
    assert [len(row) for row in rows] == [11, 7, 2]
    assert rows[0][0][0] == 0
    assert rows[1][0][0] == 11
    assert rows[2][0][0] == 18
