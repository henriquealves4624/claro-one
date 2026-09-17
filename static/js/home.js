(() => {
  const { api, toast, store } = ClaroOne;
  const healthList = document.getElementById('health-list');
  const guidance = document.getElementById('health-guidance');

  function setStatus(index, text, kind) {
    const badge = healthList.children[index].querySelector('b');
    badge.textContent = text;
    badge.className = `status-dot ${kind}`;
  }

  async function loadHealth() {
    try {
      const health = await api('/api/health');
      setStatus(0, health.backend === 'ok' ? 'Operacional' : 'Erro', health.backend === 'ok' ? 'ok' : 'error');
      setStatus(1, health.database === 'ok' ? 'Conectado' : 'Erro', health.database === 'ok' ? 'ok' : 'error');
      const groqReady = health.groq === 'ok';
      setStatus(2, groqReady ? 'Disponível' : health.groq === 'not_configured' ? 'Chave ausente' : 'Indisponível', groqReady ? 'ok' : 'warning');
      setStatus(3, groqReady ? 'Disponível' : health.groq === 'model_missing' ? 'Modelo ausente' : health.groq === 'authentication_error' ? 'Chave inválida' : 'Indisponível', groqReady ? 'ok' : 'warning');
      setStatus(4, health.sms_mode === 'REAL' ? 'Envio real' : 'Simulado', 'ok');
      if (!groqReady) {
        guidance.textContent = health.groq === 'not_configured'
          ? 'Configure GROQ_API_KEY no arquivo .env para habilitar o processamento.'
          : 'Groq indisponível. Verifique a chave, a internet e os modelos configurados.';
        guidance.classList.remove('hidden');
      } else guidance.classList.add('hidden');
    } catch (error) {
      [0, 1, 2, 3, 4].forEach(i => setStatus(i, 'Indisponível', 'error'));
    }
  }

  document.getElementById('refresh-health').addEventListener('click', loadHealth);
  document.getElementById('home-reset').addEventListener('click', async () => {
    if (!confirm('Reiniciar a demonstração? Os atendimentos criados serão removidos e o histórico fictício será recriado.')) return;
    try {
      await api('/api/demo/reset', { method: 'POST' });
      ['claroOneCpf', 'claroOneProtocol'].forEach(key => store.remove(key));
      toast('Demonstração reiniciada.');
      setTimeout(() => location.reload(), 600);
    } catch (error) { toast(error.message, true); }
  });
  loadHealth();
})();
