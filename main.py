import asyncio
import json
import re
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright

app = FastAPI(title="Free Fire Topup API")

async def process_freefire_topup(player_uid: str, diamond_amount: str, voucher_code: str, pin_code: str = ""):
    browser = None
    try:
        async with async_playwright() as p:
            # Docker & Low RAM Environment এর জন্য স্পেশাল ব্রাউজার ফ্ল্যাগস
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",  # Docker Memory Fix
                    "--disable-gpu",            # Docker GPU Fix
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-infobars",
                    "--window-size=1280,800",
                ]
            )

            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 800},
                locale="en-US"
            )
            
            page = await context.new_page()

            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            await page.goto("https://shop.garena.my/?app=100067&channel=202953", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            uid_input = page.locator("input[placeholder*='player ID'], input[placeholder*='Player ID'], input[type='text']").first
            await uid_input.wait_for(timeout=15000)
            await uid_input.click()
            await uid_input.type(str(player_uid), delay=100)
            await page.wait_for_timeout(1000)

            login_btn = page.locator("button:has-text('Login'), div[role='button']:has-text('Login'), .login-btn").first
            if await login_btn.is_visible():
                await login_btn.click()
            else:
                await page.keyboard.press("Enter")

            await page.wait_for_timeout(3000)

            proceed_btn = page.locator("button:has-text('Proceed to Payment'), div[role='button']:has-text('Proceed to Payment'), button:has-text('Login')").first
            await proceed_btn.wait_for(timeout=10000)
            await proceed_btn.click()
            await page.wait_for_timeout(2000)

            num_only = re.sub(r"\D", "", str(diamond_amount))

            diamond_option = page.locator(f"text=/{num_only}\\s*Diamond/i").first
            if await diamond_option.is_visible():
                await diamond_option.click()
            else:
                await page.locator(f"text={num_only}").first.click()

            await page.wait_for_timeout(1500)

            physical_voucher_tab = page.locator("text=Physical Vouchers").first
            await physical_voucher_tab.wait_for(timeout=10000)
            await physical_voucher_tab.click()
            await page.wait_for_timeout(1500)

            if " " in voucher_code or "," in voucher_code:
                parts = re.split(r'[\s,]+', voucher_code.strip())
                raw_serial = parts[0]
                raw_pin = parts[1] if len(parts) > 1 else pin_code
            else:
                raw_serial = voucher_code
                raw_pin = pin_code

            clean_serial = re.sub(r'[^A-Za-z0-9]', '', raw_serial).strip().upper()
            clean_pin = re.sub(r'[^A-Za-z0-9]', '', raw_pin).strip()

            if clean_serial.startswith("BDMB"):
                unipin_option = page.locator("text=/UniPin/i").first
                await unipin_option.click()
            elif clean_serial.startswith("UPBD"):
                up_gift_option = page.locator("text=/UP Gift/i").first
                await up_gift_option.click()
            else:
                await browser.close()
                return {"success": False, "reason": "INVALID_PREFIX", "message": "Invalid Voucher Prefix"}

            await page.wait_for_timeout(2000)

            target_scope = page
            for frame in page.frames:
                if "unipin" in frame.url or "unibox" in frame.url:
                    target_scope = frame
                    break

            serial_input = target_scope.locator("input[placeholder*='UPBD'], input[placeholder*='Serial'], input[type='text']").first
            await serial_input.wait_for(timeout=10000)
            await serial_input.click()
            await serial_input.fill(clean_serial)
            await page.wait_for_timeout(500)

            pin_inputs = target_scope.locator("input[type='password'], input[name*='pin'], input[id*='pin']")
            pin_count = await pin_inputs.count()

            if pin_count >= 4 and len(clean_pin) >= 12:
                chunks = [clean_pin[i:i+4] for i in range(0, len(clean_pin), 4)]
                for idx, chunk in enumerate(chunks[:4]):
                    inp = pin_inputs.nth(idx)
                    await inp.click()
                    await inp.fill(chunk)
                    await page.wait_for_timeout(100)
            elif pin_count > 0:
                await pin_inputs.first.click()
                if len(clean_pin) == 16:
                    formatted_pin = "-".join([clean_pin[i:i+4] for i in range(0, 16, 4)])
                    await pin_inputs.first.fill(formatted_pin)
                else:
                    await pin_inputs.first.fill(clean_pin)

            await page.wait_for_timeout(1500)

            confirm_btn = target_scope.locator("input[type='submit'][value='Confirm'], input[value='Confirm']").first

            if await confirm_btn.is_visible(timeout=3000):
                await confirm_btn.scroll_into_view_if_needed()
                await confirm_btn.click(force=True)
            else:
                await target_scope.evaluate("""
                    const btn = document.querySelector("input[type='submit'][value='Confirm']") || 
                                document.querySelector("input[value='Confirm']");
                    if (btn) btn.click();
                """)

            await page.wait_for_timeout(7000)

            content = await target_scope.content()
            main_content = await page.content()
            full_text = (content + main_content).lower()
            current_url = page.url.lower()

            await browser.close()

            if "consumed voucher" in full_text or "consumed%20voucher" in current_url:
                return {"success": False, "reason": "CONSUMED_VOUCHER", "message": "Voucher is already consumed/used."}

            success_keywords = [
                "transaction successful",
                "transactions successful",
                "successful",
                "transaction success",
                "transactions success",
                "success",
                "completed",
            ]

            if any(word in full_text for word in success_keywords):
                return {"success": True, "message": "Topup Completed Successfully!"}
            else:
                return {"success": False, "reason": "FAILED", "message": "Transaction Failed or Invalid Voucher Error."}

    except Exception as e:
        if browser:
            await browser.close()
        return {"success": False, "reason": "ERROR", "message": str(e)}

@app.get("/")
async def topup_api(
    uid: str = Query(..., description="Player UID"),
    amount: str = Query(..., description="Diamond Amount"),
    voucher: str = Query(..., description="Voucher Serial"),
    pin: str = Query("", description="Voucher PIN Code")
):
    result = await process_freefire_topup(player_uid=uid, diamond_amount=amount, voucher_code=voucher, pin_code=pin)
    return JSONResponse(content=result)
