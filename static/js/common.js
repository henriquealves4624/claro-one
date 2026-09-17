(() => {
  const taxonomy = (() => {
    try { return JSON.parse(document.getElementById('claro-taxonomy')?.textContent || '{}'); }
    catch { return {}; }
  })();
  const categories = taxonomy.categories || [];
  const byCategory = Object.fromEntries(categories.map(item => [item.value, item]));
  const byDepartment = Object.fromEntries(categories.map(item => [item.department, item]));

  const onlyDigits = (value, limit = 11) => String(value || '').replace(/\D/g, '').slice(0, limit);
  const formatCpf = value => {
    const digits = onlyDigits(value);
    return digits
      .replace(/^(\d{3})(\d)/, '$1.$2')
      .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
      .replace(/\.(\d{3})(\d)/, '.$1-$2');
  };
  const maskCpf = cpf => `***.${formatCpf(cpf).slice(4, 11)}-**`;

  document.querySelectorAll('.cpf-input').forEach(input => {
    input.addEventListener('input', () => { input.value = formatCpf(input.value); });
  });

  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const contentType = response.headers.get('content-type') || '';
    const data = contentType.includes('application/json') ? await response.json() : null;
    if (!response.ok) {
      const detail = Array.isArray(data?.detail) ? 'Verifique os dados informados.' : data?.detail;
      const error = new Error(detail || 'Não foi possível concluir a operação.');
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function jsonRequest(method, body) {
    return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) };
  }

  /** Cliente da API dos canais: envia o token do cliente em todas as chamadas. */
  function channelClient() {
    let token = null;
    const request = (url, options = {}) => api(`/api/channel${url}`, {
      ...options,
      headers: { ...(options.headers || {}), ...(token ? { 'X-Channel-Token': token } : {}) }
    });
    return {
      setToken(value) { token = value; },
      hasToken() { return Boolean(token); },
      get: url => request(url),
      post: (url, body) => request(url, jsonRequest('POST', body)),
      upload: (url, form) => request(url, { method: 'POST', body: form }),
      remove: url => request(url, { method: 'DELETE' })
    };
  }

  function showAlert(element, message, kind = 'error') {
    element.textContent = message;
    element.classList.toggle('success', kind === 'success' || kind === true);
    element.classList.toggle('info', kind === 'info');
    element.classList.remove('hidden');
  }

  function hideAlert(element) { element?.classList.add('hidden'); }

  function toast(message, isError = false) {
    const region = document.getElementById('toast-region');
    const item = document.createElement('div');
    item.className = `toast${isError ? ' error' : ''}`;
    item.textContent = message;
    region.appendChild(item);
    setTimeout(() => item.remove(), 3800);
  }

  /** Cria elementos com texto seguro (sem innerHTML para dados). */
  function el(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    Object.entries(attributes || {}).forEach(([key, value]) => {
      if (value === undefined || value === null || value === false) return;
      if (key === 'class') node.className = value;
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
      else if (key === 'text') node.textContent = value;
      else node.setAttribute(key, value === true ? '' : value);
    });
    children.flat(Infinity).forEach(child => {
      if (child === undefined || child === null || child === false) return;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    });
    return node;
  }

  function friendly(value) {
    if (!value) return 'Não identificado';
    const text = String(value).replaceAll('_', ' ').toLowerCase();
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  const categoryLabel = value => byCategory[value]?.label || (value ? friendly(value) : 'Em análise');
  const departmentLabel = value => byDepartment[value]?.departmentLabel || (value ? friendly(value) : 'Em análise');
  const categoryArea = value => byCategory[value]?.area || 'help';
  const channelLabel = value => taxonomy.channels?.[value] || friendly(value);
  const statusLabel = value => taxonomy.statuses?.[value] || friendly(value);
  const priorityLabel = value => taxonomy.priorities?.[value] || friendly(value);
  const interactionTypeLabel = value => taxonomy.interactionTypes?.[value] || friendly(value);

  const tz = 'America/Sao_Paulo';
  // "2026-09-17" é uma data civil: parseada como UTC, ela voltaria um dia no fuso local.
  const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
  function asDate(value) {
    const parts = DATE_ONLY.exec(String(value));
    return parts ? new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3])) : new Date(value);
  }
  function brDate(value) {
    if (!value) return '—';
    return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: tz }).format(asDate(value));
  }
  function brTime(value) {
    if (!value) return '—';
    return new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: tz }).format(asDate(value));
  }
  function brDay(value) {
    if (!value) return '—';
    const parts = DATE_ONLY.exec(String(value));
    if (parts) return `${parts[3]}/${parts[2]}`;
    return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', timeZone: tz }).format(new Date(value));
  }
  function isoDay(value) {
    if (DATE_ONLY.test(String(value))) return String(value);
    return new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: tz }).format(new Date(value));
  }

  function currency(value) {
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(value));
  }

  function formatEntity(key, value) {
    if (typeof value === 'boolean') return value ? 'Sim' : 'Não';
    if (/valor|preco|preço|cobranca|cobrança/i.test(key) && !Number.isNaN(Number(value))) return currency(value);
    if (Array.isArray(value)) return value.join(', ');
    if (typeof value === 'object' && value !== null) return JSON.stringify(value);
    return String(value);
  }

  function initials(name) { return String(name || '').split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase(); }
  const firstName = name => String(name || '').split(/\s+/)[0] || '';

  const store = {
    get(key) { try { return sessionStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { sessionStorage.setItem(key, value); } catch { /* armazenamento indisponível */ } },
    remove(key) { try { sessionStorage.removeItem(key); } catch { /* armazenamento indisponível */ } }
  };

  const params = new URLSearchParams(location.search);

  window.ClaroOne = {
    taxonomy, categories, api, jsonRequest, channelClient, showAlert, hideAlert, toast, el, friendly,
    categoryLabel, departmentLabel, categoryArea, channelLabel, statusLabel, priorityLabel, interactionTypeLabel,
    brDate, brTime, brDay, isoDay, currency, formatEntity, formatCpf, maskCpf, onlyDigits, initials, firstName,
    store, params
  };
})();
