# 09 — Training strategy: baseline → LoRA → subnetworks, com curvas

> Formato e comandos Needle em `docs/00 §1.5`; dados em `docs/07`/`docs/08`; bench em `docs/10`. Decisões em ADR resumido.

## ADR-025 — Val-loss tracking determinístico para os próximos LoRAs (F15)

- **Decision:** cada treino de LoRA registra a curva real por época em `training/val_loss.py` (`ValLossTracker`: `{step, train_loss, val_loss, timestamp}` UTC validado) e recebe veredito determinístico de `analyze_curve`: tendência por regressão linear de mínimos quadrados sobre a **cauda** (padrão 5 pontos, ajustável), `overfit_gap` = val − train na cauda e veredito `continue`/`stop_overfitting`/`add_data` (val subindo → parar; platô com gap > 0.10 → adicionar dados; caso restante → continuar). O run é gravado via `experiments.log.new_run` (provenance completa: `siga_commit`, `sigateste_commit`, dataset/needle/depth, `artifact_hash`) em `experiments/runs/<id>.json`, e `experiments/reports/val_loss_tracking.json` agrega o histórico comparável entre LoRAs. Só stdlib; relógio injetável para reprodutibilidade.
- **Reason:** `docs/09` §1 fixa a regra ("início ~1.0 é normal; val-loss subindo = parar ou adicionar dados") e o ADR-017 exige go/no-go por degrau — mas até o F15 a leitura de val-loss era só narrativa (strings do P07), sem instrumento determinístico para os próximos treinos.
- **Alternatives:** TensorBoard/W&B — dependência externa nova contra o standard-first; ler só o valor absoluto do loss — ignora a regra do protocolo, que é de tendência; early stopping automático no trainer — não existe trainer no repo e esconderia a decisão humana.
- **Advantages:** veredito idêntico entre operadores e máquinas; decisão pela cauda, imune ao início alto; gap val−train explícito; histórico comparável entre runs sem gerenciar infra de tracking; provenance herda o schema já validado em 15+ runs.
- **Disadvantages:** regressão linear é aproximação (curvas muito não-monomótonas exigem janela menor); contador não substitui o julgamento humano do go/no-go do degrau (a decisão final segue sendo revisada).
- **Risks:** curta janela de observação com ruído pode pegar falsa subida — mitigado por `tail_points`/`slope_tolerance` configuráveis e por manter a curva inteira no run para reanálise offline; run sem curva é rejeitado no registro.
- **Validate:** testes cobrem queda→continue, subida sustentada→stop_overfitting (e U-curto com janela apertada), platô com gap alto→add_data, rejeição de curvas malformadas e run validado pelo `experiments/schema.json` com provenance completa.

## ADR-017 — Progressão científica com gates de escala, sem salto p/ 10k

- **Decision:** treinar e avaliar em 100 → 500 → 2k → 5k → 10k exemplos, publicando a cada degrau `dataset size × accuracy × latência × profundidade`; só subir de degrau com análise de erros escrita.
- **Reason:** regra oficial (`docs/00 §1.5`): seleção move com centenas, grounding exige milhares; escalar sem diagnóstico queima budget e mascara overfit.
- **Alternatives:** gerar 10k+ de uma vez; treinar até loss zerar.
- **Advantages:** encontra o menor dataset que mostra benefício (pergunta 9 do plano); cada degrau é um ponto de go/no-go.
- **Disadvantages:** mais ciclos de treino+eval.
- **Risks:** overfit mascarado por bench contaminado — bloqueado pelo isolamento (`docs/10`).
- **Validate:** curvas publicadas em `experiments/` com `experiment_id` (P07).

## 1. Protocolo por degrau

Baseline Needle base (sem LoRA, `docs/03`) → LoRA rank 16 (defaults: batch 16, lr 1e-4 warmup+cosine, clip 1.0, alpha 32, max-len 1024, val-split 0.1, 10–30 épocas em datasets pequenos) → eval no holdout → export `.cact` (`needle build`) → subnetworks 20→…→2 (`--layers N`). Se acerta tool e erra valor: mais dados/variação + `reasoning`, depois rank 32. Leitura de loss pela tendência (início ~1.0 é normal); val-loss subindo = parar ou adicionar dados — desde F15/ADR-025 com instrumento determinístico (`training/val_loss.py`): curva por época → veredito `continue`/`stop_overfitting`/`add_data` + run com provenance em `experiments/runs/`.

## 2. O que o fine-tune não muda (e o plano assume)

`confidence=None` em tuned → roteamento por verifier próprio (ADR-005 L2); tokenizer fragmenta PT-BR ~1.7× → budget medido em PT-BR; bits locais 4-bit; `.cact` amarrado à engine pinada no lockfile. Nada disso é descoberto na hora — está precificado desde P00.
