# Claro One

Protótipo acadêmico de continuidade de contexto entre Telefone/URA, WhatsApp, Minha Claro e o Cockpit interno. Os dados e canais são simulados.

## O problema

O cliente entra em contato por um canal, muda para outro e precisa repetir a triagem — às vezes com outro atendente. A Cápsula de Contexto Efêmera (CCE) mantém o contexto do protocolo e permite que cada canal o use da forma mais adequada.

## Arquitetura

- FastAPI, Jinja2, HTML/CSS/JavaScript e SQLite.
- **Protocolo** (um atendimento sobre um tema) → **contatos** (cada passagem por um canal) → **CCE** (contexto consolidado do protocolo).
- GroqCloud em duas etapas separadas: áudio → texto com `whisper-large-v3-turbo`; texto → case com `openai/gpt-oss-20b`, em JSON Schema estrito validado por Pydantic.
- Taxonomia centralizada: Internet, Telefonia, Fatura e pagamentos, TV, Planos, Instalação, Cancelamento e Outros, cada uma com um departamento de destino.
- A IA trabalha apenas no backend. Nenhuma resposta ao cliente é texto livre do modelo.
- Não há modelos executados localmente. O uso das IAs exige internet e uma chave da Groq.

## Instalação no Windows

Para clonar o projeto:

```powershell
git clone https://github.com/alencasz/ClaroOne.git
cd ClaroOne
```

Depois:

1. Execute `INSTALAR.bat` uma vez.
2. Crie uma chave em <https://console.groq.com/keys>.
3. No arquivo `.env`, cole a chave após `GROQ_API_KEY=`.
4. Execute `INICIAR_CLARO_ONE.bat` nos usos seguintes.
5. Acesse <http://127.0.0.1:8000>.

O `.env` não é versionado. A chave fica somente no backend.
`DEMO_FALLBACK` permanece `false` por padrão; quando ativado manualmente, o modo simulado fica visível na interface.

## Roteiro de demonstração

**Retorno (cliente com contexto):** no Telefone, digite o protocolo `123` e o CPF `123.456.789-00`. A URA envia um código por SMS — no modo simulado ele aparece como notificação na própria tela. Confirmado o código, digite `1` para continuar o atendimento ou `2` para tratar de outro tema. O mesmo caminho existe no WhatsApp; no Minha Claro o login já autentica e o SMS não é pedido.

**Primeiro contato:** use o CPF `987.654.321-00` sem protocolo. No Telefone, escolha o assunto na URA e grave pelo microfone (ou envie um arquivo da pasta `Audios`); no WhatsApp e no Minha Claro, descreva o pedido em texto.

**Cockpit:** busque por CPF, protocolo, departamento ou canal. A timeline mostra os canais navegados, com data, protocolo, atendente e o resumo do que foi tratado em cada canal; clicar em um contato troca o snapshot para aquele momento. O resumo executivo consolida a vivência do CPF. A aba **Visão do gestor** traz os indicadores de funcionamento da solução.

A Home e o Debug reiniciam a demonstração. O reinício recria o histórico fictício; "Limpar dados" deixa a base vazia.

## Segurança e privacidade

- Verificação por SMS na retomada em Telefone e WhatsApp: código de 6 dígitos guardado apenas como hash, com validade, limite de tentativas e de reenvios. O canal só recebe dados do protocolo depois da verificação, e ainda assim uma projeção reduzida (sem CPF, transcrição ou campos internos).
- Minimização de dados: CPF, CNPJ, cartão, telefone, e-mail, senha, código de verificação e dados bancários são mascarados antes de qualquer envio às IAs e antes de serem gravados. A saída da IA passa pelo mesmo filtro, e entidades com chaves sensíveis são descartadas.
- Prompt injection: o texto do cliente é delimitado por tags, o prompt instrui a ignorar instruções contidas nele, a saída é restrita por JSON Schema estrito e nenhum texto livre do modelo chega ao cliente.
- A gravação de áudio é apagada assim que a transcrição é armazenada.

## Uso e testes

Para executar a suíte:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Envio real de SMS é opcional e exige conta própria: defina `SMS_PROVIDER=twilio` com `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` e `SMS_TEST_DESTINATION` no `.env`. Sem isso, o modo simulado (sem custo) exibe o código na tela.

## Limites do protótipo

Não há telefonia, WhatsApp, CRM, billing ou autenticação reais. O navegador precisa autorizar o microfone, e o uso da Groq está sujeito à conectividade, aos limites e custos da conta. A estimativa de tempo de triagem poupado na visão do gestor usa uma premissa configurável (`TRIAGE_MINUTES_ESTIMATE`). Em produção, seriam necessários gestão segura de segredos, autenticação corporativa, observabilidade, armazenamento apropriado, integrações oficiais e políticas de privacidade e retenção.
