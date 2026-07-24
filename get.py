from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    
    page.goto('https://www.instagram.com/')
    
    print("กรุณา login ด้วยตนเอง...")
    input("กด Enter เมื่อ Login เสร็จแล้ว: ")
    
    # บันทึก session
    context.storage_state(path="instagram_session.json")
    print("บันทึก session เสร็จ!")
    
    browser.close()