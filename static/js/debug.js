(() => {
  const { api, el, friendly, brDate, maskCpf, toast, categoryLabel, departmentLabel, channelLabel, statusLabel } = ClaroOne;
  const tableBody = document.getElementById('debug-sessions');
  const jsonCode = document.getElementById('session-json');
  const modal = document.getElementById('reset-modal');

  async function load() {
    const sessions = await api('/api/sessions?include_closed=true');
    tableBody.replaceChildren();
    if (!sessions.length) {
      tableBody.append(el('tr', {}, el('td', { colspan: '10' }, 'Nenhum protocolo armazenado.')));
      return;
    }
    sessions.forEach(item => {
      const row = el('tr', { dataset: { id: item.id }, onclick: () => show(item.id, row) },
        el('td', {}, item.protocol),
        el('td', {}, maskCpf(item.cpf)),
        el('td', {}, item.customer_name),
        el('td', {}, el('span', { class: 'table-status' }, statusLabel(item.status))),
        el('td', {}, categoryLabel(item.category)),
        el('td', {}, departmentLabel(item.destination_department)),
        el('td', {}, channelLabel(item.current_channel)),
        el('td', {}, item.assigned_agent || '—'),
        el('td', {}, brDate(item.created_at)),
        el('td', {}, brDate(item.updated_at)));
      tableBody.append(row);
    });
    const queryId = new URLSearchParams(location.search).get('session');
    const targetRow = queryId && tableBody.querySelector(`[data-id="${CSS.escape(queryId)}"]`);
    if (targetRow) show(queryId, targetRow);
  }

  async function show(id, row) {
    const full = await api(`/api/sessions/${id}`);
    tableBody.querySelectorAll('tr').forEach(item => item.classList.remove('selected'));
    row?.classList.add('selected');
    document.getElementById('json-protocol').textContent = `Protocolo ${full.protocol} · ${full.interactions.length} contato(s) · ${full.events.length} evento(s)`;
    jsonCode.textContent = JSON.stringify(full, null, 2);
  }

  document.getElementById('debug-refresh').addEventListener('click', () => load().catch(error => toast(error.message, true)));
  document.getElementById('copy-json').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(jsonCode.textContent); toast('JSON copiado.'); }
    catch { toast('Não foi possível copiar o JSON.', true); }
  });

  let resetEndpoint = '/api/demo/reset';
  function openConfirmation(mode) {
    const isReset = mode === 'reset';
    resetEndpoint = isReset ? '/api/demo/reset' : '/api/demo/clear';
    document.getElementById('reset-title').textContent = isReset ? 'Reiniciar demonstração?' : 'Limpar dados da demonstração?';
    document.getElementById('reset-description').textContent = isReset
      ? 'Todos os protocolos, contatos e gravações serão removidos e o histórico fictício de demonstração será recriado.'
      : 'Todos os protocolos, contatos e gravações serão removidos, deixando a base vazia. Os clientes fictícios são preservados.';
    document.getElementById('confirm-reset').textContent = isReset ? 'Sim, reiniciar' : 'Sim, limpar';
    modal.showModal();
  }
  document.getElementById('debug-clear').addEventListener('click', () => openConfirmation('clear'));
  document.getElementById('debug-reset').addEventListener('click', () => openConfirmation('reset'));
  document.getElementById('cancel-reset').addEventListener('click', () => modal.close());
  document.getElementById('confirm-reset').addEventListener('click', async () => {
    const button = document.getElementById('confirm-reset');
    button.disabled = true;
    try {
      await api(resetEndpoint, { method: 'POST' });
      try { sessionStorage.clear(); } catch { /* armazenamento indisponível */ }
      modal.close();
      document.getElementById('json-protocol').textContent = 'Selecione um protocolo';
      jsonCode.textContent = '{\n  "mensagem": "Selecione um protocolo na tabela"\n}';
      await load();
      toast(resetEndpoint.endsWith('reset') ? 'Demonstração reiniciada.' : 'Dados removidos.');
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; }
  });

  load().catch(error => toast(error.message, true));
})();
