from pathlib import Path

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from core import (
    DEPOSIT_INFO,
    FEE_MASTER_PATH,
    REGION_MAPPING_PATH,
    ValidationError,
    calculate_case,
    document_check,
    load_json,
    save_json,
)

st.set_page_config(page_title="저울 검정 내부 확인 도구", layout="wide")
st.title("저울 검정 내부 확인 도구")
st.caption("내부 접수 담당자 전용 도구 (저장 기능 없음)")

MENU_DOC = "신청서류 확인"
MENU_CALC = "검정비 계산"
MENU_ADMIN = "관리자"

APPLICANT_OPTIONS = {
    "제조사/수리업체": "manufacturer_or_repair_company",
    "계량증명업체/기타": "weighing_certificate_company_or_other",
}
INSPECTION_OPTIONS = {
    "제작검정": "manufacturing",
    "재검정": "reinspection",
    "제작 + 재검": "mixed",
}
CAPACITY_OPTIONS = {
    "선택": "",
    "30톤 이하": "up_to_30_ton",
    "31톤 이상": "over_31_ton",
}
DOC_FIELD_LABELS = {
    "document_scale_verification_application": "검정신청서",
    "document_personal_information_consent": "개인정보동의서",
    "document_business_registration": "사업자등록증",
    "document_invoice_company_info": "세금계산서 업체정보",
    "document_weight_certificate": "분동성적서",
    "document_weighing_certificate_business_registration": "계량증명업 사업자등록증",
    "document_self_inspection_sheet": "자체점검표",
    "document_self_inspection_signature": "자체점검표 서명",
    "document_scale_nameplate_photo": "저울 명판사진",
    "kc_mark_present": "KC 마크 확인",
}

if "latest_document_payload" not in st.session_state:
    st.session_state.latest_document_payload = {}
if "latest_calc_result" not in st.session_state:
    st.session_state.latest_calc_result = None
if "manual_overrides" not in st.session_state:
    st.session_state.manual_overrides = []

fee_master = load_json(FEE_MASTER_PATH)
region_rows = load_json(REGION_MAPPING_PATH)
region_mapping = {r["region_name"]: r["group"] for r in region_rows}

menu = st.sidebar.radio("메뉴", [MENU_DOC, MENU_CALC, MENU_ADMIN])

if menu == MENU_DOC:
    st.header("1) 신청서류 확인")
    if st.button("초기화", key="reset_doc"):
        st.session_state.clear()
        st.rerun()

    applicant_label = st.selectbox("신청업체 유형", list(APPLICANT_OPTIONS.keys()))
    online = st.checkbox("온라인 접수 여부", value=False)

    cols = st.columns(2)
    docs = {}
    for i, field in enumerate(DOC_FIELD_LABELS):
        docs[field] = cols[i % 2].checkbox(DOC_FIELD_LABELS[field], value=(field == "kc_mark_present"))

    if st.button("서류 확인"):
        payload = {
            "applicant_type": APPLICANT_OPTIONS[applicant_label],
            "online_application": online,
            **docs,
        }
        st.session_state.latest_document_payload = payload
        res = document_check(payload)

        st.subheader("서류 확인 결과")
        st.write("누락서류", [DOC_FIELD_LABELS.get(x, x) for x in res.missing_document_list])
        st.write("경고", res.warnings)
        st.write("참고", res.notes)
        st.info(f"입금계좌: {DEPOSIT_INFO['bank']} {DEPOSIT_INFO['account']} ({DEPOSIT_INFO['branch']})")

        st.subheader("판단 로그")
        st.dataframe(pd.DataFrame([x.__dict__ for x in res.decision_log]), use_container_width=True)

elif menu == MENU_CALC:
    st.header("2) 검정비 계산")
    if st.button("초기화", key="reset_calc"):
        st.session_state.clear()
        st.rerun()

    case_id = st.text_input("접수번호", "CASE-001")
    applicant_label = st.selectbox("신청업체 유형", list(APPLICANT_OPTIONS.keys()))
    inspection_label = st.selectbox("검정 유형", list(INSPECTION_OPTIONS.keys()))
    max_between_locations = st.number_input("현장 간 최대 거리(km)", min_value=0.0, value=0.0)

    include_doc = st.checkbox("서류 확인 결과를 계산/로그에 포함", value=True)
    doc_payload = st.session_state.latest_document_payload if include_doc else {}

    location_count = st.number_input("장소 수", min_value=1, max_value=10, value=1, step=1)
    locations = []
    st.session_state.manual_overrides = []

    for i in range(int(location_count)):
        with st.expander(f"장소 {i + 1}", expanded=True):
            l_id = st.text_input(f"장소 ID {i + 1}", f"L{i+1}")
            addr = st.text_input(f"주소 {i + 1}", "")
            norm = st.text_input(f"정규화 주소 {i + 1}", "")
            dist = st.number_input(f"왕복 거리(km) {i + 1}", min_value=0.0, value=0.0)
            pc = st.number_input(f"제품 수 {i + 1}", min_value=0, value=1)
            cap_label = st.selectbox(f"용량 구분 {i + 1}", list(CAPACITY_OPTIONS.keys()))
            region = st.selectbox(f"지역 {i + 1}", [""] + list(region_mapping.keys()))
            wc = st.checkbox(f"분동성적서 제출 {i + 1}", value=False)
            same_override = st.checkbox(f"동일주소 수동 분리 {i + 1}", value=False)
            fee_excl = st.checkbox(f"사용설비수수료 제외 수동처리 {i + 1}", value=False)

            if same_override:
                st.session_state.manual_overrides.append(
                    {
                        "field": f"same_address_group_{l_id}",
                        "before": "auto",
                        "after": "manual",
                        "by": "staff",
                        "at": pd.Timestamp.now().isoformat(),
                    }
                )
            if fee_excl:
                st.session_state.manual_overrides.append(
                    {
                        "field": f"fee_exclusion_{l_id}",
                        "before": "false",
                        "after": "true",
                        "by": "staff",
                        "at": pd.Timestamp.now().isoformat(),
                    }
                )

            locations.append(
                {
                    "location_id": l_id,
                    "inspection_type": INSPECTION_OPTIONS[inspection_label],
                    "address": addr,
                    "normalized_address": norm if not same_override else f"MANUAL_{l_id}",
                    "distance_km_round_trip": dist,
                    "product_count": pc,
                    "capacity_group": CAPACITY_OPTIONS[cap_label],
                    "region_name": region,
                    "weight_certificate_present": wc,
                    "fee_exclusion_override": fee_excl,
                }
            )

    case_payload = {
        "case_id": case_id,
        "applicant_type": APPLICANT_OPTIONS[applicant_label],
        "inspection_type": INSPECTION_OPTIONS[inspection_label],
        "max_distance_between_locations_km": max_between_locations,
        "document_payload": doc_payload,
        "locations": locations,
        "manual_overrides": st.session_state.manual_overrides,
    }

    if st.button("검정비 계산"):
        try:
            result = calculate_case(case_payload, fee_master, region_mapping)
            st.session_state.latest_calc_result = {"result": result, "case_id": case_id}
            st.success("검정비 계산이 완료되었습니다.")
        except ValidationError:
            st.error("오류가 발생했습니다. 입력값을 확인해주세요.")

    calc_state = st.session_state.latest_calc_result
    if calc_state and calc_state.get("case_id") == case_id:
        result = calc_state["result"]

        st.subheader("검정 결과 요약")
        c1, c2, c3 = st.columns(3)
        c1.metric("사용설비수수료", f"{result['equipment_usage_fee_total']:,} 원")
        c2.metric("출장일수", f"{result['travel_days']} 일")
        c3.metric("숙박 여부", "적용" if result["lodging_nights"] > 0 else "미적용")
        st.write("계산 참고사항", result.get("calculation_notes") or [])

        st.subheader("장소별 계산 내역")
        loc_df = pd.DataFrame(result["location_results"])
        st.dataframe(loc_df, use_container_width=True)

        st.subheader("서류 확인 결과")
        doc_result = result.get("document_check") or {}
        st.write(
            {
                "누락서류": doc_result.get("missing_document_list", []),
                "경고": doc_result.get("warnings", []),
                "참고": doc_result.get("notes", []),
            }
        )

        st.subheader("판단 로그")
        log_df = pd.DataFrame(result["decision_log"])
        st.dataframe(log_df, use_container_width=True)

        st.subheader("접수 메모")
        st.text_area("접수 메모", value=result["reception_memo"], height=220)
        st.code(result["reception_memo"], language="text")

        excel_path = Path("exports") / f"{case_id}.xlsx"
        pdf_path = Path("exports") / f"{case_id}.pdf"
        excel_path.parent.mkdir(exist_ok=True)

        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            loc_df.to_excel(writer, sheet_name="locations", index=False)
            pd.DataFrame(
                [
                    {
                        "case_id": result["case_id"],
                        "equipment_usage_fee_total": result["equipment_usage_fee_total"],
                        "travel_days": result["travel_days"],
                        "lodging_nights": result["lodging_nights"],
                        "reception_memo": result["reception_memo"],
                    }
                ]
            ).to_excel(writer, sheet_name="summary", index=False)
            log_df.to_excel(writer, sheet_name="decision_log", index=False)

        c = canvas.Canvas(str(pdf_path), pagesize=A4)
        y = 800
        c.drawString(40, y, f"case_id: {result['case_id']}")
        y -= 20
        c.drawString(40, y, f"equipment_usage_fee_total: {result['equipment_usage_fee_total']}")
        y -= 20
        c.drawString(40, y, f"travel_days: {result['travel_days']} / lodging_nights: {result['lodging_nights']}")
        y -= 30
        c.drawString(40, y, "reception memo")
        for line in result["reception_memo"].split("\n")[:10]:
            y -= 16
            c.drawString(40, y, line[:90])
        y -= 20
        c.drawString(40, y, "decision log")
        for row in result["decision_log"][:18]:
            y -= 16
            c.drawString(40, y, f"[{row['category']}] {row['message'][:80]}")
            if y < 60:
                c.showPage()
                y = 800
        c.save()

        st.download_button("엑셀 다운로드", data=excel_path.read_bytes(), file_name=excel_path.name)
        st.download_button("PDF 다운로드", data=pdf_path.read_bytes(), file_name=pdf_path.name)

else:
    st.header("3) 관리자")
    st.caption("요율표 / 지역 매핑 편집")

    if st.button("초기화", key="reset_admin"):
        st.rerun()

    st.subheader("요율표")
    fee_df = pd.DataFrame(fee_master)
    edited_fee = st.data_editor(fee_df, num_rows="dynamic", use_container_width=True)

    st.subheader("지역 매핑")
    region_df = pd.DataFrame(region_rows)
    edited_region = st.data_editor(region_df, num_rows="dynamic", use_container_width=True)

    if st.button("저장"):
        save_json(FEE_MASTER_PATH, edited_fee.to_dict(orient="records"))
        save_json(REGION_MAPPING_PATH, edited_region.to_dict(orient="records"))
        st.success("저장되었습니다.")
