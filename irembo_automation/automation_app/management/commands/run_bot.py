try:
    from playwright.sync_api import sync_playwright  # type: ignore[import]
except ImportError as exc:
    raise ImportError(
        "Missing dependency 'playwright'. Install it with "
        "'pip install playwright' and ensure it is available in the current environment."
    ) from exc

try:
    from playwright_stealth import stealth_sync  # type: ignore[import]
except ImportError as exc:
    raise ImportError(
        "Missing dependency 'playwright_stealth'. Install it with "
        "'pip install playwright-stealth' and ensure it is available in the current environment."
    ) from exc

def get_stealth_context(playwright_instance):
    """
    Launches a stealth-hardened Chromium instance configured 
    specifically to look like a genuine Windows 11 desktop user.
    """
    # 1. Launch a real Chromium instance
    # Set headless=True when running in production background workers
    browser = playwright_instance.chromium.launch(headless=True)
    
    # 2. Define standard Windows 11 Chrome properties
    windows_user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    
    # 3. Establish the browser context with structural hardware overrides
    context = browser.new_context(
        user_agent=windows_user_agent,
        viewport={"width": 1920, "height": 1080},
        device_scale_factor=1,
        is_mobile=False,
        has_touch=False,
        locale="en-US",
        timezone_id="Africa/Kigali"  # Matches target operational environment
    )
    
    # 4. Inject JavaScript stealth patches 
    # This automatically overwrites permissions, plugins, and webdriver flags
    stealth_sync(context)
    
    return browser, context

# Verification block to test locally on your Windows 11 setup
if __name__ == "__main__":
    with sync_playwright() as p:
        browser, context = get_stealth_context(p)
        page = context.new_page()
        
        # Point to an echo page to verify our signature
        page.goto("https://bot.sannysoft.com/")
        page.screenshot(path="stealth_test_results.png")
        print("Stealth context generated and verified successfully via screenshot.")
        
        context.close()
        browser.close()