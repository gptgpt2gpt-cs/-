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
st.caption("내부 접수 담당자 전용 공유 도구 (저장 기능 없음)")

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
    "document_scale_verification_application": "계량기검정신청서",
    "document_personal_information_consent": "개인정보동의서",
    "document_business_registration": "사업자등록증",
    "document_invoice_company_info": "계산서업체 정보",
    "document_weight_certificate": "분동 교정성적서",
    "document_weighing_certificate_business_registration": "계량증명업소 등록증",
    "document_self_inspection_sheet": "자가점검표",
    "document_self_inspection_signature": "자가점검표 서명",
    "document_scale_nameplate_photo": "저울 명판 사진",
    "kc_mark_present": "KC 확인",
}

if "latest_document_payload" not in st.session_state:
    st.session_state.latest_document_payload = {}
if "latest_document_result" not in st.session_state:
    st.session_state.latest_document_result = None
if "latest_calc_result" not in st.session_state:
    st.session_state.latest_calc_result = None

fee_master = load_json(FEE_MASTER_PATH)
region_rows = load_json(REGION_MAPPING_PATH)
region_mapping = {r["region_name"]: r["group"] for r in region_rows}


def reset_page_state() -> None:
    st.session_state.pop("latest_document_payload", None)
    st.session_state.pop("latest_document_result", None)
    st.session_state.pop("latest_calc_result", None)


menu = st.sidebar.radio("메뉴", [MENU_DOC, MENU_CALC, MENU_ADMIN])

if menu == MENU_DOC:
    st.header("신청서류 확인")

    with st.container(border=True):
        st.subheader("SECTION 1: 기본 입력")
        c1, c2 = st.columns(2)
        applicant_label = c1.selectbox("신청업체 유형", list(APPLICANT_OPTIONS.keys()))
        online = c2.checkbox("온라인 신청 여부", value=False)

    with st.container(border=True):
        st.subheader("SECTION 2: 제출서류 체크")
        cols = st.columns(2)
        docs = {}
        for i, field in enumerate(DOC_FIELD_LABELS):
            docs[field] = cols[i % 2].checkbox(DOC_FIELD_LABELS[field], value=(field == "kc_mark_present"))

        b1, b2 = st.columns([1, 1])
        run_doc_check = b1.button("서류 확인", use_container_width=True)
        if b2.button("초기화", use_container_width=True, key="reset_doc"):
            reset_page_state()
            st.rerun()

    if run_doc_check:
        payload = {
            "applicant_type": APPLICANT_OPTIONS[applicant_label],
            "online_application": online,
            **docs,
        }
        result = document_check(payload)
        st.session_state.latest_document_payload = payload
        st.session_state.latest_document_result = result

    if st.session_state.latest_document_result is not None:
        result = st.session_state.latest_document_result
        with st.container(border=True):
            st.subheader("SECTION 3: 확인 결과")
            kc_checked = "확인" if docs.get("kc_mark_present", True) else "미확인"
            weight_cert = "제출" if docs.get("document_weight_certificate", False) else "미제출"
            st.write("- 누락서류:", [DOC_FIELD_LABELS.get(x, x) for x in result.missing_document_list])
            st.write("- 주의사항:", result.warnings)
            st.write("- KC 미확인 경고:", "있음" if any("KC" in w for w in result.warnings) else "없음")
            st.write("- 사용설비수수료 제외 가능 여부:", "가능성 있음" if result.notes else "해당 없음")
            st.write("- KC 확인 여부:", kc_checked)
            st.write("- 분동 교정성적서 여부:", weight_cert)
            st.info(f"입금계좌 안내: {DEPOSIT_INFO['bank']} {DEPOSIT_INFO['account']} ({DEPOSIT_INFO['branch']})")

        with st.container(border=True):
            st.subheader("판단 로그")
            st.dataframe(pd.DataFrame([x.__dict__ for x in result.decision_log]), use_container_width=True)

elif menu == MENU_CALC:
    st.header("검정비 계산")

    with st.container(border=True):
        st.subheader("SECTION 1: 기본 정보 입력")
        c1, c2, c3 = st.columns(3)
        case_id = c1.text_input("접수번호", "CASE-001")
        company_name = c2.text_input("업체명", "")
        staff_name = c3.text_input("담당자", "")

        c4, c5 = st.columns(2)
        applicant_label = c4.selectbox("신청업체 유형", list(APPLICANT_OPTIONS.keys()), key="calc_applicant_type")
        inspection_label = c5.selectbox("검정 유형", list(INSPECTION_OPTIONS.keys()))

        include_doc = st.checkbox("신청서류 확인 결과를 계산/로그에 포함", value=True)

    with st.container(border=True):
        st.subheader("SECTION 2: 장소 정보 입력")
        location_count = st.number_input("장소 수", min_value=1, max_value=10, value=1, step=1)
        max_between_locations = st.number_input("현장 간 최대 거리(km)", min_value=0.0, value=0.0)

        locations = []
        manual_overrides = []
        for i in range(int(location_count)):
            with st.container(border=True):
                st.markdown(f"**장소 {i + 1}**")
                l1, l2 = st.columns(2)
                l_id = l1.text_input(f"장소 ID {i + 1}", f"L{i+1}")
                addr = l2.text_input(f"주소 {i + 1}", "")

                l3, l4, l5 = st.columns(3)
                dist = l3.number_input(f"왕복 거리(km) {i + 1}", min_value=0.0, value=0.0)
                pc = l4.number_input(f"제품 수 {i + 1}", min_value=0, value=1)
                region = l5.selectbox(f"지역 {i + 1}", [""] + list(region_mapping.keys()))

                l6, l7 = st.columns(2)
                cap_label = l6.selectbox(f"용량 구분 {i + 1}", list(CAPACITY_OPTIONS.keys()))
                norm = l7.text_input(f"정규화 주소 {i + 1}", "")

                l8, l9, l10 = st.columns(3)
                wc = l8.checkbox(f"분동 교정성적서 제출 {i + 1}", value=False)
                same_override = l9.checkbox(f"동일주소 수동 지정 {i + 1}", value=False)
                fee_excl = l10.checkbox(f"수수료 제외 override {i + 1}", value=False)

                if same_override:
                    manual_overrides.append(
                        {
                            "field": f"same_address_group_{l_id}",
                            "before": "auto",
                            "after": "manual",
                            "by": staff_name or "staff",
                            "at": pd.Timestamp.now().isoformat(),
                        }
                    )
                if fee_excl:
                    manual_overrides.append(
                        {
                            "field": f"fee_exclusion_{l_id}",
                            "before": "false",
                            "after": "true",
                            "by": staff_name or "staff",
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

    with st.container(border=True):
        st.subheader("SECTION 3: 실행 버튼")
        b1, b2 = st.columns(2)
        run_calc = b1.button("검정비 계산", use_container_width=True)
        if b2.button("초기화", use_container_width=True, key="reset_calc"):
            reset_page_state()
            st.rerun()

    if run_calc:
        case_payload = {
            "case_id": case_id,
            "company_name": company_name,
            "staff_name": staff_name,
            "applicant_type": APPLICANT_OPTIONS[applicant_label],
            "inspection_type": INSPECTION_OPTIONS[inspection_label],
            "max_distance_between_locations_km": max_between_locations,
            "document_payload": st.session_state.latest_document_payload if include_doc else {},
            "locations": locations,
            "manual_overrides": manual_overrides,
        }
        try:
            result = calculate_case(case_payload, fee_master, region_mapping)
            st.session_state.latest_calc_result = result
            st.success("검정비 계산이 완료되었습니다.")
        except ValidationError:
            st.error("오류가 발생했습니다. 입력값을 확인해주세요.")

    result = st.session_state.latest_calc_result
    if result is not None and result.get("case_id") == case_id:
        with st.container(border=True):
            st.subheader("SECTION 4: 검정 결과 요약")
            s1, s2, s3 = st.columns(3)
            s1.metric("사용설비수수료", f"{result['equipment_usage_fee_total']:,} 원")
            s2.metric("출장일수", f"{result['travel_days']} 일")
            s3.metric("숙박", "적용" if result["lodging_nights"] > 0 else "미적용")

        with st.container(border=True):
            st.subheader("SECTION 5: 장소별 계산 내역")
            detail_df = pd.DataFrame(result["location_results"])
            st.dataframe(detail_df, use_container_width=True)
            st.markdown("**장소별 계산 근거**")
            for row in result["location_results"]:
                st.write(f"- {row['location_id']}: {row['calculation_explanation']}")

        with st.container(border=True):
            st.subheader("SECTION 6: 서류 확인 결과")
            doc_result = result.get("document_check") or {}
            payload = st.session_state.latest_document_payload or {}
            st.write("- 누락서류:", doc_result.get("missing_document_list", []))
            st.write("- KC 확인 여부:", "확인" if payload.get("kc_mark_present", True) else "미확인")
            st.write("- 분동 성적서 여부:", "제출" if payload.get("document_weight_certificate", False) else "미제출")

        with st.container(border=True):
            st.subheader("SECTION 7: 판단 로그")
            log_df = pd.DataFrame(result["decision_log"])
            st.dataframe(log_df, use_container_width=True)

        with st.container(border=True):
            st.subheader("SECTION 8: 접수 메모")
            st.text_area("접수 메모", value=result["reception_memo"], height=260)

        with st.container(border=True):
            st.subheader("SECTION 9: 출력 영역")
            excel_path = Path("exports") / f"{case_id}.xlsx"
            pdf_path = Path("exports") / f"{case_id}.pdf"
            excel_path.parent.mkdir(exist_ok=True)

            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                detail_df.to_excel(writer, sheet_name="locations", index=False)
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

            d1, d2 = st.columns(2)
            d1.download_button("엑셀 다운로드", data=excel_path.read_bytes(), file_name=excel_path.name, use_container_width=True)
            d2.download_button("PDF 다운로드", data=pdf_path.read_bytes(), file_name=pdf_path.name, use_container_width=True)

else:
    st.header("관리자")

    with st.container(border=True):
        st.subheader("SECTION 1: 수수료 기준표")
        fee_df = pd.DataFrame(fee_master)
        edited_fee = st.data_editor(fee_df, num_rows="dynamic", use_container_width=True)
        if st.button("수수료 기준표 저장", use_container_width=True):
            save_json(FEE_MASTER_PATH, edited_fee.to_dict(orient="records"))
            st.success("수수료 기준표가 저장되었습니다.")

    with st.container(border=True):
        st.subheader("SECTION 2: 지역 그룹 설정")
        region_df = pd.DataFrame(region_rows)
        edited_region = st.data_editor(region_df, num_rows="dynamic", use_container_width=True)
        if st.button("지역 그룹 설정 저장", use_container_width=True):
            save_json(REGION_MAPPING_PATH, edited_region.to_dict(orient="records"))
            st.success("지역 그룹 설정이 저장되었습니다.")
