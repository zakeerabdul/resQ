document.addEventListener('DOMContentLoaded', () => {
  const controls = [
    ...document.querySelectorAll('[data-emergency-live-location]'),
    ...document.querySelectorAll('[data-provider-live-location]'),
  ];

  controls.forEach((control) => {
    const button = control.querySelector('[data-live-location-toggle]');
    const status = control.querySelector('[data-live-location-status]');
    const isProvider = control.hasAttribute('data-provider-live-location');
    const endpoint = isProvider
      ? '/api/provider-location'
      : `/api/emergency-location/${encodeURIComponent(control.dataset.emergencyId)}`;
    let watchId = null;
    let lastPosition = null;
    let lastSentAt = 0;
    let sending = false;
    let pendingPosition = null;

    const setSharing = (active) => {
      button.textContent = active
        ? 'Stop sharing live location'
        : (isProvider ? 'Start sharing live location' : 'Start live sharing');
      status.textContent = active
        ? 'Live location sharing is active. You can stop sharing at any time.'
        : 'Live location sharing is off.';
    };

    const sendPosition = async (position) => {
      pendingPosition = position;
      if (sending) return;
      sending = true;

      try {
        while (pendingPosition) {
          const current = pendingPosition;
          pendingPosition = null;
          const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              latitude: current.coords.latitude,
              longitude: current.coords.longitude,
            }),
            signal: AbortSignal.timeout(10000),
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || `Location update failed (${response.status})`);
          lastSentAt = Date.now();
          lastPosition = current;
          status.textContent = `Live location shared at ${new Date(lastSentAt).toLocaleTimeString()}.`;
        }
      } catch (error) {
        if (error.message.includes('Location sharing is closed')) {
          if (watchId !== null) navigator.geolocation.clearWatch(watchId);
          watchId = null;
          setSharing(false);
        }
        status.textContent = error.message;
        console.error(error);
      } finally {
        sending = false;
      }
    };

    const shouldSend = (position) => {
      if (!lastPosition || Date.now() - lastSentAt >= 15000) return true;
      if (Date.now() - lastSentAt < 5000) return false;
      const radians = (degrees) => degrees * Math.PI / 180;
      const latDelta = radians(position.coords.latitude - lastPosition.coords.latitude);
      const lonDelta = radians(position.coords.longitude - lastPosition.coords.longitude);
      const haversine = Math.sin(latDelta / 2) ** 2
        + Math.cos(radians(lastPosition.coords.latitude))
        * Math.cos(radians(position.coords.latitude))
        * Math.sin(lonDelta / 2) ** 2;
      return 6371000 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine)) >= 20;
    };

    button.addEventListener('click', () => {
      if (watchId !== null) {
        navigator.geolocation.clearWatch(watchId);
        watchId = null;
        setSharing(false);
        return;
      }

      if (!navigator.geolocation) {
        status.textContent = 'Location sharing is not supported by this browser.';
        return;
      }

      status.textContent = 'Waiting for location permission and GPS…';
      watchId = navigator.geolocation.watchPosition(
        (position) => {
          if (shouldSend(position)) sendPosition(position);
        },
        (error) => {
          if (watchId !== null) navigator.geolocation.clearWatch(watchId);
          watchId = null;
          status.textContent = `Could not share location: ${error.message}`;
          setSharing(false);
        },
        { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
      );
      setSharing(true);
      status.textContent = 'Waiting for GPS location…';
    });
  });
});
