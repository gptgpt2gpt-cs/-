from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
FEE_MASTER_PATH = DATA_DIR / "fee_master.json"
REGION_MAPPING_PATH = DATA_DIR / "region_mapping.json"


DEPOSIT_INFO = {
    "bank": "국민은행",
    "account": "096-01-0034-207",
    "branch": "분당",
}


@dataclass
class DecisionEntry:
    category: str
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


@dataclass
class DocumentCheckResult:
    missing_document_list: list[str]
    warnings: list[str]
    notes: list[str]
    present_documents: list[str]
    required_documents: list[str]
    decision_log: list[DecisionEntry]


class ValidationError(Exception):
    pass


def load_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def document_check(payload: dict[str, Any]) -> DocumentCheckResult:
    decision_log: list[DecisionEntry] = []
    required = [
        "document_scale_verification_application",
        "document_business_registration",
        "document_invoice_company_info",
    ]
    if not payload.get("online_application", False):
        required.append("document_personal_information_consent")
        decision_log.append(DecisionEntry("서류검토", "오프라인 접수이므로 개인정보동의서 필수"))
    else:
        decision_log.append(DecisionEntry("서류검토", "온라인 접수이므로 개인정보동의서 생략 가능"))

    if payload.get("applicant_type") == "weighing_certificate_company_or_other":
        required.extend(
            [
                "document_weighing_certificate_business_registration",
                "document_self_inspection_sheet",
                "document_self_inspection_signature",
                "document_scale_nameplate_photo",
            ]
        )
        decision_log.append(
            DecisionEntry(
                "서류검토",
                "계량증명업체/기타 유형으로 판단되어 계량증명업 사업자등록증, 자체점검표, 서명, 명판사진 필수",
            )
        )

    missing = [doc for doc in required if not payload.get(doc, False)]
    present = [doc for doc in required if payload.get(doc, False)]

    warnings: list[str] = []
    notes: list[str] = []

    if not payload.get("kc_mark_present", True):
        warnings.append("KC mark not confirmed → must apply as manufacturing inspection through manufacturer")
        decision_log.append(DecisionEntry("서류검토", "KC 마크 미확인: 제조검정(제조사 경유) 안내 필요"))
    else:
        decision_log.append(DecisionEntry("서류검토", "KC 마크 확인 완료"))

    if payload.get("document_weight_certificate", False):
        notes.append("Equipment usage fee may be excluded depending on internal review")
        decision_log.append(DecisionEntry("서류검토", "추 분동 성적서 제출됨: 장비사용료 제외 여부 내부검토 필요"))
    else:
        decision_log.append(DecisionEntry("서류검토", "추 분동 성적서 미제출"))

    if payload.get("applicant_type") == "weighing_certificate_company_or_other" and not payload.get(
        "document_self_inspection_signature", False
    ):
        decision_log.append(DecisionEntry("서류검토", "자체점검표 서명 누락"))

    for m in missing:
        decision_log.append(DecisionEntry("서류검토", f"필수서류 누락: {m}"))

    return DocumentCheckResult(missing, warnings, notes, present, required, decision_log)


def lookup_base_fee(
    fee_master: list[dict[str, Any]],
    distance_km: float,
    capacity_group: str,
    inspection_type: str,
    region_name: str | None,
    region_mapping: dict[str, str],
) -> tuple[int, str]:
    rows = sorted(fee_master, key=lambda x: x["distance_km"])
    matched = None
    for row in rows:
        if distance_km <= float(row["distance_km"]):
            matched = row
            break
    if matched is None and rows:
        matched = rows[-1]
    if matched is None:
        raise ValidationError("요율표 데이터가 없습니다.")

    if inspection_type == "manufacturing":
        if not capacity_group:
            raise ValidationError("manufacturing은 capacity_group이 필요합니다.")
        return int(matched["manufacturing_fee"][capacity_group]), f"거리 {distance_km}km / 용량 {capacity_group} 제조검정 요율 적용"

    if not region_name:
        raise ValidationError("reinspection/mixed는 region_name이 필요합니다.")
    group = region_mapping.get(region_name)
    if not group:
        raise ValidationError(f"지역 매핑 누락: {region_name}")
    return int(matched[f"reinspection_fee_{group}"]), f"거리 {distance_km}km / 지역 {region_name}({group}) 재검정 요율 적용"


def _max_location_distance(case_payload: dict[str, Any], locations: list[dict[str, Any]]) -> float:
    if case_payload.get("max_distance_between_locations_km") is not None:
        return float(case_payload["max_distance_between_locations_km"])

    pairwise = case_payload.get("pairwise_location_distances_km", [])
    if pairwise:
        return max(float(x) for x in pairwise)

    # fallback: 좌표가 있는 경우 계산 가능하도록 확장 포인트. 현재는 값 없으면 0으로 처리
    return 0.0 if len(locations) <= 1 else 0.0


def generate_reception_memo(
    case_payload: dict[str, Any],
    result: dict[str, Any],
    document_result: DocumentCheckResult | None,
) -> str:
    applicant_type = case_payload.get("applicant_type", "미입력")
    locations = case_payload.get("locations", [])
    total_products = sum(int(loc.get("product_count") or 0) for loc in locations)
    missing_docs = document_result.missing_document_list if document_result else []
    kc_confirmed = "확인" if (case_payload.get("document_payload") or {}).get("kc_mark_present", True) else "미확인"
    lodging_text = "적용" if result["lodging_nights"] > 0 else "미적용"

    lines = [
        "[접수 메모]",
        f"- 신청업체 유형: {applicant_type}",
        f"- 검정유형: {result['inspection_type']} (계산적용: {result['effective_inspection_type']})",
        f"- 장소 수: {len(locations)}",
        f"- 제품 수: {total_products}",
        f"- 누락 서류: {', '.join(missing_docs) if missing_docs else '없음'}",
        f"- KC 확인 여부: {kc_confirmed}",
        f"- 사용설비수수료 계산 요약: 총 {result['equipment_usage_fee_total']:,}원",
        f"- 출장일수: {result['travel_days']}일 ({', '.join(result['travel_reasons']) if result['travel_reasons'] else '기본 1일'})",
        f"- 숙박 적용 여부: {lodging_text} ({result['lodging_nights']}박)",
    ]
    return "\n".join(lines)


def calculate_case(case_payload: dict[str, Any], fee_master: list[dict[str, Any]], region_mapping: dict[str, str]) -> dict[str, Any]:
    decision_log: list[DecisionEntry] = []
    inspection_type = case_payload.get("inspection_type")
    if not inspection_type:
        raise ValidationError("inspection_type 누락")

    locations = case_payload.get("locations", [])
    if not locations:
        raise ValidationError("locations 누락")

    for loc in locations:
        if loc.get("distance_km_round_trip") is None:
            raise ValidationError(f"distance 누락: {loc.get('location_id')}")

    document_payload = case_payload.get("document_payload")
    document_result: DocumentCheckResult | None = None
    if document_payload:
        document_result = document_check(document_payload)
        decision_log.extend(document_result.decision_log)
        decision_log.append(DecisionEntry("서류검토", f"누락서류 개수: {len(document_result.missing_document_list)}"))

    effective_type = "reinspection" if inspection_type == "mixed" else inspection_type
    if inspection_type == "mixed":
        decision_log.append(DecisionEntry("수수료계산", "혼합검정은 정책상 재검정 로직으로 계산"))
    elif inspection_type == "manufacturing":
        decision_log.append(DecisionEntry("수수료계산", "제조검정 규칙(최원거리 100%, 나머지 40%) 적용"))
    else:
        decision_log.append(DecisionEntry("수수료계산", "재검정 규칙(지역요율 + 동일주소 가산) 적용"))

    farthest_location_id = None
    farthest_base = 0
    if inspection_type == "manufacturing":
        farthest = max(locations, key=lambda x: x["distance_km_round_trip"])
        farthest_location_id = farthest["location_id"]
        decision_log.append(DecisionEntry("수수료계산", f"최원거리 현장({farthest_location_id}) 100% 적용"))

    loc_results = []
    total_fee = 0
    normalized_groups: dict[str, list[dict[str, Any]]] = {}
    for loc in locations:
        norm = loc.get("normalized_address") or ""
        normalized_groups.setdefault(norm, []).append(loc)

    for loc in locations:
        base_fee_raw, reason = lookup_base_fee(
            fee_master,
            float(loc["distance_km_round_trip"]),
            loc.get("capacity_group", ""),
            effective_type,
            loc.get("region_name"),
            region_mapping,
        )
        base_fee = base_fee_raw
        adjustment_40 = 0
        additional_30 = 0
        same_addr_surcharge = 0
        explanation = [reason]

        if inspection_type == "manufacturing":
            if loc["location_id"] != farthest_location_id:
                adjusted = int(base_fee_raw * 0.4)
                adjustment_40 = adjusted - base_fee_raw
                base_fee = adjusted
                explanation.append("제조검정 잔여 현장 40% 적용")
                decision_log.append(DecisionEntry("수수료계산", f"{loc['location_id']}: 최원거리 외 현장이라 40% 적용"))
            else:
                farthest_base = base_fee_raw
                explanation.append("제조검정 최원거리 100% 적용")

        if inspection_type == "manufacturing" and float(loc["distance_km_round_trip"]) > 300:
            additional_30 = int(farthest_base * 0.3)
            explanation.append("왕복 300km 초과로 최원거리 기준 30% 가산")
            decision_log.append(DecisionEntry("수수료계산", f"{loc['location_id']}: 왕복 300km 초과로 30% 가산"))

        if effective_type == "reinspection":
            same_group = normalized_groups.get(loc.get("normalized_address") or "", [])
            if len(same_group) > 1:
                idx = [x["location_id"] for x in same_group].index(loc["location_id"])
                if idx > 0:
                    same_addr_surcharge = 100000
                    explanation.append("동일주소 추가 대수 +100,000")
                    decision_log.append(DecisionEntry("수수료계산", f"{loc['location_id']}: 동일주소 추가건 +100,000 가산"))

        loc_fee = base_fee + additional_30 + same_addr_surcharge
        if loc.get("fee_exclusion_override") is True or loc.get("weight_certificate_present") is True:
            explanation.append("추 분동 성적서/수동처리로 장비사용료 제외")
            decision_log.append(DecisionEntry("수수료계산", f"{loc['location_id']}: 장비사용료 제외 처리"))
            loc_fee = 0

        total_fee += loc_fee
        loc_results.append(
            {
                "location_id": loc["location_id"],
                "inspection_type": inspection_type,
                "base_fee": base_fee,
                "adjustment_40": adjustment_40,
                "additional_30": additional_30,
                "same_address_surcharge": same_addr_surcharge,
                "location_fee": loc_fee,
                "calculation_explanation": " / ".join(explanation),
            }
        )

    total_products = sum(int(loc.get("product_count") or 0) for loc in locations)
    non_empty_addresses = [loc.get("normalized_address") for loc in locations if loc.get("normalized_address")]
    same_location_all = len(set(non_empty_addresses)) == 1 and len(non_empty_addresses) == len(locations)
    between_locations_km = _max_location_distance(case_payload, locations)

    travel_reason = []
    if same_location_all:
        travel_days = 2 if total_products >= 5 else 1
        if total_products >= 5:
            travel_reason.append("same_location_over_5")
            decision_log.append(DecisionEntry("출장판정", "동일주소 예외 규칙: 5대 이상이므로 출장 2일"))
        else:
            decision_log.append(DecisionEntry("출장판정", "동일주소 예외 규칙: 4대 이하이므로 출장 1일"))
    else:
        travel_days = 1
        if between_locations_km > 30:
            travel_days = 2
            travel_reason.append("distance_over_30km")
            decision_log.append(DecisionEntry("출장판정", f"현장 간 거리 {between_locations_km}km > 30km 이므로 출장 2일"))
        if total_products >= 4:
            travel_days = 2
            travel_reason.append("product_count_over_4")
            decision_log.append(DecisionEntry("출장판정", f"총 제품수 {total_products}대 >= 4대 이므로 출장 2일"))
        if travel_days == 1:
            decision_log.append(DecisionEntry("출장판정", "거리/제품수 조건 미충족으로 출장 1일"))

    max_round_trip = max(float(loc["distance_km_round_trip"]) for loc in locations)
    lodging_nights = 0
    if inspection_type == "manufacturing" and max_round_trip > 300:
        lodging_nights = 1
        decision_log.append(DecisionEntry("숙박판정", "제조검정 + 왕복 300km 초과로 숙박 1박 적용"))
    else:
        decision_log.append(DecisionEntry("숙박판정", "숙박 조건 미충족(제조검정 300km 초과 아님)"))

    for ov in case_payload.get("manual_overrides", []):
        decision_log.append(
            DecisionEntry(
                "수동변경",
                f"{ov.get('field')} 변경: {ov.get('before')} -> {ov.get('after')} / {ov.get('by')} / {ov.get('at')}",
            )
        )

    result = {
        "case_id": case_payload.get("case_id"),
        "inspection_type": inspection_type,
        "effective_inspection_type": effective_type,
        "location_results": loc_results,
        "equipment_usage_fee_total": total_fee,
        "travel_days": travel_days,
        "travel_reasons": travel_reason,
        "lodging_nights": lodging_nights,
        "calculation_notes": ["수수료는 장비사용료 기준이며 출장/숙박비는 별도"],
        "decision_log": [asdict(x) for x in decision_log],
        "document_check": {
            "missing_document_list": document_result.missing_document_list,
            "warnings": document_result.warnings,
            "notes": document_result.notes,
        }
        if document_result
        else None,
    }
    result["reception_memo"] = generate_reception_memo(case_payload, result, document_result)
    return result
