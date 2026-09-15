# -*- coding: utf-8 -*-
"""브라우저 UI 스모크 테스트 (Playwright). 개발 검증용이며 CI 필수는 아님."""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = os.environ.get("PP_URL", "http://127.0.0.1:8099/")
SAMPLE = os.path.join(BASE, "tmp", "wips_sample.xlsx")
SHOTS = os.path.join(BASE, "tmp", "shots")


def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(SHOTS, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("dialog", lambda dialog: dialog.accept())
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.goto(URL, wait_until="networkidle")
        print("1) 초기 로드:", page.title(), "|", page.text_content("#pp-storage-badge"))

        # 업로드
        page.set_input_files("#pp-file", SAMPLE)
        page.wait_for_selector('.pp-panel[data-panel="applicant"].pp-panel-active', timeout=60000)
        page.wait_for_selector("#pp-app-table tbody tr", timeout=30000)
        page.wait_for_timeout(500)
        print("2-1) 출원인 표준화:", " ".join(page.text_content("#pp-app-summary").split()))
        first_row = page.locator("#pp-app-table tbody tr").first
        print("     첫 그룹 표준명:", first_row.locator("input").input_value(),
              "| 상태:", " ".join(first_row.locator("td").nth(3).text_content().split()))

        # 그룹별 [변경] 버튼
        first_row.locator("input").fill("표준명_수동변경")
        first_row.get_by_role("button", name="변경").click()
        page.wait_for_timeout(300)
        print("     변경 버튼:", " ".join(page.text_content("#pp-toast").split())[:40])
        page.locator("#pp-app-table tbody tr").first.get_by_role(
            "button", name="추천값 복원").click()
        page.wait_for_timeout(300)

        # 그룹별 [승인] 버튼 - 승인 대기 그룹을 모두 승인한다
        page.check("#pp-app-only-pending")
        page.wait_for_timeout(300)
        pending = page.locator("#pp-app-table tbody tr").count()
        for _ in range(pending):
            buttons = page.locator("#pp-app-table tbody tr").first.get_by_role("button",
                                                                               name="승인")
            if not buttons.count():
                break
            buttons.first.click()
            page.wait_for_timeout(200)
        page.uncheck("#pp-app-only-pending")
        page.wait_for_timeout(300)
        print("     그룹별 승인:", pending, "건 처리 · 남은 승인대기",
              page.locator("#pp-app-summary .pp-metric").nth(3).text_content().replace("승인 대기", ""))

        page.click("#pp-app-approve")
        page.wait_for_timeout(1200)
        print("     승인:", " ".join(page.text_content("#pp-toast").split())[:40])
        page.click('.pp-tab[data-tab="mapping"]')
        page.wait_for_selector("#pp-map-table tbody tr", timeout=20000)
        print("2) 업로드:", page.text_content("#pp-file-name"), "|", page.text_content("#pp-toast"))
        print("   매핑 상태:", page.text_content("#pp-map-status")[:140])
        rows = page.locator("#pp-map-table tbody tr").count()
        print("   매핑 표 행 수:", rows)
        page.screenshot(path=os.path.join(SHOTS, "02_mapping.png"), full_page=False)

        # 매핑 수동 변경 → 되돌리기
        first_select = page.locator("#pp-map-table tbody tr select").first
        first_select.select_option("__none__")
        page.wait_for_timeout(700)
        print("3) 미사용 처리 후 상태:", page.text_content("#pp-map-status")[:120])
        page.click("#pp-map-reset")
        page.wait_for_timeout(700)
        print("   자동복원 후 상태:", page.text_content("#pp-map-status")[:120])

        # 설정
        page.click('.pp-tab[data-tab="config"]')
        page.fill("#cfg-topic-name", "첨단 반도체 패키징")
        page.fill("#cfg-topic-keywords", "하이브리드 본딩, TSV, 팬아웃, 미세 피치")
        # 핵심기술 설명을 비우면 실행 시 확인 창이 떠 분석이 시작되지 않는다.
        page.fill("#cfg-core-tech",
                  "하이브리드 본딩을 이용한 미세 피치 칩 접합 구조. "
                  "핵심 구성요소: 구리 패드, 절연층, 5㎛ 이하 접합 피치")
        page.fill("#cfg-peer-min", "10")
        page.fill("#cfg-as-of", "2026-08-25")
        page.screenshot(path=os.path.join(SHOTS, "03_config.png"))
        print("4) 설정 입력 완료, LLM 배지:", page.text_content("#pp-llm-badge"))

        # 실행
        page.click("#pp-run")
        try:
            page.wait_for_selector('.pp-panel[data-panel="result"].pp-panel-active', timeout=120000)
        except Exception:
            print("   실행 실패 토스트:", page.text_content("#pp-toast"),
                  "| 진행:", page.text_content("#pp-run-message"))
            raise
        page.wait_for_timeout(800)
        print("5) 분석 완료:", " ".join(page.text_content("#pp-summary").split())[:220])
        result_rows = page.locator("#pp-result-table tbody tr").count()
        print("   결과 표 행 수:", result_rows, "|", page.text_content("#pp-page-info"))
        page.screenshot(path=os.path.join(SHOTS, "04_result.png"), full_page=False)

        # 정렬/필터
        page.click('#pp-result-table thead th[data-sort="totalScore"]')
        page.wait_for_timeout(600)
        page.select_option("#pp-filter-grade", "A")
        page.wait_for_timeout(700)
        print("6) 등급 A 필터:", page.text_content("#pp-page-info"))
        page.select_option("#pp-filter-grade", "")
        page.wait_for_timeout(600)

        # 상세 드로어
        page.locator("#pp-result-table tbody tr").first.click()
        page.wait_for_selector("#pp-detail:not([hidden])", timeout=10000)
        detail_title = page.text_content("#pp-detail-title")
        comps = page.locator("#pp-detail-body .pp-comp").count()
        print("7) 상세 패널:", detail_title, "| 세부지표", comps, "개")
        page.screenshot(path=os.path.join(SHOTS, "05_detail.png"))
        page.click("#pp-detail-close")

        # 저장
        page.click("#pp-open-save")
        page.wait_for_selector("#pp-save-modal:not([hidden])")
        page.fill("#save-department", "IP전략팀")
        page.fill("#save-owner", "홍길동")
        page.fill("#save-project", "2026 첨단패키징 핵심특허")
        page.fill("#save-note", "1차 스크리닝")
        page.screenshot(path=os.path.join(SHOTS, "06_save.png"))
        page.click("#pp-save-confirm")
        page.wait_for_timeout(2500)
        print("8) 저장 결과 토스트:", page.text_content("#pp-toast"))

        # 저장소 목록 → 재조회
        page.click('.pp-tab[data-tab="library"]')
        page.wait_for_timeout(1200)
        run_rows = page.locator("#pp-runs-table tbody tr").count()
        print("9) 저장소 행 수:", run_rows, "|", " ".join(page.text_content("#pp-runs-table tbody").split())[:160])
        page.screenshot(path=os.path.join(SHOTS, "07_library.png"))
        page.locator("#pp-runs-table tbody tr button", has_text="불러오기").first.click()
        page.wait_for_selector('.pp-panel[data-panel="result"].pp-panel-active', timeout=20000)
        page.wait_for_timeout(1200)
        print("10) 저장본 불러오기:", page.text_content("#pp-result-title"))
        page.screenshot(path=os.path.join(SHOTS, "08_reloaded.png"), full_page=False)

        # 설명 화면
        page.click('.pp-tab[data-tab="guide"]')
        page.wait_for_selector("#pp-guide-components .pp-guide-card", timeout=20000)
        page.wait_for_timeout(600)
        print("11) 설명 화면 · 영역", page.locator("#pp-guide-areas .pp-guide-area").count(),
              "· 지표", page.locator("#pp-guide-components .pp-guide-card").count(),
              "· 규칙", page.locator("#pp-guide-rules .pp-rule").count(),
              "·", " / ".join(page.locator("#pp-guide-split .pp-split-part").all_text_contents()))
        page.screenshot(path=os.path.join(SHOTS, "09_guide.png"), full_page=False)

        browser.close()

    real_errors = [e for e in errors if "favicon" not in e.lower()]
    print("\n콘솔 오류:", real_errors if real_errors else "없음")
    return 1 if real_errors else 0


if __name__ == "__main__":
    sys.exit(main())
