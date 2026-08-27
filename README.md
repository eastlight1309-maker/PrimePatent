# PrimePatent — 윈텔립스 RAW DATA 기반 핵심특허 선별 앱

윈텔립스(WIPS ON)에서 내려받은 엑셀을 업로드하면 **컬럼 자동 매핑 → 패밀리 대표문헌 선정 →
정량 스코어링 → LLM 분석 → 100점 총점 산출** 까지 수행하고, 결과를 저장소에 보관·재조회·
다운로드할 수 있는 **Dataiku Standard Webapp** 입니다.

```
총점 100 = 권리 중요도 27 + 기술 중요도 21 + 시장 중요도 27 + 영향력·경쟁성 25
         = 정량점수 84 + LLM 분석점수 16
```

> 배점은 `config.COMPONENT_MAX` 한 곳에서 관리되며 영역 합계·총점은 여기서 자동 계산됩니다.
> 화면·엑셀 헤더·설명 화면의 배점 표기도 모두 이 값에서 생성되므로, 지표를 추가/삭제해도
> 문서와 코드가 어긋나지 않습니다.

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
│  ├─ export.py                엑셀·CSV 내보내기(수식 인젝션 차단 포함)
│  ├─ guide.py                 설명 화면 데이터(배점 상수에서 생성)
│  ├─ applicants.py            출원인 표준화(표기 묶기·승인 반영)
│  └─ webapp_routes.py         REST API
├─ dist/backend_bundle.py      DSS 백엔드 단일 파일 번들(자동 생성물)
├─ tools/
│  ├─ build_backend_bundle.py  번들 생성기
│  └─ deploy_to_dss.py         프로젝트 라이브러리 업로드 도구
├─ run_local.py                로컬 standalone 실행(개발/검증용)
├─ tests/                      단위·통합·UI 테스트
└─ docs/                       배포 및 스코어링 상세 문서
```

## 2. Dataiku 배포

공통 준비
1. **코드환경**: `pandas`, `numpy`, `openpyxl`, `Flask` 설치 (`requirements.txt` 참고)
2. **관리 폴더** 생성(예: ID `PATENT_STORE`) — 결과 저장소로 사용(선택)
3. **웹앱 생성**: `Webapps → New → Standard`, Settings 에서 **Python backend 활성화**
   - HTML 탭 ← `webapp/body.html`
   - CSS 탭 ← `webapp/style.css`
   - JS 탭 ← `webapp/script.js`

Python backend 탭은 아래 **A 또는 B** 중 하나를 선택합니다.

### 방법 A — 단일 파일 번들 (가장 간단, 프로젝트 라이브러리 불필요)

`dist/backend_bundle.py` **전체를 [Python backend] 탭에 붙여넣고** 저장합니다.
패키지 29개 모듈이 파일 안에 압축 포함되어 있어 별도 배치가 필요 없습니다.
관리 폴더를 쓰려면 파일 상단 `PRIMEPATENT_FOLDER_ID` 에 폴더 ID 를 입력하십시오.

```bash
python tools/build_backend_bundle.py   # 소스 수정 후 번들 재생성
```

### 방법 B — 프로젝트 라이브러리 배치 (권장, 유지보수 용이)

`python-lib/primepatent/` 를 DSS 프로젝트 라이브러리의 **`python/` 폴더 아래**에 둡니다.
(DSS 화면: 프로젝트 → `</>` **Libraries** → `python/` → `primepatent/` 생성)
실제 서버 경로는 `$DIP_HOME/config/projects/<PROJECT_KEY>/lib/python/primepatent` 입니다.

API 로 한 번에 올리려면:

```bash
export DSS_URL=https://dss.example.com
export DSS_API_KEY=<개인 API 키>
python tools/deploy_to_dss.py --project PRIMEPATENT           # 미리보기
python tools/deploy_to_dss.py --project PRIMEPATENT --apply   # 실제 업로드
```

그 다음 [Python backend] 탭에는 `webapp/backend.py` 를 붙여넣고
`FOLDER_ID` 에 관리 폴더 ID 를 입력합니다.

> **중요**: `primepatent` 패키지가 `python/` 아래에 없으면
> `ModuleNotFoundError: No module named 'primepatent'` 로 백엔드가 기동하지 않습니다.
> 이때 `/api/health` 는 503 과 함께 **탐색한 경로 목록**을 알려 줍니다(7.3 참조).

### LLM

LLM 은 **LLM Mesh** 에 등록된 아래 4개만 사용합니다(`config.py` 고정).

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
2. **출원인 표준화** — 같은 회사의 여러 표기(삼성전자(주) / 삼성전자 주식회사 /
   SAMSUNG ELECTRONICS CO., LTD.)를 자동으로 묶어 후보를 제시합니다.
   표준명을 확인·수정하고 **승인**하면 그때부터 분석에 반영됩니다.
   승인 전에는 원본 표기를 그대로 사용하며, 실행 시 확인 창으로 알려 줍니다.
3. **컬럼 매핑** — 자동 매핑 결과 확인 후 필요한 항목만 수정
   (화면의 매핑 상태가 그대로 실행됩니다. 미매핑 주요 항목은 관련 점수가 0점 처리되고 경고로 표시)
4. **분석 설정** — 주제(Primary Topic)·키워드, LLM 모델, Gate 기준, 비교집단, 국가 가중치
5. **실행** — 백그라운드 작업으로 실행되며 진행률 표시·취소 가능
6. **결과** — 요약/분포/정렬/필터/상세 확인, 엑셀·CSV 다운로드.
   상세에는 세부지표 18종의 점수·산출근거와 함께 **비교집단 분포(최소·25%·중앙·75%·최대·평균)** 가
   표시되어, 백분위가 실제로 어느 수준인지 바로 확인할 수 있습니다.
7. **저장소** — 부서·이름·프로젝트명 입력 후 저장(저장 시각 자동 기록), 이후 재조회·다운로드·삭제
8. **설명** — 앱 상단 오른쪽 `? 설명` 탭에서 총점 구성, 세부지표 18종의 계산식과 사용 데이터,
   공통 규칙(패밀리 대표문헌·비교집단·Gate), 등급·검토 루트, 입력 항목 목록을 확인할 수 있습니다.
   이 화면의 배점·가중치는 **실제 계산 코드의 상수에서 생성**되므로 코드와 어긋나지 않습니다.

## 5. 스코어링 요약

| 영역 | 배점 | 세부지표(배점) |
|---|---|---|
| 권리 중요도 | 27 | 권리 생존성 10 · 청구범위 강도 5(정량2+LLM3) · 잔존기간 5 · 권리유지·방어 7 |
| 기술 중요도 | 21 | Topic 적합도 8(IPURE) · 핵심기술 중심성 5 · 청구항 확장도 5 · 독립항 유형 다양성 3 |
| 시장 중요도 | 27 | 주요시장 진입도 15(소비10+공급망5) · 출원인 영향력 4 · 상업화·거래 6 · 패밀리 건수 2 |
| 영향력·경쟁성 | 25 | 경쟁사 커버리지 5 · 연령보정 피인용 15 · 기술 선도성 5 |

- **Primary Topic 적합도는 LLM 판정이 아니라 엑셀의 `IPURE AI Score` 컬럼값**을 백분율로 환산해 씁니다.
  Gate 1 판정도 이 값 기준입니다.
- 기술 중요도의 나머지 3개 지표와 청구범위 강도의 LLM 부분은 **설정 화면에 입력한 "핵심기술 설명"**
  을 기준으로 판정합니다. 설명이 없으면 정확도가 크게 떨어지므로 실행 시 확인 창으로 알려 줍니다.

- **패밀리 대표문헌 단위 평가**: 등록·존속 > 등록·소멸 > 공개·심사중 > 거절·취하 순으로 대표 선정
- **연령 편향 보정**: 비교집단 = `Primary Topic + 최초 우선연도` → 부족 시 `±N년` → `Topic 전체` → 전체
- **오른쪽 꼬리분포 보정**: 피인용·인용은 `LN(1+x)` 변환 후 `PERCENTRANK.INC` 백분위
- **Gate 1**: Topic 적합도 70% 미만은 `제외(Gate 미통과)` 로 표시
- 상세 계산식은 [`docs/SCORING.md`](docs/SCORING.md) 참조

## 6. 테스트

```bash
python -m unittest discover -s tests -p "test_*.py" -v   # 단위 + 통합 + DSS 기동 + 회귀 (118건)
python tests/ui_smoke.py                                 # 브라우저 UI 스모크(Playwright, 서버 실행 필요)
python tools/build_backend_bundle.py --check             # 번들이 소스와 동기화됐는지 확인
```

> `python-lib/` 를 수정하면 **`python tools/build_backend_bundle.py` 로 번들을 재생성**해야
> 방법 A 로 배포한 웹앱에 반영됩니다(테스트가 동기화 여부를 검사합니다).

## 7. 문제 해결 (Troubleshooting)

### 7.1 `web_apps/XXXX.json` 의 `apiKey` 변경 diff 는 오류가 아닙니다

```
web_apps/ZLjnfbG.json   +1 −1
-  "apiKey": "e:AES:X2:aU8hk0B9sb..."
+  "apiKey": "e:AES:X2:Elxe5H3c+hE..."
```

DSS 는 프로젝트를 내부 Git 으로 버전 관리하며, **웹앱을 저장/재시작할 때마다 백엔드
호출용 API 키를 새로 발급**합니다. 위 diff 는 그 정상적인 변경 기록(`e:AES:` 는 DSS 암호화
접두사)이며 앱 오류가 아닙니다. 커밋하거나 무시하면 됩니다.

> 실제 오류 메시지는 **웹앱 화면의 [Log] 탭**(백엔드 기동 로그)에 표시됩니다.
> 앱이 뜨지 않을 때는 반드시 이 로그와 아래 `/api/health` 결과를 확인하십시오.

### 7.2 앱이 뜨지 않을 때 진단 순서

1. 화면 상단에 붉은 **"백엔드 상태 확인 필요"** 배너가 있으면 그 내용이 곧 원인입니다.
   `자세한 오류 내용` 을 펼치면 스택트레이스를 볼 수 있습니다.
2. 브라우저에서 백엔드 상태를 직접 확인합니다(웹앱 URL 뒤에 붙임).

   ```
   .../api/health
   ```

   ```jsonc
   {
     "storage": "dataiku",              // unavailable 이면 저장소 문제
     "storageLocation": "관리 폴더 PATENT_STORE",
     "storageError": null,
     "degraded": [],                    // 비어 있지 않으면 그 내용이 원인
     "environment": {
       "python": "3.9.x",
       "flask": "1.1.4",
       "sendFileKwarg": "attachment_filename",
       "packages": {"pandas": "1.3.5", "openpyxl": "3.0.9", "numpy": "1.21.6", "dataiku": "설치됨"}
     }
   }
   ```

3. `/api/health` 가 **503** 을 반환하면 백엔드가 **진단 모드**로 뜬 것입니다.
   응답에 원인과 함께 **어디를 찾아봤는지**가 들어 있습니다.

   ```jsonc
   {
     "error": "PrimePatent 라이브러리(primepatent)를 불러오지 못했습니다. ...",
     "detail": "Traceback ... ModuleNotFoundError: No module named 'primepatent'",
     "searchedPaths": [
       "/dataiku/design/config/projects/PRIMEPATENT/lib/python (primepatent 없음)",
       "/dataiku/design/lib/python (디렉터리 없음)"
     ],
     "projectKey": "PRIMEPATENT",
     "dipHome": "/dataiku/design"
   }
   ```

   `searchedPaths` 에 `패키지 있음` 이 하나도 없으면 라이브러리가 배치되지 않은 것입니다.
   백엔드 기동 로그([Log] 탭)에도 같은 경로 목록이 남습니다.

### 7.3 증상별 원인

| 증상 | 원인 | 조치 |
|---|---|---|
| 화면은 뜨지만 모든 API 가 실패 | 백엔드 미기동 | [Log] 탭 확인 → 아래 항목들 점검 |
| `Backend died before startup complete` + `ModuleNotFoundError: No module named 'primepatent'` | **프로젝트 라이브러리 미배치** (가장 흔함) | 방법 A(번들 붙여넣기) 또는 방법 B(라이브러리 배치) 수행 |
| `NameError: name '__file__' is not defined` | DSS 가 백엔드 코드를 문자열로 exec | 현재 `backend.py` 는 `__file__` 에 의존하지 않음(구버전을 붙여넣었다면 최신으로 교체) |
| `No module named 'pandas'` / `openpyxl` | 코드환경 패키지 누락 | 웹앱 Settings 의 코드환경에 `requirements.txt` 패키지 설치 |
| `send_file() got an unexpected keyword argument 'download_name'` | Flask 1.x 환경 | 현재 코드가 버전을 자동 판별함(`environment.sendFileKwarg` 로 확인) |
| 저장 시 `결과 저장소를 사용할 수 없습니다` | 관리 폴더 ID 오기재 또는 권한 없음 | `backend.py` 의 `FOLDER_ID` 확인, 폴더 접근 권한 부여 |
| 저장은 되는데 재시작하면 사라짐 | 쓰기 불가로 임시 디렉터리로 폴백됨 | `/api/health` 의 `storageNote` 확인 후 관리 폴더 사용 |

> 백엔드는 **저장소를 못 쓰더라도 분석 기능은 계속 동작**하도록 되어 있으며,
> 저장 관련 API 만 원인을 담아 503 을 반환합니다.

## 8. 주의사항

- LLM 분석에 실패한 문헌은 **LLM 점수 0점**으로 처리되고 `notes` 에 사유가 남습니다.
  (점수를 임의로 보정하지 않습니다)
- 실시권·양도 등 **데이터가 없는 항목은 0점으로 두고 `데이터 없음`으로 구분 표기**합니다.
  결측 항목을 제외하고 만점 환산하려면 설정에서 해당 옵션을 켜십시오.
- 잔존기간은 `최초우선일 + 20년` 근사치이며(만료일 컬럼이 있으면 그 값 사용),
  국가별 제도·연장·포기·무효를 반영하지 않은 **선별용 값**입니다. 제도상 상한(20년)으로 제한됩니다.
- 백분위 비교집단은 **채점 단위(패밀리 대표문헌)** 로 구성됩니다. 인용 문헌의 출원인 해석과
  출원인 포트폴리오 통계에는 업로드된 전체 문헌을 사용합니다.
- 분석 결과는 메모리에 최근 3건만 유지됩니다. 그 이후에는 저장소에 저장한 결과를 불러오거나
  다시 실행해야 합니다(대용량 결과가 쌓여 백엔드가 메모리 부족으로 죽는 것을 막기 위함).
- 내보내기 파일의 셀은 `=`, `+`, `-`, `@` 로 시작하면 텍스트로 고정됩니다(엑셀 수식 실행 방지).
