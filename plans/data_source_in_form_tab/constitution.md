# Paste-split YAML constitution

## 1. Principles

* **Sample is law**: `spec.md` §4 is the only schema; no legacy five-field list (`determiner/order/field/index/is_id` per array item).
* **YAML splits paste**: TSV → form is 100% YAML-driven; no YAML → no parse.
* **Phi-3.5 = vLLM**: local multimodal model fills YAML; not Excel; not a remote HTTP vLLM server name.
* **0-based index**: source columns start at 0; prompts and UI agree.
* **Paste mapping serves data entry**: one mapping semantics only.
* **Do not overwrite manual input** on split failure.

## 2. Technical constraints

* UI: Streamlit; model: OpenVINO + `app/vllm/`.
* Paths: `pathlib.Path`.
* Comments: English in code prompts for Phi-3.5; plan docs in English.
* YAML key `filed` (typo) is intentional — match sample.

## 3. Prohibited

* Phi-3.5 outputting old `delimiter/fields/target` YAML.
* Mixing 0-based and 1-based `index`.
* Requiring fixed text (e.g. `pickup`) before date regex matches.
