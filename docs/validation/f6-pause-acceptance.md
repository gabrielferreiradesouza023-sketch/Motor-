# Aceite humano F6: uma pausa

Só no host do humano, após F5 real e revisão das evidências. O agente cloud não executa
este kit contra a Meta. Não cria campanhas, anúncios nem orçamento. O humano cria
manualmente um anúncio **exclusivamente de teste**, registra sua entidade local e id real,
e mantém credenciais e versão validadas no próprio host. Não use anúncios de produção.

1. `arb accept register-test --meta-id <id> --database <banco>` em TTY: confirmar cadastro
   explícito. A flag se vincula ao id remoto atual; campanha/conjunto e id ambíguo recusados.
2. No host humano, com modo live deliberadamente configurado e confirmação interativa:
   `arb accept pause --meta-id <id> --database <banco> --out <novo-f6.json>`.
3. Revisar evidência redigida: GET antes, intenção no banco antes do POST, somente
   `status=PAUSED`, GET depois. Já pausado evita POST. JSON contém data/hash e sufixo.
4. Qualquer perda de resposta ou GET posterior não confirmado mantém intenção pendente.
   Execute `arb ops reconcile` no host humano; nunca repetir POST às cegas. O ledger
   interno contém ids completos necessários à auditoria, a evidência exportável não.

O kit recusa quarentena ou qualquer intenção pendente. A execução exige TTY e confirmação
mostrando o id completo. Os testes usam somente MockTransport e chave sintética.
A evidência SHA256 prova integridade, não substitui revisão humana nem assinatura de origem.
O arquivo de saída é exclusivo, privado e não sobrescreve aceite anterior.
