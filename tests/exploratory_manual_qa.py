#!/usr/bin/env python3
import time
import os
from playwright.sync_api import sync_playwright

def run_exploratory_qa():
    artifacts_dir = "/Users/singhujwal/.gemini/jetski/brain/6bebea5b-6c02-495e-964f-161f576c31ee/artifacts"
    os.makedirs(artifacts_dir, exist_ok=True)
    
    print("🚀 STARTING EXPLORATORY MANUAL QA CHECK VIA PLAYWRIGHT 🚀")
    print("---------------------------------------------------------")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Navigate to application
        url = "http://127.0.0.1:5001/jobs?city=Bengaluru%2C%20KA"
        print(f"1. Navigating to: {url}")
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        
        # Capture Initial State
        initial_zoom = page.evaluate("() => WorldTechApp.map.getZoom()")
        initial_center = page.evaluate("() => { const c = WorldTechApp.map.getCenter(); return [c.lng, c.lat]; }")
        print(f"   [Initial State] Zoom: {initial_zoom:.2f}, Center: {initial_center}")
        page.screenshot(path=f"{artifacts_dir}/01_initial_state.png")
        
        # 2. Perform Zoom In
        print("2. Zooming in map to level 14...")
        page.evaluate("() => WorldTechApp.map.setZoom(14)")
        page.wait_for_timeout(2000)
        
        zoom_after = page.evaluate("() => WorldTechApp.map.getZoom()")
        center_after_zoom = page.evaluate("() => { const c = WorldTechApp.map.getCenter(); return [c.lng, c.lat]; }")
        print(f"   [Zoomed State] Zoom: {zoom_after:.2f}, Center: {center_after_zoom}")
        page.screenshot(path=f"{artifacts_dir}/02_zoomed_state.png")
        
        # 3. Perform Pan
        print("3. Panning map by [150, 150]...")
        page.evaluate("() => WorldTechApp.map.panBy([150, 150], {animate: false})")
        page.wait_for_timeout(2000)
        
        zoom_after_pan = page.evaluate("() => WorldTechApp.map.getZoom()")
        center_after_pan = page.evaluate("() => { const c = WorldTechApp.map.getCenter(); return [c.lng, c.lat]; }")
        print(f"   [Panned State] Zoom: {zoom_after_pan:.2f}, Center: {center_after_pan}")
        page.screenshot(path=f"{artifacts_dir}/03_panned_state.png")
        
        # 4. Click a company card
        print("4. Waiting for directory cards to load...")
        first_card = page.locator("#directory-list .directory-item").first
        first_card.wait_for(state="visible", timeout=5000)
        
        card_name = first_card.locator(".card-title").text_content()
        print(f"   Clicking company card: '{card_name}'...")
        first_card.click()
        page.wait_for_timeout(2500)
        
        selected_zoom = page.evaluate("() => WorldTechApp.map.getZoom()")
        selected_center = page.evaluate("() => { const c = WorldTechApp.map.getCenter(); return [c.lng, c.lat]; }")
        print(f"   [Company Selected State] Zoom: {selected_zoom:.2f}, Center: {selected_center}")
        page.screenshot(path=f"{artifacts_dir}/04_company_selected.png")
        
        # 5. Close drawer
        print("5. Clicking the close drawer button (#close-drawer-btn)...")
        page.click("#close-drawer-btn")
        page.wait_for_timeout(2500)
        
        closed_zoom = page.evaluate("() => WorldTechApp.map.getZoom()")
        closed_center = page.evaluate("() => { const c = WorldTechApp.map.getCenter(); return [c.lng, c.lat]; }")
        print(f"   [Drawer Closed State] Zoom: {closed_zoom:.2f}, Center: {closed_center}")
        page.screenshot(path=f"{artifacts_dir}/05_drawer_closed.png")
            
        browser.close()
        print("---------------------------------------------------------")
        print("🎉 EXPLORATORY MANUAL QA CHECK COMPLETE! Screenshots saved to artifacts directory.")

if __name__ == '__main__':
    run_exploratory_qa()
