(() => {
  const { api, el, brDay, toast } = ClaroOne;
  const tooltip = document.getElementById('viz-tooltip');
  const body = document.getElementById('gestor-body');
  let days = 14;
  let loaded = false;
  let loading = false;

  const percent = value => (value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`);
  const number = value => new Intl.NumberFormat('pt-BR').format(value);
  const decimal = value => (value === null || value === undefined ? '—' : new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(value));

  // ------------------------------------------------------------ tooltip

  const tips = new WeakMap();
  function withTip(node, title, rows) {
    tips.set(node, { title, rows });
    node.tabIndex = 0;
    node.addEventListener('pointerenter', showTip);
    node.addEventListener('pointermove', moveTip);
    node.addEventListener('pointerleave', hideTip);
    node.addEventListener('focus', showTip);
    node.addEventListener('blur', hideTip);
    return node;
  }

  function showTip(event) {
    const data = tips.get(event.currentTarget);
    if (!data) return;
    tooltip.replaceChildren(
      el('strong', {}, data.title),
      ...data.rows.map(([label, value, color]) => el('span', { class: 'tip-row' },
        color ? el('i', { class: `tip-key ${color}` }) : null,
        el('b', {}, String(value)),
        el('small', {}, label))));
    tooltip.classList.remove('hidden');
    moveTip(event);
  }

  function moveTip(event) {
    if (tooltip.classList.contains('hidden')) return;
    const shell = tooltip.parentElement.getBoundingClientRect();
    const x = (event.clientX ?? shell.left + shell.width / 2) - shell.left;
    const y = (event.clientY ?? shell.top) - shell.top;
    tooltip.style.left = `${Math.min(Math.max(x + 14, 8), shell.width - tooltip.offsetWidth - 8)}px`;
    tooltip.style.top = `${Math.max(y - tooltip.offsetHeight - 12, 8)}px`;
  }

  function hideTip() { tooltip.classList.add('hidden'); }

  // ------------------------------------------------------------ componentes

  function legend(items) {
    return items.map(([label, color]) => el('span', { class: 'legend-item' }, el('i', { class: `legend-key ${color}` }), label));
  }

  function table(headers, rows) {
    return el('table', {},
      el('thead', {}, el('tr', {}, headers.map(header => el('th', {}, header)))),
      el('tbody', {}, rows.map(row => el('tr', {}, row.map(cell => el('td', {}, String(cell)))))));
  }

  function statTile(label, value, detail) {
    return el('div', { class: 'stat-tile' }, el('small', {}, label), el('strong', {}, value), el('span', {}, detail));
  }

  function columnChart(container, data) {
    container.replaceChildren();
    const max = Math.max(1, ...data.map(item => item.openings + item.resumptions));
    const ticks = [max, Math.round(max / 2), 0];
    const plot = el('div', { class: 'plot' },
      el('div', { class: 'grid' }, ticks.map(tick => el('span', { class: 'grid-line' }, el('i', {}, number(tick))))),
      el('div', { class: 'columns' }, data.map(item => {
        const total = item.openings + item.resumptions;
        const column = el('div', { class: 'column' },
          total ? el('em', { style: `bottom: calc(${(total / max) * 100}% + 5px)` }, total) : null,
          el('span', { class: 'stack' },
            item.resumptions ? el('span', { class: 'seg accent', style: `height:${(item.resumptions / max) * 100}%` }) : null,
            item.openings ? el('span', { class: 'seg muted', style: `height:${(item.openings / max) * 100}%` }) : null));
        return withTip(column, brDay(item.date), [
          ['Retomadas com contexto', item.resumptions, 'accent'],
          ['Novos atendimentos', item.openings, 'muted'],
          ['Total de contatos', total]
        ]);
      })));
    const step = data.length > 10 ? Math.ceil(data.length / 7) : 1;
    container.append(plot, el('div', { class: 'x-axis' }, data.map((item, index) =>
      el('span', {}, index % step === 0 || index === data.length - 1 ? brDay(item.date) : ''))));
  }

  function barChart(container, rows, { stacked = false } = {}) {
    container.replaceChildren();
    if (!rows.length) {
      container.append(el('p', { class: 'muted-empty' }, 'Sem dados no período selecionado.'));
      return;
    }
    const max = Math.max(1, ...rows.map(row => row.total));
    rows.forEach(row => {
      const track = el('span', { class: 'bar-track' },
        stacked
          ? [
            row.primary ? el('span', { class: 'bar accent', style: `width:${(row.primary / max) * 100}%` }) : null,
            row.secondary ? el('span', { class: 'bar muted', style: `width:${(row.secondary / max) * 100}%` }) : null
          ]
          : el('span', { class: 'bar accent', style: `width:${(row.total / max) * 100}%` }));
      const node = el('div', { class: 'bar-row' },
        el('span', { class: 'bar-label' }, row.label),
        track,
        el('b', {}, number(row.total)));
      container.append(withTip(node, row.label, row.tip || [['Total', row.total]]));
    });
  }

  function aiHealth(container, stages) {
    const statusOf = stage => {
      if (!stage.runs) return ['neutral', '–', 'Sem execuções'];
      if (stage.success_rate >= 0.9) return ['good', '✓', 'Operando'];
      return ['warning', '!', 'Atenção'];
    };
    container.replaceChildren(el('div', { class: 'ai-health' }, stages.map(stage => {
      const [tone, icon, label] = statusOf(stage);
      return el('div', { class: 'ai-row' },
        el('span', { class: `ai-status ${tone}` }, el('i', {}, icon), label),
        el('div', {}, el('strong', {}, stage.label), el('small', {}, `${number(stage.runs)} execução(ões) · ${stage.runs ? percent(stage.success_rate) : '—'} de sucesso`)),
        el('b', {}, stage.avg_latency_ms ? `${number(stage.avg_latency_ms)} ms` : '—'));
    })));
  }

  // ------------------------------------------------------------ render

  function render(data) {
    const kpis = data.kpis;
    document.getElementById('kpi-continuity').textContent = percent(kpis.continuity_rate);
    document.getElementById('kpi-continuity-detail').textContent = kpis.channel_handoffs || kpis.duplicate_openings
      ? `${number(kpis.channel_handoffs)} transbordo(s) com contexto preservado · ${number(kpis.duplicate_openings)} protocolo(s) abertos em duplicidade`
      : 'Ainda não houve transbordo entre canais no período.';

    document.getElementById('kpi-grid').replaceChildren(
      statTile('Contatos registrados', number(kpis.contacts), `${number(kpis.openings)} novos · ${number(kpis.resumptions)} retomadas`),
      statTile('Contexto reaproveitado', percent(kpis.context_reuse_rate), `${number(kpis.resumptions)} de ${number(kpis.contacts)} contatos sem nova triagem`),
      statTile('Triagens evitadas', number(kpis.triage_avoided), `≈ ${decimal(kpis.triage_minutes_saved)} min poupados · premissa de ${decimal(kpis.triage_minutes_assumption)} min por triagem`),
      statTile('Protocolos multicanal', number(kpis.cross_channel_cases), `${percent(kpis.cross_channel_rate)} dos protocolos passaram por 2+ canais`),
      statTile('Contatos por protocolo', decimal(kpis.contacts_per_case), 'média no período'),
      statTile('Tempo até a resolução', kpis.avg_resolution_hours === null ? '—' : `${decimal(kpis.avg_resolution_hours)} h`, `${number(kpis.resolved_cases)} protocolo(s) resolvidos`),
      statTile('Classificação específica', percent(kpis.classification_coverage), 'protocolos fora de “Outros assuntos”'),
      statTile('Dados mascarados', number(kpis.redactions), 'trechos sensíveis removidos antes das IAs'));

    document.getElementById('daily-legend').replaceChildren(...legend([['Retomadas com contexto', 'accent'], ['Novos atendimentos', 'muted']]));
    columnChart(document.getElementById('daily-chart'), data.daily);
    document.getElementById('daily-table').replaceChildren(table(
      ['Dia', 'Novos', 'Retomadas', 'Total'],
      data.daily.map(item => [brDay(item.date), item.openings, item.resumptions, item.openings + item.resumptions])));

    const flows = data.handoff_flows.map(flow => ({
      label: `${flow.from_label} → ${flow.to_label}`,
      total: flow.count,
      tip: [['Transbordos no período', flow.count, 'accent']]
    }));
    barChart(document.getElementById('flows-chart'), flows);
    document.getElementById('flows-table').replaceChildren(table(['Origem', 'Destino', 'Transbordos'],
      data.handoff_flows.map(flow => [flow.from_label, flow.to_label, flow.count])));

    document.getElementById('channels-legend').replaceChildren(...legend([['Retomadas', 'accent'], ['Novos atendimentos', 'muted']]));
    const channels = data.channels.map(channel => ({
      label: channel.label,
      primary: channel.resumptions,
      secondary: channel.openings,
      total: channel.resumptions + channel.openings,
      tip: [['Retomadas', channel.resumptions, 'accent'], ['Novos atendimentos', channel.openings, 'muted']]
    }));
    barChart(document.getElementById('channels-chart'), channels, { stacked: true });
    document.getElementById('channels-table').replaceChildren(table(['Canal', 'Novos', 'Retomadas', 'Total'],
      data.channels.map(channel => [channel.label, channel.openings, channel.resumptions, channel.openings + channel.resumptions])));

    document.getElementById('departments-legend').replaceChildren(...legend([['Em aberto', 'accent'], ['Encerrados', 'muted']]));
    const departments = data.departments.filter(item => item.cases).map(item => ({
      label: item.label,
      primary: item.open,
      secondary: item.cases - item.open,
      total: item.cases,
      tip: [['Em aberto', item.open, 'accent'], ['Encerrados', item.cases - item.open, 'muted'], ['Contatos no departamento', item.contacts]]
    }));
    barChart(document.getElementById('departments-chart'), departments, { stacked: true });
    document.getElementById('departments-table').replaceChildren(table(['Departamento', 'Protocolos', 'Em aberto', 'Contatos'],
      data.departments.map(item => [item.label, item.cases, item.open, item.contacts])));

    aiHealth(document.getElementById('ai-health'), data.ai_health);

    const provenance = data.provenance;
    document.getElementById('gestor-provenance').textContent = provenance.demo_contacts
      ? `Base: ${number(provenance.contacts)} contatos · ${number(provenance.demo_contacts)} do histórico de demonstração`
      : `Base: ${number(provenance.contacts)} contatos registrados`;
    document.getElementById('gestor-footnote').textContent =
      'Indicadores de funcionamento da solução, calculados sobre os atendimentos simulados. A estimativa de tempo poupado usa a premissa configurável de '
      + `${decimal(kpis.triage_minutes_assumption)} minuto(s) por triagem evitada. Não há dados de satisfação ou NPS.`;
  }

  async function load(force = false) {
    if (loading || (loaded && !force)) return;
    loading = true;
    body.classList.add('is-loading');
    try {
      const data = await api(`/api/cockpit/metrics?days=${days}`);
      render(data);
      loaded = true;
    } catch (error) {
      toast(error.message, true);
    } finally {
      loading = false;
      body.classList.remove('is-loading');
    }
  }

  document.querySelectorAll('.segmented button').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('.segmented button').forEach(item => item.classList.toggle('active', item === button));
    days = Number(button.dataset.days);
    load(true);
  }));
  document.getElementById('gestor-refresh').addEventListener('click', () => load(true));

  window.ClaroGestor = { load: () => load(false), reload: () => load(true) };
})();
