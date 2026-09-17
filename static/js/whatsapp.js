(() => {
  const { channelClient, el, formatCpf, onlyDigits, brDate, store, params } = ClaroOne;
  const client = channelClient();
  const chat = document.getElementById('chat-body');
  const input = document.getElementById('wa-input');
  const sendButton = document.getElementById('wa-send');
  const toolbar = document.getElementById('chat-toolbar');
  const smsSlot = document.getElementById('sms-slot');
  const hint = document.getElementById('chat-hint');
  const PLACEHOLDERS = {
    protocol: 'Digite o número do protocolo',
    cpf: 'Digite seu CPF',
    code: 'Digite o código de 6 dígitos',
    'new-topic': 'Descreva como podemos ajudar',
    chat: 'Digite sua mensagem'
  };

  let mode = 'idle';
  let protocol = '';
  let firstName = '';
  let focusCase = null;
  let interaction = null;
  let generation = 0;

  const now = () => new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' }).format(new Date());
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

  function setMode(next) {
    mode = next;
    const typing = Boolean(PLACEHOLDERS[next]);
    input.disabled = !typing;
    sendButton.disabled = !typing;
    input.placeholder = PLACEHOLDERS[next] || 'Escolha uma opção acima';
    toolbar.classList.toggle('hidden', next !== 'chat');
    hint.classList.toggle('hidden', !['protocol', 'cpf'].includes(next));
    if (next === 'protocol') hint.textContent = 'Retomada: envie o protocolo 123 · Primeiro contato: toque em “Não tenho protocolo”';
    if (next === 'cpf') {
      hint.textContent = protocol
        ? `Protocolo ${protocol} · teste com o CPF 123.456.789-00`
        : 'Primeiro contato: teste com 987.654.321-00 (sem atendimento em aberto)';
    }
    if (typing) setTimeout(() => input.focus(), 30);
  }

  /** Converte *negrito* no estilo WhatsApp sem usar innerHTML. */
  function rich(text) {
    return String(text).split(/(\*[^*]+\*)/g).filter(Boolean).map(part => (
      part.startsWith('*') && part.endsWith('*') ? el('strong', {}, part.slice(1, -1)) : document.createTextNode(part)
    ));
  }

  function scroll() { chat.scrollTop = chat.scrollHeight; }

  function append(node) { chat.append(node); scroll(); return node; }

  async function bot(content, { highlight = false, delay = 450 } = {}) {
    const token = generation;
    const typing = append(el('div', { class: 'bubble incoming typing', 'aria-label': 'digitando' }, el('i'), el('i'), el('i')));
    await wait(delay);
    typing.remove();
    if (token !== generation) return null;
    const body = typeof content === 'string' ? rich(content) : content;
    return append(el('div', { class: `bubble incoming${highlight ? ' highlight' : ''}` }, body, el('time', {}, now())));
  }

  function me(text) {
    return append(el('div', { class: 'bubble outgoing' }, text, el('time', {}, `${now()} ✓✓`)));
  }

  function agent(name, text) {
    return append(el('div', { class: 'bubble agent' },
      el('span', { class: 'mini-avatar' }, (name || 'E')[0]),
      el('strong', {}, name || 'Especialista Claro'),
      el('p', {}, text),
      el('time', {}, now())));
  }

  function system(text, loading = false) {
    return append(el('div', { class: `system-message${loading ? ' loading' : ''}` }, loading ? el('i') : null, text));
  }

  function quickReplies(options) {
    const group = el('div', { class: 'quick-replies' });
    options.forEach(option => {
      const attributes = { class: `quick-reply${option.primary ? ' primary' : ''}` };
      const node = option.href
        ? el('a', { ...attributes, href: option.href }, option.label)
        : el('button', {
          ...attributes,
          type: 'button',
          onclick: () => {
            if (group.classList.contains('used')) return;
            group.classList.add('used');
            group.querySelectorAll('button').forEach(button => { button.disabled = true; });
            option.action();
          }
        }, option.label);
      group.append(node);
    });
    return append(group);
  }

  function caseCard(info, title) {
    const last = info.last_contact;
    return el('article', { class: 'case-card' },
      el('span', { class: 'found-label' }, title),
      el('strong', {}, info.problem || info.summary || 'Atendimento em andamento'),
      el('dl', {},
        el('div', {}, el('dt', {}, 'Protocolo'), el('dd', {}, info.protocol)),
        el('div', {}, el('dt', {}, 'Tema'), el('dd', {}, info.category_label)),
        el('div', {}, el('dt', {}, 'Departamento'), el('dd', {}, info.department_label)),
        el('div', {}, el('dt', {}, 'Status'), el('dd', {}, info.status_label)),
        el('div', {}, el('dt', {}, 'Aberto em'), el('dd', {}, `${brDate(info.created_at)} · ${info.channel_origin_label}`)),
        last ? el('div', { class: 'wide' }, el('dt', {}, 'Último contato'), el('dd', {}, `${last.channel_label} · ${brDate(last.at)}`)) : null));
  }

  function showSmsNotification(sms) {
    const message = sms.demo_code
      ? el('small', {}, 'Claro One: seu código de verificação é ', el('span', { class: 'sms-code' }, sms.demo_code), '. Não compartilhe.')
      : el('small', {}, 'Enviamos um SMS real para o celular configurado para a demonstração.');
    smsSlot.replaceChildren(el('div', { class: 'sms-notification', role: 'status' },
      el('span', { class: 'sms-app', 'aria-hidden': 'true' }, '✉'),
      el('div', {}, el('strong', {}, sms.mode === 'REAL' ? 'Mensagens · SMS enviado' : 'Mensagens · agora (SMS simulado)'), message, sms.notice ? el('em', {}, sms.notice) : null),
      el('button', { type: 'button', 'aria-label': 'Fechar notificação', onclick: () => smsSlot.replaceChildren() }, '×')));
  }

  function failure(error, retryMode) {
    return bot(`⚠️ ${error.message}`).then(() => { if (retryMode) setMode(retryMode); });
  }

  // ------------------------------------------------------------ fluxo

  async function start() {
    generation += 1;
    chat.replaceChildren(el('div', { class: 'date-chip' }, 'Hoje'));
    smsSlot.replaceChildren();
    client.setToken(null);
    protocol = '';
    focusCase = null;
    interaction = null;
    setMode('idle');
    await bot('Olá! Aqui é a *Claro*. 👋', { delay: 250 });
    await askProtocol();
  }

  async function askProtocol() {
    await bot('Se você já tem um número de protocolo, envie agora. Se é um novo atendimento, toque em *Não tenho protocolo*.');
    quickReplies([{ label: 'Não tenho protocolo', action: () => { me('Não tenho protocolo'); protocol = ''; askCpf(); } }]);
    setMode('protocol');
    const preset = onlyDigits(params.get('protocolo'), 12);
    if (preset && !input.value) input.value = preset;
  }

  async function askCpf() {
    setMode('idle');
    await bot('Obrigado! Agora informe o seu *CPF*.');
    setMode('cpf');
    const remembered = store.get('claroOneCpf');
    if (remembered && !input.value) input.value = formatCpf(remembered);
  }

  async function identify(cpf) {
    setMode('idle');
    const loading = system('Localizando seu cadastro...', true);
    try {
      const result = await client.post('/identify', { channel: 'WHATSAPP', cpf, protocol: protocol || null });
      loading.remove();
      if (result.protocol_status === 'NOT_FOUND') {
        await bot(`Não encontrei o protocolo *${protocol}* para este CPF. Envie o número novamente ou toque em *Não tenho protocolo*.`);
        quickReplies([{ label: 'Não tenho protocolo', action: () => { me('Não tenho protocolo'); protocol = ''; askCpf(); } }]);
        protocol = '';
        setMode('protocol');
        return;
      }
      client.setToken(result.access_token);
      firstName = result.customer.first_name;
      store.set('claroOneCpf', cpf);
      if (result.protocol_status === 'CLOSED') {
        await bot(`O protocolo *${result.closed_protocol}* já foi encerrado. Vou seguir com o seu atendimento.`);
      }
      if (result.verification === 'SMS') {
        showSmsNotification(result.sms);
        await bot(`Encontrei um atendimento em aberto. 🔒 Para sua segurança, enviei um código de 6 dígitos por SMS para *${result.sms.masked_phone}*. Digite o código aqui.`);
        quickReplies([{ label: 'Reenviar código', action: resendCode }]);
        setMode('code');
      } else {
        await afterVerification();
      }
    } catch (error) {
      loading.remove();
      await failure(error, 'cpf');
    }
  }

  async function resendCode() {
    try {
      const sms = await client.post('/sms/resend');
      showSmsNotification(sms);
      await bot('Enviei um novo código. Digite-o aqui.');
      quickReplies([{ label: 'Reenviar código', action: resendCode }]);
    } catch (error) { await failure(error); }
    setMode('code');
  }

  async function verify(code) {
    setMode('idle');
    try {
      await client.post('/verify', { code });
      smsSlot.replaceChildren();
      await bot('Identidade confirmada ✅');
      await afterVerification();
    } catch (error) {
      await failure(error, 'code');
    }
  }

  async function afterVerification() {
    const data = await client.get('/cases');
    focusCase = data.cases.find(item => item.protocol === data.focus_protocol) || null;
    if (!focusCase) {
      await askNewTopic(`Olá, *${firstName}*! Conte em uma mensagem como podemos ajudar.`);
      return;
    }
    await bot(`Você já possui um atendimento em aberto sobre *${focusCase.category_label}*. O que deseja fazer?`);
    append(caseCard(focusCase, 'ATENDIMENTO EM ABERTO'));
    quickReplies([
      { label: 'Continuar atendimento', primary: true, action: continueCase },
      { label: 'Falar sobre outro tema', action: () => { me('Falar sobre outro tema'); askNewTopic('Claro! Conte em uma mensagem o que você precisa.'); } }
    ]);
    setMode('menu');
  }

  async function askNewTopic(message) {
    setMode('idle');
    await bot(message);
    append(el('div', { class: 'message-examples' }, 'Exemplo: “Minha internet está sem funcionar desde ontem.”'));
    setMode('new-topic');
  }

  function openChat(info) {
    focusCase = info;
    document.getElementById('chat-toolbar-label').textContent = `Protocolo ${info.protocol} · ${info.department_label}`;
    setMode('chat');
  }

  async function continueCase() {
    me('Continuar atendimento');
    setMode('idle');
    const loading = system('Recuperando o contexto do atendimento...', true);
    try {
      const result = await client.post(`/cases/${encodeURIComponent(focusCase.protocol)}/resume`);
      loading.remove();
      interaction = result.interaction;
      const info = result.case;
      await bot(`Contexto recuperado ✓ Você está com o time de *${info.department_label}*, que já sabe o que aconteceu: ${info.summary || info.problem}`, { highlight: true });
      await wait(600);
      agent(info.agent || `Especialista · ${info.department_label}`, `Olá, ${firstName}. Já estou com o histórico do protocolo ${info.protocol}, não precisa repetir nada. Como posso ajudar agora?`);
      openChat(info);
    } catch (error) {
      loading.remove();
      await failure(error);
      await afterVerification();
    }
  }

  async function openCase(message) {
    setMode('idle');
    const loading = system('IA de contexto interpretando sua mensagem...', true);
    try {
      const result = await client.post('/cases', { message });
      loading.remove();
      interaction = result.interaction;
      const info = result.case;
      await bot(`Entendi: *${info.problem}*`, { highlight: true });
      await bot(`Direcionei seu atendimento para *${info.department_label}*. Seu protocolo é *${info.protocol}*. Com ele você continua de onde parou em qualquer canal.`);
      store.set('claroOneProtocol', info.protocol);
      await wait(500);
      agent(`Especialista · ${info.department_label}`, `Olá, ${firstName}. Já recebi o contexto da sua mensagem. Pode me contar mais detalhes por aqui.`);
      openChat(info);
    } catch (error) {
      loading.remove();
      await failure(error, 'new-topic');
    }
  }

  async function sendChatMessage(text) {
    setMode('idle');
    try {
      const result = await client.post(`/interactions/${interaction.id}/messages`, { text });
      if (result.reply) await bot(result.reply.text, { delay: 700 });
    } catch (error) {
      await failure(error);
    }
    setMode('chat');
  }

  async function askFinish() {
    setMode('idle');
    await bot('Como esta conversa terminou?', { delay: 200 });
    quickReplies([
      { label: '✓ Resolvido pelo atendente', primary: true, action: () => finish('RESOLVIDO') },
      { label: '⏸ Cliente ausente · manter em aberto', action: () => finish('EM_ABERTO') },
      { label: 'Voltar à conversa', action: () => setMode('chat') }
    ]);
    setMode('menu');
  }

  async function finish(outcome) {
    setMode('idle');
    me(outcome === 'RESOLVIDO' ? 'Resolvido pelo atendente' : 'Cliente ausente');
    const loading = system('IA de contexto consolidando a conversa na CCE...', true);
    try {
      const result = await client.post(`/interactions/${interaction.id}/finish`, { outcome });
      loading.remove();
      const info = result.case;
      await bot(outcome === 'RESOLVIDO'
        ? 'Atendimento encerrado como *resolvido* ✅'
        : `Conversa encerrada por ausência. O protocolo *${info.protocol}* segue em aberto para você continuar por qualquer canal.`, { highlight: true });
      await bot(`Registramos na CCE: ${result.interaction.summary || info.summary}`);
      append(caseCard(info, 'CCE ATUALIZADA'));
      quickReplies([
        { label: 'Iniciar novo atendimento', primary: true, action: start },
        { label: 'Ver no Cockpit', href: `/atendente?protocolo=${encodeURIComponent(info.protocol)}` }
      ]);
      interaction = null;
      setMode('closed');
    } catch (error) {
      loading.remove();
      await failure(error);
      await askFinish();
    }
  }

  function submit() {
    const text = input.value.trim();
    if (!text || input.disabled) return;
    input.value = '';
    if (mode === 'protocol') {
      const digits = onlyDigits(text, 12);
      if (!digits) {
        bot('Envie apenas os números do protocolo ou toque em *Não tenho protocolo*.');
        return;
      }
      me(digits);
      protocol = digits;
      askCpf();
    } else if (mode === 'cpf') {
      const digits = onlyDigits(text);
      me(formatCpf(digits));
      if (digits.length !== 11) { bot('O CPF precisa ter 11 números. Pode enviar novamente?'); return; }
      identify(digits);
    } else if (mode === 'code') {
      const digits = onlyDigits(text, 6);
      me(digits);
      verify(digits);
    } else if (mode === 'new-topic') {
      if (text.length < 3) { bot('Escreva um pouco mais sobre o que você precisa.'); return; }
      me(text);
      openCase(text);
    } else if (mode === 'chat') {
      me(text);
      sendChatMessage(text);
    }
  }

  input.addEventListener('input', () => {
    if (mode === 'cpf') input.value = formatCpf(input.value);
    if (mode === 'code') input.value = onlyDigits(input.value, 6);
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
  });
  sendButton.addEventListener('click', submit);
  document.getElementById('wa-finish').addEventListener('click', askFinish);
  document.getElementById('wa-restart').addEventListener('click', () => {
    if (interaction && !window.confirm('Reiniciar a conversa? O contato atual continuará em andamento na CCE.')) return;
    start();
  });

  start();
})();
