(() => {
  const {
    api, el, showAlert, hideAlert, friendly, brDate, brTime, brDay, isoDay, formatEntity, initials,
    categoryLabel, departmentLabel, channelLabel, statusLabel, priorityLabel, interactionTypeLabel,
    params, toast
  } = ClaroOne;

  const list = document.getElementById('customer-list');
  const content = document.getElementById('cockpit-content');
  const empty = document.getElementById('cockpit-empty');
  const alertBox = document.getElementById('cp-alert');
  const modal = document.getElementById('transcript-modal');
  const search = document.getElementById('customer-search');
  const departmentFilter = document.getElementById('department-filter');
  const channelFilter = document.getElementById('channel-filter');
  const timelineFilters = {
    channel: document.getElementById('tl-channel'),
    department: document.getElementById('tl-department'),
    protocol: document.getElementById('tl-protocol'),
    from: document.getElementById('tl-from'),
    to: document.getElementById('tl-to')
  };
  const CHANNEL_ICONS = { TELEFONE: '☎', WHATSAPP: '▰', MINHA_CLARO: '▦' };

  let customers = [];
  let selectedCpf = null;
  let overview = null;
  let selectedInteractionId = null;

  // ------------------------------------------------------------ abas

  function openTab(name) {
    document.querySelectorAll('.cockpit-tabs button').forEach(button => {
      const active = button.dataset.tab === name;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.toggle('hidden', panel.id !== `panel-${name}`));
    const url = new URL(location.href);
    if (name === 'gestor') { url.searchParams.set('aba', 'gestor'); window.ClaroGestor?.load(); }
    else url.searchParams.delete('aba');
    history.replaceState(null, '', url);
  }
  document.querySelectorAll('.cockpit-tabs button').forEach(button => button.addEventListener('click', () => openTab(button.dataset.tab)));

  // ------------------------------------------------------------ lista de clientes

  function customerQuery() {
    const query = new URLSearchParams();
    if (search.value.trim()) query.set('q', search.value.trim());
    if (departmentFilter.value) query.set('department', departmentFilter.value);
    if (channelFilter.value) query.set('channel', channelFilter.value);
    return query.toString();
  }

  function renderCustomers() {
    document.getElementById('customer-count').textContent = customers.length;
    list.replaceChildren();
    if (!customers.length) {
      list.append(el('div', { class: 'sidebar-loading' }, 'Nenhum cliente encontrado com esses filtros.'));
      content.classList.add('hidden');
      empty.classList.remove('hidden');
      return;
    }
    customers.forEach(customer => {
      list.append(el('button', {
        type: 'button',
        class: `session-item${customer.cpf === selectedCpf ? ' active' : ''}`,
        dataset: { cpf: customer.cpf },
        onclick: () => selectCustomer(customer.cpf)
      },
        el('span', {}, el('b', {}, customer.masked_cpf), el('time', {}, customer.last_contact_at ? brDate(customer.last_contact_at) : '—')),
        el('strong', {}, customer.name),
        el('small', {}, customer.contacts
          ? `${channelLabel(customer.last_channel)} · ${departmentLabel(customer.last_department)}`
          : 'Sem contatos registrados'),
        el('span', { class: 'item-tags' },
          customer.open_cases ? el('em', { class: 'open' }, `${customer.open_cases} em aberto`) : null,
          customer.total_cases ? el('em', {}, `${customer.total_cases} protocolo(s)`) : null,
          customer.contacts ? el('em', {}, `${customer.contacts} contato(s)`) : null)));
    });
  }

  async function loadCustomers(preferredCpf) {
    customers = await api(`/api/cockpit/customers?${customerQuery()}`);
    const target = customers.some(item => item.cpf === preferredCpf) ? preferredCpf
      : customers.some(item => item.cpf === selectedCpf) ? selectedCpf
        : customers[0]?.cpf;
    selectedCpf = target || null;
    renderCustomers();
    if (target) await selectCustomer(target);
  }

  async function selectCustomer(cpf) {
    try {
      selectedCpf = cpf;
      overview = await api(`/api/cockpit/customers/${encodeURIComponent(cpf)}`);
      selectedInteractionId = null;
      [...list.children].forEach(node => node.classList?.toggle('active', node.dataset?.cpf === cpf));
      resetTimelineFilters();
      render();
      empty.classList.add('hidden');
      content.classList.remove('hidden');
      loadExecutiveSummary(cpf);
    } catch (error) { toast(error.message, true); }
  }

  // ------------------------------------------------------------ detalhe

  const caseOf = interaction => overview.cases.find(item => item.id === interaction?.session_id) || null;
  const latestInteraction = () => overview.interactions[overview.interactions.length - 1] || null;
  const selectedInteraction = () => overview.interactions.find(item => item.id === selectedInteractionId) || null;
  const focusInteraction = () => selectedInteraction() || latestInteraction();

  function focusCase() {
    const interaction = focusInteraction();
    if (interaction) return caseOf(interaction);
    return overview.cases[overview.cases.length - 1] || null;
  }

  function set(id, value) { document.getElementById(id).textContent = value ?? '—'; }

  function renderHeader() {
    const customer = overview.customer;
    const current = focusCase();
    set('cp-initials', initials(customer.name));
    set('cp-name', customer.name);
    const open = overview.cases.filter(item => !['RESOLVIDA', 'EXPIRADA'].includes(item.status)).length;
    set('cp-identity', `${customer.masked_cpf} · ${overview.cases.length} protocolo(s) · ${open} em aberto · ${overview.interactions.length} contato(s)`);
    const status = document.getElementById('cp-status');
    status.textContent = current ? statusLabel(current.status) : 'Sem protocolo';
    status.className = `status-badge ${current && ['RESOLVIDA', 'EXPIRADA'].includes(current.status) ? 'closed' : 'open'}`;
    set('cp-origin', current ? channelLabel(current.channel_origin) : '—');
    set('cp-channel', current ? channelLabel(current.current_channel) : '—');
  }

  function renderSnapshot() {
    const interaction = selectedInteraction();
    const current = focusCase();
    const base = interaction || latestInteraction();
    const isSelection = Boolean(interaction);
    document.getElementById('snapshot-title').textContent = isSelection ? 'Contato selecionado' : 'Último contato';
    document.getElementById('snapshot-back').classList.toggle('hidden', !isSelection);
    const source = document.getElementById('snapshot-source');
    source.textContent = base?.source === 'DEMO' ? 'HISTÓRICO DE DEMONSTRAÇÃO' : 'IA DE CONTEXTO';
    source.classList.toggle('demo', base?.source === 'DEMO');
    document.getElementById('snapshot-context').textContent = base
      ? `${channelLabel(base.channel)} · ${brDate(base.started_at)} · protocolo ${base.protocol} · ${interactionTypeLabel(base.interaction_type)}`
      : 'Nenhum contato registrado para este CPF.';
    const intent = base?.intent || current?.intent;
    set('cp-intent', intent ? friendly(intent) : 'Não identificada');
    set('cp-problem', base?.problem || current?.problem || 'Não identificado');
    document.getElementById('cp-summary-label').textContent = isSelection ? 'RESUMO DESTE CONTATO' : 'RESUMO DO PROTOCOLO';
    set('cp-summary', isSelection ? (base?.summary || 'Sem resumo registrado.') : (current?.summary || 'Contexto ainda não processado.'));
    set('cp-department', departmentLabel(base?.destination_department || current?.destination_department));
    set('cp-protocol', base?.protocol || current?.protocol || '—');
    set('cp-priority', current ? priorityLabel(current.priority) : '—');
    set('cp-action', current?.suggested_action ? friendly(current.suggested_action) : '—');

    const entities = isSelection ? (base?.structured_context || {}) : (current?.structured_context || {});
    document.getElementById('entities-title').textContent = isSelection ? 'Entidades deste contato' : 'Entidades do protocolo';
    const grid = document.getElementById('cp-entities');
    grid.replaceChildren();
    const entries = Object.entries(entities).filter(([, value]) => value !== null && value !== '');
    if (!entries.length) grid.append(el('p', { class: 'muted-empty' }, 'Nenhuma entidade extraída.'));
    entries.forEach(([key, value]) => grid.append(el('div', { class: 'entity-card' },
      el('small', {}, friendly(key)), el('strong', {}, formatEntity(key, value)))));

    renderLineage(base);
    const record = document.getElementById('view-record');
    record.disabled = !base?.has_record;
    record.textContent = base?.input_kind === 'AUDIO' ? 'Ver transcrição do contato' : 'Ver conversa do contato';
    document.getElementById('focus-protocol').textContent = current?.protocol || '—';
    const closed = !current || ['RESOLVIDA', 'EXPIRADA'].includes(current.status);
    document.getElementById('cp-handoff').disabled = closed;
    document.getElementById('cp-resolve').disabled = closed;
  }

  function renderLineage(interaction) {
    const node = (title, subtitle, accent = false) => el('span', { class: `lineage-node${accent ? ' accent' : ''}` }, el('b', {}, title), el('small', {}, subtitle));
    const arrow = () => el('i', {}, '→');
    const lineage = document.getElementById('cp-lineage');
    lineage.replaceChildren();
    if (!interaction) { lineage.append(el('p', { class: 'muted-empty' }, 'Sem contatos para exibir a origem do contexto.')); return; }
    const entry = { AUDIO: ['ÁUDIO', 'Ligação'], CONVERSA: ['MENSAGENS', 'WhatsApp'], FORMULARIO: ['PORTAL', 'Minha Claro'] }[interaction.input_kind] || ['ENTRADA', 'Canal'];
    const steps = [node(entry[0], entry[1])];
    if (interaction.input_kind === 'AUDIO') steps.push(arrow(), node('IA DE TRANSCRIÇÃO', 'Áudio → texto'));
    steps.push(arrow(), node('PROTEÇÃO', 'Dados mascarados'), arrow(), node('IA DE CONTEXTO', 'Case estruturado'), arrow(), node('CCE', 'Continuidade', true));
    lineage.append(...steps);
    if (interaction.source === 'DEMO') lineage.append(el('span', { class: 'lineage-note' }, 'Histórico de demonstração'));
  }

  // ------------------------------------------------------------ timeline

  function resetTimelineFilters() {
    Object.values(timelineFilters).forEach(field => { field.value = ''; });
    const protocols = [...new Set(overview.interactions.map(item => item.protocol))];
    timelineFilters.protocol.replaceChildren(
      el('option', { value: '' }, 'Todos'),
      ...protocols.map(protocol => el('option', { value: protocol }, protocol)));
  }

  function filteredInteractions() {
    return overview.interactions.filter(item => {
      if (timelineFilters.channel.value && item.channel !== timelineFilters.channel.value) return false;
      if (timelineFilters.department.value && item.destination_department !== timelineFilters.department.value) return false;
      if (timelineFilters.protocol.value && item.protocol !== timelineFilters.protocol.value) return false;
      const day = isoDay(item.started_at);
      if (timelineFilters.from.value && day < timelineFilters.from.value) return false;
      if (timelineFilters.to.value && day > timelineFilters.to.value) return false;
      return true;
    });
  }

  function renderTimeline() {
    const timeline = document.getElementById('cp-timeline');
    const items = filteredInteractions().slice().reverse();
    document.getElementById('timeline-count').textContent = items.length;
    timeline.replaceChildren();
    if (!items.length) {
      timeline.append(el('p', { class: 'muted-empty' }, 'Nenhum contato com os filtros aplicados.'));
      return;
    }
    items.forEach(item => {
      const tags = [
        el('span', { class: 'tag date' }, `${brDay(item.started_at)} · ${brTime(item.started_at)}`),
        el('span', { class: 'tag protocol' }, `Prot. ${item.protocol}`),
        item.agent ? el('span', { class: 'tag agent' }, item.agent) : null,
        el('span', { class: 'tag dept' }, departmentLabel(item.destination_department)),
        item.status === 'EM_ANDAMENTO' ? el('span', { class: 'tag live' }, 'Em andamento') : null
      ];
      timeline.append(el('button', {
        type: 'button',
        class: `timeline-item${item.id === selectedInteractionId ? ' selected' : ''}`,
        onclick: () => { selectedInteractionId = item.id === selectedInteractionId ? null : item.id; render(); }
      },
        el('span', { class: `timeline-marker channel-${item.channel}` }, CHANNEL_ICONS[item.channel] || '•'),
        el('span', { class: 'timeline-body' },
          el('span', { class: 'timeline-head' },
            el('b', {}, channelLabel(item.channel)),
            el('em', { class: item.interaction_type === 'RETOMADA' ? 'resumed' : '' }, interactionTypeLabel(item.interaction_type))),
          el('span', { class: 'timeline-tags' }, tags),
          el('span', { class: 'timeline-summary' }, item.summary || 'Sem resumo registrado.'))));
    });
  }

  Object.values(timelineFilters).forEach(field => field.addEventListener('change', renderTimeline));
  document.getElementById('tl-clear').addEventListener('click', () => { resetTimelineFilters(); renderTimeline(); });
  document.getElementById('snapshot-back').addEventListener('click', () => { selectedInteractionId = null; render(); });

  // ------------------------------------------------------------ resumo executivo

  function renderExecutive(summary) {
    const kpis = document.getElementById('executive-kpis');
    const body = document.getElementById('executive-body');
    const stats = summary.stats;
    document.getElementById('executive-source').textContent = summary.source === 'IA' ? 'IA DE CONTEXTO' : 'REGRAS';
    kpis.replaceChildren(...[
      ['Contatos', stats.contacts],
      ['Canais usados', stats.channels_used],
      ['Protocolos em aberto', `${stats.cases_open} de ${stats.cases_total}`],
      ['Retomadas', stats.context_reuses]
    ].map(([label, value]) => el('div', {}, el('small', {}, label), el('strong', {}, String(value)))));
    body.replaceChildren(
      el('strong', { class: 'executive-headline' }, summary.headline),
      el('p', {}, summary.narrative),
      summary.attention_points?.length
        ? el('ul', { class: 'attention-points' }, summary.attention_points.map(point => el('li', {}, point)))
        : null,
      summary.next_best_action ? el('div', { class: 'next-action' }, el('small', {}, 'PRÓXIMA AÇÃO SUGERIDA'), el('span', {}, summary.next_best_action)) : null,
      stats.top_topics?.length
        ? el('div', { class: 'topic-chips' }, stats.top_topics.map(topic => el('span', {}, `${topic.label} · ${topic.count}`)))
        : null,
      el('div', { class: 'executive-footer' },
        el('span', {}, stats.first_contact_at ? `Primeiro contato: ${brDate(stats.first_contact_at)}` : 'Sem contatos'),
        el('span', {}, stats.preferred_channel ? `Canal mais usado: ${stats.preferred_channel}` : ''),
        el('span', {}, stats.cross_channel_cases ? `${stats.cross_channel_cases} protocolo(s) multicanal` : '')));
  }

  async function loadExecutiveSummary(cpf) {
    const body = document.getElementById('executive-body');
    body.replaceChildren(el('p', { class: 'muted-empty' }, 'Gerando resumo da vivência do cliente...'));
    try {
      const summary = await api(`/api/cockpit/customers/${encodeURIComponent(cpf)}/executive-summary`);
      if (cpf !== selectedCpf) return;
      renderExecutive(summary);
    } catch (error) {
      body.replaceChildren(el('p', { class: 'muted-empty' }, `Resumo indisponível: ${error.message}`));
    }
  }

  function render() {
    hideAlert(alertBox);
    renderHeader();
    renderSnapshot();
    renderTimeline();
  }

  // ------------------------------------------------------------ ações

  document.getElementById('view-record').addEventListener('click', async () => {
    const interaction = focusInteraction();
    if (!interaction) return;
    try {
      const record = await api(`/api/cockpit/interactions/${interaction.id}/record`);
      const isAudio = record.input_kind === 'AUDIO';
      const heading = el('div', { class: 'modal-heading' },
        el('div', {},
          el('span', { class: 'eyebrow' }, isAudio ? 'IA DE TRANSCRIÇÃO · ÁUDIO → TEXTO' : `ENTRADA DE TEXTO · ${channelLabel(record.channel)}`),
          el('h2', {}, isAudio ? 'Transcrição original' : 'Conversa registrada')),
        el('button', { type: 'button', 'aria-label': 'Fechar', onclick: () => modal.close() }, '×'));
      const description = el('p', {}, `Protocolo ${record.protocol} · dados pessoais mascarados antes do armazenamento`);
      const body = record.messages?.length
        ? el('div', { class: 'record-chat' }, record.messages.map(message => el('div', { class: `record-message ${message.author.toLowerCase()}` },
          el('small', {}, message.author === 'CLIENTE' ? 'Cliente' : 'Claro'), el('span', {}, message.text))))
        : el('blockquote', {}, record.transcript || 'Conteúdo original indisponível.');
      modal.replaceChildren(heading, description, body,
        el('button', { type: 'button', class: 'button secondary', onclick: () => modal.close() }, 'Fechar'));
      modal.showModal();
    } catch (error) { showAlert(alertBox, error.message); }
  });

  document.getElementById('cp-handoff').addEventListener('click', async () => {
    const current = focusCase();
    if (!current) return;
    try {
      await api(`/api/sessions/${current.id}/handoff`, { method: 'POST' });
      await selectCustomer(selectedCpf);
      showAlert(alertBox, `Atendimento do protocolo ${current.protocol} assumido. O contexto seguiu com você.`, 'success');
      await loadCustomers(selectedCpf);
    } catch (error) { showAlert(alertBox, error.message); }
  });

  document.getElementById('cp-resolve').addEventListener('click', async () => {
    const current = focusCase();
    if (!current) return;
    if (!window.confirm(`Marcar o protocolo ${current.protocol} como resolvido? Ele não poderá mais ser retomado pelo cliente.`)) return;
    try {
      await api(`/api/sessions/${current.id}/resolve`, { method: 'POST' });
      toast('Protocolo resolvido.');
      await loadCustomers(selectedCpf);
    } catch (error) { showAlert(alertBox, error.message); }
  });

  let searchTimer = null;
  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadCustomers().catch(error => toast(error.message, true)), 250);
  });
  [departmentFilter, channelFilter].forEach(field => field.addEventListener('change', () => loadCustomers().catch(error => toast(error.message, true))));
  document.getElementById('refresh-customers').addEventListener('click', () => loadCustomers(selectedCpf).catch(error => toast(error.message, true)));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && !document.getElementById('panel-atendimento').classList.contains('hidden')) {
      loadCustomers(selectedCpf).catch(() => { /* silencioso ao voltar para a aba */ });
    }
  });

  const protocolParam = params.get('protocolo');
  if (protocolParam) search.value = protocolParam;
  if (params.get('aba') === 'gestor') openTab('gestor');
  loadCustomers().catch(error => { list.replaceChildren(el('div', { class: 'sidebar-loading' }, error.message)); });
})();
