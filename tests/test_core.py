import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core import calculate_case, document_check, load_json, FEE_MASTER_PATH, REGION_MAPPING_PATH

fee_master = load_json(FEE_MASTER_PATH)
region_mapping = {r["region_name"]: r["group"] for r in load_json(REGION_MAPPING_PATH)}


def loc(
    location_id: str,
    distance_km_round_trip: float,
    normalized_address: str,
    product_count: int = 1,
    capacity_group: str = "",
    region_name: str = "",
    weight_certificate_present: bool = False,
    fee_exclusion_override: bool = False,
):
    return {
        "location_id": location_id,
        "distance_km_round_trip": distance_km_round_trip,
        "normalized_address": normalized_address,
        "product_count": product_count,
        "capacity_group": capacity_group,
        "region_name": region_name,
        "weight_certificate_present": weight_certificate_present,
        "fee_exclusion_override": fee_exclusion_override,
    }


# ---------------------------
# 1) Manufacturing inspection
# ---------------------------
def test_manufacturing_single_location_only():
    payload = {
        "case_id": "m-1",
        "inspection_type": "manufacturing",
        "locations": [loc("A", 120, "addr-a", capacity_group="up_to_30_ton")],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    row = result["location_results"][0]
    assert row["adjustment_40"] == 0
    assert row["additional_30"] == 0


def test_manufacturing_multi_location_farthest_100_others_40():
    payload = {
        "case_id": "m-2",
        "inspection_type": "manufacturing",
        "locations": [
            loc("F", 280, "a", capacity_group="up_to_30_ton"),  # farthest
            loc("B", 200, "b", capacity_group="up_to_30_ton"),
            loc("C", 100, "c", capacity_group="up_to_30_ton"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    rows = {r["location_id"]: r for r in result["location_results"]}
    assert rows["F"]["adjustment_40"] == 0
    assert rows["B"]["adjustment_40"] < 0
    assert rows["C"]["adjustment_40"] < 0


def test_manufacturing_same_address_multiple_units_no_same_address_surcharge():
    payload = {
        "case_id": "m-3",
        "inspection_type": "manufacturing",
        "locations": [
            loc("A", 180, "same", capacity_group="up_to_30_ton"),
            loc("B", 170, "same", capacity_group="up_to_30_ton"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert all(x["same_address_surcharge"] == 0 for x in result["location_results"])


def test_manufacturing_distance_exactly_300_no_30_percent_addition():
    payload = {
        "case_id": "m-4",
        "inspection_type": "manufacturing",
        "locations": [loc("A", 300, "addr-a", capacity_group="up_to_30_ton")],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["location_results"][0]["additional_30"] == 0


def test_manufacturing_distance_over_300_add_30_percent():
    payload = {
        "case_id": "m-5",
        "inspection_type": "manufacturing",
        "locations": [loc("A", 301, "addr-a", capacity_group="up_to_30_ton")],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["location_results"][0]["additional_30"] > 0


def test_manufacturing_weight_certificate_excludes_fee():
    payload = {
        "case_id": "m-6",
        "inspection_type": "manufacturing",
        "locations": [
            loc(
                "A",
                150,
                "addr-a",
                capacity_group="up_to_30_ton",
                weight_certificate_present=True,
            )
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["equipment_usage_fee_total"] == 0


# ----------------
# 2) Reinspection
# ----------------
def test_reinspection_single_location():
    payload = {
        "case_id": "r-1",
        "inspection_type": "reinspection",
        "locations": [loc("A", 50, "a", region_name="서울")],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["equipment_usage_fee_total"] > 0
    assert result["location_results"][0]["same_address_surcharge"] == 0


def test_reinspection_same_address_2_units_one_surcharge():
    payload = {
        "case_id": "r-2",
        "inspection_type": "reinspection",
        "locations": [
            loc("A", 50, "same", region_name="서울"),
            loc("B", 50, "same", region_name="서울"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert sum(x["same_address_surcharge"] for x in result["location_results"]) == 100000


def test_reinspection_same_address_3_units_two_surcharge():
    payload = {
        "case_id": "r-3",
        "inspection_type": "reinspection",
        "locations": [
            loc("A", 50, "same", region_name="서울"),
            loc("B", 50, "same", region_name="서울"),
            loc("C", 50, "same", region_name="서울"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert sum(x["same_address_surcharge"] for x in result["location_results"]) == 200000


def test_reinspection_different_addresses_no_surcharge():
    payload = {
        "case_id": "r-4",
        "inspection_type": "reinspection",
        "locations": [
            loc("A", 50, "addr-1", region_name="서울"),
            loc("B", 50, "addr-2", region_name="서울"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert all(x["same_address_surcharge"] == 0 for x in result["location_results"])


def test_reinspection_mixed_same_and_different_addresses():
    payload = {
        "case_id": "r-5",
        "inspection_type": "reinspection",
        "locations": [
            loc("A", 50, "same", region_name="서울"),
            loc("B", 50, "same", region_name="서울"),
            loc("C", 50, "diff", region_name="서울"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert sum(x["same_address_surcharge"] for x in result["location_results"]) == 100000


def test_reinspection_address_normalization_exact_match_only():
    payload = {
        "case_id": "r-6",
        "inspection_type": "reinspection",
        "locations": [
            loc("A", 50, "서울시 강남구 테헤란로 1", region_name="서울"),
            loc("B", 50, "서울시 강남구 테헤란로1", region_name="서울"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert sum(x["same_address_surcharge"] for x in result["location_results"]) == 0


# -------------------
# 3) Mixed inspection
# -------------------
def test_mixed_always_uses_reinspection_logic():
    payload = {
        "case_id": "x-1",
        "inspection_type": "mixed",
        "locations": [
            loc("A", 50, "same", region_name="서울"),
            loc("B", 50, "same", region_name="서울"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["effective_inspection_type"] == "reinspection"
    assert sum(x["same_address_surcharge"] for x in result["location_results"]) == 100000


def test_mixed_lodging_always_zero():
    payload = {
        "case_id": "x-2",
        "inspection_type": "mixed",
        "locations": [loc("A", 500, "a", region_name="서울")],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["lodging_nights"] == 0


def test_mixed_never_applies_manufacturing_adjustment_40():
    payload = {
        "case_id": "x-3",
        "inspection_type": "mixed",
        "locations": [
            loc("A", 400, "a", region_name="서울"),
            loc("B", 200, "b", region_name="서울"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert all(x["adjustment_40"] == 0 for x in result["location_results"])


# ------------------
# 4) Travel day rules
# ------------------
def test_travel_same_address_4_units_1_day():
    payload = {
        "case_id": "t-1",
        "inspection_type": "reinspection",
        "locations": [loc(str(i), 10, "same", product_count=1, region_name="서울") for i in range(4)],
    }
    assert calculate_case(payload, fee_master, region_mapping)["travel_days"] == 1


def test_travel_same_address_5_units_2_days():
    payload = {
        "case_id": "t-2",
        "inspection_type": "reinspection",
        "locations": [loc(str(i), 10, "same", product_count=1, region_name="서울") for i in range(5)],
    }
    assert calculate_case(payload, fee_master, region_mapping)["travel_days"] == 2


def test_travel_different_addresses_exactly_30km_is_not_trigger():
    payload = {
        "case_id": "t-3",
        "inspection_type": "reinspection",
        "max_distance_between_locations_km": 30,
        "locations": [
            loc("A", 20, "a", product_count=1, region_name="서울"),
            loc("B", 20, "b", product_count=1, region_name="서울"),
        ],
    }
    assert calculate_case(payload, fee_master, region_mapping)["travel_days"] == 1


def test_travel_different_addresses_31km_trigger():
    payload = {
        "case_id": "t-4",
        "inspection_type": "reinspection",
        "max_distance_between_locations_km": 31,
        "locations": [
            loc("A", 20, "a", product_count=1, region_name="서울"),
            loc("B", 20, "b", product_count=1, region_name="서울"),
        ],
    }
    assert calculate_case(payload, fee_master, region_mapping)["travel_days"] == 2


def test_travel_total_product_count_4_across_locations_2_days():
    payload = {
        "case_id": "t-5",
        "inspection_type": "reinspection",
        "max_distance_between_locations_km": 5,
        "locations": [
            loc("A", 20, "a", product_count=2, region_name="서울"),
            loc("B", 20, "b", product_count=2, region_name="서울"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["travel_days"] == 2
    assert "product_count_over_4" in result["travel_reasons"]


# -----------------
# 5) Document check
# -----------------
def test_document_online_omit_consent_ok():
    res = document_check(
        {
            "applicant_type": "manufacturer_or_repair_company",
            "online_application": True,
            "document_scale_verification_application": True,
            "document_business_registration": True,
            "document_invoice_company_info": True,
            "document_personal_information_consent": False,
            "kc_mark_present": True,
        }
    )
    assert "document_personal_information_consent" not in res.missing_document_list


def test_document_weighing_company_missing_self_inspection_sheet():
    res = document_check(
        {
            "applicant_type": "weighing_certificate_company_or_other",
            "online_application": False,
            "document_scale_verification_application": True,
            "document_business_registration": True,
            "document_invoice_company_info": True,
            "document_personal_information_consent": True,
            "document_weighing_certificate_business_registration": True,
            "document_self_inspection_sheet": False,
            "document_self_inspection_signature": True,
            "document_scale_nameplate_photo": True,
            "kc_mark_present": True,
        }
    )
    assert "document_self_inspection_sheet" in res.missing_document_list


def test_document_self_inspection_sheet_without_signature():
    res = document_check(
        {
            "applicant_type": "weighing_certificate_company_or_other",
            "online_application": False,
            "document_scale_verification_application": True,
            "document_business_registration": True,
            "document_invoice_company_info": True,
            "document_personal_information_consent": True,
            "document_weighing_certificate_business_registration": True,
            "document_self_inspection_sheet": True,
            "document_self_inspection_signature": False,
            "document_scale_nameplate_photo": True,
            "kc_mark_present": True,
        }
    )
    assert "document_self_inspection_signature" in res.missing_document_list
    assert any("서명 누락" in x.message for x in res.decision_log)


def test_document_missing_kc_mark_warning():
    res = document_check(
        {
            "applicant_type": "manufacturer_or_repair_company",
            "online_application": False,
            "document_scale_verification_application": True,
            "document_business_registration": True,
            "document_invoice_company_info": True,
            "document_personal_information_consent": True,
            "kc_mark_present": False,
        }
    )
    assert res.warnings
    assert "KC mark not confirmed" in res.warnings[0]


def test_document_weight_certificate_note():
    res = document_check(
        {
            "applicant_type": "manufacturer_or_repair_company",
            "online_application": False,
            "document_scale_verification_application": True,
            "document_business_registration": True,
            "document_invoice_company_info": True,
            "document_personal_information_consent": True,
            "kc_mark_present": True,
            "document_weight_certificate": True,
        }
    )
    assert res.notes
    assert "Equipment usage fee may be excluded" in res.notes[0]


# --------------------------------
# 6) Decision log and reception memo
# --------------------------------
def test_decision_log_and_reception_memo_generated_with_korean_text():
    payload = {
        "case_id": "memo-1",
        "applicant_type": "manufacturer_or_repair_company",
        "inspection_type": "manufacturing",
        "document_payload": {
            "applicant_type": "manufacturer_or_repair_company",
            "online_application": False,
            "document_scale_verification_application": True,
            "document_business_registration": False,
            "document_invoice_company_info": True,
            "document_personal_information_consent": False,
            "kc_mark_present": False,
            "document_weight_certificate": True,
        },
        "locations": [
            loc("A", 350, "A", product_count=2, capacity_group="up_to_30_ton"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["decision_log"]
    assert "[접수 메모]" in result["reception_memo"]
    assert "누락 서류" in result["reception_memo"]
    assert any("수수료계산" in x["category"] for x in result["decision_log"])
    assert any("출장" in x["category"] for x in result["decision_log"])


def test_decision_log_reasoning_matches_calculation_result_for_mixed():
    payload = {
        "case_id": "memo-2",
        "inspection_type": "mixed",
        "locations": [loc("A", 400, "same", region_name="서울"), loc("B", 400, "same", region_name="서울")],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["effective_inspection_type"] == "reinspection"
    assert any("혼합검정은 정책상 재검정 로직" in x["message"] for x in result["decision_log"])


# ---------------------------
# Integration-style full flows
# ---------------------------
def test_integration_full_manufacturing_case():
    payload = {
        "case_id": "int-m",
        "applicant_type": "manufacturer_or_repair_company",
        "inspection_type": "manufacturing",
        "max_distance_between_locations_km": 40,
        "document_payload": {
            "applicant_type": "manufacturer_or_repair_company",
            "online_application": False,
            "document_scale_verification_application": True,
            "document_business_registration": True,
            "document_invoice_company_info": True,
            "document_personal_information_consent": True,
            "kc_mark_present": True,
        },
        "locations": [
            loc("A", 440, "a", product_count=2, capacity_group="up_to_30_ton"),
            loc("B", 200, "b", product_count=1, capacity_group="up_to_30_ton"),
            loc("C", 180, "c", product_count=1, capacity_group="up_to_30_ton"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["lodging_nights"] == 1
    assert result["travel_days"] == 2
    assert result["equipment_usage_fee_total"] > 0


def test_integration_full_reinspection_case():
    payload = {
        "case_id": "int-r",
        "inspection_type": "reinspection",
        "max_distance_between_locations_km": 10,
        "locations": [
            loc("A", 60, "same", product_count=1, region_name="서울"),
            loc("B", 60, "same", product_count=1, region_name="서울"),
            loc("C", 60, "diff", product_count=1, region_name="서울"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert sum(x["same_address_surcharge"] for x in result["location_results"]) == 100000
    assert result["lodging_nights"] == 0


def test_integration_full_mixed_case():
    payload = {
        "case_id": "int-x",
        "inspection_type": "mixed",
        "max_distance_between_locations_km": 31,
        "locations": [
            loc("A", 350, "x1", product_count=2, region_name="서울"),
            loc("B", 120, "x2", product_count=2, region_name="서울"),
        ],
    }
    result = calculate_case(payload, fee_master, region_mapping)
    assert result["effective_inspection_type"] == "reinspection"
    assert result["lodging_nights"] == 0
    assert result["travel_days"] == 2
