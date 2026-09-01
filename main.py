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
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-infobars",
                    "--window-size=1280,800",
                ]
            )

            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 800},
                locale="en-US"
            )
            
            page = await context.new_page()

            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            # 1. Garena Shop Open
            try:
                await page.goto("https://shop.garena.my/?app=100067&channel=202953", wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
                
            await page.wait_for_timeout(3000)

            # Check Cloudflare Protection
            page_title = (await page.title()).lower()
            page_content = (await page.content()).lower()
            if "just a moment" in page_title or "attention required" in page_title or ("cloudflare" in page_content and "verify" in page_content):
                await browser.close()
                return {"success": False, "reason": "CLOUDFLARE_BLOCKED", "message": "Garena blocked the request with Cloudflare protection."}

            # Close Cookie/Region Dialog if present
            close_popup = page.locator("button.close, .modal-close, button:has-text('Accept'), button:has-text('Agree')").first
            if await close_popup.is_visible(timeout=2000):
                await close_popup.click()
                await page.wait_for_timeout(1000)

            # Click "Player ID" option if visible
            player_id_btn = page.locator("text='Player ID', div:has-text('Player ID'), button:has-text('Player ID')").first
            if await player_id_btn.is_visible(timeout=3000):
                await player_id_btn.click()
                await page.wait_for_timeout(1500)

            # Multi-selector for UID Input Box
            uid_input = page.locator(
                "input[placeholder*='player ID'], input[placeholder*='Player ID'], input[placeholder*='player'], input[name*='uid'], input[name*='player'], input[type='text'], input[type='number']"
            ).first

            try:
                await uid_input.wait_for(timeout=15000)
            except Exception:
                await browser.close()
                return {"success": False, "reason": "UID_INPUT_NOT_FOUND", "message": "Could not find Player ID input box on Garena shop."}

            await uid_input.click()
            await uid_input.fill("")
            await uid_input.type(str(player_uid), delay=80)
            # Dispatch React state input events
            await uid_input.evaluate("el => el.dispatchEvent(new Event('input', { bubbles: true }))")
            await uid_input.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
            await page.wait_for_timeout(1500)

            login_btn = page.locator("button[type='submit']:has-text('Login'), button:has-text('Login'), .login-btn").first
            if await login_btn.is_visible(timeout=3000):
                await login_btn.click(force=True)
            else:
                await page.keyboard.press("Enter")

            await page.wait_for_timeout(3500)

            # Proceed button (Fixed: Removed 'Login' from locator)
            proceed_btn = page.locator("button:has-text('Proceed to Payment'), div[role='button']:has-text('Proceed to Payment'), button:has-text('Proceed')").first
            if await proceed_btn.is_visible(timeout=5000):
                await proceed_btn.click(force=True)
                await page.wait_for_timeout(2000)

            num_only = re.sub(r"\D", "", str(diamond_amount))

            diamond_option = page.locator(f"text=/{num_only}\\s*Diamond/i").first
            if await diamond_option.is_visible(timeout=3000):
                await diamond_option.click()
            else:
                num_loc = page.locator(f"text={num_only}").first
                if await num_loc.is_visible(timeout=3000):
                    await num_loc.click()

            await page.wait_for_timeout(1500)

            physical_voucher_tab = page.locator("text='Physical Vouchers'").first
            if await physical_voucher_tab.is_visible(timeout=5000):
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
                unipin_option = page.locator("text='UniPin'").first
                if await unipin_option.is_visible(timeout=3000):
                    await unipin_option.click()
            elif clean_serial.startswith("UPBD"):
                up_gift_option = page.locator("text='UP Gift'").first
                if await up_gift_option.is_visible(timeout=3000):
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
            if await serial_input.is_visible(timeout=5000):
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
