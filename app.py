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

st.set_page_config(page_title="Scale Verification Reception Checker", layout="wide")
st.title("Scale Verification Reception Checker + Cost Calculator")
st.caption("내부 접수 담당자 전용 도구 (외부 고객 안내용 아님)")

if "manual_overrides" not in st.session_state:
    st.session_state.manual_overrides = []
if "latest_document_payload" not in st.session_state:
    st.session_state.latest_document_payload = {}

fee_master = load_json(FEE_MASTER_PATH)
region_rows = load_json(REGION_MAPPING_PATH)
region_mapping = {r["region_name"]: r["group"] for r in region_rows}

menu = st.sidebar.radio("메뉴", ["Application Document Check", "Inspection Cost Calculation", "Admin"])

if menu == "Application Document Check":
    st.header("1) Application Document Check")
    applicant_type = st.selectbox(
        "applicant_type",
        ["manufacturer_or_repair_company", "weighing_certificate_company_or_other"],
    )
    online = st.checkbox("online_application", value=False)

    cols = st.columns(2)
    docs = {}
    fields = [
        "document_scale_verification_application",
        "document_personal_information_consent",
        "document_business_registration",
        "document_invoice_company_info",
        "document_weight_certificate",
        "document_weighing_certificate_business_registration",
        "document_self_inspection_sheet",
        "document_self_inspection_signature",
        "document_scale_nameplate_photo",
        "kc_mark_present",
    ]
    for i, f in enumerate(fields):
        docs[f] = cols[i % 2].checkbox(f, value=(f == "kc_mark_present"))

    if st.button("서류 점검 실행"):
        payload = {"applicant_type": applicant_type, "online_application": online, **docs}
        st.session_state.latest_document_payload = payload
        res = document_check(payload)
        st.subheader("결과")
        st.write("missing_document_list", res.missing_document_list)
        st.write("warnings", res.warnings)
        st.write("notes", res.notes)
        st.info(f"입금계좌: {DEPOSIT_INFO['bank']} {DEPOSIT_INFO['account']} ({DEPOSIT_INFO['branch']})")
        st.subheader("Decision Log")
        st.dataframe(pd.DataFrame([x.__dict__ for x in res.decision_log]), use_container_width=True)

elif menu == "Inspection Cost Calculation":
    st.header("2) Inspection Cost Calculation")
    case_id = st.text_input("case_id", "CASE-001")
    applicant_type = st.selectbox(
        "applicant_type",
        ["manufacturer_or_repair_company", "weighing_certificate_company_or_other"],
        key="calc_applicant_type",
    )
    inspection_type = st.selectbox("inspection_type", ["manufacturing", "reinspection", "mixed"])
    max_between_locations = st.number_input("max_distance_between_locations_km", min_value=0.0, value=0.0)

    include_doc = st.checkbox("문서검토 결과를 계산/로그에 포함", value=True)
    doc_payload = st.session_state.latest_document_payload if include_doc else {}

    n = st.number_input("location count", min_value=1, max_value=10, value=1, step=1)
    locations = []
    for i in range(int(n)):
        with st.expander(f"location {i + 1}", expanded=True):
            l_id = st.text_input(f"location_id_{i}", f"L{i+1}")
            addr = st.text_input(f"address_{i}", "")
            norm = st.text_input(f"normalized_address_{i}", "")
            dist = st.number_input(f"distance_km_round_trip_{i}", min_value=0.0, value=0.0)
            pc = st.number_input(f"product_count_{i}", min_value=0, value=1)
            cap = st.selectbox(f"capacity_group_{i}", ["", "up_to_30_ton", "over_31_ton"])
            region = st.selectbox(f"region_name_{i}", [""] + list(region_mapping.keys()))
            wc = st.checkbox(f"weight_certificate_present_{i}", value=False)
            same_override = st.checkbox(f"same_address_manual_override_{i}", value=False)
            fee_excl = st.checkbox(f"fee_exclusion_override_{i}", value=False)
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
                    "inspection_type": inspection_type,
                    "address": addr,
                    "normalized_address": norm if not same_override else f"MANUAL_{l_id}",
                    "distance_km_round_trip": dist,
                    "product_count": pc,
                    "capacity_group": cap,
                    "region_name": region,
                    "weight_certificate_present": wc,
                    "fee_exclusion_override": fee_excl,
                }
            )

    case_payload = {
        "case_id": case_id,
        "applicant_type": applicant_type,
        "inspection_type": inspection_type,
        "max_distance_between_locations_km": max_between_locations,
        "document_payload": doc_payload,
        "locations": locations,
        "manual_overrides": st.session_state.manual_overrides,
    }

    if st.button("비용 계산 실행"):
        try:
            result = calculate_case(case_payload, fee_master, region_mapping)
            st.subheader("Location Breakdown")
            df = pd.DataFrame(result["location_results"])
            st.dataframe(df, use_container_width=True)

            st.subheader("Total Summary")
            st.json(
                {
                    "equipment_usage_fee_total": result["equipment_usage_fee_total"],
                    "travel_days": result["travel_days"],
                    "lodging_nights": result["lodging_nights"],
                    "calculation_notes": result["calculation_notes"],
                    "document_check": result["document_check"],
                }
            )

            st.subheader("계산 근거")
            for row in result["location_results"]:
                st.markdown(f"- **{row['location_id']}**: {row['calculation_explanation']}")

            st.subheader("Decision Log")
            log_df = pd.DataFrame(result["decision_log"])
            st.dataframe(log_df, use_container_width=True)

            st.subheader("접수 메모 자동생성")
            st.text_area("복사해서 접수기록에 사용", value=result["reception_memo"], height=220)
            st.code(result["reception_memo"], language="text")

            excel_path = Path("exports") / f"{case_id}.xlsx"
            pdf_path = Path("exports") / f"{case_id}.pdf"
            excel_path.parent.mkdir(exist_ok=True)
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="locations", index=False)
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

            st.success(f"Export completed: {excel_path}, {pdf_path}")
            st.download_button("Excel 다운로드", data=excel_path.read_bytes(), file_name=excel_path.name)
            st.download_button("PDF 다운로드", data=pdf_path.read_bytes(), file_name=pdf_path.name)
        except ValidationError as e:
            st.error(f"입력오류: {e}")

else:
    st.header("Admin mode")
    st.caption("fee master table / region mapping 편집")

    st.subheader("Fee Master")
    fee_df = pd.DataFrame(fee_master)
    edited_fee = st.data_editor(fee_df, num_rows="dynamic", use_container_width=True)

    st.subheader("Region Mapping")
    region_df = pd.DataFrame(region_rows)
    edited_region = st.data_editor(region_df, num_rows="dynamic", use_container_width=True)

    if st.button("관리 데이터 저장"):
        save_json(FEE_MASTER_PATH, edited_fee.to_dict(orient="records"))
        save_json(REGION_MAPPING_PATH, edited_region.to_dict(orient="records"))
        st.success("저장 완료")
