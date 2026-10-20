document.addEventListener('DOMContentLoaded', () => {
  const statusElement = document.querySelector('[data-tracking-status]');
  const locationStatus = document.querySelector('[data-tracking-location-status]');
  const mapFrame = document.querySelector('[data-tracking-map-frame]');
  const mapElement = document.querySelector('[data-tracking-map]');
  const emergencyId = document.querySelector('[data-emergency-live-location]')?.dataset.emergencyId
    || document.querySelector('[data-tracking-emergency-id]')?.dataset.trackingEmergencyId;
  if (!statusElement || !locationStatus || !mapFrame || !mapElement || !emergencyId) return;

  let map;
  let marker;
  let lastLocation;
  let refreshInProgress = false;

  const showLocation = (result) => {
    if (result.latitude === null || result.longitude === null) {
      if (map) mapFrame.hidden = false;
      locationStatus.textContent = 'No location has been shared yet. Start live sharing above or use the location provided with the request.';
      return;
    }

    const position = [result.latitude, result.longitude];
    mapFrame.hidden = false;
    if (!map) {
      if (!window.L) {
        locationStatus.textContent = 'The latest coordinates are available, but the map could not load.';
        return;
      }
      map = L.map(mapElement).setView(position, 16);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);
      marker = L.marker(position).addTo(map);
      window.setTimeout(() => map.invalidateSize(), 0);
    } else if (!lastLocation || lastLocation[0] !== position[0] || lastLocation[1] !== position[1]) {
      marker.setLatLng(position);
      map.panTo(position);
    }
    lastLocation = position;
    const updateTime = result.updated_at
      ? new Date(result.updated_at).toLocaleTimeString()
      : 'time unavailable';
    locationStatus.textContent = `Latest shared location: ${result.location || 'GPS coordinates'} · updated ${updateTime}.`;
  };

  const refresh = async () => {
    if (refreshInProgress) return;
    refreshInProgress = true;
    try {
      const response = await fetch(`/api/request-tracking/${encodeURIComponent(emergencyId)}`, {
        cache: 'no-store',
        signal: AbortSignal.timeout(10000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `Tracking update failed (${response.status})`);
      statusElement.textContent = result.status;
      showLocation(result);
    } catch (error) {
      locationStatus.textContent = 'Could not refresh the latest location. Retrying shortly.';
      console.error(error);
    } finally {
      refreshInProgress = false;
    }
  };

  refresh();
  window.setInterval(refresh, 5000);
});
