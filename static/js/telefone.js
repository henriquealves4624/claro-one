(() => {
  const { channelClient, showAlert, hideAlert, initials, formatCpf, onlyDigits, brDate, el, store } = ClaroOne;
  const client = channelClient();
  const device = document.getElementById('phone-device');
  const alertBox = document.getElementById('phone-alert');
  const keypadArea = document.getElementById('keypad-area');
  const keypadSecondary = document.getElementById('keypad-secondary');
  const keypadConfirm = document.getElementById('keypad-confirm');
  const smsSlot = document.getElementById('sms-slot');
  const callState = document.getElementById('call-state');
  const callStateText = document.getElementById('call-state-text');
  const microphoneStatus = document.getElementById('microphone-status');
  const startCallButton = document.getElementById('start-call');
  const endCallButton = document.getElementById('end-call');
  const cancelCallButton = document.getElementById('cancel-call');
  const processFileButton = document.getElementById('process-file');
  const audioInput = document.getElementById('audio-file');
  const uploadBox = document.querySelector('.upload-box');
  const KEYPAD_STEPS = new Set(['protocol', 'cpf', 'sms', 'return-menu']);

  let currentStep = 'protocol';
  let protocolDigits = '';
  let cpfDigits = '';
  let codeDigits = '';
  let customerFirstName = '';
  let focusCase = null;
  let callMode = 'new';
  let interaction = null;
  let busy = false;
  let pendingNotice = null;

  let audioFile = null;
  let recordedDurationMs = null;
  let mediaRecorder = null;
  let mediaStream = null;
  let recordedChunks = [];
  let timerHandle = null;
  let startedAt = null;
  let failedStage = null;
  let processingLocked = false;
  let callRegistered = false;

  // ------------------------------------------------------------ navegação

  function step(name) {
    currentStep = name;
    document.querySelectorAll('.phone-step').forEach(section => section.classList.toggle('active', section.dataset.step === name));
    keypadArea.classList.toggle('hidden', !KEYPAD_STEPS.has(name));
    keypadArea.classList.toggle('menu-only', name === 'return-menu');
    keypadSecondary.classList.toggle('hidden', !['protocol', 'cpf'].includes(name));
    keypadSecondary.textContent = name === 'protocol' ? 'Não tenho protocolo' : '← Voltar ao protocolo';
    keypadConfirm.classList.toggle('hidden', name === 'return-menu');
    if (name === 'cpf') {
      // A dica acompanha o caminho escolhido: o CPF de retorno já tem protocolo aberto.
      document.getElementById('cpf-hint').textContent = protocolDigits
        ? `Protocolo ${protocolDigits} · teste com o CPF 123.456.789-00`
        : 'Primeiro contato: teste com 987.654.321-00 (sem atendimento em aberto)';
    }
    hideAlert(alertBox);
    if (pendingNotice) { showAlert(alertBox, pendingNotice, 'info'); pendingNotice = null; }
    renderDisplays();
  }

  function setBusy(state, label) {
    busy = state;
    keypadConfirm.disabled = state;
    keypadConfirm.textContent = state ? label : 'Confirmar #';
    device.classList.toggle('is-busy', state);
  }

  function renderDisplays() {
    document.getElementById('protocol-display').textContent = protocolDigits;
    document.getElementById('cpf-display').textContent = formatCpf(cpfDigits);
    const code = document.getElementById('code-display');
    code.replaceChildren(...Array.from({ length: 6 }, (_, index) => el('span', { class: codeDigits[index] ? 'filled' : '' }, codeDigits[index] || '')));
  }

  document.getElementById('device-time').textContent = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' }).format(new Date());

  // ------------------------------------------------------------ teclado

  function pressDigit(digit) {
    if (busy) return;
    if (currentStep === 'protocol') protocolDigits = onlyDigits(protocolDigits + digit, 12);
    else if (currentStep === 'cpf') cpfDigits = onlyDigits(cpfDigits + digit, 11);
    else if (currentStep === 'sms') {
      codeDigits = onlyDigits(codeDigits + digit, 6);
      if (codeDigits.length === 6) { renderDisplays(); confirmCode(); return; }
    } else if (currentStep === 'return-menu') { chooseReturnOption(digit); return; }
    else if (currentStep === 'ura') {
      document.querySelector(`.ura-grid [data-digit="${digit}"]`)?.click();
      return;
    }
    renderDisplays();
  }

  function erase() {
    if (busy) return;
    if (currentStep === 'protocol') protocolDigits = protocolDigits.slice(0, -1);
    if (currentStep === 'cpf') cpfDigits = cpfDigits.slice(0, -1);
    if (currentStep === 'sms') codeDigits = codeDigits.slice(0, -1);
    renderDisplays();
  }

  function confirm() {
    if (busy) return;
    if (currentStep === 'protocol') step('cpf');
    else if (currentStep === 'cpf') identify();
    else if (currentStep === 'sms') confirmCode();
  }

  function flash(key) {
    const button = document.querySelector(`#keypad [data-key="${CSS.escape(key)}"]`);
    if (!button) return;
    button.classList.add('pressed');
    setTimeout(() => button.classList.remove('pressed'), 140);
  }

  function handleKey(key) {
    flash(key);
    if (key === '*') erase();
    else if (key === '#') confirm();
    else pressDigit(key);
  }

  document.querySelectorAll('#keypad [data-key]').forEach(button => button.addEventListener('click', () => handleKey(button.dataset.key)));
  keypadConfirm.addEventListener('click', confirm);
  keypadSecondary.addEventListener('click', () => {
    if (currentStep === 'protocol') { protocolDigits = ''; step('cpf'); }
    else step('protocol');
  });
  document.addEventListener('keydown', event => {
    if (event.target.closest('input, textarea, select') || event.ctrlKey || event.metaKey || event.altKey) return;
    const visibleKeypad = !keypadArea.classList.contains('hidden') || currentStep === 'ura';
    if (!visibleKeypad) return;
    if (/^[0-9]$/.test(event.key)) { event.preventDefault(); handleKey(event.key); }
    else if (event.key === 'Backspace') { event.preventDefault(); handleKey('*'); }
    else if (event.key === 'Enter' || event.key === '#') { event.preventDefault(); handleKey('#'); }
  });

  // ------------------------------------------------------------ identificação

  function showSmsNotification(sms) {
    smsSlot.replaceChildren();
    const message = sms.demo_code
      ? el('small', {}, 'Claro One: seu código de verificação é ', el('span', { class: 'sms-code' }, sms.demo_code), '. Não compartilhe.')
      : el('small', {}, 'Enviamos um SMS real para o celular configurado para a demonstração.');
    const notice = sms.notice ? el('em', {}, sms.notice) : null;
    const close = el('button', { type: 'button', 'aria-label': 'Fechar notificação', onclick: () => smsSlot.replaceChildren() }, '×');
    smsSlot.append(el('div', { class: 'sms-notification', role: 'status' },
      el('span', { class: 'sms-app', 'aria-hidden': 'true' }, '✉'),
      el('div', {}, el('strong', {}, sms.mode === 'REAL' ? 'Mensagens · SMS enviado' : 'Mensagens · agora (SMS simulado)'), message, notice),
      close));
    document.getElementById('sms-phone').textContent = sms.masked_phone;
    document.getElementById('sms-hint').textContent = sms.demo_code
      ? 'SMS simulado: o código aparece na notificação no topo do aparelho'
      : 'Confira o SMS no celular configurado';
  }

  async function identify() {
    if (cpfDigits.length !== 11) { showAlert(alertBox, 'Digite os 11 números do CPF.'); return; }
    setBusy(true, 'Localizando...');
    try {
      const result = await client.post('/identify', { channel: 'TELEFONE', cpf: cpfDigits, protocol: protocolDigits || null });
      if (result.protocol_status === 'NOT_FOUND') {
        const typed = protocolDigits;
        protocolDigits = '';
        pendingNotice = `Não encontramos o protocolo ${typed} para este CPF. Digite novamente ou toque em “Não tenho protocolo”.`;
        step('protocol');
        return;
      }
      client.setToken(result.access_token);
      customerFirstName = result.customer.first_name;
      store.set('claroOneCpf', cpfDigits);
      if (result.protocol_status === 'CLOSED') {
        pendingNotice = `O protocolo ${result.closed_protocol} já foi encerrado. Vamos seguir com o seu atendimento.`;
      }
      if (result.verification === 'SMS') {
        codeDigits = '';
        showSmsNotification(result.sms);
        step('sms');
      } else {
        await routeAfterVerification();
      }
    } catch (error) {
      showAlert(alertBox, error.message);
    } finally { setBusy(false); }
  }

  async function confirmCode() {
    if (codeDigits.length !== 6) { showAlert(alertBox, 'Digite os 6 números do código.'); return; }
    setBusy(true, 'Verificando...');
    try {
      await client.post('/verify', { code: codeDigits });
      smsSlot.replaceChildren();
      await routeAfterVerification();
    } catch (error) {
      codeDigits = '';
      renderDisplays();
      showAlert(alertBox, error.message);
    } finally { setBusy(false); }
  }

  document.getElementById('sms-resend').addEventListener('click', async () => {
    try {
      const sms = await client.post('/sms/resend');
      codeDigits = '';
      showSmsNotification(sms);
      renderDisplays();
      showAlert(alertBox, 'Enviamos um novo código.', 'success');
    } catch (error) { showAlert(alertBox, error.message); }
  });

  async function routeAfterVerification() {
    const data = await client.get('/cases');
    focusCase = data.cases.find(item => item.protocol === data.focus_protocol) || null;
    document.getElementById('ura-greeting').textContent = `Olá, ${customerFirstName}`;
    if (!focusCase) { step('ura'); return; }
    document.getElementById('return-topic').textContent = focusCase.category_label;
    document.getElementById('return-protocol').textContent = focusCase.protocol;
    document.getElementById('return-status').textContent = focusCase.status_label;
    document.getElementById('return-problem').textContent = focusCase.problem || 'Atendimento em andamento';
    document.getElementById('return-opened').textContent = `${brDate(focusCase.created_at)} · ${focusCase.channel_origin_label}`;
    const last = focusCase.last_contact;
    document.getElementById('return-last').textContent = last ? `${last.channel_label} · ${brDate(last.at)}` : '—';
    document.getElementById('return-department').textContent = focusCase.department_label;
    step('return-menu');
  }

  document.querySelectorAll('.ura-options [data-option]').forEach(button => button.addEventListener('click', () => chooseReturnOption(button.dataset.option)));

  async function chooseReturnOption(option) {
    if (busy) return;
    if (option === '2') { step('ura'); return; }
    if (option !== '1') return;
    setBusy(true, 'Recuperando...');
    document.querySelectorAll('.ura-options button').forEach(button => { button.disabled = true; });
    try {
      const result = await client.post(`/cases/${encodeURIComponent(focusCase.protocol)}/resume`);
      focusCase = result.case;
      interaction = result.interaction;
      prepareCall('continue');
    } catch (error) {
      showAlert(alertBox, error.message);
    } finally {
      setBusy(false);
      document.querySelectorAll('.ura-options button').forEach(button => { button.disabled = false; });
    }
  }

  document.querySelectorAll('.ura-grid button').forEach(button => button.addEventListener('click', async () => {
    if (busy) return;
    const buttons = document.querySelectorAll('.ura-grid button');
    buttons.forEach(item => { item.disabled = true; });
    try {
      const result = await client.post('/cases/phone', { department: button.dataset.department });
      focusCase = result.case;
      interaction = result.interaction;
      prepareCall('new', button.querySelector('span').textContent);
    } catch (error) {
      showAlert(alertBox, error.message);
    } finally { buttons.forEach(item => { item.disabled = false; }); }
  }));

  // ------------------------------------------------------------ ligação

  function setCallState(state, text) {
    callState.className = `call-state ${state}`;
    callStateText.textContent = text;
  }

  function prepareCall(mode, departmentLabel = '') {
    callMode = mode;
    resetCallUi();
    const context = document.getElementById('call-context');
    if (mode === 'continue') {
      document.getElementById('phone-avatar').textContent = initials(focusCase.department_label);
      document.getElementById('call-title').textContent = `Especialista · ${focusCase.department_label}`;
      document.getElementById('call-subtitle').textContent = 'Quem vai te atender já recebeu o contexto. Continue de onde parou.';
      document.getElementById('call-context-protocol').textContent = focusCase.protocol;
      document.getElementById('call-context-problem').textContent = focusCase.problem || '';
      document.getElementById('call-context-summary').textContent = focusCase.summary || '';
      context.classList.remove('hidden');
      startCallButton.textContent = 'Falar com o especialista';
    } else {
      document.getElementById('phone-avatar').textContent = initials(customerFirstName);
      document.getElementById('call-title').textContent = `Ligação · ${departmentLabel}`;
      document.getElementById('call-subtitle').textContent = `Protocolo ${focusCase.protocol} · conte o que aconteceu após iniciar.`;
      context.classList.add('hidden');
      startCallButton.textContent = 'Iniciar ligação';
    }
    startCallButton.dataset.label = startCallButton.textContent;
    step('call');
  }

  function loading(button, state, label) {
    button.disabled = state;
    if (!button.dataset.label) button.dataset.label = button.textContent;
    button.textContent = state ? label : button.dataset.label;
  }

  function stopTimer() { clearInterval(timerHandle); timerHandle = null; }

  function startTimer() {
    stopTimer();
    startedAt = Date.now();
    const render = () => {
      const total = Math.floor((Date.now() - startedAt) / 1000);
      document.getElementById('call-timer').textContent = `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
    };
    render();
    timerHandle = setInterval(render, 250);
  }

  function stopMicrophoneTracks() {
    if (mediaStream) mediaStream.getTracks().forEach(track => track.stop());
    mediaStream = null;
  }

  function resetProcessingRows() {
    document.querySelectorAll('.processing-list li').forEach(row => {
      row.className = '';
      row.querySelector('em').textContent = 'Aguardando';
    });
  }

  function resetCallControls() {
    startCallButton.classList.remove('hidden');
    endCallButton.classList.add('hidden');
    cancelCallButton.classList.add('hidden');
    uploadBox.classList.remove('disabled');
    audioInput.disabled = false;
    microphoneStatus.classList.remove('active');
    microphoneStatus.querySelector('span').textContent = 'Microfone ainda não iniciado';
    setCallState('preparing', callMode === 'continue' ? 'CONECTADO AO ESPECIALISTA' : 'PREPARANDO LIGAÇÃO');
  }

  function resetCallUi() {
    stopTimer();
    stopMicrophoneTracks();
    mediaRecorder = null;
    recordedChunks = [];
    audioFile = null;
    recordedDurationMs = null;
    processingLocked = false;
    callRegistered = false;
    audioInput.value = '';
    document.getElementById('call-timer').textContent = '00:00';
    document.getElementById('file-selected').classList.add('hidden');
    processFileButton.classList.add('hidden');
    document.getElementById('retry-processing').classList.add('hidden');
    document.getElementById('choose-another-audio').classList.add('hidden');
    resetCallControls();
    resetProcessingRows();
  }

  function chooseRecorderType() {
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg', 'audio/mp4'];
    if (typeof MediaRecorder.isTypeSupported !== 'function') return '';
    return candidates.find(type => MediaRecorder.isTypeSupported(type)) || '';
  }

  function recorderExtension(mimeType) {
    if (mimeType.includes('ogg')) return '.ogg';
    if (mimeType.includes('mp4')) return '.m4a';
    return '.webm';
  }

  function microphoneErrorMessage(error) {
    if (['NotAllowedError', 'SecurityError'].includes(error.name)) return 'A permissão do microfone foi negada. Permita o acesso no navegador ou use o upload manual.';
    if (['NotFoundError', 'DevicesNotFoundError'].includes(error.name)) return 'Nenhum microfone foi encontrado. Conecte um microfone ou use o upload manual.';
    if (['NotReadableError', 'TrackStartError'].includes(error.name)) return 'O microfone está ocupado ou indisponível. Feche outros aplicativos e tente novamente.';
    return 'Não foi possível iniciar o microfone. Use o upload manual ou tente outro navegador.';
  }

  async function registerCallStart() {
    if (callRegistered) return;
    await client.post(`/interactions/${interaction.id}/call/start`);
    callRegistered = true;
  }

  startCallButton.addEventListener('click', async () => {
    if (processingLocked || (mediaRecorder && mediaRecorder.state !== 'inactive')) {
      showAlert(alertBox, 'A ligação já está em andamento.');
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      showAlert(alertBox, 'Este navegador não suporta gravação pelo microfone. Use o upload manual.');
      return;
    }
    try {
      loading(startCallButton, true, 'Solicitando microfone...');
      hideAlert(alertBox);
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = chooseRecorderType();
      mediaRecorder = mimeType ? new MediaRecorder(mediaStream, { mimeType }) : new MediaRecorder(mediaStream);
      recordedChunks = [];
      mediaRecorder.addEventListener('dataavailable', event => { if (event.data?.size) recordedChunks.push(event.data); });
      mediaRecorder.addEventListener('error', event => {
        stopTimer();
        stopMicrophoneTracks();
        processingLocked = false;
        resetCallControls();
        setCallState('preparing', 'GRAVAÇÃO INTERROMPIDA');
        showAlert(alertBox, microphoneErrorMessage(event.error || new Error()));
      });
      await registerCallStart();
      audioFile = null;
      audioInput.value = '';
      document.getElementById('file-selected').classList.add('hidden');
      processFileButton.classList.add('hidden');
      uploadBox.classList.add('disabled');
      audioInput.disabled = true;
      mediaRecorder.start(250);
      startTimer();
      setCallState('recording', callMode === 'continue' ? 'EM CONVERSA COM ESPECIALISTA' : 'LIGAÇÃO EM ANDAMENTO');
      microphoneStatus.classList.add('active');
      microphoneStatus.querySelector('span').textContent = 'Microfone ativo · gravando';
      startCallButton.classList.add('hidden');
      endCallButton.classList.remove('hidden');
      cancelCallButton.classList.remove('hidden');
    } catch (error) {
      stopMicrophoneTracks();
      mediaRecorder = null;
      showAlert(alertBox, error.status ? error.message : microphoneErrorMessage(error));
    } finally {
      loading(startCallButton, false);
    }
  });

  function stopRecording() {
    return new Promise((resolve, reject) => {
      const recorder = mediaRecorder;
      if (!recorder || recorder.state === 'inactive') { reject(new Error('A gravação não foi iniciada.')); return; }
      recorder.addEventListener('stop', () => {
        const mimeType = recorder.mimeType || recordedChunks[0]?.type || 'audio/webm';
        const blob = new Blob(recordedChunks, { type: mimeType });
        mediaRecorder = null;
        recordedChunks = [];
        resolve({ blob, mimeType });
      }, { once: true });
      try { recorder.stop(); } catch (error) { reject(error); }
    });
  }

  audioInput.addEventListener('change', event => {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      event.target.value = '';
      showAlert(alertBox, 'Encerre ou cancele a gravação do microfone antes de escolher um arquivo.');
      return;
    }
    audioFile = event.target.files[0] || null;
    recordedDurationMs = null;
    document.getElementById('file-selected').classList.toggle('hidden', !audioFile);
    processFileButton.classList.toggle('hidden', !audioFile);
    if (audioFile) {
      document.getElementById('file-name').textContent = audioFile.name;
      setCallState('preparing', 'GRAVAÇÃO PRONTA');
    }
  });

  const processRow = name => document.querySelector(`[data-process="${name}"]`);
  function processState(name, state, label) {
    const row = processRow(name);
    row.className = state;
    row.querySelector('em').textContent = label || ({ done: 'Concluído', processing: 'Processando', error: 'Erro' }[state] || 'Aguardando');
  }

  endCallButton.addEventListener('click', beginProcessing);
  processFileButton.addEventListener('click', beginProcessing);
  document.getElementById('retry-processing').addEventListener('click', () => {
    if (failedStage === 'upload') beginProcessing();
    else runIAs(failedStage);
  });
  document.getElementById('choose-another-audio').addEventListener('click', () => {
    audioFile = null;
    recordedDurationMs = null;
    processingLocked = false;
    audioInput.value = '';
    document.getElementById('file-selected').classList.add('hidden');
    document.getElementById('retry-processing').classList.add('hidden');
    document.getElementById('choose-another-audio').classList.add('hidden');
    processFileButton.classList.add('hidden');
    resetCallControls();
    resetProcessingRows();
    step('call');
  });

  async function prepareRecordedAudio() {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') return;
    const duration = Date.now() - startedAt;
    setCallState('preparing', 'FINALIZANDO GRAVAÇÃO');
    const recording = await stopRecording();
    stopTimer();
    stopMicrophoneTracks();
    if (duration < 1000) throw new Error('A gravação é curta demais. Fale por pelo menos 1 segundo.');
    if (recording.blob.size < 256) throw new Error('A gravação está vazia. Verifique o microfone e tente novamente.');
    recordedDurationMs = Math.round(duration);
    audioFile = recording.blob;
    audioFile.uploadName = `gravacao${recorderExtension(recording.mimeType)}`;
  }

  async function beginProcessing() {
    if (processingLocked) return;
    processingLocked = true;
    const actionButton = mediaRecorder?.state === 'recording' ? endCallButton : processFileButton;
    loading(actionButton, true, 'Finalizando...');
    try {
      if (mediaRecorder?.state === 'recording') await prepareRecordedAudio();
      if (!audioFile) throw new Error('Inicie a ligação ou adicione uma gravação para processar o atendimento.');
      await registerCallStart();
      step('processing');
      document.getElementById('choose-another-audio').classList.add('hidden');
      failedStage = 'upload';
      processState('audio', 'processing', 'Enviando');
      const form = new FormData();
      form.append('audio', audioFile, audioFile.uploadName || audioFile.name);
      if (recordedDurationMs !== null) form.append('duration_ms', String(recordedDurationMs));
      await client.upload(`/interactions/${interaction.id}/audio`, form);
      processState('audio', 'done', 'Recebido');
      failedStage = 'transcription';
      await runIAs('transcription');
    } catch (error) {
      stopTimer();
      stopMicrophoneTracks();
      if (currentStep === 'processing') {
        processState('audio', 'error', 'Falhou');
        const retry = document.getElementById('retry-processing');
        retry.textContent = 'Tentar envio novamente';
        retry.classList.remove('hidden');
        document.getElementById('choose-another-audio').classList.remove('hidden');
      } else {
        resetCallControls();
      }
      showAlert(alertBox, error.message || 'Não foi possível enviar a gravação. Verifique sua internet.');
      processingLocked = false;
    } finally {
      loading(actionButton, false);
    }
  }

  async function runIAs(startAt = 'transcription') {
    const retry = document.getElementById('retry-processing');
    retry.classList.add('hidden');
    hideAlert(alertBox);
    processingLocked = true;
    let stage = startAt;
    try {
      if (startAt === 'transcription') {
        processState('transcription', 'processing', 'Transcrevendo');
        await client.post(`/interactions/${interaction.id}/transcribe`);
        processState('transcription', 'done');
        processState('privacy', 'done', 'Aplicada');
      }
      stage = 'context';
      processState('context', 'processing', 'Analisando');
      const result = await client.post(`/interactions/${interaction.id}/finish`, { outcome: 'EM_ABERTO' });
      processState('context', 'done');
      processState('updated', 'done');
      showResult(result);
    } catch (error) {
      failedStage = stage;
      processState(stage, 'error', 'Falhou');
      showAlert(alertBox, error.message);
      retry.textContent = stage === 'transcription' ? 'Tentar transcrição novamente' : 'Tentar contextualização novamente';
      retry.classList.remove('hidden');
      processingLocked = false;
    }
  }

  async function cancelCall() {
    if (processingLocked) return;
    if (!window.confirm('Cancelar esta ligação? Nada será registrado na CCE.')) return;
    processingLocked = true;
    try {
      if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
      stopTimer();
      stopMicrophoneTracks();
      await client.remove(`/interactions/${interaction.id}`);
      interaction = null;
      if (callMode === 'continue') await routeAfterVerification();
      else step('ura');
    } catch (error) {
      showAlert(alertBox, error.message);
    } finally {
      processingLocked = false;
    }
  }
  cancelCallButton.addEventListener('click', cancelCall);

  function showResult(result) {
    processingLocked = false;
    const info = result.case;
    const continued = callMode === 'continue';
    document.getElementById('result-eyebrow').textContent = continued ? 'CONTEXTO RETROALIMENTADO' : 'CONTEXTO REGISTRADO';
    document.getElementById('result-title').textContent = continued ? 'Seu atendimento foi atualizado' : 'Atendimento registrado na CCE';
    document.getElementById('result-voice').textContent = continued
      ? `“Registramos esta conversa no protocolo ${info.protocol}. Se precisar, continue por qualquer canal.”`
      : `“Anote o seu protocolo: ${info.protocol.split('').join(' ')}. Com ele, você continua de onde parou em qualquer canal.”`;
    document.getElementById('result-protocol').textContent = info.protocol;
    document.getElementById('result-topic').textContent = info.category_label;
    document.getElementById('result-summary').textContent = result.interaction.summary || info.summary || '—';
    document.getElementById('result-destination').textContent = info.department_label;
    const query = `?protocolo=${encodeURIComponent(info.protocol)}`;
    store.set('claroOneProtocol', info.protocol);
    document.getElementById('go-whatsapp').href = `/whatsapp${query}`;
    document.getElementById('go-minha-claro').href = `/minha-claro${query}`;
    document.getElementById('view-cockpit').href = `/atendente${query}`;
    step('result');
  }

  document.getElementById('phone-restart').addEventListener('click', () => {
    client.setToken(null);
    protocolDigits = '';
    cpfDigits = '';
    codeDigits = '';
    focusCase = null;
    interaction = null;
    smsSlot.replaceChildren();
    step('protocol');
  });

  // Protocolo recebido de outro canal (ex.: link do resultado).
  const presetProtocol = ClaroOne.params.get('protocolo');
  if (presetProtocol) protocolDigits = onlyDigits(presetProtocol, 12);
  const rememberedCpf = store.get('claroOneCpf');
  if (rememberedCpf && presetProtocol) cpfDigits = onlyDigits(rememberedCpf);

  window.addEventListener('pagehide', stopMicrophoneTracks);
  step('protocol');
})();
