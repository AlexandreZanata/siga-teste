"""Adapter de inferência neural real do Needle 3 (P13-T03, docs/21 §7, docs/22 §6–§7).

Fronteira de verdade (docs/21 §1): este módulo fala apenas com o engine oficial
`cactus-needle` e com pesos reais (`.cact`/`.safetensors`). O simulador
`evaluation.NeedleTunedModel` é estritamente proibido como evidência neural.

Perfil corrigido pelo P13-T03 (docs/24 §3.4):

- B1 usa `Needle.complete()` **uma única geração** por tarefa e nunca executa
  tools; `Needle.run(max_steps=8)` com schemas sem callables é o bug antigo
  (loop de `unknown tool`) e não é usado aqui;
- B2 usa `Needle.run()` somente com callables Python reais registrados pelo
  runner (as cinco tools do projeto);
- argumentos são validados contra o JSON Schema **completo** do tool (required,
  type incluindo `null`, enum, additionalProperties, items, minimum/maximum);
- toda geração tem timeout por tarefa; o envelope bruto é preservado no
  checkpoint para auditoria e o record normalizado alimenta o scorer.

Este módulo não importa `tools/`, `graph/`, `retrieval/` nem `context/`
(fronteira de `inference/`, AGENTS.md §2).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import signal
import threading
import time
from typing import Any, Iterator


class TaskTimeout(RuntimeError):
    """Timeout por tarefa: aborto honesto, nunca resultado fabricado."""


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True  # keyword desconhecida: validação determinística ignora


def validate_arguments(parameters: dict[str, Any], arguments: Any) -> list[str]:
    """Valida `arguments` contra JSON Schema (subset determinístico, só stdlib).

    Cobre o contrato dos cinco tools (docs/22 §6): `type` (inclusive listas com
    `null`), `enum`, `required`, `properties`, `additionalProperties` (bool ou
    schema), `items`, `minItems`, `maxItems`, `minimum`, `maximum`, `minLength`
    e `maxLength`. Keywords desconhecidas são ignoradas. Retorna lista de erros
    legíveis (vazia = válido), nunca lança.
    """
    errors: list[str] = []

    def walk(schema: Any, value: Any, path: str) -> None:
        if not isinstance(schema, dict):
            return
        expected = schema.get("type")
        if expected is not None:
            kinds = expected if isinstance(expected, list) else [expected]
            if not any(_type_ok(value, kind) for kind in kinds):
                errors.append(f"{path}: tipo incompatível com {expected!r}")
                return
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path}: valor fora do enum {schema['enum']!r}")
        if isinstance(value, dict):
            properties = schema.get("properties") or {}
            for required in schema.get("required") or []:
                if required not in value:
                    errors.append(f"{path}: campo obrigatório {required!r} ausente")
            extra = schema.get("additionalProperties", True)
            for key, item in value.items():
                if key in properties:
                    walk(properties[key], item, f"{path}.{key}")
                elif extra is False:
                    errors.append(f"{path}: propriedade extra {key!r}")
                elif isinstance(extra, dict):
                    walk(extra, item, f"{path}.{key}")
        if isinstance(value, list):
            items = schema.get("items")
            if isinstance(items, dict):
                for index, item in enumerate(value):
                    walk(items, item, f"{path}[{index}]")
            if "minItems" in schema and len(value) < schema["minItems"]:
                errors.append(f"{path}: minItems={schema['minItems']} não satisfeito")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                errors.append(f"{path}: maxItems={schema['maxItems']} excedido")
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                errors.append(f"{path}: minLength={schema['minLength']} não satisfeito")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                errors.append(f"{path}: maxLength={schema['maxLength']} excedido")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                errors.append(f"{path}: abaixo de minimum={schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                errors.append(f"{path}: acima de maximum={schema['maximum']}")

    walk(parameters, arguments, "$")
    return errors


@contextmanager
def _deadline(seconds: float) -> Iterator[None]:
    """Timeout real por tarefa via SIGALRM (thread principal, Linux).

    Em thread secundária o alarme não é aplicável; o chamador continua no
    modo cooperativo (o runner só executa no thread principal).
    """
    if seconds <= 0 or threading.current_thread() is not threading.main_thread():
        yield
        return

    def _on_alarm(signum: int, frame: Any) -> None:
        raise TaskTimeout(f"timeout de {seconds:.0f}s por tarefa excedido")

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)


class RealNeedleModel:
    """Pesos reais carregados no engine oficial, sem qualquer simulação."""

    def __init__(
        self,
        weights_path: str | Path,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        task_timeout_s: float = 120.0,
        needle_module: Any | None = None,
    ) -> None:
        self.weights_path = Path(weights_path).resolve()
        if not self.weights_path.is_file():
            raise FileNotFoundError(f"Pesos reais ausentes: {self.weights_path}")
        self.tools = list(tools or [])
        self.task_timeout_s = float(task_timeout_s)
        if needle_module is None:
            import needle as needle_module  # import tardio: só aqui o engine entra
        self._needle_module = needle_module
        self._engine = needle_module.Needle(
            weights=str(self.weights_path), tools=self.tools, system=system
        )
        self._schemas: dict[str, dict[str, Any]] = {}
        for tool in self.tools:
            schema = tool if isinstance(tool, dict) else getattr(tool, "_needle_tool", None)
            if isinstance(schema, dict) and "name" in schema:
                self._schemas[schema["name"]] = schema.get("parameters") or {}
        self.tool_names = frozenset(self._schemas)

    def close(self) -> None:
        close = getattr(self._engine, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "RealNeedleModel":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def complete_once(
        self,
        query: str,
        max_new_tokens: int = 128,
        escalate_to: int | None = 256,
    ) -> dict[str, Any]:
        """B1: exatamente uma geração (`Needle.complete`), sem executar tools.

        Truncamento medido (envelope ilegível) escala uma única vez para
        `escalate_to`; o record registra gerações gastas e o orçamento usado.
        Timeout por tarefa retorna record com `timeout=True` (nunca exceção).
        """
        budgets = [int(max_new_tokens)]
        if escalate_to:
            budgets.append(int(escalate_to))
        start = time.perf_counter()
        for index, budget in enumerate(budgets):
            generated = index + 1
            try:
                with _deadline(self.task_timeout_s):
                    raw = self._engine.complete(query, max_new_tokens=budget)
            except TaskTimeout as exc:
                return self._record(
                    raw=None,
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                    generations=generated,
                    max_new_tokens=budget,
                    timeout=True,
                    error=str(exc),
                )
            except Exception as exc:  # engine pode devolver envelope ilegível
                message = str(exc)
                if "unparseable envelope" in message and index + 1 < len(budgets):
                    continue  # truncamento medido: sobe o orçamento uma vez
                return self._record(
                    raw=None,
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                    generations=generated,
                    max_new_tokens=budget,
                    truncated="unparseable envelope" in message,
                    error=message,
                )
            truncated_response = self._is_truncated(raw)
            if truncated_response and index + 1 < len(budgets):
                continue  # engine reportou `error_code=truncated`: sobe uma vez
            return self._record(
                raw=raw,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                generations=generated,
                max_new_tokens=budget,
                truncated=truncated_response,
                escalated=index > 0,
            )
        raise AssertionError("loop de geração sem retorno")  # pragma: no cover

    @staticmethod
    def _is_truncated(raw: Any) -> bool:
        """Detecta truncamento explícito do engine (`error_code=truncated`)."""
        if not isinstance(raw, dict):
            return False
        if str(raw.get("error_code") or "").lower() == "truncated":
            return True
        return "truncat" in str(raw.get("error") or "").lower()

    def run_agent(
        self,
        query: str,
        max_steps: int = 3,
        max_new_tokens: int = 256,
    ) -> dict[str, Any]:
        """B2: `Needle.run()` com callables reais já registrados no engine.

        O runner registra as cinco tools reais (com schema curado) na
        construção; aqui só se executa o loop oficial modelo→tool→observação.
        """
        start = time.perf_counter()
        try:
            with _deadline(self.task_timeout_s):
                raw = self._engine.run(query, max_steps=max_steps, max_new_tokens=max_new_tokens)
        except TaskTimeout as exc:
            return self._record(
                raw=None,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                generations=0,
                max_new_tokens=max_new_tokens,
                timeout=True,
                error=str(exc),
            )
        except Exception as exc:
            return self._record(
                raw=None,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                generations=0,
                max_new_tokens=max_new_tokens,
                error=str(exc),
            )
        record = self._record(
            raw=raw,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            generations=len(raw.get("results") or []) + 1,
            max_new_tokens=max_new_tokens,
        )
        record["executed_calls"] = list(raw.get("results") or [])
        record["max_steps"] = int(max_steps)
        return record

    def _record(
        self,
        raw: dict[str, Any] | None,
        latency_ms: float,
        generations: int,
        max_new_tokens: int,
        timeout: bool = False,
        truncated: bool = False,
        escalated: bool = False,
        error: str | None = None,
    ) -> dict[str, Any]:
        raw = raw if isinstance(raw, dict) else {}
        response_type = raw.get("type")
        calls = raw.get("function_calls") or []
        if not isinstance(calls, list):
            calls = []
        primary = calls[0] if calls and isinstance(calls[0], dict) else None
        arguments = primary.get("arguments") if primary else None
        if not isinstance(arguments, dict):
            arguments = {}

        invalid_reasons: list[str] = []
        if timeout:
            invalid_reasons.append("timeout por tarefa")
        if truncated:
            invalid_reasons.append("resposta truncada (orçamento de tokens)")
        if response_type == "call":
            if not calls:
                invalid_reasons.append("type=call sem function_calls")
            for call in calls:
                if not isinstance(call, dict):
                    invalid_reasons.append("function_call não-objeto")
                    continue
                name = call.get("name")
                if name not in self._schemas:
                    invalid_reasons.append(f"tool desconhecida: {name!r}")
                    continue
                args = call.get("arguments")
                invalid_reasons.extend(
                    validate_arguments(self._schemas[name], args if isinstance(args, dict) else {})
                )
        engine_error = raw.get("error") or error
        if engine_error:
            invalid_reasons.append(f"engine: {engine_error}")

        validation = raw.get("validation") or {}
        suppressed = raw.get("suppressed_calls") or []
        return {
            "type": response_type,
            "success": raw.get("success"),
            "tool": primary.get("name") if primary else None,
            "arguments": arguments,
            "reasoning": raw.get("reasoning"),
            "confidence": raw.get("confidence"),
            "schema_valid": not invalid_reasons,
            "is_invalid_call": bool(invalid_reasons),
            "invalid_reasons": invalid_reasons,
            "grounding_violations": list(validation.get("ungrounded") or []),
            "suppressed_calls": len(suppressed) if isinstance(suppressed, list) else 0,
            "error": engine_error,
            "error_code": raw.get("error_code"),
            "timeout": timeout,
            "truncated": truncated,
            "escalated": escalated,
            "generations": int(generations),
            "max_new_tokens": int(max_new_tokens),
            "prefill_tps": float(raw.get("prefill_tps") or 0.0),
            "decode_tps": float(raw.get("decode_tps") or 0.0),
            "peak_ram_mb": float(raw.get("peak_ram_mb") or 0.0),
            "latency_ms": float(latency_ms),
            "raw": raw,
        }
