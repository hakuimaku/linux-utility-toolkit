"""Search service implementing content search with ripgrep and name search with Python."""

import codecs
import fnmatch
import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lut.core.dependencies import require_executable
from lut.core.errors import (
    CancelledError,
    InputError,
    OutputError,
    ProcessError,
    UsageError,
)
from lut.core.process import _stop


@dataclass
class ContentMatch:
    """A single line match in a file."""

    line_number: int
    line: str
    submatches: list[tuple[int, int, str]]  # (byte_start, byte_end, text)


@dataclass
class FileMatches:
    """Matches found within a single file."""

    path: str
    matches: list[ContentMatch]


@dataclass
class NameMatch:
    """A file or directory found by name search."""

    path: str
    is_dir: bool


MAX_RECORD_CHARS = 10 * 1024 * 1024  # 10 MiB record character limit (TextIOWrapper code points)
MAX_STDERR_BYTES = 64 * 1024  # 64 KiB stderr retention limit


def _format_relative(target_path: str | Path, base_dir: Path | None = None) -> str:
    """Format path relative to current working directory, prefixed with ./ if local."""
    target = Path(target_path)
    cwd = Path.cwd().resolve() if base_dir is None else Path(base_dir).resolve()
    resolved = target.resolve()
    try:
        rel = resolved.relative_to(cwd)
        return f"./{rel}" if str(rel) != "." else "."
    except ValueError:
        return str(target)


def _truncate_and_highlight(
    line: str,
    submatches: Sequence[tuple[int, int, str]],
    is_tty: bool,
    max_length: int = 200,
) -> str:
    """Format and optionally highlight a matching line with bounded length."""
    # Strip trailing newline
    content = line.rstrip("\r\n")

    # If line is within limit
    if len(content) <= max_length:
        display = content
    else:
        # Find position of first match
        first_match_text = submatches[0][2] if submatches else ""
        first_idx = content.find(first_match_text) if first_match_text else -1
        if first_idx == -1 or first_idx < 140:
            display = content[:max_length] + "..."
        else:
            start = max(0, first_idx - 60)
            end = min(len(content), start + max_length)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(content) else ""
            display = prefix + content[start:end] + suffix

    if not is_tty or not submatches:
        return display

    # Highlight matches using ANSI bold red: \033[1;31m ... \033[0m
    unique_matches = {m[2] for m in submatches if m[2]}
    for term in sorted(unique_matches, key=len, reverse=True):
        pattern = re.escape(term)
        display = re.sub(pattern, f"\033[1;31m{term}\033[0m", display)

    return display


def search_content(
    keyword: str,
    path: str | Path = ".",
    *,
    ignore_case: bool = False,
    extension: str | None = None,
    files_only: bool = False,
    count_only: bool = False,
    is_regex: bool = False,
    hidden: bool = False,
    no_ignore: bool = False,
    glob_pattern: str | None = None,
    max_depth: int | None = None,
    as_json: bool = False,
    stdout_stream=None,
) -> int:
    """Search file contents using ripgrep backend with bounded memory and streaming."""
    out = sys.stdout if stdout_stream is None else stdout_stream
    is_tty = hasattr(out, "isatty") and out.isatty()

    if max_depth is not None and max_depth < 0:
        raise UsageError("Max depth must be a nonnegative integer.")

    # Validate backend
    require_executable(
        "rg",
        packages={
            "arch": "ripgrep",
            "debian": "ripgrep",
            "ubuntu": "ripgrep",
            "fedora": "ripgrep",
        },
    )

    search_path = Path(path)
    if not search_path.exists():
        raise InputError(f"Search path does not exist: {search_path}")

    # Build ripgrep command
    command = ["rg"]

    if files_only:
        command.extend(["-l", "--null"])
    else:
        command.append("--json")

    if not is_regex:
        command.append("-F")

    if ignore_case:
        command.append("-i")

    if extension:
        ext = extension.lstrip(".")
        command.extend(["-g", f"*.{ext}"])

    if glob_pattern:
        command.extend(["-g", glob_pattern])

    if hidden:
        command.append("--hidden")

    if no_ignore:
        command.append("--no-ignore")

    if max_depth is not None:
        command.extend(["--max-depth", str(max_depth)])

    command.extend(["--", keyword, str(search_path)])

    # Stream ripgrep execution
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as err:
        raise OutputError(f"Cannot execute search backend: {err}") from None

    # Track results using bounded spool file to avoid large memory consumption
    spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+", encoding="utf-8")
    stderr_lines: list[str] = []
    total_stderr_bytes = 0
    stderr_truncated = False
    total_matches = 0
    total_files = 0
    current_file = None
    current_file_matches = 0
    first_file_json = True
    null_buffer = ""
    utf8_decoder = codecs.getincrementaldecoder("utf-8")("replace")

    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")

            while selector.get_map():
                for key, _ in selector.select(0.1):
                    stream = key.data

                    if stream == "stderr":
                        line = key.fileobj.readline(65536)
                        if not line:
                            selector.unregister(key.fileobj)
                            continue
                        if total_stderr_bytes < MAX_STDERR_BYTES:
                            remaining = MAX_STDERR_BYTES - total_stderr_bytes
                            chunk = line[:remaining]
                            stderr_lines.append(chunk)
                            total_stderr_bytes += len(chunk.encode("utf-8", errors="replace"))
                            if total_stderr_bytes >= MAX_STDERR_BYTES:
                                stderr_truncated = True
                        continue

                    # stdout processing
                    if files_only:
                        if hasattr(key.fileobj, "buffer") and hasattr(key.fileobj.buffer, "read1"):
                            raw = key.fileobj.buffer.read1(65536)
                        elif hasattr(key.fileobj, "read1"):
                            raw = key.fileobj.read1(65536)
                        elif hasattr(key.fileobj, "fileno"):
                            try:
                                raw = os.read(key.fileobj.fileno(), 65536)
                            except OSError:
                                raw = b""
                        else:
                            raw = key.fileobj.read(65536)

                        if not raw:
                            selector.unregister(key.fileobj)
                            final_text = (
                                utf8_decoder.decode(b"", final=True)
                                if isinstance(raw, bytes)
                                else ""
                            )
                            if final_text:
                                null_buffer += final_text
                            if null_buffer:
                                formatted_path = _format_relative(null_buffer)
                                if as_json:
                                    if not first_file_json:
                                        spool.write(",\n")
                                    spool.write(f"    {json.dumps(formatted_path)}")
                                    first_file_json = False
                                else:
                                    spool.write(f"{formatted_path}\n")
                                total_files += 1
                                null_buffer = ""
                            continue

                        chunk = (
                            utf8_decoder.decode(raw, final=False) if isinstance(raw, bytes) else raw
                        )
                        null_buffer += chunk
                        parts = null_buffer.split("\0")
                        null_buffer = parts.pop()
                        for raw_path in parts:
                            if not raw_path:
                                continue
                            formatted_path = _format_relative(raw_path)
                            if as_json:
                                if not first_file_json:
                                    spool.write(",\n")
                                spool.write(f"    {json.dumps(formatted_path)}")
                                first_file_json = False
                            else:
                                spool.write(f"{formatted_path}\n")
                            total_files += 1
                        continue

                    # Non-files-only: read json record with MAX_RECORD_CHARS bound
                    line = key.fileobj.readline(MAX_RECORD_CHARS + 1)
                    if not line:
                        selector.unregister(key.fileobj)
                        continue

                    if len(line) > MAX_RECORD_CHARS and not line.endswith("\n"):
                        _stop(process)
                        spool.close()
                        limit_desc = (
                            f"{MAX_RECORD_CHARS // (1024 * 1024)} MiB"
                            if MAX_RECORD_CHARS >= 1024 * 1024
                            else f"{MAX_RECORD_CHARS} characters"
                        )
                        raise ProcessError(
                            f"Search record in '{current_file or search_path}' "
                            f"exceeded maximum supported size ({limit_desc})."
                        )

                    clean_line = line.strip()
                    if not clean_line:
                        continue

                    try:
                        record = json.loads(clean_line)
                    except json.JSONDecodeError as err:
                        _stop(process)
                        spool.close()
                        raise ProcessError(
                            f"Failed to parse backend search output: {err}"
                        ) from None

                    rec_type = record.get("type")
                    data = record.get("data", {})

                    if rec_type == "begin":
                        raw_path = data.get("path", {}).get("text", "")
                        current_file = _format_relative(raw_path)
                        current_file_matches = 0
                        if not as_json:
                            spool.write(f"\n{current_file}\n")

                    elif rec_type == "match":
                        total_matches += 1
                        line_num = data.get("line_number", 0)
                        lines_text = data.get("lines", {}).get("text", "")
                        submatches = [
                            (
                                sm.get("start", 0),
                                sm.get("end", 0),
                                sm.get("match", {}).get("text", ""),
                            )
                            for sm in data.get("submatches", [])
                        ]

                        if current_file_matches == 0:
                            total_files += 1
                            if as_json:
                                if not first_file_json:
                                    spool.write(",\n")
                                spool.write(
                                    f"    {{\n"
                                    f'      "path": {json.dumps(current_file)},\n'
                                    f'      "matches": [\n'
                                )
                                first_file_json = False
                        else:
                            if as_json:
                                spool.write(",\n")

                        if as_json:
                            match_dict = {
                                "line_number": line_num,
                                "line": lines_text.rstrip("\r\n"),
                                "submatches": [sm[2] for sm in submatches],
                            }
                            spool.write(f"        {json.dumps(match_dict)}")
                        else:
                            formatted_line = _truncate_and_highlight(lines_text, submatches, is_tty)
                            spool.write(f"  {line_num}: {formatted_line}\n")

                        current_file_matches += 1

                    elif rec_type == "end":
                        if as_json and current_file_matches > 0:
                            spool.write("\n      ]\n    }")

        process.wait()
    except KeyboardInterrupt:
        _stop(process)
        spool.close()
        raise CancelledError("Operation cancelled.") from None
    except BrokenPipeError:
        _stop(process)
        spool.close()
        raise
    except BaseException:
        _stop(process)
        spool.close()
        raise

    returncode = process.returncode
    stderr_content = "".join(stderr_lines).strip()
    if stderr_truncated:
        stderr_content += "\n... [stderr truncated]"

    if returncode == 2:
        spool.close()
        if "Permission denied" in stderr_content:
            raise OutputError(f"Permission denied during search: {stderr_content}")
        if "regex parse error" in stderr_content or "unclosed" in stderr_content:
            raise UsageError(f"Invalid search regular expression: {stderr_content}")
        raise UsageError(f"Search syntax error: {stderr_content}")

    has_matches = total_files > 0 if files_only else total_matches > 0

    if not has_matches:
        spool.close()
        if as_json:
            if files_only:
                if count_only:
                    out.write(json.dumps({"files_count": 0}, indent=2) + "\n")
                else:
                    out.write(json.dumps({"files_count": 0, "files": []}, indent=2) + "\n")
            else:
                if count_only:
                    out.write(json.dumps({"matches_count": 0, "files_count": 0}, indent=2) + "\n")
                else:
                    out.write(
                        json.dumps({"matches_count": 0, "files_count": 0, "files": []}, indent=2)
                        + "\n"
                    )
        else:
            out.write("No matches found.\n")
        return 1

    # Output results
    spool.seek(0)
    try:
        if as_json:
            if files_only:
                if count_only:
                    out.write(json.dumps({"files_count": total_files}, indent=2) + "\n")
                else:
                    out.write("{\n")
                    out.write(f'  "files_count": {total_files},\n')
                    out.write('  "files": [\n')
                    shutil.copyfileobj(spool, out)
                    out.write("\n  ]\n}\n")
            elif count_only:
                out.write(
                    json.dumps(
                        {"matches_count": total_matches, "files_count": total_files},
                        indent=2,
                    )
                    + "\n"
                )
            else:
                out.write(
                    f"{{\n"
                    f'  "matches_count": {total_matches},\n'
                    f'  "files_count": {total_files},\n'
                    f'  "files": [\n'
                )
                shutil.copyfileobj(spool, out)
                out.write("\n  ]\n}\n")
        elif count_only:
            file_unit = "file" if total_files == 1 else "files"
            if files_only:
                out.write(f"Found {total_files} {file_unit} with matches\n")
            else:
                match_unit = "match" if total_matches == 1 else "matches"
                out.write(f"Found {total_matches} {match_unit} in {total_files} {file_unit}\n")
        elif files_only:
            file_unit = "file" if total_files == 1 else "files"
            out.write(f"Found {total_files} {file_unit} with matches:\n")
            shutil.copyfileobj(spool, out)
        else:
            file_unit = "file" if total_files == 1 else "files"
            match_unit = "match" if total_matches == 1 else "matches"
            out.write(f"Found {total_matches} {match_unit} in {total_files} {file_unit}\n")
            shutil.copyfileobj(spool, out)
    finally:
        spool.close()

    return 0


def search_name(
    pattern: str,
    path: str | Path = ".",
    *,
    files_only: bool = False,
    dirs_only: bool = False,
    hidden: bool = False,
    no_ignore: bool = False,
    max_depth: int | None = None,
    as_json: bool = False,
    stdout_stream=None,
) -> int:
    """Search files and directories by name using standard library filesystem traversal."""
    out = sys.stdout if stdout_stream is None else stdout_stream

    if max_depth is not None and max_depth < 0:
        raise UsageError("Max depth must be a nonnegative integer.")

    search_path = Path(path)
    if not search_path.exists():
        raise InputError(f"Search path does not exist: {search_path}")

    results: list[NameMatch] = []
    skipped_paths: list[str] = []

    # Iterative traversal queue: (Path, current_depth)
    queue = [(search_path, 0)]

    while queue:
        current, depth = queue.pop(0)

        # Check self match (if not root search_path itself or if matching)
        if current != search_path:
            is_entry_dir = current.is_dir()
            name = current.name

            # Skip hidden unless --hidden is requested
            if not hidden and name.startswith("."):
                continue
            # Skip .git unless --no-ignore is requested
            if name == ".git" and not no_ignore:
                continue

            # Check pattern match against entry name
            if fnmatch.fnmatchcase(name, pattern):
                if is_entry_dir:
                    if not files_only:
                        results.append(NameMatch(_format_relative(current), is_dir=True))
                else:
                    if not dirs_only:
                        results.append(NameMatch(_format_relative(current), is_dir=False))

        # Check if we should descend into directory
        if current.is_dir():
            # Don't follow symlinked directories
            if current != search_path and current.is_symlink():
                continue

            if max_depth is not None and depth >= max_depth:
                continue

            try:
                entries = sorted(os.scandir(current), key=lambda e: e.name)
            except PermissionError:
                print(
                    f"lut: warning: Permission denied accessing directory: {current}",
                    file=sys.stderr,
                )
                skipped_paths.append(str(current))
                continue
            except OSError as err:
                raise OutputError(f"Cannot access directory: {err}") from None

            for entry in entries:
                entry_name = entry.name
                # Skip hidden entries unless --hidden is requested
                if not hidden and entry_name.startswith("."):
                    continue
                # Skip .git unless --no-ignore is requested
                if entry_name == ".git" and not no_ignore:
                    continue
                queue.append((Path(entry.path), depth + 1))

    # Sort results for stable output
    results.sort(key=lambda m: (m.path, m.is_dir))

    if not results:
        if as_json:
            out.write(
                json.dumps(
                    {
                        "matches_count": 0,
                        "matches": [],
                        "complete": len(skipped_paths) == 0,
                        "skipped_paths": skipped_paths,
                    }
                )
                + "\n"
            )
        else:
            if skipped_paths:
                out.write(
                    f"Warning: Scan was incomplete; {len(skipped_paths)} "
                    "directories were skipped due to permission errors.\n\n"
                )
            out.write("No matches found.\n")
        return 1

    if as_json:
        payload = {
            "matches_count": len(results),
            "matches": [
                {"path": r.path, "type": "directory" if r.is_dir else "file"} for r in results
            ],
            "complete": len(skipped_paths) == 0,
            "skipped_paths": skipped_paths,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        if skipped_paths:
            out.write(
                f"Warning: Scan was incomplete; {len(skipped_paths)} "
                "directories were skipped due to permission errors.\n\n"
            )
        out.write(f"Found {len(results)} matches\n\n")
        for r in results:
            display_path = f"{r.path}/" if r.is_dir and not r.path.endswith("/") else r.path
            out.write(f"{display_path}\n")

    return 0
