document.addEventListener('DOMContentLoaded', () => {
  const widget = document.querySelector('[data-location-widget]');
  if (!widget) return;

  const button = widget.querySelector('[data-location-button]');
  const feedback = widget.querySelector('[data-location-feedback]');
  const latitudeInput = widget.querySelector('[data-latitude]');
  const longitudeInput = widget.querySelector('[data-longitude]');
  const addressInput = widget.querySelector('[data-location-address]');
  const mapFrame = widget.querySelector('[data-map-frame]');
  const mapElement = widget.querySelector('[data-location-map]');
  const nearbyHospitals = widget.querySelector('[data-nearby-hospitals]');
  const hospitalStatus = widget.querySelector('[data-hospital-status]');
  const hospitalCount = widget.querySelector('[data-hospital-count]');
  const hospitalList = widget.querySelector('[data-hospital-list]');

  let map;
  let marker;
  let accuracyCircle;
  let hospitalLayer;
  let hospitals = [];
  let lookupSequence = 0;
  let hospitalsSequence = 0;

  const updateAddress = async (latitude, longitude) => {
    const sequence = ++lookupSequence;
    feedback.textContent = 'Location captured. Finding the address…';
    feedback.classList.remove('location-error', 'location-success');

    try {
      const response = await fetch(`/api/reverse-geocode?${new URLSearchParams({
        lat: latitude,
        lon: longitude,
      })}`, { signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error(`Address lookup failed with HTTP ${response.status}`);

      const result = await response.json();
      if (sequence !== lookupSequence) return;
      const address = result.display_name;
      if (address) {
        addressInput.value = address;
        feedback.textContent = `Location captured and address filled: ${latitude.toFixed(5)}, ${longitude.toFixed(5)}.`;
      } else {
        feedback.textContent = `Location captured: ${latitude.toFixed(5)}, ${longitude.toFixed(5)}. Enter a nearby landmark if you know one.`;
      }
      feedback.classList.add('location-success');
    } catch {
      if (sequence !== lookupSequence) return;
      feedback.textContent = `Coordinates captured: ${latitude.toFixed(5)}, ${longitude.toFixed(5)}. We couldn’t look up the address, so please enter it manually.`;
      feedback.classList.add('location-error');
    }
  };

  const renderHospitals = () => {
    hospitalList.replaceChildren();
    if (!map || !window.L) return;

    if (!hospitalLayer) hospitalLayer = L.layerGroup().addTo(map);
    hospitalLayer.clearLayers();

    hospitals.forEach((hospital) => {
      const icon = L.divIcon({
        className: 'hospital-map-marker',
        html: '<span>+</span>',
        iconSize: [30, 30],
        iconAnchor: [15, 29],
        popupAnchor: [0, -27],
      });
      const hospitalMarker = L.marker([hospital.latitude, hospital.longitude], { icon }).addTo(hospitalLayer);
      const popup = document.createElement('div');
      const name = document.createElement('strong');
      name.textContent = hospital.name;
      popup.append(name);
      if (hospital.address) {
        const address = document.createElement('div');
        address.textContent = hospital.address;
        popup.append(address);
      }
      const distance = document.createElement('div');
      distance.textContent = `${hospital.distance_km.toFixed(1)} km straight-line distance`;
      popup.append(distance);
      hospitalMarker.bindPopup(popup);

      const listItem = document.createElement('li');
      const selectButton = document.createElement('button');
      selectButton.type = 'button';
      selectButton.className = 'nearby-hospital-button';
      const details = document.createElement('span');
      const hospitalName = document.createElement('span');
      hospitalName.className = 'nearby-hospital-name';
      hospitalName.textContent = hospital.name;
      details.append(hospitalName);
      if (hospital.address) {
        const address = document.createElement('span');
        address.className = 'nearby-hospital-address';
        address.textContent = hospital.address;
        details.append(address);
      }
      const distanceLabel = document.createElement('span');
      distanceLabel.className = 'nearby-hospital-distance';
      distanceLabel.textContent = `${hospital.distance_km.toFixed(1)} km`;
      selectButton.append(details, distanceLabel);
      selectButton.addEventListener('click', () => {
        map.setView([hospital.latitude, hospital.longitude], 16);
        hospitalMarker.openPopup();
      });
      listItem.append(selectButton);
      hospitalList.append(listItem);
    });
  };

  const findNearbyHospitals = async (latitude, longitude) => {
    const sequence = ++hospitalsSequence;
    nearbyHospitals.hidden = false;
    hospitalCount.textContent = '';
    hospitalStatus.textContent = 'Searching OpenStreetMap for nearby hospitals…';
    hospitals = [];
    renderHospitals();

    try {
      const response = await fetch(`/api/nearby-hospitals?${new URLSearchParams({
        lat: latitude,
        lon: longitude,
      })}`, { signal: AbortSignal.timeout(30000) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `Hospital lookup failed with HTTP ${response.status}`);
      if (sequence !== hospitalsSequence) return;

      hospitals = (result.hospitals || []).slice(0, 1);
      hospitalCount.textContent = `Within ${result.radius_km} km`;
      if (hospitals.length) {
        hospitalStatus.textContent = 'Nearest mapped hospital found. Distance is a straight-line estimate.';
      } else {
        hospitalStatus.textContent = 'No mapped hospitals were found nearby. Map listings may be incomplete.';
      }
      renderHospitals();
    } catch (error) {
      if (sequence !== hospitalsSequence) return;
      hospitalStatus.textContent = `Nearby hospital search is unavailable. You can still use the map and submit the request.`;
    }
  };

  const showMap = (latitude, longitude, accuracy) => {
    mapFrame.hidden = false;
    if (!window.L) {
      feedback.textContent = 'Coordinates captured, but the map could not load. Enter a nearby landmark if you know one.';
      feedback.classList.add('location-error');
      return;
    }

    if (!map) {
      map = L.map(mapElement).setView([latitude, longitude], 16);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);
      marker = L.marker([latitude, longitude], { draggable: true }).addTo(map);
      accuracyCircle = L.circle([latitude, longitude], {
        radius: accuracy || 0,
        color: '#1d6ed8',
        weight: 1,
        fillColor: '#1d6ed8',
        fillOpacity: 0.1,
      }).addTo(map);

      marker.on('dragend', () => {
        const point = marker.getLatLng();
        setLocation(point.lat, point.lng);
      });
      map.on('click', (event) => {
        setLocation(event.latlng.lat, event.latlng.lng);
      });
      renderHospitals();
    } else {
      map.setView([latitude, longitude], 16);
      marker.setLatLng([latitude, longitude]);
      accuracyCircle.setLatLng([latitude, longitude]);
      accuracyCircle.setRadius(accuracy || 0);
      window.setTimeout(() => map.invalidateSize(), 0);
    }
  };

  const setLocation = (latitude, longitude, accuracy) => {
    latitudeInput.value = latitude.toFixed(6);
    longitudeInput.value = longitude.toFixed(6);
    if (marker) marker.setLatLng([latitude, longitude]);
    if (accuracyCircle) {
      accuracyCircle.setLatLng([latitude, longitude]);
      accuracyCircle.setRadius(accuracy || 0);
    }
    if (map) map.panTo([latitude, longitude]);
    updateAddress(latitude, longitude);
    findNearbyHospitals(latitude, longitude);
  };

  button.addEventListener('click', () => {
    if (!('geolocation' in navigator)) {
      feedback.textContent = 'Location access is not supported by this browser. Enter an address or coordinates instead.';
      feedback.classList.add('location-error');
      return;
    }

    button.disabled = true;
    button.classList.add('is-loading');
    button.innerHTML = '<span class="location-spinner" aria-hidden="true"></span> Finding your location…';
    feedback.textContent = 'Waiting for permission and GPS signal…';
    feedback.classList.remove('location-error', 'location-success');

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude, accuracy } = position.coords;
        setLocation(latitude, longitude, accuracy);
        showMap(latitude, longitude, accuracy);
        feedback.textContent = `Location captured (approximately ${Math.round(accuracy)} m accuracy). Looking up the address…`;
        button.disabled = false;
        button.classList.remove('is-loading');
        button.innerHTML = '<span aria-hidden="true">✓</span> Update my location';
      },
      (error) => {
        const messages = {
          1: 'Location permission was denied. Allow it in your browser settings or enter your address manually.',
          2: 'Your location could not be determined. Check your device location settings or enter your address manually.',
          3: 'Finding your location took too long. Try again or enter your address manually.',
        };
        feedback.textContent = messages[error.code] || 'Unable to get your location. Enter your address manually.';
        feedback.classList.add('location-error');
        button.disabled = false;
        button.classList.remove('is-loading');
        button.innerHTML = '<span aria-hidden="true">◎</span> Try location again';
      },
      {
        enableHighAccuracy: true,
        timeout: 30000,
        maximumAge: 0,
      },
    );
  });
});
