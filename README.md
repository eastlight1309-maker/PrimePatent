# PrimePatent — 윈텔립스 RAW DATA 기반 핵심특허 선별 앱

윈텔립스(WIPS ON)에서 내려받은 엑셀을 업로드하면 **컬럼 자동 매핑 → 패밀리 대표문헌 선정 →
정량 스코어링 → LLM 분석 → 100점 총점 산출** 까지 수행하고, 결과를 저장소에 보관·재조회·
다운로드할 수 있는 **Dataiku Standard Webapp** 입니다.

```
총점 100 = 권리 중요도 30 + 기술 중요도 30 + 시장 중요도 20 + 영향력·경쟁성 20
         = 정량점수 71 + LLM 분석점수 29
```

## 1. 구성

```
PrimePatent/
├─ webapp/                     Dataiku Standard Webapp 구성요소
│  ├─ backend.py               Python backend (Flask 라우트 등록)
│  ├─ body.html                HTML
│  ├─ style.css                CSS
│  └─ script.js                JavaScript
├─ python-lib/primepatent/     프로젝트 라이브러리(분석 엔진)
│  ├─ config.py                배점·가중치·허용 LLM 목록
│  ├─ columns.py               WIPS 항목 사전(97개 표준 필드 + 별칭)
│  ├─ mapping.py               컬럼 자동 매핑
│  ├─ ingest.py                엑셀/CSV 적재(헤더행 탐지, 인코딩 처리)
│  ├─ parsing.py               날짜/숫자/다중값/불리언 파서
│  ├─ records.py               표준 레코드 변환 및 파생값
│  ├─ status.py                법적상태 분류
│  ├─ family.py                패밀리 그룹핑·대표문헌 선정
│  ├─ peers.py                 비교집단·백분위(PERCENTRANK.INC)
│  ├─ scoring/                 권리/기술/시장/영향력 채점 + 엔진
│  ├─ llm/                     LLM Mesh 클라이언트·프롬프트·배치 분석기
│  ├─ pipeline.py              전체 실행 파이프라인
│  ├─ jobs.py                  백그라운드 작업(진행률·취소)
│  ├─ uploads.py               업로드 세션
│  ├─ storage.py               결과 저장소(관리 폴더 / 로컬)
│  ├─ export.py                엑셀·CSV 내보내기
│  └─ webapp_routes.py         REST API
├─ run_local.py                로컬 standalone 실행(개발/검증용)
├─ tests/                      단위·통합·UI 테스트
└─ docs/                       배포 및 스코어링 상세 문서
```

## 2. Dataiku 배포

1. **코드환경**: `pandas`, `numpy`, `openpyxl`, `Flask` 설치 (`requirements.txt` 참고)
2. **프로젝트 라이브러리**: `python-lib/primepatent/` 를 DSS 프로젝트의
   *Libraries → Python* 에 그대로 복사
3. **관리 폴더** 생성(예: ID `PATENT_STORE`) — 결과 저장소로 사용
4. **웹앱 생성**: `Webapps → New → Standard`
   - HTML 탭 ← `webapp/body.html`
   - CSS 탭 ← `webapp/style.css`
   - JS 탭 ← `webapp/script.js`
   - Python 탭 ← `webapp/backend.py` (파일 상단 `FOLDER_ID` 에 관리 폴더 ID 입력)
   - Settings 에서 **Python backend 활성화**
5. LLM 은 **LLM Mesh** 에 등록된 아래 4개만 사용합니다(`config.py` 고정).

| 표시명 | LLM ID |
|---|---|
| gpt-5-mini \| DW_AOAI_APIM_DES1_LOW | `azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5-mini` |
| gpt-5 \| DW_AOAI_APIM_DES1_MID | `azureopenai:DW_AOAI_APIM_DES1_MID:gpt-5` |
| gpt-5.4-mini \| DW_AOAI_APIM_DES1_LOW | `azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5.4-mini` |
| gpt-5.4 \| DW_AOAI_APIM_DES1_MID | `azureopenai:DW_AOAI_APIM_DES1_MID:gpt-5.4` |

> 관리 폴더를 지정하지 않으면 DSS 서버 로컬 디렉터리(`.primepatent_store`)에 저장됩니다.
> 환경변수 `PRIMEPATENT_FOLDER_ID`, `PRIMEPATENT_STORE` 로도 지정할 수 있습니다.

## 3. 로컬 실행 (개발·검증용)

```bash
pip install -r requirements.txt
python run_local.py --port 8088          # http://127.0.0.1:8088
python tests/make_sample.py tmp/wips_sample.xlsx 120   # 테스트용 모사 데이터 생성
```

로컬에는 Dataiku LLM Mesh 가 없으므로 LLM 점수는 **휴리스틱 추정치**로 대체되고,
화면·결과 파일·경고 문구에 `heuristic` 으로 표시됩니다. **실제 평가에 사용하지 마십시오.**

## 4. 사용 절차

1. **업로드** — WIPS 엑셀/CSV 업로드 (검색식 안내 행이 있어도 헤더행 자동 탐지)
2. **컬럼 매핑** — 자동 매핑 결과 확인 후 필요한 항목만 수정
   (화면의 매핑 상태가 그대로 실행됩니다. 미매핑 주요 항목은 관련 점수가 0점 처리되고 경고로 표시)
3. **분석 설정** — 주제(Primary Topic)·키워드, LLM 모델, Gate 기준, 비교집단, 국가 가중치
4. **실행** — 백그라운드 작업으로 실행되며 진행률 표시·취소 가능
5. **결과** — 요약/분포/정렬/필터/상세(세부지표 18종 근거) 확인, 엑셀·CSV 다운로드
6. **저장소** — 부서·이름·프로젝트명 입력 후 저장(저장 시각 자동 기록), 이후 재조회·다운로드·삭제

## 5. 스코어링 요약

| 영역 | 배점 | 세부지표(배점) |
|---|---|---|
| 권리 중요도 | 30 | 생존성 8 · 청구범위 강도 8(정량4+LLM4) · 글로벌 권리범위 7 · 잔존기간 4 · 권리유지·방어 3 |
| 기술 중요도 | 30 | Topic 적합도 8 · 핵심 기술기여도 8 · 문제·효과 6 · 범용성 4(LLM3+CPC1) · 후속개량 4 |
| 시장 중요도 | 20 | 주요시장 진입도 8 · 출원인 영향력 5 · 상업화·거래 4 · 경쟁사 커버리지 3 |
| 영향력·경쟁성 | 20 | 연령보정 피인용 8 · 비자기 확산성 5 · 기술 원천성 4 · 권리충돌 3 |

- **패밀리 대표문헌 단위 평가**: 등록·존속 > 등록·소멸 > 공개·심사중 > 거절·취하 순으로 대표 선정
- **연령 편향 보정**: 비교집단 = `Primary Topic + 최초 우선연도` → 부족 시 `±N년` → `Topic 전체` → 전체
- **오른쪽 꼬리분포 보정**: 피인용·인용은 `LN(1+x)` 변환 후 `PERCENTRANK.INC` 백분위
- **Gate 1**: Topic 적합도 70% 미만은 `제외(Gate 미통과)` 로 표시
- 상세 계산식은 [`docs/SCORING.md`](docs/SCORING.md) 참조

## 6. 테스트

```bash
python -m unittest discover -s tests -p "test_*.py" -v   # 단위 + 통합 (60건)
python tests/ui_smoke.py                                 # 브라우저 UI 스모크(Playwright, 서버 실행 필요)
```

## 7. 주의사항

- LLM 분석에 실패한 문헌은 **LLM 점수 0점**으로 처리되고 `notes` 에 사유가 남습니다.
  (점수를 임의로 보정하지 않습니다)
- 실시권·양도 등 **데이터가 없는 항목은 0점으로 두고 `데이터 없음`으로 구분 표기**합니다.
  결측 항목을 제외하고 만점 환산하려면 설정에서 해당 옵션을 켜십시오.
- 잔존기간은 `최초우선일 + 20년` 근사치이며(만료일 컬럼이 있으면 그 값 사용),
  국가별 제도·연장·포기·무효를 반영하지 않은 **선별용 값**입니다.
