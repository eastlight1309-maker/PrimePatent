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
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.goto(URL, wait_until="networkidle")
        print("1) 초기 로드:", page.title(), "|", page.text_content("#pp-storage-badge"))

        # 업로드
        page.set_input_files("#pp-file", SAMPLE)
        page.wait_for_selector('.pp-panel[data-panel="mapping"].pp-panel-active', timeout=60000)
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

        browser.close()

    real_errors = [e for e in errors if "favicon" not in e.lower()]
    print("\n콘솔 오류:", real_errors if real_errors else "없음")
    return 1 if real_errors else 0


if __name__ == "__main__":
    sys.exit(main())
