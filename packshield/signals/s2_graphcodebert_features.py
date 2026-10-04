"""Build GraphCodeBERT code and data-flow features for MalwareBench S2.

The DFG extraction and graph layout follow Microsoft's GraphCodeBERT
codesearch preprocessing. Package contents are read as inert text; no sample
code is imported or executed.
"""

from __future__ import annotations

import ast

from packshield.signals.s2_graphcodebert_parser import (
    DFG_javascript,
    DFG_python,
    index_to_code_token,
    remove_comments_and_docstrings,
    tree_to_token_index,
)


DFG_FUNCTIONS = {"python": DFG_python, "javascript": DFG_javascript}


def extract_code_dfg(source: str, language: str, parser) -> tuple[list[str], list[tuple]]:
    """Use GraphCodeBERT's Tree-sitter token indexing and language DFG routine."""
    if language == "python":
        # The upstream helper uses Python's tokenizer to remove comments and
        # docstrings. Validate independently with stdlib ast before DFG parsing.
        ast.parse(source)
    else:
        # Reuse S3's existing Esprima syntax-validation path, then let the
        # GraphCodeBERT Tree-sitter grammar produce the DFG-compatible tokens.
        import esprima
        try:
            esprima.parseScript(source, options={"tolerant": True})
        except Exception:
            esprima.parseModule(source, options={"tolerant": True})
    source = remove_comments_and_docstrings(source, language)
    tree = parser.parse(source.encode("utf-8", errors="replace"))
    root = tree.root_node
    token_spans = tree_to_token_index(root)
    lines = source.split("\n")
    tokens = [index_to_code_token(span, lines) for span in token_spans]
    index_to_code = {span: (i, token) for i, (span, token) in enumerate(zip(token_spans, tokens))}
    try:
        dfg, _ = DFG_FUNCTIONS[language](root, index_to_code, {})
    except Exception:
        dfg = []
    dfg = sorted(dfg, key=lambda item: item[1])
    referenced = {node[1] for node in dfg if node[-1]}
    referenced.update(index for node in dfg for index in node[-1])
    return tokens, [node for node in dfg if node[1] in referenced]


def graphcodebert_feature(code: str, language: str, parser, tokenizer,
                          code_length: int = 256, data_flow_length: int = 64) -> dict:
    """Return GraphCodeBERT's serialized input_ids/position/DFG alignment."""
    tokens, dfg = extract_code_dfg(code, language, parser)
    split_tokens = [
        tokenizer.tokenize(token) if index == 0 else tokenizer.tokenize("@ " + token)[1:]
        for index, token in enumerate(tokens)
    ]
    original_to_subtoken = {}
    offset = 0
    for index, subtokens in enumerate(split_tokens):
        original_to_subtoken[index] = (offset, offset + len(subtokens))
        offset += len(subtokens)
    code_tokens = [piece for group in split_tokens for piece in group]
    max_code_tokens = code_length + data_flow_length - 2 - min(len(dfg), data_flow_length)
    code_tokens = code_tokens[:max_code_tokens]
    source_tokens = [tokenizer.cls_token, *code_tokens, tokenizer.sep_token]
    input_ids = tokenizer.convert_tokens_to_ids(source_tokens)
    position_idx = [i + tokenizer.pad_token_id + 1 for i in range(len(source_tokens))]
    dfg = dfg[:code_length + data_flow_length - len(source_tokens)]
    source_tokens.extend(node[0] for node in dfg)
    input_ids.extend([tokenizer.unk_token_id] * len(dfg))
    position_idx.extend([0] * len(dfg))
    pad = code_length + data_flow_length - len(input_ids)
    input_ids.extend([tokenizer.pad_token_id] * pad)
    position_idx.extend([tokenizer.pad_token_id] * pad)
    reverse = {node[1]: i for i, node in enumerate(dfg)}
    dfg_to_dfg = [[reverse[i] for i in node[-1] if i in reverse] for node in dfg]
    dfg_to_code = []
    for node in dfg:
        start, end = original_to_subtoken.get(node[1], (0, 0))
        dfg_to_code.append([start + 1, end + 1])
    return {
        "input_ids": input_ids,
        "position_idx": position_idx,
        "dfg_to_code": dfg_to_code,
        "dfg_to_dfg": dfg_to_dfg,
        "code_length": code_length,
        "data_flow_length": data_flow_length,
        "language": language,
    }


def build_source_feature(row: dict, relative_file: str, source: bytes,
                         parser_by_language: dict, tokenizer,
                         code_length: int, data_flow_length: int) -> dict:
    language = "python" if row["ecosystem"] == "pypi" else "javascript"
    try:
        code = source.decode("utf-8", errors="replace")
        feature = graphcodebert_feature(code, language, parser_by_language[language],
                                        tokenizer, code_length, data_flow_length)
        feature.update({"group_id": row["group_id"], "label": row["label"],
                        "ecosystem": row["ecosystem"], "relative_file": relative_file,
                        "status": "ok"})
    except Exception as exc:
        feature = {"group_id": row["group_id"], "label": row["label"],
                   "ecosystem": row["ecosystem"], "relative_file": relative_file,
                   "language": language, "status": "parse_error",
                   "error": f"{type(exc).__name__}: {exc}"}
    return feature


