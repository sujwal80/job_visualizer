import * as config from '../config.js';
import { safeFloat, checkHasPin, sanitizeString, sanitizeUrl, stripRedundant } from '../utils/validators.js';

const COUNTRY_NAMES = new Set(['india', 'in', 'usa', 'us', 'united states', 'america', 'uk', 'united kingdom', 'gb', 'great britain']);

let cacheData = null;
let cacheMtime = 0;
let cacheStartups = null;

let fs = null;
async function getFs() {
  if (fs) return fs;
  if (typeof globalThis.WebSocketPair === 'undefined' && typeof process !== 'undefined') {
    fs = await import('node:fs/promises');
  }
  return fs;
}

export async function loadStartups() {
  const dataPath = './backend/startups.json'; 
  const _fs = await getFs();
  if (!_fs) return []; 
  
  try {
    const stat = await _fs.stat(dataPath);
    const currentMtime = stat.mtimeMs;
    if (cacheData !== null && currentMtime === cacheMtime) {
      return cacheData;
    }
    
    const rawData = await _fs.readFile(dataPath, 'utf-8');
    let data = JSON.parse(rawData);
    if (!Array.isArray(data)) data = [];
    
    for (const s of data) {
      if (typeof s !== 'object') continue;
      s.has_pin = checkHasPin(s);
      for (const fKey of ["name", "city", "description", "industry", "funding_stage", "total_raised", "verified_email"]) {
        if (fKey in s) s[fKey] = sanitizeString(s[fKey]);
      }
      if (s.website) s.website = sanitizeUrl(s.website);
      if (s.url) s.url = sanitizeUrl(s.url);
      
      for (const fObj of (s.founders || [])) {
        if (typeof fObj === 'object') {
          if (fObj.name) fObj.name = sanitizeString(fObj.name);
          if (fObj.linkedin) fObj.linkedin = sanitizeUrl(fObj.linkedin);
        }
      }
      for (const jObj of (s.job_openings || [])) {
        if (typeof jObj === 'object') {
          for (const jKey of ["title", "department", "experience", "salary", "job_type", "location", "posted_date", "source"]) {
            if (jKey in jObj) jObj[jKey] = sanitizeString(jObj[jKey]);
          }
          if (jObj.url) jObj.url = sanitizeUrl(jObj.url);
          if (Array.isArray(jObj.skills)) {
            jObj.skills = jObj.skills.map(sanitizeString).filter(Boolean);
          }
        }
      }
    }
    
    cacheData = data;
    cacheMtime = currentMtime;
    return data;
  } catch (e) {
    return cacheData || [];
  }
}

export function filterAndSortStartups(startups, minLat, maxLat, minLng, maxLng, limit, options = {}) {
  const {
    cityQuery = "", skillQuery = "", industryQuery = "", searchQuery = "",
    deptQuery = "", expQuery = "", hasJobs = false, roleQuery = "",
    salaryMinQuery = null, expLevelQuery = "", workTypeQuery = ""
  } = options;
  
  const filtered = [];
  for (const s of startups) {
    const lat = safeFloat(s.lat);
    const lng = safeFloat(s.lng);
    
    if (minLat !== null && maxLat !== null && minLng !== null && maxLng !== null) {
      const latSpan = Math.abs(maxLat - minLat);
      const effLat = lat !== null ? lat : config.DEFAULT_MAP_CENTER_LAT;
      const effLng = lng !== null ? lng : config.DEFAULT_MAP_CENTER_LNG;
      
      if (s.has_pin === false) {
        if (latSpan < 1.0) {
          if (effLat < minLat || effLat > maxLat || effLng < minLng || effLng > maxLng) continue;
        }
      } else {
        if (effLat < minLat || effLat > maxLat || effLng < minLng || effLng > maxLng) continue;
      }
    }
    
    if (cityQuery) {
      const cityQueryClean = cityQuery.trim().toLowerCase();
      const cityVal = (s.city || s.location || "").toLowerCase();
      let isMatch = false;
      
      for (const [regionKey, synSet] of Object.entries(config.REGION_SYNONYM_MAP)) {
        if (synSet.has(cityQueryClean)) {
          let targetSyns = synSet;
          if (!COUNTRY_NAMES.has(cityQueryClean)) {
            targetSyns = new Set([...synSet].filter(syn => !COUNTRY_NAMES.has(syn)));
          }
          
          for (const syn of targetSyns) {
            const regex = new RegExp(`\\b${escapeRegExp(syn)}\\b`);
            if (regex.test(cityVal)) {
              isMatch = true;
              break;
            }
          }
          if (isMatch) break;
        }
      }
      
      if (!isMatch) {
        const normalizedQuery = cityQueryClean.replace(/,\s*[a-z\s]+$/, '').trim();
        const compQuery = normalizedQuery.replace("bangalore", "bengaluru");
        const compCity = cityVal.replace("bangalore", "bengaluru");
        if (!compCity.includes(compQuery) && !compCity.includes(cityQueryClean)) {
          continue;
        }
      }
    }
    
    if (skillQuery) {
      const sSkills = [];
      if (Array.isArray(s.skills)) {
        sSkills.push(...s.skills.map(sk => String(sk).toLowerCase()));
      } else if (typeof s.skills === 'string') {
        sSkills.push(s.skills.toLowerCase());
      }
      for (const j of (s.job_openings || [])) {
        if (j && Array.isArray(j.skills)) {
          sSkills.push(...j.skills.map(sk => String(sk).toLowerCase()));
        }
      }
      if (!sSkills.some(sk => sk.includes(skillQuery))) continue;
    }
    
    if (industryQuery) {
      const industryVal = (s.industry || "").toLowerCase();
      if (!industryVal.includes(industryQuery)) continue;
    }
    
    if (searchQuery) {
      const tokens = searchQuery.split(/\s+/).map(t => t.toLowerCase()).filter(Boolean);
      if (tokens.length > 0) {
        let startupMatches = true;
        for (const token of tokens) {
          const nameVal = (s.name || "").toLowerCase();
          const descVal = (s.description || "").toLowerCase();
          const cityVal = (s.city || s.location || "").toLowerCase();
          
          let tokenMatched = nameVal.includes(token) || descVal.includes(token) || cityVal.includes(token);
          
          if (!tokenMatched) {
            const sSkills = s.skills;
            if (Array.isArray(sSkills)) {
              tokenMatched = sSkills.some(sk => String(sk).toLowerCase().includes(token));
            } else if (typeof sSkills === 'string') {
              tokenMatched = sSkills.toLowerCase().includes(token);
            }
          }
          
          if (!tokenMatched) {
            const founderNames = (s.founders || []).map(f => (f.name || "").toLowerCase());
            tokenMatched = founderNames.some(fn => fn.includes(token));
          }
          
          if (!tokenMatched) {
            for (const j of (s.job_openings || [])) {
              if (typeof j !== 'object') continue;
              const jTitle = (j.title || "").toLowerCase();
              const jDept = (j.department || "").toLowerCase();
              const jSalary = (j.salary || "").toLowerCase();
              const jExp = (j.experience || "").toLowerCase();
              const jSkills = j.skills || [];
              
              if (jTitle.includes(token) || jDept.includes(token) || jSalary.includes(token) || jExp.includes(token) ||
                  jSkills.some(sk => String(sk).toLowerCase().includes(token))) {
                tokenMatched = true;
                break;
              }
            }
          }
          
          if (!tokenMatched) {
            startupMatches = false;
            break;
          }
        }
        if (!startupMatches) continue;
      }
    }
    
    const hasJobFilters = !!(roleQuery || salaryMinQuery !== null || expLevelQuery || workTypeQuery);
    const jobOpenings = s.job_openings || [];
    const filteredJobs = [];
    
    for (const j of jobOpenings) {
      if (typeof j !== 'object') continue;
      if (roleQuery && !j.title.toLowerCase().includes(roleQuery)) continue;
      if (salaryMinQuery !== null) {
        const maxSal = parseMaxSalary(j.salary);
        if (maxSal === null || maxSal < salaryMinQuery) continue;
      }
      if (expLevelQuery && !matchExpLevel(j.experience || "", expLevelQuery)) continue;
      if (workTypeQuery && !matchWorkType(j, workTypeQuery, s.is_remote_office)) continue;
      filteredJobs.push(j);
    }
    
    let sCopy;
    if (hasJobFilters) {
      if (filteredJobs.length === 0) continue;
      sCopy = { ...s, job_openings: filteredJobs };
    } else {
      sCopy = s;
    }
    
    const effectiveJobs = sCopy.job_openings || sCopy.jobs || [];
    if (deptQuery) {
      if (!effectiveJobs.some(j => (j.department || "").toLowerCase().includes(deptQuery))) continue;
    }
    if (expQuery) {
      if (!effectiveJobs.some(j => (j.experience || "").toLowerCase().includes(expQuery) || (j.job_type || "").toLowerCase().includes(expQuery))) continue;
    }
    if (hasJobs) {
      const jobCnt = effectiveJobs.length > 0 ? effectiveJobs.length : (sCopy.job_count || 0);
      if (jobCnt === 0) continue;
    }
    
    filtered.push(sCopy);
  }
  
  filtered.sort((a, b) => {
    const aJobs = a.job_openings || a.jobs || [];
    const bJobs = b.job_openings || b.jobs || [];
    return bJobs.length - aJobs.length;
  });
  
  if (!hasJobs && limit >= 0) {
    return filtered.slice(0, limit);
  }
  return filtered;
}

export function formatStartupSummary(s) {
  const logoDomain = s.logo_domain || "";
  const logoSvgUrl = s.logo_svg_url || "";
  const logoUrl = logoSvgUrl || "";
  const website = sanitizeUrl(s.website || "");
  
  const jobOpenings = s.job_openings || [];
  const experiences = [...new Set(jobOpenings.map(j => sanitizeString(j.experience)).filter(exp => exp && exp !== "Not specified"))];
  const salaries = [...new Set(jobOpenings.map(j => sanitizeString(j.salary)).filter(sal => sal && sal !== "Not disclosed"))];
  const jobTypes = [...new Set(jobOpenings.map(j => sanitizeString(j.job_type)).filter(Boolean))];
  const skillsSet = new Set();
  for (const j of jobOpenings) {
    if (j && Array.isArray(j.skills)) {
      j.skills.forEach(sk => skillsSet.add(sk.trim()));
    }
  }
  
  const latVal = safeFloat(s.lat);
  const lngVal = safeFloat(s.lng);
  
  return {
    id: s.id,
    name: sanitizeString(s.name),
    lat: latVal !== null ? latVal : config.DEFAULT_MAP_CENTER_LAT,
    lng: lngVal !== null ? lngVal : config.DEFAULT_MAP_CENTER_LNG,
    city: sanitizeString(s.city),
    experience: experiences,
    salary: salaries,
    job_type: jobTypes,
    skills: [...skillsSet],
    logo_url: logoUrl,
    url: website,
    description: sanitizeString(s.description).substring(0, 120),
    has_pin: s.has_pin !== false,
    industry: sanitizeString(s.industry),
    head_count: s.head_count,
    logo_domain: logoDomain,
    website: website,
    funding_stage: sanitizeString(s.funding_stage || "Seed / Active"),
    total_raised: sanitizeString(s.total_raised || "Undisclosed"),
    is_active_website: s.is_active_website !== false,
    verified_email: sanitizeString(s.verified_email),
    job_count: jobOpenings.length,
    job_titles: jobOpenings.map(j => sanitizeString(j.title || "")),
    founder_names: (s.founders || []).map(f => sanitizeString(f.name || ""))
  };
}

export function formatStartupDetails(s) {
  const sCopy = { ...s };
  for (const field of ["name", "city", "description", "industry", "funding_stage", "total_raised", "verified_email"]) {
    if (field in sCopy) sCopy[field] = sanitizeString(sCopy[field]);
  }
  const logoDomain = sCopy.logo_domain || "";
  const logoSvgUrl = sCopy.logo_svg_url || "";
  sCopy.logo_url = logoSvgUrl || "";
  sCopy.url = sanitizeUrl(sCopy.website || "");
  if (sCopy.website) sCopy.website = sanitizeUrl(sCopy.website);
  
  const jobOpenings = sCopy.job_openings || [];
  delete sCopy.job_openings;
  
  const cleanJobs = jobOpenings.map(j => ({
    title: sanitizeString(j.title),
    url: sanitizeUrl(j.url || ""),
    department: sanitizeString(j.department || "General"),
    experience: sanitizeString(j.experience),
    salary: sanitizeString(j.salary),
    job_type: sanitizeString(j.job_type),
    skills: (j.skills || []).map(sanitizeString).filter(Boolean),
    location: sanitizeString(j.location || sCopy.city || config.DEFAULT_TARGET_CITY),
    posted_date: sanitizeString(j.posted_date || "Active"),
    source: sanitizeString(j.source || "Direct")
  }));
  
  sCopy.jobs = cleanJobs;
  sCopy.job_count = cleanJobs.length;
  
  sCopy.experience = [...new Set(cleanJobs.map(j => j.experience).filter(exp => exp && exp !== "Not specified"))];
  sCopy.salary = [...new Set(cleanJobs.map(j => j.salary).filter(sal => sal && sal !== "Not disclosed"))];
  sCopy.job_type = [...new Set(cleanJobs.map(j => j.job_type).filter(Boolean))];
  
  const skillsSet = new Set();
  for (const j of cleanJobs) {
    j.skills.forEach(sk => skillsSet.add(sk.trim()));
  }
  sCopy.skills = [...skillsSet];
  
  if (Array.isArray(sCopy.founders)) {
    sCopy.founders = sCopy.founders.map(f => {
      if (typeof f === 'object') {
        const fCopy = { ...f };
        if (fCopy.name) fCopy.name = sanitizeString(fCopy.name);
        if (fCopy.linkedin) fCopy.linkedin = sanitizeUrl(fCopy.linkedin);
        return fCopy;
      }
      return f;
    });
  }
  
  return stripRedundant(sCopy);
}

export function formatLightweightSummary(s) {
  const logoSvgUrl = s.logo_svg_url || "";
  const logoUrl = logoSvgUrl || "";
  const latVal = safeFloat(s.lat);
  const lngVal = safeFloat(s.lng);
  const jobs = s.job_openings || s.jobs || [];
  const jobCount = jobs.length > 0 ? jobs.length : (s.job_count || 0);
  
  return {
    id: s.id,
    name: sanitizeString(s.name),
    lat: latVal !== null ? latVal : config.DEFAULT_MAP_CENTER_LAT,
    lng: lngVal !== null ? lngVal : config.DEFAULT_MAP_CENTER_LNG,
    city: sanitizeString(s.city),
    logo_url: logoUrl,
    industry: sanitizeString(s.industry),
    job_count: jobCount,
    has_pin: s.has_pin !== false,
    head_count: s.head_count,
    funding_stage: sanitizeString(s.funding_stage || "Seed / Active"),
    verified_email: sanitizeString(s.verified_email),
    founder_names: (s.founders || []).map(f => sanitizeString(f.name || ""))
  };
}

export async function getDataVersion() {
  const _fs = await getFs();
  if (!_fs) return "v1.0.0";
  try {
    const stat = await _fs.stat('./startups.json');
    return String(Math.floor(stat.mtimeMs / 1000));
  } catch (e) {
    return "v1.0.0";
  }
}

export async function loadStartupsFromAssets(assetsBinding) {
  if (cacheStartups !== null) return cacheStartups;
  
  const req = new Request("http://assets/static/data/startups.json");
  const resp = await assetsBinding.fetch(req);
  let data = await resp.json();
  
  if (!Array.isArray(data)) data = [];
  
  for (const s of data) {
    if (typeof s !== 'object') continue;
    s.has_pin = checkHasPin(s);
    for (const fKey of ["name", "city", "description", "industry", "funding_stage", "total_raised", "verified_email"]) {
      if (fKey in s) s[fKey] = sanitizeString(s[fKey]);
    }
    if (s.website) s.website = sanitizeUrl(s.website);
    if (s.url) s.url = sanitizeUrl(s.url);
    for (const fObj of (s.founders || [])) {
      if (typeof fObj === 'object') {
        if (fObj.name) fObj.name = sanitizeString(fObj.name);
        if (fObj.linkedin) fObj.linkedin = sanitizeUrl(fObj.linkedin);
      }
    }
    for (const jObj of (s.job_openings || [])) {
      if (typeof jObj === 'object') {
        for (const jKey of ["title", "department", "experience", "salary", "job_type", "location", "posted_date", "source"]) {
          if (jKey in jObj) jObj[jKey] = sanitizeString(jObj[jKey]);
        }
        if (jObj.url) jObj.url = sanitizeUrl(jObj.url);
        if (Array.isArray(jObj.skills)) {
          jObj.skills = jObj.skills.map(sanitizeString).filter(Boolean);
        }
      }
    }
  }
  cacheStartups = data;
  return data;
}

export async function loadStartupsUnified(env = null) {
  const assetsBinding = env ? env.ASSETS : null;
  if (assetsBinding) {
    return await loadStartupsFromAssets(assetsBinding);
  }
  return await loadStartups();
}

function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function parseMaxSalary(salaryStr) {
  if (!salaryStr) return null;
  const s = salaryStr.trim().toLowerCase();
  const ignorable = ["not specified", "not disclosed", "undisclosed", "competitive", "negotiable"];
  if (ignorable.some(x => s.includes(x))) return null;
  
  const clean = s.replace(/₹/g, "").replace(/,/g, "");
  const numbers = (clean.match(/\d+\.?\d*/g) || []).map(Number);
  if (numbers.length === 0) return null;
  
  const processed = numbers.map(num => num >= 1000 ? num / 100000.0 : num);
  return Math.max(...processed);
}

export function parseExperienceYears(expStr) {
  if (!expStr) return [null, null];
  const s = expStr.trim().toLowerCase();
  if (s === "fresher" || s === "entry") return [0, 0];
  if (s.includes("not specified") || s.includes("not disclosed")) return [null, null];
  
  const numbers = (s.match(/\d+/g) || []).map(Number);
  if (numbers.length === 0) return [null, null];
  
  if (numbers.length >= 2) {
    return [numbers[0], numbers[1]];
  } else if (s.includes("+") || s.includes("above") || s.includes("more")) {
    return [numbers[0], 100];
  } else {
    return [numbers[0], numbers[0]];
  }
}

export function matchExpLevel(expStr, expLevelQuery) {
  if (!expLevelQuery) return true;
  const q = expLevelQuery.trim().toLowerCase();
  
  const qNum = parseFloat(q);
  if (!isNaN(qNum)) {
    const [minYears, maxYears] = parseExperienceYears(expStr);
    if (minYears === null) return false;
    return qNum >= minYears && qNum <= maxYears;
  } else {
    const [minYears, maxYears] = parseExperienceYears(expStr);
    if (minYears === null) return expStr.trim().toLowerCase().includes(q);
    
    if (q === "entry" || q === "fresher") {
      return minYears <= 2;
    } else if (q === "mid" || q === "intermediate") {
      return minYears < 5 && maxYears >= 2;
    } else if (q === "senior" || q === "lead") {
      return minYears >= 5;
    } else {
      return expStr.trim().toLowerCase().includes(q);
    }
  }
}

export function matchWorkType(job, workTypeQuery, isRemoteOffice = null) {
  if (!workTypeQuery) return true;
  const q = workTypeQuery.trim().toLowerCase();
  
  const jobType = (job.job_type || "").toLowerCase();
  const location = (job.location || "").toLowerCase();
  const title = (job.title || "").toLowerCase();
  
  const hasRemote = jobType.includes("remote") || location.includes("remote") || title.includes("remote");
  const hasHybrid = jobType.includes("hybrid") || location.includes("hybrid") || title.includes("hybrid");
  const hasOnsite = ["onsite", "on-site", "in-office", "in office"].some(kw => jobType.includes(kw) || location.includes(kw) || title.includes(kw));
  
  if (q === "remote") {
    if (hasOnsite) return false;
    if (hasRemote) return true;
    if (!hasRemote && !hasHybrid) {
      if (isRemoteOffice === true) return true;
    }
    return false;
  }
  if (q === "hybrid") {
    return hasHybrid;
  }
  if (q === "on-site" || q === "onsite") {
    if (hasOnsite) return true;
    if (hasRemote || hasHybrid) return false;
    if (isRemoteOffice === true) return false;
    return true;
  }
  return location.includes(q);
}
