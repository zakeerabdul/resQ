document.addEventListener('DOMContentLoaded', () => {
  const requestList = document.querySelector('[data-ambulance-requests]');
  const updateStatus = document.querySelector('[data-request-update-status]');
  if (!requestList || !updateStatus) return;

  const appendText = (parent, tag, text) => {
    const element = document.createElement(tag);
    element.textContent = text;
    parent.append(element);
    return element;
  };

  const renderRequests = (requests) => {
    requestList.replaceChildren();
    if (!requests.length) {
      appendText(requestList, 'p', 'No ambulance requests have been submitted yet.');
      return;
    }

    requests.forEach((request) => {
      const card = document.createElement('article');
      card.className = 'panel';
      appendText(card, 'h3', `${request.emergency_id} · ${request.category}`);
      appendText(card, 'p', `Status: ${request.status} · Priority: ${request.priority}`);

      const contact = document.createElement('p');
      contact.append(document.createTextNode('Requester: '));
      const phone = document.createElement('a');
      phone.href = `tel:${request.phone}`;
      phone.textContent = request.phone;
      contact.append(document.createTextNode(`${request.name} · `), phone);
      card.append(contact);

      appendText(card, 'p', `Location: ${request.location || 'Not provided'}`);
      if (request.latitude || request.longitude) {
        const mapLine = document.createElement('p');
        const mapLink = document.createElement('a');
        mapLink.href = `https://www.google.com/maps?q=${encodeURIComponent(`${request.latitude},${request.longitude}`)}`;
        mapLink.target = '_blank';
        mapLink.rel = 'noopener';
        mapLink.textContent = 'Open requester location in Maps';
        mapLine.append(mapLink);
        card.append(mapLine);
      }
      appendText(card, 'p', `Help requested: ${request.required_assistance}`);
      appendText(card, 'p', `Emergency details: ${request.problem_description}`);
      appendText(card, 'small', `Received ${new Date(request.created_at).toLocaleString()}`);
      requestList.append(card);
    });
  };

  const refresh = async () => {
    try {
      const response = await fetch('/api/ambulance/requests', {
        cache: 'no-store',
        signal: AbortSignal.timeout(10000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `Request update failed (${response.status})`);
      renderRequests(result);
      updateStatus.textContent = ` · Updated ${new Date().toLocaleTimeString()}`;
    } catch (error) {
      updateStatus.textContent = ' · Live updates unavailable; retrying.';
      console.error(error);
    }
  };

  refresh();
  window.setInterval(refresh, 10000);
});
