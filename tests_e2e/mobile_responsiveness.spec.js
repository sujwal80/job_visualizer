import { test, expect } from '@playwright/test';

test.describe('Responsive Layout Rules', () => {

  test.beforeEach(async ({ page }) => {
    // Setup route mocks for external CDNs
    const tailwindMockJs = `
    window.tailwind = { config: {} };
    const style = document.createElement('style');
    style.textContent = \`
        #app-container {
            position: absolute !important;
            top: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            left: 0 !important;
            z-index: 30 !important;
            display: flex !important;
            flex-direction: column !important;
            height: 100% !important;
            width: 100% !important;
            background-color: #ffffff !important;
        }
        .content-wrapper {
            flex: 1 1 0% !important;
            display: flex !important;
            overflow: hidden !important;
            position: relative !important;
        }
        #back-drawer-btn {
            min-width: 24px !important;
            min-height: 24px !important;
        }
    \`;
    document.head.appendChild(style);
    `;

    await page.route(/https:\/\/cdn\.tailwindcss\.com.*/, route => route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: tailwindMockJs
    }));

    await page.route(/https:\/\/unpkg\.com\/maplibre-gl@.*\/dist\/maplibre-gl\.js/, route => route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: `
      window.maplibregl = {
          Map: function() {
              const self = this;
              this.callbacks = {};
              this.on = function(event, cb) {
                  if (event === 'load' || event === 'style.load') {
                      setTimeout(cb, 10);
                  } else {
                      if (!self.callbacks[event]) self.callbacks[event] = [];
                      self.callbacks[event].push(cb);
                  }
                  return this;
              };
              setTimeout(() => {
                  const mapEl = document.getElementById('map');
                  if (mapEl && !mapEl.querySelector('.maplibregl-canvas')) {
                      const canvas = document.createElement('canvas');
                      canvas.className = 'maplibregl-canvas';
                      canvas.style.width = '100%';
                      canvas.style.height = '100%';
                      canvas.style.touchAction = 'none';
                      mapEl.appendChild(canvas);
                  }
              }, 50);

              this.zoom = 11;
              this.center = { lng: 77.5946, lat: 12.9716 };
              this.addControl = function() { return this; };
              this.getContainer = function() {
                  return { clientWidth: 1024, clientHeight: 768 };
              };
              this.getBounds = function() {
                  return {
                      getSouth: () => 12.9,
                      getNorth: () => 13.0,
                      getWest: () => 77.5,
                      getEast: () => 77.6
                  };
              };
              this.flyTo = function(options) {
                  if (options && options.center) this.center = options.center;
                  if (self.callbacks['moveend']) {
                      self.callbacks['moveend'].forEach(cb => cb());
                  }
                  return this;
              };
              this.getZoom = function() { return this.zoom; };
              this.setZoom = function(z) { this.zoom = z; return this; };
              this.getCenter = function() { return this.center; };
              this.touchZoomRotate = { disableRotation: function() {} };
          },
          NavigationControl: function() {},
          Marker: function() {
              const el = document.createElement('div');
              el.className = 'logo-marker-container';
              const fallbackEl = document.createElement('div');
              fallbackEl.className = 'logo-marker-fallback';
              fallbackEl.style.backgroundColor = 'rgb(234, 88, 12)';
              el.appendChild(fallbackEl);
              this.setLngLat = function() { return this; };
              this.addTo = function(map) {
                  const mapContainer = document.getElementById('map') || document.body;
                  mapContainer.appendChild(el);
                  return this;
              };
              this.remove = function() {
                  if (el.parentNode) {
                      el.parentNode.removeChild(el);
                  }
                  return this;
              };
              this.getElement = function() { return el; };
          }
      };
      `
    }));

    await page.route(/https:\/\/cdnjs\.cloudflare\.com\/ajax\/libs\/font-awesome\/.*/, route => route.fulfill({ status: 200, contentType: 'text/css', body: '' }));
    await page.route(/https:\/\/unpkg\.com\/maplibre-gl@.*\/dist\/maplibre-gl\.css/, route => route.fulfill({ status: 200, contentType: 'text/css', body: '' }));
    await page.route(/https:\/\/fonts\.googleapis\.com\/.*/, route => route.fulfill({ status: 200, contentType: 'text/css', body: '' }));
    await page.route(/https:\/\/fonts\.gstatic\.com\/.*/, route => route.fulfill({ status: 200, contentType: 'text/css', body: '' }));
  });

  test('desktop layout rules (1024x768)', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.goto('/jobs?city=Bengaluru%2C%20KA');
    
    await page.waitForFunction(() => 
      typeof window.WorldTechApp !== 'undefined' &&
      window.WorldTechApp.state &&
      window.WorldTechApp.state.startupsData &&
      window.WorldTechApp.state.startupsData.length > 0
    );

    const mobileToggle = page.locator('#mobile-toggle-btn');
    await expect(mobileToggle).toBeHidden();

    const brandText = page.locator('#app-container .brand-text-label');
    await expect(brandText).toBeVisible();

    // Click first item to open drawer
    await page.locator('#directory-list .directory-item').first().click();
    await page.waitForSelector('#details-drawer.active');

    const closeBtn = page.locator('#close-drawer-btn');
    const backBtn = page.locator('#back-drawer-btn');
    await expect(closeBtn).toBeVisible();
    await expect(backBtn).toBeHidden();
  });

  test('mobile layout rules (800x600)', async ({ page }) => {
    await page.setViewportSize({ width: 800, height: 600 });
    await page.goto('/jobs?city=Bengaluru%2C%20KA');

    await page.waitForFunction(() => 
      typeof window.WorldTechApp !== 'undefined' &&
      window.WorldTechApp.state &&
      window.WorldTechApp.state.startupsData &&
      window.WorldTechApp.state.startupsData.length > 0
    );

    const mobileToggle = page.locator('#mobile-toggle-btn');
    await expect(mobileToggle).toBeVisible();

    const brandText = page.locator('#app-container .brand-text-label');
    await expect(brandText).toBeVisible();

    const sidebar = page.locator('#sidebar');
    const isSidebarActive = await sidebar.evaluate(el => el.classList.contains('active'));
    expect(isSidebarActive).toBe(false);

    await mobileToggle.click();
    await page.waitForTimeout(500);
    const isSidebarActiveAfter = await sidebar.evaluate(el => el.classList.contains('active'));
    expect(isSidebarActiveAfter).toBe(true);

    // Open details drawer
    await page.locator('#directory-list .directory-item').first().click();
    await page.waitForSelector('#details-drawer.active');

    const closeBtn = page.locator('#close-drawer-btn');
    const backBtn = page.locator('#back-drawer-btn');
    await expect(closeBtn).toBeHidden();
    await expect(backBtn).toBeVisible();

    await backBtn.click();
    await page.waitForTimeout(500);
    const isDrawerActive = await page.locator('#details-drawer').evaluate(el => el.classList.contains('active'));
    expect(isDrawerActive).toBe(false);
  });

  test('small mobile brand text hidden (<= 360px)', async ({ page }) => {
    await page.setViewportSize({ width: 350, height: 600 });
    await page.goto('/jobs?city=Bengaluru%2C%20KA');

    await page.waitForFunction(() => 
      typeof window.WorldTechApp !== 'undefined' &&
      window.WorldTechApp.state &&
      window.WorldTechApp.state.startupsData &&
      window.WorldTechApp.state.startupsData.length > 0
    );

    const brandText = page.locator('#app-container .brand-text-label');
    await expect(brandText).toBeHidden();
  });
});
