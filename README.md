# Scale Verification Reception Checker + Cost Calculator

KTC 내부 접수 담당자를 위한 **서류 검토 + 장비사용료 계산 + 판단 로그** 공유 도구입니다.

## 주요 기능
- 신청서류 확인
- 검정비 계산 (제작검정/재검정/제작+재검)
- 판단 로그 패널(판정 근거 한글 기록)
- 접수 메모 자동 생성 (`[접수 메모]`)
- 엑셀/PDF 내보내기 (요약 + 장소별 계산 + 판단 로그 + 메모)
- 관리자 모드에서 요율표/지역 매핑 수정
- 동일주소 자동 그룹핑 + 수동 override 이력 기록

## 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 데이터
- `data/fee_master.json`: 거리별/용량별/지역그룹별 장비사용료 마스터
- `data/region_mapping.json`: 지역명 -> 재검정 그룹 매핑

## 테스트
```bash
pytest -q
```
