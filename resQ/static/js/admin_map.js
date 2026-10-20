document.addEventListener('DOMContentLoaded', () => {
  const mapElement = document.querySelector('[data-admin-live-map]');
  const status = document.querySelector('[data-live-map-status]');
  if (!mapElement || !status) return;
  if (!window.L) {
    status.textContent = 'The interactive map could not load. Refresh the page to try again.';
    return;
  }

  const map = L.map(mapElement).setView([20.5937, 78.9629], 5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const requestMarkers = new Map();
  const ambulanceMarkers = new Map();
  let fittedInitialLocations = false;

  const popupFor = (title, lines) => {
    const popup = document.createElement('div');
    const heading = document.createElement('strong');
    heading.textContent = title;
    popup.append(heading);
    lines.filter(Boolean).forEach((line) => {
      const detail = document.createElement('div');
      detail.textContent = line;
      popup.append(detail);
    });
    return popup;
  };

  const icons = {
    request: L.divIcon({
      className: 'live-location-marker live-request-marker',
      html: '<span>!</span>',
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    }),
    ambulance: L.divIcon({
      className: 'live-location-marker live-ambulance-marker',
      html: '<span>+</span>',
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    }),
  };

  const updateMarkers = (layer, items, kind) => {
    const activeIds = new Set();
    items.forEach((item) => {
      const key = String(item.id);
      activeIds.add(key);
      const isRequest = kind === 'request';
      const markerOptions = isRequest
        ? { title: `Emergency ${item.id}`, icon: icons.request }
        : { title: item.name, icon: icons.ambulance };
      const existing = layer.get(key);
      const marker = existing || L.marker(
        [item.latitude, item.longitude],
        markerOptions,
      ).addTo(map);
      marker.setLatLng([item.latitude, item.longitude]);
      marker.bindPopup(isRequest
        ? popupFor(`Emergency ${item.id}`, [
          item.name,
          `${item.category} · ${item.priority} priority · ${item.status}`,
          item.required_assistance ? `Needs: ${item.required_assistance}` : '',
          item.location,
        ])
        : popupFor(item.name, [
          `${item.type} · ${item.availability}`,
          item.location,
        ]));
      if (!existing) layer.set(key, marker);
    });

    layer.forEach((marker, key) => {
      if (!activeIds.has(key)) {
        map.removeLayer(marker);
        layer.delete(key);
      }
    });
  };

  const refresh = async () => {
    try {
      const response = await fetch('/api/admin/live-locations', {
        cache: 'no-store',
        signal: AbortSignal.timeout(10000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `Live location update failed (${response.status})`);

      updateMarkers(requestMarkers, result.requests, 'request');
      updateMarkers(ambulanceMarkers, result.ambulances, 'ambulance');
      if (!fittedInitialLocations) {
        const markers = [...requestMarkers.values(), ...ambulanceMarkers.values()];
        if (markers.length) {
          map.fitBounds(L.featureGroup(markers).getBounds().pad(0.15), { maxZoom: 13 });
          fittedInitialLocations = true;
        }
      }
      status.textContent = `Live · updated ${new Date(result.updated_at).toLocaleTimeString()}`;
    } catch (error) {
      status.textContent = 'Live location updates are unavailable. Retrying shortly.';
      console.error(error);
    }
  };

  refresh();
  window.setInterval(refresh, 10000);
});
