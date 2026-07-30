import { sanitizeString, safeFloat, checkHasPin, sanitizeUrl, stripRedundant } from '../backend/utils/validators.js';
import { checkRateLimit, rateLimits } from '../backend/utils/rate_limiter.js';
import { filterAndSortStartups, formatStartupSummary, formatStartupDetails } from '../backend/services/startup_service.js';

describe('Modular Validators', () => {
  test('sanitizeString', () => {
    expect(sanitizeString(null)).toBe("");
    expect(sanitizeString(123)).toBe(123);
    expect(sanitizeString("  <script>alert(1)</script>Hello World  ")).toBe("alert(1)Hello World");
  });

  test('safeFloat', () => {
    expect(safeFloat("12.9716")).toBe(12.9716);
    expect(safeFloat("invalid_float")).toBeNull();
    expect(safeFloat("nan")).toBeNull();
    expect(safeFloat("inf")).toBeNull();
    expect(safeFloat("nan", 0.0)).toBe(0.0);
  });

  test('checkHasPin', () => {
    expect(checkHasPin({ lat: 12.9716, lng: 77.5946, city: "Bengaluru" })).toBe(false);
    expect(checkHasPin({ lat: 12.9352, lng: 77.6245, address: "Koramangala 4th Block, Bengaluru" })).toBe(true);
  });

  test('sanitizeUrl', () => {
    expect(sanitizeUrl("https://worldtech.map")).toBe("https://worldtech.map");
    expect(sanitizeUrl("javascript:alert(1)")).toBe("");
    expect(sanitizeUrl("data:text/html,<script>")).toBe("");
    expect(sanitizeUrl("vbscript:msgbox")).toBe("");
  });

  test('stripRedundant', () => {
    const sample = {
      id: 1,
      name: "Test AI",
      lat: NaN,
      lng: 77.59,
      empty_dict: {},
      empty_list: [],
      none_val: null
    };
    const cleaned = stripRedundant(sample);
    expect(cleaned.lat).toBe(0.0);
    expect(cleaned.empty_dict).toBeUndefined();
    expect(cleaned.empty_list).toBeUndefined();
    expect(cleaned.none_val).toBe(""); 
  });
});

describe('Modular Rate Limiter', () => {
  test('rate limiter in memory', () => {
    const testIp = "192.0.2.100";
    rateLimits.delete(testIp);
    
    for (let i = 0; i < 5; i++) {
      const [allowed, retryAfter, remaining, limitVal] = checkRateLimit(testIp, 5, 10);
      expect(allowed).toBe(true);
      expect(remaining).toBe(5 - (i + 1));
      expect(limitVal).toBe(5);
    }
    
    const [allowed, retryAfter, remaining] = checkRateLimit(testIp, 5, 10);
    expect(allowed).toBe(false);
    expect(remaining).toBe(0);
    expect(retryAfter).toBeGreaterThanOrEqual(1);
  });
});

describe('Modular Startup Service', () => {
  let sampleStartups;
  
  beforeEach(() => {
    sampleStartups = [
      { id: 1, name: "AI Corp", lat: 12.95, lng: 77.60, city: "Bengaluru", industry: "AI", job_openings: [{ title: "Eng", skills: ["Python", "PyTorch"] }], has_pin: true },
      { id: 2, name: "Fintech Inc", lat: 13.05, lng: 77.70, city: "Hyderabad", industry: "Fintech", job_openings: [], has_pin: true },
      { id: 3, name: "Remote Hub", lat: null, lng: null, city: "Remote", industry: "SaaS", job_openings: [{ title: "Dev", skills: ["React"] }], has_pin: false }
    ];
  });

  test('filter_and_sort_startups_by_bounds', () => {
    const res = filterAndSortStartups(sampleStartups, 12.00, 13.00, 77.50, 77.65, 10);
    const ids = res.map(s => s.id);
    expect(ids).toContain(1);
    expect(ids).toContain(3);
    expect(ids).not.toContain(2);
  });

  test('filter_by_skill_query', () => {
    const res = filterAndSortStartups(sampleStartups, null, null, null, null, 10, { skillQuery: "pytorch" });
    expect(res.length).toBe(1);
    expect(res[0].id).toBe(1);
  });

  test('format_startup_summary', () => {
    const summary = formatStartupSummary(sampleStartups[0]);
    expect(summary.job_count).toBe(1);
    expect(summary.skills).toContain("Python");
    expect(summary.job_openings).toBeUndefined();
  });
});
