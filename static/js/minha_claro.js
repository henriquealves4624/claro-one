(() => {
  const {
    channelClient, showAlert, hideAlert, el, formatCpf, onlyDigits, formatEntity, friendly,
    initials, currency, brDate, store, params
  } = ClaroOne;
  const client = channelClient();
  const alertBox = document.getElementById('mc-alert');
  const cpfInput = document.getElementById('mc-cpf');
  const protocolInput = document.getElementById('mc-protocol');
  const form = document.getElementById('mc-request-form');
  const textArea = document.getElementById('mc-request-text');
  const submitButton = document.getElementById('mc-request-submit');
  const AREA_CATEGORY = {
    billing: 'FATURAMENTO', payments: 'FATURAMENTO', internet: 'INTERNET', phone: 'TELEFONIA',
    tv: 'TV', plans: 'PLANOS', address: 'INSTALACAO', cancel: 'CANCELAMENTO', help: null
  };

  let customerName = '';
  let cases = [];
  let focusProtocol = null;
  // Contexto da área aberta: caso retomado (com o último contato anterior) ou área manual.
  let areaState = { area: 'help', caseInfo: null, previousContact: null, interaction: null };

  function step(name) {
    document.querySelectorAll('.mc-step').forEach(section => section.classList.toggle('active', section.dataset.step === name));
    hideAlert(alertBox);
    document.getElementById('mc-app').scrollTo?.({ top: 0 });
  }

  // ------------------------------------------------------------ login

  async function login() {
    const button = document.getElementById('mc-login');
    const cpf = onlyDigits(cpfInput.value);
    if (cpf.length !== 11) { showAlert(alertBox, 'Informe um CPF com 11 dígitos.'); return; }
    button.disabled = true;
    try {
      const protocol = onlyDigits(protocolInput.value, 12);
      const result = await client.post('/identify', { channel: 'MINHA_CLARO', cpf, protocol: protocol || null });
      if (result.protocol_status === 'NOT_FOUND') {
        showAlert(alertBox, `Não encontramos o protocolo ${protocol} para este CPF. Confira o número ou entre sem protocolo.`);
        return;
      }
      client.setToken(result.access_token);
      store.set('claroOneCpf', cpf);
      await loadHome();
      if (result.protocol_status === 'CLOSED') {
        showAlert(alertBox, `O protocolo ${result.closed_protocol} já foi encerrado. Você pode abrir uma nova solicitação.`, 'info');
      }
    } catch (error) {
      showAlert(alertBox, error.message);
    } finally { button.disabled = false; }
  }

  function logout() {
    client.setToken(null);
    cases = [];
    document.getElementById('mc-logout').classList.add('hidden');
    document.getElementById('mc-header-user').textContent = 'Dados simulados';
    document.getElementById('mc-user-dot').textContent = '';
    step('login');
  }

  // ------------------------------------------------------------ início

  async function loadHome() {
    const data = await client.get('/cases');
    customerName = data.customer.name;
    cases = data.cases;
    focusProtocol = data.focus_protocol;
    document.getElementById('mc-name').textContent = customerName;
    document.getElementById('mc-initials').textContent = initials(customerName);
    document.getElementById('mc-header-user').textContent = data.customer.first_name;
    document.getElementById('mc-user-dot').textContent = initials(customerName);
    document.getElementById('mc-logout').classList.remove('hidden');
    renderOpenCases();
    step('home');
  }

  const TITLES = {
    billing: 'Encontramos uma solicitação sobre sua fatura.',
    internet: 'Encontramos um atendimento sobre sua internet.',
    phone: 'Encontramos um atendimento sobre sua linha.',
    tv: 'Encontramos um atendimento sobre sua TV.',
    plans: 'Encontramos uma solicitação sobre seu plano.',
    address: 'Encontramos uma solicitação de instalação ou endereço.',
    cancel: 'Encontramos uma solicitação de cancelamento.',
    help: 'Encontramos um atendimento em andamento.'
  };

  function renderOpenCases() {
    const container = document.getElementById('mc-open-cases');
    container.replaceChildren();
    if (!cases.length) {
      container.append(el('div', { class: 'manual-welcome' },
        el('span', {}, 'ÁREA DE AUTOATENDIMENTO'),
        el('h3', {}, 'O que você precisa hoje?'),
        el('p', {}, 'Nenhum atendimento está em aberto. Escolha um serviço ou abra uma nova solicitação.')));
      return;
    }
    const ordered = [...cases].sort((a, b) => (b.protocol === focusProtocol) - (a.protocol === focusProtocol));
    const [focus, ...others] = ordered;
    const entities = Object.entries(focus.entities || {}).slice(0, 3).map(([key, value]) => el('div', {},
      el('small', {}, friendly(key)), el('strong', {}, formatEntity(key, value))));
    container.append(el('article', { class: 'ongoing-card' },
      el('div', { class: 'ongoing-top' },
        el('span', {}, el('i'), ' ATENDIMENTO EM ANDAMENTO'),
        el('small', {}, `PROTOCOLO ${focus.protocol}`)),
      el('h3', {}, TITLES[focus.area] || TITLES.help),
      el('p', {}, focus.problem || focus.summary || ''),
      el('div', { class: 'ongoing-context-meta' },
        el('span', {}, focus.category_label), el('span', {}, focus.department_label), el('span', {}, focus.status_label),
        el('span', {}, `Aberto em ${brDate(focus.created_at)} · ${focus.channel_origin_label}`)),
      entities.length ? el('div', { class: 'entity-preview' }, entities) : null,
      el('div', { class: 'ongoing-actions' },
        el('button', { type: 'button', class: 'button white-button', onclick: () => continueCase(focus) }, 'Continuar de onde parei ', el('b', {}, '→')),
        el('button', { type: 'button', class: 'button outline-white', onclick: openNewRequest }, 'Falar sobre outro assunto'))));
    if (others.length) {
      container.append(el('div', { class: 'other-cases' },
        el('h3', { class: 'section-mini-title' }, 'Outros atendimentos em aberto'),
        others.map(item => el('button', { type: 'button', class: 'other-case', onclick: () => continueCase(item) },
          el('span', {}, el('b', {}, item.category_label), el('small', {}, `Protocolo ${item.protocol} · ${item.status_label}`)),
          el('i', {}, 'Continuar →')))));
    }
  }

  // ------------------------------------------------------------ áreas

  function areaConfig(area, caseInfo) {
    const entity = caseInfo?.entities || {};
    const fromContext = Boolean(caseInfo);
    const badge = fromContext ? 'CONTEXTO RECUPERADO' : 'AUTOATENDIMENTO';
    const configs = {
      billing: { icon: '▤', label: 'FATURAS', title: fromContext ? 'Fatura e contestação' : 'Minhas faturas', trail: ['Início', 'Faturas'], item: entity.produto || 'Fatura atual', detailLabel: fromContext ? 'Valor relacionado' : 'Opções', detail: entity.valor !== undefined ? currency(entity.valor) : 'Consultar fatura, itens e segunda via', status: fromContext ? caseInfo.status_label : 'Área disponível' },
      payments: { icon: '$', label: 'PAGAMENTOS', title: 'Pagamentos', trail: ['Início', 'Pagamentos'], item: 'Formas de pagamento', detailLabel: 'Opções', detail: 'Código de barras, Pix e débito automático', status: 'Área disponível' },
      internet: { icon: '⌁', label: 'INTERNET', title: fromContext ? 'Suporte da conexão' : 'Minha internet', trail: ['Início', 'Internet', fromContext ? 'Suporte' : 'Resumo'], item: entity.equipamento || 'Internet residencial', detailLabel: fromContext ? 'Situação informada' : 'Opções', detail: fromContext ? caseInfo.problem : 'Status da conexão, Wi-Fi e diagnóstico', status: fromContext ? caseInfo.status_label : 'Dados não consultados' },
      phone: { icon: '▯', label: 'MINHA LINHA', title: fromContext ? 'Suporte da linha' : 'Minha linha', trail: ['Início', 'Minha linha'], item: entity.linha || 'Linha móvel', detailLabel: fromContext ? 'Situação informada' : 'Opções', detail: fromContext ? caseInfo.problem : 'Consumo, chip e chamadas', status: fromContext ? caseInfo.status_label : 'Dados não consultados' },
      tv: { icon: '▣', label: 'TV E STREAMING', title: fromContext ? 'Suporte de TV' : 'Minha TV', trail: ['Início', 'TV'], item: entity.equipamento || 'Claro TV+', detailLabel: fromContext ? 'Situação informada' : 'Opções', detail: fromContext ? caseInfo.problem : 'Canais, decodificador e streaming', status: fromContext ? caseInfo.status_label : 'Área disponível' },
      plans: { icon: '＋', label: 'PLANOS E OFERTAS', title: fromContext ? 'Seu pedido de plano' : 'Planos e serviços', trail: ['Início', 'Planos'], item: entity.plano || entity.franquia_desejada || 'Plano atual', detailLabel: fromContext ? 'Solicitação' : 'Opções', detail: fromContext ? caseInfo.problem : 'Comparar planos, pacotes e franquia', status: fromContext ? caseInfo.status_label : 'Ofertas disponíveis' },
      address: { icon: '⌂', label: 'ENDEREÇO E INSTALAÇÃO', title: fromContext ? 'Instalação e endereço' : 'Endereço e instalação', trail: ['Início', 'Endereço'], item: entity.servico || 'Endereço de instalação', detailLabel: fromContext ? 'Solicitação' : 'Opções', detail: fromContext ? caseInfo.problem : 'Mudança de endereço e agendamentos', status: fromContext ? caseInfo.status_label : 'Área disponível' },
      cancel: { icon: '⊘', label: 'PLANO E SERVIÇOS', title: 'Solicitação sobre o seu plano', trail: ['Início', 'Plano e serviços'], item: entity.plano || entity.produto || 'Plano atual', detailLabel: 'Próxima etapa', detail: 'Um especialista de retenção já tem o seu contexto', status: fromContext ? caseInfo.status_label : 'Área disponível' },
      help: { icon: '?', label: 'ATENDIMENTO', title: fromContext ? caseInfo.category_label : 'Nova solicitação', trail: ['Início', 'Ajuda'], item: fromContext ? (caseInfo.problem || 'Solicitação em andamento') : 'Fale com a Claro', detailLabel: fromContext ? 'Encaminhamento' : 'Como funciona', detail: fromContext ? caseInfo.department_label : 'Descreva o pedido e a IA direciona para o time certo', status: fromContext ? caseInfo.status_label : 'Canal disponível' }
    };
    return { ...configs[area] || configs.help, badge };
  }

  function renderArea(area, caseInfo) {
    const config = areaConfig(area, caseInfo);
    document.getElementById('adaptive-content').replaceChildren(
      el('div', { class: 'adaptive-hero' },
        el('div', { class: 'adaptive-icon' }, config.icon),
        el('div', {}, el('span', {}, config.label), el('h2', {}, config.title))),
      el('div', { class: 'breadcrumb' }, config.trail.map((item, index) => [index ? el('i', {}, '›') : null, el('b', {}, item)])),
      el('article', { class: 'service-detail' },
        el('header', {}, el('strong', {}, config.item), el('span', {}, config.badge)),
        el('div', { class: 'service-line' }, el('div', {}, el('small', {}, config.detailLabel), el('strong', {}, config.detail || '—'))),
        el('div', { class: 'service-line' }, el('div', {}, el('small', {}, 'Status'), el('strong', {}, config.status)), el('b', {}, 'Dados simulados'))));
  }

  function renderContextSummary(caseInfo, previousContact) {
    const container = document.getElementById('mc-context-summary');
    container.replaceChildren();
    if (!caseInfo) return;
    container.append(el('article', { class: 'context-summary' },
      el('span', { class: 'summary-label' }, `RESUMO DO SEU ÚLTIMO ATENDIMENTO · PROTOCOLO ${caseInfo.protocol}`),
      el('div', { class: 'summary-tags' },
        el('span', {}, caseInfo.category_label), el('span', {}, caseInfo.department_label), el('span', {}, caseInfo.status_label)),
      el('p', {}, caseInfo.summary || caseInfo.problem || ''),
      previousContact ? el('div', { class: 'summary-last' },
        el('small', {}, `Última sessão · ${previousContact.channel_label} · ${brDate(previousContact.at)}`),
        el('span', {}, previousContact.summary || '')) : null,
      el('em', {}, 'Você chegou direto a esta área porque o contexto foi preservado entre os canais.')));
  }

  function setForm(title, subtitle, placeholder) {
    document.getElementById('mc-form-title').textContent = title;
    document.getElementById('mc-form-subtitle').textContent = subtitle;
    textArea.placeholder = placeholder;
    textArea.value = '';
    form.classList.remove('hidden');
  }

  function openArea(area, { caseInfo = null, previousContact = null, notice = null } = {}) {
    areaState = { area, caseInfo, previousContact, interaction: areaState.caseInfo?.protocol === caseInfo?.protocol ? areaState.interaction : null };
    renderContextSummary(caseInfo, previousContact);
    renderArea(area, caseInfo);
    const noticeBox = document.getElementById('mc-area-notice');
    noticeBox.replaceChildren(notice ? el('div', { class: 'area-notice' }, notice) : '');
    document.getElementById('mc-request-result').replaceChildren();
    if (caseInfo) {
      setForm(`Quer acrescentar algo ao protocolo ${caseInfo.protocol}?`,
        'O que você enviar aqui entra no contexto do atendimento e fica visível para o especialista.',
        'Ex.: A luz do modem continua vermelha e posso receber o técnico depois das 14h.');
    } else {
      const label = areaConfig(area, null).title;
      setForm(area === 'help' ? 'Descreva sua solicitação' : `Precisa de ajuda com ${label.toLowerCase()}?`,
        'A IA identifica o assunto, abre um protocolo e direciona para o departamento certo.',
        'Ex.: Quero trocar meu plano por um com mais internet.');
    }
    step('area');
  }

  async function continueCase(caseInfo) {
    try {
      const result = await client.post(`/cases/${encodeURIComponent(caseInfo.protocol)}/resume`);
      areaState.interaction = null;
      openArea(result.case.area, { caseInfo: result.case, previousContact: caseInfo.last_contact });
      areaState.interaction = result.interaction;
    } catch (error) { showAlert(alertBox, error.message); }
  }

  function openNewRequest() { openArea('help'); }

  function renderRequestResult(title, info, summary) {
    document.getElementById('mc-request-result').replaceChildren(el('article', { class: 'request-result' },
      el('div', { class: 'result-icon' }, '✓'),
      el('div', {},
        el('strong', {}, title),
        el('small', {}, `Protocolo ${info.protocol} · ${info.category_label} · ${info.department_label} · ${info.status_label}`),
        el('p', {}, summary || info.summary || ''),
        el('a', { href: `/atendente?protocolo=${encodeURIComponent(info.protocol)}` }, 'Ver no Cockpit →'))));
  }

  async function submitRequest(event) {
    event.preventDefault();
    const text = textArea.value.trim();
    if (text.length < 3) { showAlert(alertBox, 'Escreva pelo menos 3 caracteres.'); return; }
    submitButton.disabled = true;
    submitButton.textContent = 'IA analisando...';
    hideAlert(alertBox);
    try {
      if (areaState.caseInfo) {
        if (!areaState.interaction) {
          const resumed = await client.post(`/cases/${encodeURIComponent(areaState.caseInfo.protocol)}/resume`);
          areaState.interaction = resumed.interaction;
        }
        await client.post(`/interactions/${areaState.interaction.id}/messages`, { text });
        const result = await client.post(`/interactions/${areaState.interaction.id}/finish`, { outcome: 'EM_ABERTO' });
        areaState.interaction = null;
        areaState.caseInfo = result.case;
        renderContextSummary(result.case, { channel_label: 'Minha Claro', at: new Date().toISOString(), summary: result.interaction.summary });
        textArea.value = '';
        renderRequestResult('Atendimento atualizado', result.case, result.interaction.summary);
      } else {
        const category = AREA_CATEGORY[areaState.area] || null;
        const result = await client.post('/cases', { message: text, area_category: category });
        const info = result.case;
        const moved = info.area !== areaState.area && !(areaState.area === 'payments' && info.area === 'billing');
        openArea(info.area, {
          caseInfo: info,
          previousContact: info.last_contact,
          notice: moved ? `Levamos você para a área mais adequada ao seu pedido: ${info.category_label}.` : null
        });
        renderRequestResult('Solicitação registrada', info, result.interaction.summary);
      }
    } catch (error) {
      showAlert(alertBox, error.message);
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = 'Enviar';
    }
  }

  document.getElementById('mc-login').addEventListener('click', login);
  [cpfInput, protocolInput].forEach(input => input.addEventListener('keydown', event => { if (event.key === 'Enter') login(); }));
  protocolInput.addEventListener('input', () => { protocolInput.value = onlyDigits(protocolInput.value, 12); });
  document.getElementById('mc-logout').addEventListener('click', logout);
  document.getElementById('mc-back').addEventListener('click', () => loadHome().catch(error => showAlert(alertBox, error.message)));
  document.getElementById('mc-new-request').addEventListener('click', openNewRequest);
  document.querySelectorAll('.quick-grid button').forEach(button => button.addEventListener('click', () => openArea(button.dataset.area)));
  form.addEventListener('submit', submitRequest);

  const presetProtocol = onlyDigits(params.get('protocolo'), 12);
  if (presetProtocol) protocolInput.value = presetProtocol;
  const rememberedCpf = store.get('claroOneCpf');
  if (rememberedCpf) cpfInput.value = formatCpf(rememberedCpf);
})();
