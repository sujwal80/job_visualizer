# Locality Search & Dynamic Map Zoom

> Technical documentation on locality-level search indexing, tokenization algorithms, dynamic viewport bounding box computation, smart zoom clamps, and map marker deconfliction.

---

## 1. Problem Statement & User Experience Challenges

When users navigate a geospatial job visualizer, they frequently search for specific micro-markets, neighborhoods, and tech hubs (such as *"Koramangala"*, *"HSR Layout"*, *"Indiranagar"*, *"Cyber City"*, *"BKC"*, *"Gachibowli"*, or *"Whitefield"*) rather than just broad city names.

### Historical Failure Modes
1. **Search Misses**: The search engine initially only evaluated company names and industry tags, returning zero results when users typed locality names.
2. **Zoom Disconnect**: When a user queried a specific neighborhood, the map remained zoomed out at the national level (`zoom 4.5`) or broad city level (`zoom 11`), forcing users to manually pinch-to-zoom and pan.
3. **Over-Zooming / Under-Zooming**: Nominatim bounding box returns for single points often caused the camera to zoom in excessively (`zoom 19+` where map tiles were empty) or zoom out inappropriately.
4. **Co-location Clutter**: When dozens of startups were located in the same tech park or co-working building, their markers rendered on top of each other, obscuring all but the top logo.

---

## 2. Solutions & Technical Implementation

```mermaid
flowchart TD
    UserInput["User Enters Query (e.g. 'Koramangala' or 'BKC')"] --> Tokenizer["Tokenize & Normalize Query"]
    
    Tokenizer --> Classifier{"Is Job Keyword or Location?"}
    
    Classifier -->|Job Keyword (e.g. 'DevOps')| KeywordFilter["Filter by Job Openings & Keep Viewport"]
    Classifier -->|Location Query| GeoResolver["Geocode / Locality Cache Lookup"]
    
    GeoResolver --> ViewportCalc["Calculate Bounding Box & Center Lat/Lng"]
    ViewportCalc --> ZoomClamp["Apply Smart Zoom Clamps (13.5x for Locality, 11x for City)"]
    
    ZoomClamp --> CameraAnim["Execute Smooth Animated flyTo()"]
    CameraAnim --> EdgeQuery["Fetch Filtered Startups from /api/startups"]
    
    EdgeQuery --> Deconflict["Apply Spiral Marker Deconfliction"]
    Deconflict --> ViewportCull["Perform Dynamic Viewport Marker Culling"]
```

---

## 3. Tokenized Address & Multi-Field Search

### 3.1 Backend Indexing (`backend/services/startup_service.js`)
In `filterAndSortStartups()`, search queries are split into discrete lowercased tokens:
```javascript
const tokens = searchQuery.split(/\s+/).map(t => t.toLowerCase()).filter(Boolean);
```
Every token must match at least one attribute across the startup entity:
* Company Name & Canonical Slug
* Company Description & Mission Statement
* Office Address & City of all items in `offices[]`
* Required Technical Skills (both company-level and job-specific)
* Founder Names
* Open Job Titles, Departments, and Salary Strings

### 3.2 Metro Synonym Normalization
To handle alternative spellings and administrative variations across Indian metros, the system normalizes queries using `config.REGION_SYNONYM_MAP`:
* `bangalore` ⟷ `bengaluru` ⟷ `blr`
* `delhi` ⟷ `new delhi` ⟷ `ncr` ⟷ `gurugram` ⟷ `gurgaon` ⟷ `noida`
* `bombay` ⟷ `mumbai`
* `madras` ⟷ `chennai`

---

## 4. Smart Viewport Bounding Box & Zoom Clamping

### 4.1 Zoom Hierarchy & Clamping Rules (`modules/router.js` & `modules/map_manager.js`)

| Query Type | Examples | Target Zoom Level | Camera Behavior |
| :--- | :--- | :--- | :--- |
| **All India / Global** | Blank query, `"All locations"` | `4.5` (center: `[78.9629, 22.5937]`) | Global view of India tech ecosystem |
| **Metro Hub** | `"Bengaluru"`, `"Mumbai"`, `"Delhi NCR"` | `11.0 – 12.0` | Encompasses entire metropolitan ring road |
| **Locality / Suburb** | `"Koramangala"`, `"BKC"`, `"Cyber City"`, `"Gachibowli"` | `13.5 – 14.5` | Focuses on neighborhood street layout |
| **Single Entity Focus** | Clicking a company card or direct URL `#company_id=142` | `15.0 – 16.0` | Direct rooftop focus with active pin highlight |

### 4.2 Programmatic Camera Lock
During animated transitions (`map.flyTo`), user interactions and bounding box auto-refetches are temporarily suspended for 2,500ms using `lockProgrammaticMove(2500)` to prevent jarring viewport feedback loops.

---

## 5. Marker Overlap Deconfliction: Mathematical Spiral

When multiple startups share the exact same physical building or tech park coordinates, rendering markers directly on top of each other prevents users from clicking individual companies.

### Spiral Layout Algorithm (`modules/map_manager.js`)
```javascript
const coordKey = `${lat.toFixed(5)},${lng.toFixed(5)}`;

if (coordinatesRegistry[coordKey]) {
    const count = coordinatesRegistry[coordKey];
    const angle = count * (2 * Math.PI / 8);            // 8 markers per concentric ring
    const radius = 0.00025 * Math.ceil(count / 8);      // ~25 meters radial increment
    lat += radius * Math.sin(angle);
    lng += radius * Math.cos(angle);
    coordinatesRegistry[coordKey] = count + 1;
} else {
    coordinatesRegistry[coordKey] = 1;
}
```
* **Coordinate Drift Prevention**: On every filter change or search execution, `coordinatesRegistry` is reset, restoring all markers to their canonical `orig_lat` / `orig_lng` before computing new spiral offsets.

---

## 6. Dynamic Viewport Marker Culling

Rendering thousands of DOM elements on a WebGL/Leaflet canvas degrades mobile frame rates and drains battery life. 

`map_manager.js: cullMarkers()` executes on every `moveend` event:
1. Calculates the current map viewport bounding box (`bounds.getSouth()`, `bounds.getNorth()`, `bounds.getWest()`, `bounds.getEast()`).
2. Checks if each marker's coordinate is inside the visible viewport.
3. Automatically detaches (`marker.remove()`) off-screen markers and attaches (`marker.addTo(map)`) on-screen markers.
4. **Performance Gain**: Reduces active DOM nodes from ~2,500 to <150, maintaining smooth 60 FPS scrolling and panning.
