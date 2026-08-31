import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

NAV = ["任务", "工作流", "工具管理", "Skill 管理", "模板管理", "发现", "后台日志", "设置"]

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto("http://127.0.0.1:6317", wait_until="networkidle")
        page.wait_for_timeout(1500)

        # default page
        page.screenshot(path=str(OUT / "01-run.png"), full_page=False)
        print("captured run")

        for i, label in enumerate(NAV[1:], start=2):
            btn = page.locator(f"button.nav-item:has-text('{label}')")
            btn.click()
            page.wait_for_timeout(1200)
            slug = label.lower().replace(" ", "-").replace("skill", "skills")
            page.screenshot(path=str(OUT / f"{i:02d}-{slug}.png"), full_page=False)
            print("captured", label)

        browser.close()

if __name__ == "__main__":
    main()
