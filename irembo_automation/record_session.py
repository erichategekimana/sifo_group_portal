import time
from playwright.sync_api import sync_playwright  # type: ignore[import]
from playwright_stealth import Stealth  # type: ignore[import]

def record_irembo_session():
    with sync_playwright() as p:
        # 1. Launch a visible browser context so you can interact with it
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="en-US",
            timezone_id="Africa/Kigali"
        )
        Stealth().apply_stealth_sync(context)
        page = context.new_page()

        # 2. Navigate to the Irembo landing or login portal
        print("[Setup] Opening Irembo. Please log in manually...")
        page.goto("https://irembo.gov.rw/", wait_until="networkidle")

        # 3. Halt the script execution to give you time to authenticate
        print("\n" + "="*60)
        print(" ACTION REQUIRED:")
        print(" 1. Go to the browser window that just opened.")
        print(" 2. Click 'Sign In' and enter your Agent credentials.")
        print(" 3. Complete any required login OTP step.")
        print(" 4. Once you are looking at your logged-in dashboard,")
        print("    come back here and press ENTER to save your session.")
        print("="*60 + "\n")
        
        input("Press Enter here AFTER you have successfully logged into your dashboard...")

        # 4. Extract tokens and write them directly into state.json
        context.storage_state(path="state.json")
        print("[Success] Active login session exported successfully to 'state.json'!")
        
        context.close()
        browser.close()

if __name__ == "__main__":
    record_irembo_session()
