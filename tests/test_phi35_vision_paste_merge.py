from app.services.phi35_vision_paste_infer import (
    _fill_missing_logistics_fields,
    _merge_mapping_configs,
)

GINGER_HEADERS = [
    "order",
    "YY",
    "MM",
    "DD",
    "P.O. No.",
    "Container No.",
    "Container Seal No.",
    "Lot No.",
    "Receiving Date",
    "Product Description",
    "Supplier",
    "Truck Line",
]


def test_merge_mapping_configs_combines_targets() -> None:
    configs = [
        {
            "delimiter": "tab",
            "index_base": 1,
            "fields": [{"target": "P.O. No.", "index": 1}],
        },
        {
            "delimiter": "tab",
            "index_base": 1,
            "fields": [{"target": "Supplier", "index": 3}],
        },
    ]
    merged = _merge_mapping_configs(configs)
    targets = {rule["target"] for rule in merged["fields"] if "target" in rule}
    assert targets == {"P.O. No.", "Supplier"}


def test_fill_missing_logistics_fields_adds_po_and_product() -> None:
    merged = {
        "delimiter": "tab",
        "index_base": 1,
        "fields": [
            {"target": "Supplier", "index": 3},
            {"target": "Container No.", "index": 5},
            {
                "index": 13,
                "split": "/",
                "fields": [{"target": "MM", "index": 1}],
                "derive": {"target": "Receiving Date", "from": ["MM", "DD"]},
            },
        ],
    }
    filled = _fill_missing_logistics_fields(merged, GINGER_HEADERS)
    targets = {
        rule["target"]
        for rule in filled["fields"]
        if isinstance(rule, dict) and rule.get("target")
    }
    assert "P.O. No." in targets
    assert "Product Description" in targets
