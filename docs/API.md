# REST API

모든 경로는 웹앱 백엔드 기준이며, 프론트엔드는 Dataiku 의 `getWebAppBackendUrl()` 을 사용합니다.
오류 응답은 항상 `{"ok": false, "error": "<한글 메시지>"}` 형식입니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | 구동 진단(저장소 상태·환경·degraded), 허용 LLM 목록, 기본 설정, 배점표 |
| GET | `/api/fields` | 표준 필드 카탈로그(라벨/별칭/필수 여부) |
| GET | `/api/guide` | 설명 화면 데이터(영역·세부지표 배점, 계산식, 공통 규칙, 등급·루트, 입력 항목) |
| GET | `/api/llm/probe?llmId=` | LLM 연결 점검 |
| POST | `/api/upload` | 파일 업로드(multipart `file`) → 헤더·미리보기·자동매핑 |
| POST | `/api/upload/<id>/sheet` | 시트 변경 후 재적재 |
| POST | `/api/upload/<id>/mapping` | 매핑 검증(사용자 수정 반영 결과 반환) |
| DELETE | `/api/upload/<id>` | 업로드 세션 삭제 |
| POST | `/api/analyze` | 분석 실행(백그라운드) → `job` |
| GET | `/api/jobs/<id>` | 작업 상태·진행률 |
| POST | `/api/jobs/<id>/cancel` | 작업 취소 |
| GET | `/api/jobs/<id>/result` | 결과 목록(페이징·정렬·필터) |
| GET | `/api/jobs/<id>/row/<key>` | 문헌 1건 상세(세부지표 근거 포함) |
| GET | `/api/jobs/<id>/download?format=xlsx\|csv` | 미저장 결과 다운로드 |
| POST | `/api/save` | 저장소 저장(부서/이름/프로젝트명 필수, 저장시각 자동) |
| GET | `/api/runs` | 저장 목록 + 필터 facet |
| GET | `/api/runs/<runId>/result` | 저장 결과 재조회 |
| GET | `/api/runs/<runId>/row/<key>` | 저장 결과 문헌 상세 |
| GET | `/api/runs/<runId>/download?format=` | 저장 결과 다운로드 |
| DELETE | `/api/runs/<runId>` | 저장 결과 삭제 |

## 상태 코드

| 코드 | 의미 |
|---|---|
| 400 | 입력 오류(필수 항목 누락, 지원하지 않는 파일 등) |
| 404 | 대상 없음(만료된 작업, 존재하지 않는 저장 결과) |
| 503 | 저장소 사용 불가 또는 백엔드 진단 모드 — 응답의 `error`/`detail` 이 원인 |

## 결과 목록 쿼리 파라미터

`offset`, `limit`(최대 500), `sort`, `order=asc|desc`, `q`, `grade`, `gate=pass|fail`, `route`, `country`

## 저장 데이터 구조

```
index.json                     목록 인덱스(메타만)
runs/<runId>/meta.json         부서·이름·프로젝트명·저장시각·요약 지표
runs/<runId>/result.json       분석 결과 전체(설정·매핑·행 단위 점수)
runs/<runId>/artifacts/result.xlsx
```

`meta.json` 은 인덱스 파손 시 복구용으로도 사용됩니다(`ResultStore.rebuild_index`).
