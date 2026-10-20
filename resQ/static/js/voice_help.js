document.addEventListener('DOMContentLoaded', () => {
  const button = document.querySelector('[data-voice-button]');
  const controls = button?.closest('.voice-controls');
  const buttonLabel = button?.querySelector('[data-voice-button-label]');
  const visualizer = document.querySelector('[data-voice-visualizer]');
  const language = document.querySelector('[data-voice-language]');
  const status = document.querySelector('[data-voice-status]');
  const description = document.querySelector('#problem-description');
  const assistance = document.querySelector('[name="required_assistance"]');
  const bloodRequired = document.querySelector('[name="blood_required"]');
  if (!button || !controls || !buttonLabel || !visualizer || !language || !status || !description || !assistance || !bloodRequired) return;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    controls.hidden = true;
    status.textContent = 'Voice input is not supported by this browser. You can type your emergency description instead.';
    return;
  }

  let recognition;
  let isListening = false;
  let transcriptBeforeListening = '';
  let receivedTranscript = false;

  const fillClearlySpokenNeeds = (transcript) => {
    const needs = [];
    if (/\bambulances?\b/i.test(transcript)) needs.push('Ambulance');
    if (/\bevacuat(?:e|ion|ing)\b/i.test(transcript)) needs.push('Evacuation');
    if (/\bshelter\b/i.test(transcript)) needs.push('Shelter');
    if (/\bblood\b/i.test(transcript)) {
      needs.push('Blood support');
      bloodRequired.checked = true;
    }

    const currentNeeds = assistance.value.split(',').map((need) => need.trim()).filter(Boolean);
    needs.forEach((need) => {
      if (!currentNeeds.some((current) => current.toLowerCase() === need.toLowerCase())) {
        currentNeeds.push(need);
      }
    });
    assistance.value = currentNeeds.join(', ');
  };

  const setListening = (listening) => {
    isListening = listening;
    buttonLabel.textContent = listening ? 'Stop listening' : 'Describe by voice';
    button.classList.toggle('is-listening', listening);
    button.setAttribute('aria-pressed', String(listening));
    controls.classList.toggle('is-listening', listening);
    visualizer.hidden = !listening;
  };

  button.addEventListener('click', () => {
    if (isListening) {
      recognition.stop();
      return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = language.value;
    recognition.continuous = false;
    recognition.interimResults = true;
    transcriptBeforeListening = description.value.trim();
    receivedTranscript = false;

    recognition.onstart = () => {
      setListening(true);
      status.textContent = 'Listening… Describe what happened and what help you need.';
    };

    recognition.onresult = (event) => {
      let finalTranscript = '';
      let interimTranscript = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const spokenText = event.results[index][0].transcript;
        if (event.results[index].isFinal) finalTranscript += spokenText;
        else interimTranscript += spokenText;
      }

      if (finalTranscript.trim()) {
        const separator = transcriptBeforeListening ? ' ' : '';
        description.value = `${transcriptBeforeListening}${separator}${finalTranscript.trim()}`;
        transcriptBeforeListening = description.value;
        fillClearlySpokenNeeds(finalTranscript);
        description.dispatchEvent(new Event('input', { bubbles: true }));
        receivedTranscript = true;
      }
      status.textContent = interimTranscript
        ? `Hearing: ${interimTranscript}`
        : (receivedTranscript ? 'Voice description added. Review it and complete the other required fields.' : 'Listening…');
    };

    recognition.onerror = (event) => {
      const messages = {
        'not-allowed': 'Microphone access was denied. Allow microphone access in your browser or type your description.',
        'audio-capture': 'No microphone was found. Connect a microphone or type your description.',
        'no-speech': 'No speech was detected. Try again or type your description.',
        'network': 'Speech recognition is unavailable because of a network issue. You can type your description.',
        'service-not-allowed': 'Speech recognition is blocked by the browser. Check microphone and speech permissions, or type your description.',
        'language-not-supported': 'Speech recognition does not support the selected language in this browser. Choose another language or type your description.',
      };
      status.textContent = messages[event.error] || `Voice input failed (${event.error}). You can type your description.`;
    };

    recognition.onend = () => {
      setListening(false);
      if (!receivedTranscript && (status.textContent.startsWith('Listening') || status.textContent.startsWith('Hearing:'))) {
        status.textContent = 'No speech was transcribed. Try again or type your description.';
      }
    };

    try {
      recognition.start();
    } catch (error) {
      setListening(false);
      status.textContent = `Could not start voice input: ${error.message}`;
      console.error(error);
    }
  });
});
