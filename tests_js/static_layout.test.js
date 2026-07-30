import fs from 'fs';
import path from 'path';

describe('Static Layout & CSS Rules (R1)', () => {
  let cssContent;
  let htmlContent;

  beforeAll(() => {
    cssContent = fs.readFileSync(path.resolve('./public/static/css/style.css'), 'utf-8');
    htmlContent = fs.readFileSync(path.resolve('./public/index.html'), 'utf-8');
  });

  test('mobile/tablet breakpoints in CSS', () => {
    expect(cssContent).toContain('@media');
    expect(cssContent).toContain('max-width: 900px');
    expect(cssContent).toContain('max-width: 320px');
    expect(cssContent).toContain('max-width: 768px');
    expect(cssContent).toContain('min-width: 1920px');
  });

  test('mobile toggle button in HTML', () => {
    expect(htmlContent).toContain('id="mobile-toggle-btn"');
    expect(htmlContent).toContain('class="mobile-toggle"');
    expect(htmlContent).toContain('aria-label=');
  });

  test('mobile toggle CSS visibility rules', () => {
    expect(cssContent).toContain('.mobile-toggle');
    expect(cssContent).toContain('display: none;'); // hidden on desktop by default
    expect(cssContent).toContain('display: block;'); // visible on mobile
  });

  test('sidebar responsive offscreen on mobile', () => {
    expect(cssContent).toContain('transform: translateX(-100%);');
  });

  test('.sidebar.active transition in CSS', () => {
    expect(cssContent).toContain('.sidebar.active');
    expect(cssContent).toContain('transform: translateX(0);');
  });

  test('details drawer responsive width', () => {
    expect(cssContent).toContain('.details-drawer');
    expect(cssContent).toContain('width: 100%;');
  });

  test('card title text overflow handling', () => {
    expect(cssContent).toContain('.card-title');
    expect(cssContent).toContain('text-overflow: ellipsis;');
    expect(cssContent).toContain('white-space: nowrap;');
    expect(cssContent).toContain('overflow: hidden;');
  });

  test('oklch color tokens defined in root', () => {
    expect(cssContent).toContain('oklch(');
    expect(cssContent).toContain('--surface-main:');
    expect(cssContent).toContain('--text-primary:');
    expect(cssContent).toContain('--text-muted:');
    // text-muted lightness check
    expect(cssContent).toContain('oklch(0.52 0.03 256)');
  });

  test('prefers-reduced-motion media query', () => {
    expect(cssContent).toContain('@media (prefers-reduced-motion: reduce)');
    expect(cssContent).toContain('animation-duration: 0.01ms !important;');
  });

  test('source-specific apply button classes', () => {
    const expectedClasses = [
      '.btn-linkedin', '.btn-google', '.btn-instahyre', '.btn-yc',
      '.btn-ats', '.btn-indeed', '.btn-wellfound', '.btn-naukri',
      '.btn-glassdoor', '.btn-cutshort', '.btn-hirist', '.btn-direct'
    ];
    for (const clsName of expectedClasses) {
      expect(cssContent).toContain(clsName);
    }
  });
});
