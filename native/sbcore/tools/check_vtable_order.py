#!/usr/bin/env python3
"""Fail the build unless the sbcore UE4SS shim has the runtime's virtual layout.

Compares `class CppUserModBase` in the shim against the pinned header of the
UE4SS build the game loads (RE-UE4SS d3d10044d1) and, optionally, against the
slot table read out of that UE4SS.dll (ue4ss/runtime_vtable_d3d10044d1.txt,
written by tools/probe_ue4ss_vtable.py).

Checks, all must hold:
  1. the virtual declarations appear in the same order with the same names
     and the same parameter types (aliases normalised, parameter names and
     default values ignored);
  2. the data members appear in the same order with the same types;
  3. the MSVC slot order computed from the shim equals the runtime table.
     MSVC places the destructor and each overload group at the position of
     the group's first declaration and orders overloads inside a group in
     reverse declaration order; the live UE4SS.dll confirms this for
     on_lua_start / on_lua_stop.

Exit 0 = identical, 1 = layout differs (the build must fail), 2 = parse error.
Pure standard library, no third-party modules.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TYPE_ALIASES = {
    "StringViewType": "wstring_view",
    "RC::StringViewType": "wstring_view",
    "std::wstring_view": "wstring_view",
    "std::basic_string_view<wchar_t>": "wstring_view",
    "StringType": "wstring",
    "RC::StringType": "wstring",
    "std::wstring": "wstring",
    "std::basic_string<wchar_t>": "wstring",
    "LuaMadeSimple::Lua&": "Lua&",
    "RC::LuaMadeSimple::Lua&": "Lua&",
    "std::vector<LuaMadeSimple::Lua*>&": "vector<Lua*>&",
    "std::vector<RC::LuaMadeSimple::Lua*>&": "vector<Lua*>&",
    "std::vector<std::shared_ptr<GUI::GUITab>>": "vector<shared_ptr<GUITab>>",
    "std::vector<std::shared_ptr<RC::GUI::GUITab>>": "vector<shared_ptr<GUITab>>",
}


class ParseError(Exception):
    pass


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def strip_preprocessor(text: str) -> str:
    # Conditional blocks inside the class would make the parse ambiguous; the
    # shim keeps every #if outside the class body, so only drop directive lines.
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def class_body(text: str, name: str) -> str:
    match = re.search(r"\bclass\s+(?:\w+\s+)?" + name + r"\b[^;{]*\{", text)
    if not match:
        raise ParseError(f"class {name} not found")
    depth = 0
    start = match.end() - 1
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    raise ParseError(f"class {name} body is not closed")


def top_level_statements(body: str) -> list[str]:
    """Split a class body into member statements, dropping inline bodies."""
    statements: list[str] = []
    current: list[str] = []
    depth_brace = depth_paren = 0
    index = 0
    while index < len(body):
        char = body[index]
        if char == "(":
            depth_paren += 1
        elif char == ")":
            depth_paren -= 1
        if char == "{" and depth_paren == 0:
            # Either an inline function body or a brace initialiser: keep the
            # text before it, skip the balanced block.
            is_initialiser = bool(re.search(r"[\w>\]]\s*$", "".join(current))) and "(" not in "".join(current)
            depth_brace = 1
            index += 1
            while index < len(body) and depth_brace:
                if body[index] == "{":
                    depth_brace += 1
                elif body[index] == "}":
                    depth_brace -= 1
                index += 1
            if is_initialiser:
                continue  # `Type name{}` - the statement ends at the next ';'
            statements.append("".join(current))
            current = []
            # swallow an optional ';' after an inline body (`{};`)
            while index < len(body) and body[index] in " \t\r\n":
                index += 1
            if index < len(body) and body[index] == ";":
                index += 1
            continue
        if char == ";" and depth_paren == 0:
            statements.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    return [" ".join(statement.split()) for statement in statements if statement.strip()]


def split_params(params: str) -> list[str]:
    parts, depth, current = [], 0, []
    for char in params:
        if char in "<(":
            depth += 1
        elif char in ">)":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if "".join(current).strip():
        parts.append("".join(current))
    return [part.strip() for part in parts]


def normalise_type(text: str) -> str:
    text = text.split("=")[0].strip()          # default argument
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([&*<>,:])\s*", r"\1", text)
    text = text.replace("> >", ">>")
    text = re.sub(r"^const ", "const ", text)
    return TYPE_ALIASES.get(text, text)


def param_type(param: str) -> str:
    param = param.split("=")[0].strip()
    match = re.match(r"^(.*?[\w>&*\]])\s+([A-Za-z_]\w*)$", param)
    if match and match.group(1).strip() not in ("", "const", "unsigned", "signed"):
        param = match.group(1)
    return normalise_type(param)


def parse_class(path: Path) -> tuple[list[str], list[str]]:
    text = strip_preprocessor(strip_comments(path.read_text(encoding="utf-8")))
    body = class_body(text, "CppUserModBase")
    body = re.sub(r"\b(public|protected|private)\s*:", ";", body)
    virtuals: list[str] = []
    members: list[str] = []
    for statement in top_level_statements(body):
        statement = re.sub(r"(\bRC_UE4SS_API\b|\bSBCORE_SHIM_IMPORT\b|__declspec\s*\(\s*\w+\s*\))\s*",
                           "", statement).strip()
        if not statement:
            continue
        if re.match(r"^virtual\b", statement):
            decl = statement[len("virtual"):].strip()
            if re.match(r"^~\s*CppUserModBase\s*\(", decl):
                virtuals.append("~CppUserModBase()")
                continue
            match = re.match(r"^(?:auto\s+)?(?:[\w:<>,*&\s]+?\s+)?([A-Za-z_]\w*)\s*\((.*)\)", decl)
            if not match:
                raise ParseError(f"{path}: cannot parse virtual declaration: {statement}")
            name = match.group(1)
            params_text = match.group(2)
            # `auto f(args) -> void` : cut at the matching ')'
            depth = 0
            for index, char in enumerate(decl):
                if char == "(":
                    depth += 1
                    if depth == 1:
                        open_index = index
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        params_text = decl[open_index + 1:index]
                        break
            params = [param_type(p) for p in split_params(params_text)]
            params = [p for p in params if p != "void"]
            virtuals.append(f"{name}({','.join(params)})")
            continue
        if "(" in statement or statement.startswith(("using ", "friend ", "static ", "typedef ")):
            continue  # non-virtual functions, constructors, aliases
        match = re.match(r"^(.*?[\w>&*])\s+([A-Za-z_]\w*)\s*(?:\{\})?$", statement)
        if match:
            members.append(f"{normalise_type(match.group(1))} {match.group(2)}")
    if not virtuals:
        raise ParseError(f"{path}: no virtual members found")
    return virtuals, members


def msvc_slot_order(virtuals: list[str]) -> list[str]:
    groups: list[list[str]] = []
    positions: dict[str, int] = {}
    for signature in virtuals:
        name = signature.split("(")[0]
        if name in positions:
            groups[positions[name]].insert(0, signature)  # reverse declaration order
        else:
            positions[name] = len(groups)
            groups.append([signature])
    return [signature for group in groups for signature in group]


def read_table(path: Path) -> list[str]:
    rows = []
    for line in path.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        number, signature = line.split(None, 1)
        if int(number) != len(rows):
            raise ParseError(f"{path}: slot {number} out of order")
        rows.append(signature)
    return rows


def diff(label: str, expected: list[str], actual: list[str], names: tuple[str, str]) -> bool:
    if expected == actual:
        return True
    print(f"MISMATCH {label}")
    for index in range(max(len(expected), len(actual))):
        a = expected[index] if index < len(expected) else "-"
        b = actual[index] if index < len(actual) else "-"
        print(f"  [{index:2d}] {names[0]}={a:<60} {names[1]}={b}{'' if a == b else '   <--'}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shim", required=True, type=Path)
    parser.add_argument("--runtime-header", required=True, type=Path)
    parser.add_argument("--runtime-table", type=Path)
    parser.add_argument("--stamp", type=Path)
    args = parser.parse_args()
    try:
        shim_virtuals, shim_members = parse_class(args.shim)
        runtime_virtuals, runtime_members = parse_class(args.runtime_header)
        table = read_table(args.runtime_table) if args.runtime_table else None
    except (OSError, ParseError, ValueError) as error:
        print(f"PARSE ERROR: {error}")
        return 2
    ok = diff("virtual declaration order (shim vs runtime header)",
              runtime_virtuals, shim_virtuals, ("runtime", "shim"))
    ok = diff("data members (shim vs runtime header)",
              runtime_members, shim_members, ("runtime", "shim")) and ok
    slots = msvc_slot_order(shim_virtuals)
    if table is not None:
        ok = diff("MSVC slot order (shim vs slot table read from UE4SS.dll)",
                  table, slots, ("binary", "shim")) and ok
    if not ok:
        print(f"FAIL: {args.shim} does not match {args.runtime_header}"
              + (f" / {args.runtime_table}" if table is not None else ""))
        return 1
    print(f"OK: {len(shim_virtuals)} virtual declarations, {len(slots)} slots, "
          f"{len(shim_members)} data members match")
    for number, signature in enumerate(slots):
        print(f"  slot {number:2d} +0x{8 * number:02X} {signature}")
    if args.stamp:
        args.stamp.parent.mkdir(parents=True, exist_ok=True)
        args.stamp.write_text("\n".join(slots) + "\n", encoding="ascii")
    return 0


if __name__ == "__main__":
    sys.exit(main())
