import { state } from './state.js';
import { getDomain, createElement } from './utils.js';
import { selectAndOpenStartup } from './ui_manager.js';

export const industryColors = {
    "Artificial Intelligence": "#7e22ce",
    "CleanTech": "#15803d",
    "HealthTech": "#047857",
    "Fintech": "#c2410c",
    "B2B": "#0e7490",
    "SaaS": "#0369a1",
    "E-commerce": "#be185d",
    "Service Industry": "#ea580c",
    "EdTech": "#b45309",
    "Cybersecurity": "#475569",
    "Logistics": "#4f46e5"
};
export const defaultColor = "#2563eb";

const coordinatesRegistry = {};

// Initialize MapLibre Map centered globally
export const map = new maplibregl.Map({
    container: 'map',
    style: 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json',
    center: [78.9629, 20.5937],
    zoom: 4.5,
    minZoom: 1.5,
    maxZoom: 18,
    dragRotate: false,
    touchZoomRotate: true
});

map.touchZoomRotate.disableRotation();

map.on('load', () => {
    if (map && typeof map.resize === 'function') {
        map.resize();
    }
});

// Configure blue water body styles on CartoDB style load
map.on('style.load', () => {
    if (map.getLayer('water')) map.setPaintProperty('water', 'fill-color', '#89bceb');
    if (map.getLayer('waterway')) map.setPaintProperty('waterway', 'line-color', '#7aafe0');
    if (map.getLayer('water_shadow')) map.setPaintProperty('water_shadow', 'fill-color', '#98c6f0');
});

// Add navigation controls
map.addControl(new maplibregl.NavigationControl({
    showCompass: false
}), 'top-right');

export function createLogoContent(startup) {
    const domain = getDomain(startup);
    const color = industryColors[startup.industry] || defaultColor;

    const container = createElement('div', { className: 'logo-marker-container' });

    const fallback = createElement('div', { className: 'logo-marker-fallback' }, [
        String(startup.name || 'S').substring(0, 1).toUpperCase()
    ]);
    fallback.style.backgroundColor = color;
    fallback.style.border = '2px solid #ffffff';
    container.appendChild(fallback);

    if (logoUrlForStartup(startup)) {
        const logoUrl = logoUrlForStartup(startup);
        const img = createElement('img', {
            src: logoUrl,
            className: 'logo-marker-thumbnail',
            alt: String(startup.name || 'Startup Logo'),
            loading: 'lazy'
        });
        img.style.border = `2.5px solid ${color}`;
        img.onerror = () => { img.style.display = 'none'; };
        container.appendChild(img);
    }

    container.addEventListener('click', (e) => {
        e.stopPropagation();
        selectAndOpenStartup(startup.id);
    });

    return container;
}

function logoUrlForStartup(startup) {
    return startup.logo_url || '';
}

export function clearAllMarkers() {
    for (const marker of state.markersMap.values()) {
        marker.remove();
    }
    state.markersMap.clear();
    for (const key in coordinatesRegistry) delete coordinatesRegistry[key];
    if (state.tempRemoteMarker && state.currentSelectedId === null) {
        state.tempRemoteMarker.remove();
        state.tempRemoteMarker = null;
    }
}

export function initializeMarkers(startups) {
    startups.forEach(startup => {
        if (startup.has_pin === false) return;
        if (startup.orig_lat === undefined) {
            startup.orig_lat = startup.lat;
            startup.orig_lng = startup.lng;
        }
        let lat = startup.orig_lat;
        let lng = startup.orig_lng;
        const coordKey = `${lat.toFixed(5)},${lng.toFixed(5)}`;

        if (coordinatesRegistry[coordKey]) {
            const count = coordinatesRegistry[coordKey];
            const angle = count * (2 * Math.PI / 8);
            const radius = 0.00025 * Math.ceil(count / 8);
            lat += radius * Math.sin(angle);
            lng += radius * Math.cos(angle);
            coordinatesRegistry[coordKey] = count + 1;
        } else {
            coordinatesRegistry[coordKey] = 1;
        }

        startup.lat = lat;
        startup.lng = lng;

        const markerEl = createLogoContent(startup);
        const marker = new maplibregl.Marker({
            element: markerEl,
            anchor: 'center'
        })
            .setLngLat([lng, lat])
            .addTo(map);

        markerEl.title = String(startup.name || '');
        state.markersMap.set(startup.id, marker);
    });
}

export function updateMarkersDiff(startups) {
    const activeIds = new Set(startups.map(s => String(s.id)));

    for (const [id, marker] of state.markersMap.entries()) {
        if (!activeIds.has(String(id))) {
            marker.remove();
            state.markersMap.delete(id);
        }
    }

    // Reset coordinate registry on every update to prevent coordinate drift
    for (const key in coordinatesRegistry) {
        delete coordinatesRegistry[key];
    }

    startups.forEach(startup => {
        if (startup.has_pin === false) return;

        if (startup.orig_lat === undefined) {
            startup.orig_lat = startup.lat;
            startup.orig_lng = startup.lng;
        }
        let lat = startup.orig_lat;
        let lng = startup.orig_lng;
        const coordKey = `${lat.toFixed(5)},${lng.toFixed(5)}`;

        if (coordinatesRegistry[coordKey]) {
            const count = coordinatesRegistry[coordKey];
            const angle = count * (2 * Math.PI / 8);
            const radius = 0.00025 * Math.ceil(count / 8);
            lat += radius * Math.sin(angle);
            lng += radius * Math.cos(angle);
            coordinatesRegistry[coordKey] = count + 1;
        } else {
            coordinatesRegistry[coordKey] = 1;
        }

        startup.lat = lat;
        startup.lng = lng;

        const existingMarker = state.markersMap.get(startup.id) || state.markersMap.get(String(startup.id));
        if (existingMarker) {
            // Update position in case overlap group changed
            existingMarker.setLngLat([lng, lat]);
        } else {
            const markerEl = createLogoContent(startup);
            const marker = new maplibregl.Marker({
                element: markerEl,
                anchor: 'center'
            })
                .setLngLat([lng, lat])
                .addTo(map);

            markerEl.title = String(startup.name || '');
            state.markersMap.set(startup.id, marker);
        }
    });
}

export function updateMarkersVisualState() {
    for (const [id, marker] of state.markersMap.entries()) {
        if (!marker || typeof marker.getElement !== 'function') continue;
        const el = marker.getElement();
        if (!el) continue;
        if (state.currentSelectedId === id) {
            el.classList.add('active');
            el.style.zIndex = '1000';
        } else {
            el.classList.remove('active');
            el.style.zIndex = '';
        }
    }
    if (state.tempRemoteMarker && typeof state.tempRemoteMarker.getElement === 'function') {
        const tempEl = state.tempRemoteMarker.getElement();
        if (tempEl) {
            if (state.currentSelectedId) {
                tempEl.classList.add('active');
                tempEl.style.zIndex = '10000';
            } else {
                tempEl.classList.remove('active');
                tempEl.style.zIndex = '';
            }
        }
    }
}

export function drawSearchBoundary(geojson) {
    if (!map || !geojson) return;
    const source = map.getSource('search-boundary');
    if (source) {
        source.setData(geojson);
    } else {
        map.addSource('search-boundary', {
            type: 'geojson',
            data: geojson
        });
    }
    if (!map.getLayer('search-boundary-outline')) {
        map.addLayer({
            id: 'search-boundary-outline',
            type: 'line',
            source: 'search-boundary',
            paint: {
                'line-color': '#2563eb',
                'line-width': 2.5,
                'line-opacity': 0.8
            }
        });
    }
}

export function clearSearchBoundary() {
    if (!map) return;
    if (map.getLayer('search-boundary-outline')) {
        map.removeLayer('search-boundary-outline');
    }
    if (map.getSource('search-boundary')) {
        map.removeSource('search-boundary');
    }
}

