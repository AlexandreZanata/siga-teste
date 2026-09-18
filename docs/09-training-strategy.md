# 09 — Training strategy: baseline → LoRA → subnetworks, com curvas

> Formato e comandos Needle em `docs/00 §1.5`; dados em `docs/07`/`docs/08`; bench em `docs/10`. Decisões em ADR resumido.

## ADR-017 — Progressão científica com gates de escala, sem salto p/ 10k

- **Decision:** treinar e avaliar em 100 → 500 → 2k → 5k → 10k exemplos, publicando a cada degrau `dataset size × accuracy × latência × profundidade`; só subir de degrau com análise de erros escrita.
- **Reason:** regra oficial (`docs/00 §1.5`): seleção move com centenas, grounding exige milhares; escalar sem diagnóstico queima budget e mascara overfit.
- **Alternatives:** gerar 10k+ de uma vez; treinar até loss zerar.
- **Advantages:** encontra o menor dataset que mostra benefício (pergunta 9 do plano); cada degrau é um ponto de go/no-go.
- **Disadvantages:** mais ciclos de treino+eval.
- **Risks:** overfit mascarado por bench contaminado — bloqueado pelo isolamento (`docs/10`).
- **Validate:** curvas publicadas em `experiments/` com `experiment_id` (P07).

## 1. Protocolo por degrau

Baseline Needle base (sem LoRA, `docs/03`) → LoRA rank 16 (defaults: batch 16, lr 1e-4 warmup+cosine, clip 1.0, alpha 32, max-len 1024, val-split 0.1, 10–30 épocas em datasets pequenos) → eval no holdout → export `.cact` (`needle build`) → subnetworks 20→…→2 (`--layers N`). Se acerta tool e erra valor: mais dados/variação + `reasoning`, depois rank 32. Leitura de loss pela tendência (início ~1.0 é normal); val-loss subindo = parar ou adicionar dados.

## 2. O que o fine-tune não muda (e o plano assume)

`confidence=None` em tuned → roteamento por verifier próprio (ADR-005 L2); tokenizer fragmenta PT-BR ~1.7× → budget medido em PT-BR; bits locais 4-bit; `.cact` amarrado à engine pinada no lockfile. Nada disso é descoberto na hora — está precificado desde P00.
