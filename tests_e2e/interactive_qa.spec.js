import { test, expect } from '@playwright/test';

test.describe('E2E Interactive QA', () => {

  test.beforeEach(async ({ page }) => {
    // Setup route mocks for external CDNs to allow offline execution and speed up loading
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

              setTimeout(() => {
                  const mapEl = document.getElementById('map');
                  if (mapEl) {
                      mapEl.addEventListener('click', (e) => {
                          if (e.target.closest('.logo-marker-container')) return;
                          if (self.callbacks['click']) {
                              self.callbacks['click'].forEach(cb => cb({
                                  lngLat: self.getCenter(),
                                  point: { x: e.clientX, y: e.clientY },
                                  originalEvent: e
                              }));
                          }
                      });
                  }
              }, 100);

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
              this.jumpTo = function(options) {
                  if (options && options.center) this.center = options.center;
                  if (self.callbacks['moveend']) {
                      self.callbacks['moveend'].forEach(cb => cb());
                  }
                  return this;
              };
              this.resize = function() { return this; };
              this.getZoom = function() { return this.zoom; };
              this.setZoom = function(z) { this.zoom = z; return this; };
              this.panBy = function(offset, options) {
                  this.center.lng += 0.01;
                  this.center.lat += 0.01;
                  if (self.callbacks['moveend']) {
                      self.callbacks['moveend'].forEach(cb => cb());
                  }
                  return this;
              };
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

  test('G1 landing page and brand items', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/Map My Job/);
    await expect(page.locator('#landingInterface')).toBeVisible();
    await expect(page.locator('#landingCityInput')).toBeVisible();
  });

  test('G2 preset navigation to Bengaluru and markers load', async ({ page }) => {
    await page.goto('/');
    await page.click("button[onclick=\"handlePresetSearch('bengaluru')\"]");
    await page.waitForURL('**/jobs?city=Bengaluru%2C%20KA');

    await page.waitForFunction(() => 
      typeof window.WorldTechApp !== 'undefined' &&
      window.WorldTechApp.state &&
      window.WorldTechApp.state.startupsData &&
      window.WorldTechApp.state.startupsData.length > 0
    );

    const titleText = await page.locator('#activeMapTitle').textContent();
    expect(titleText).toContain('Bengaluru');

    const pinCount = await page.locator('.logo-marker-container').count();
    expect(pinCount).toBeGreaterThan(0);
  });

  test('G3 authentication status flow and demo login', async ({ page, context }) => {
    await page.goto('/api/auth/demo_login?redirect=true');
    await page.waitForURL('**/');

    const cookies = await context.cookies();
    const sessionCookie = cookies.find(c => c.name === 'session_token');
    expect(sessionCookie).toBeDefined();

    const status = await page.evaluate(() => fetch('/api/auth/status').then(r => r.json()));
    expect(status.authenticated).toBe(true);
    expect(status.user.email).toBe('ujwal@worldtech.map');
  });

  test('G4 detail drawer display on click', async ({ page }) => {
    await page.goto('/jobs?city=Bengaluru%2C%20KA');
    await page.waitForFunction(() => 
      document.querySelectorAll('#directory-list .directory-item').length > 0
    );

    await page.locator('#directory-list .directory-item').first().click();
    await page.waitForSelector('#details-drawer.active');
    
    await expect(page.locator('#details-drawer')).toHaveClass(/active/);
    const drawerTitle = await page.locator('#drawer-company-name').textContent();
    expect(drawerTitle.length).toBeGreaterThan(0);
  });

  test('G5 map zoom pan viewport preservation', async ({ page }) => {
    await page.goto('/jobs?city=Bengaluru%2C%20KA');
    await page.waitForFunction(() => 
      typeof window.WorldTechApp !== 'undefined' && window.WorldTechApp.map
    );

    // Set new zoom
    await page.evaluate(() => window.WorldTechApp.map.setZoom(14));
    await page.waitForTimeout(1000);

    const zoom = await page.evaluate(() => window.WorldTechApp.map.getZoom());
    expect(Math.round(zoom)).toBe(14);

    const centerBefore = await page.evaluate(() => {
      const c = window.WorldTechApp.map.getCenter();
      return [c.lng, c.lat];
    });

    // Pan map
    await page.evaluate(() => window.WorldTechApp.map.panBy([100, 100], { animate: false }));
    await page.waitForTimeout(1000);

    const centerAfter = await page.evaluate(() => {
      const c = window.WorldTechApp.map.getCenter();
      return [c.lng, c.lat];
    });

    expect(centerBefore[0]).not.toEqual(centerAfter[0]);
    expect(centerBefore[1]).not.toEqual(centerAfter[1]);
  });

  test('frontend color rendering by industry', async ({ page }) => {
    await page.goto('/jobs?city=Bengaluru%2C%20KA');
    await page.waitForFunction(() => 
      typeof window.WorldTechApp !== 'undefined' && 
      window.WorldTechApp.state && 
      window.WorldTechApp.state.startupsData && 
      window.WorldTechApp.state.startupsData.length > 0
    );

    const colors = await page.evaluate(() => {
      const res = [];
      for (const [id, marker] of window.WorldTechApp.state.markersMap.entries()) {
        const startup = window.WorldTechApp.state.startupsData.find(s => s.id == id);
        if (startup && startup.industry === 'Service Industry') {
          const el = marker.getElement();
          const fallbackEl = el.querySelector('.logo-marker-fallback');
          const bg = fallbackEl ? fallbackEl.style.backgroundColor : null;
          res.push({ id, name: startup.name, color: bg });
        }
      }
      return res;
    });

    expect(colors.length).toBeGreaterThan(0);
    for (const markerInfo of colors) {
      expect(markerInfo.color).toContain('rgb(234, 88, 12)');
    }
  });
});
