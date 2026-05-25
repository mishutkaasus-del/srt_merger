#!/usr/bin/env python3
from flask import Flask, request, jsonify, send_file, render_template, make_response
import re
import io
import os

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max


# ─── Text Formatter Logic ─────────────────────────────────────────────────────

def format_text(input_text):
    result = " ".join(input_text.split())
    result = re.sub(r'\s*\u2014\s*', ' \u2014 ', result)
    return result


# ─── SRT Merger Logic ─────────────────────────────────────────────────────────

def parse_srt(content):
    blocks = re.split(r"\n\n+", content.strip())
    entries = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        m = re.match(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", lines[1])
        if m:
            entries.append({"start": m.group(1), "end": m.group(2), "text": " ".join(lines[2:])})
    return entries


def has_cyrillic(text):
    return bool(re.search(r"[а-яёА-ЯЁіїєґІЇЄҐ]", text))


def clean_parenthetical(match):
    inner = match.group(1)
    if has_cyrillic(inner):
        return ""
    if re.fullmatch(r"[\d\s]*", inner):
        return ""
    if re.match(r"(?i)asset\s*id", inner):
        return ""
    return f"({inner})"


def clean_line(line):
    if re.match(r"(?i)asset\s*id\s*[:\-]?\s*\d*", line.strip()):
        return ""
    line = re.sub(r"\(([^)]*)\)", clean_parenthetical, line)
    line = re.sub(r"^\d+\s+", "", line)
    return line.strip()


def parse_text(content):
    subtitles = []
    current_lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "":
            if current_lines:
                subtitles.append(" ".join(current_lines))
                current_lines = []
            continue
        if re.fullmatch(r"\d+", stripped):
            continue
        if has_cyrillic(stripped):
            continue
        cleaned = clean_line(stripped)
        if cleaned:
            current_lines.append(cleaned)
    if current_lines:
        subtitles.append(" ".join(current_lines))
    return [s for s in subtitles if s]


def normalize(text):
    text = re.sub(r"[—–]", " ", text)
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).split()


def ts_to_ms(ts):
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)


def ms_to_ts(ms):
    ms = max(0, int(ms))
    h = ms // 3600000; ms %= 3600000
    m = ms // 60000;   ms %= 60000
    s = ms // 1000;    ms %= 1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def expand_srt_words(entries):
    all_words = []
    imprecise_start = set()
    imprecise_end = set()

    for e in entries:
        raw_tokens = e["text"].split()
        tokens = []
        token_is_dash = []
        for rt in raw_tokens:
            parts = re.split(r"[—–]", rt)
            if len(parts) > 1:
                for p in parts:
                    if p:
                        tokens.append(p)
                        token_is_dash.append(True)
            else:
                tokens.append(rt)
                token_is_dash.append(False)

        n = len(tokens)
        if n == 0:
            continue

        start_ms = ts_to_ms(e["start"])
        end_ms = ts_to_ms(e["end"])
        duration = end_ms - start_ms
        block_is_imprecise = (n > 1)

        for i, (tok, is_dash) in enumerate(zip(tokens, token_is_dash)):
            word_start_ms = start_ms + int(duration * i / n)
            word_end_ms = start_ms + int(duration * (i + 1) / n)
            idx = len(all_words)
            if is_dash:
                imprecise_start.add(idx)
                imprecise_end.add(idx)
            elif block_is_imprecise:
                if i > 0:
                    imprecise_start.add(idx)
                if i < n - 1:
                    imprecise_end.add(idx)
            all_words.append({
                "word": tok,
                "start": ms_to_ts(word_start_ms),
                "end": ms_to_ts(word_end_ms),
            })

    return all_words, imprecise_start, imprecise_end


def fix_overlaps(result):
    for i in range(1, len(result)):
        prev_end = ts_to_ms(result[i - 1]["end"])
        curr_start = ts_to_ms(result[i]["start"])
        if curr_start < prev_end:
            result[i - 1]["end"] = result[i]["start"]
    return result


def full_match(srt_norm, sub_words, search_from, total):
    for i in range(search_from, total):
        if srt_norm[i] == sub_words[0]:
            if all(
                (i + j < total and srt_norm[i + j] == sw)
                for j, sw in enumerate(sub_words)
            ):
                return i, "full"
    for i in range(search_from, total):
        if srt_norm[i] == sub_words[0]:
            return i, "partial"
    return None, None


def merge_srt(srt_content, text_content):
    entries = parse_srt(srt_content)
    target_subs = parse_text(text_content)

    if not entries:
        return None, "Could not parse SRT file"
    if not target_subs:
        return None, "Could not parse text file"

    all_words, imprecise_start, imprecise_end = expand_srt_words(entries)
    srt_norm = [normalize(w["word"])[0] if normalize(w["word"]) else "" for w in all_words]
    total_words = len(all_words)

    result = []
    srt_ptr = 0
    log = []

    for sub_idx, sub_text in enumerate(target_subs, 1):
        sub_words = normalize(sub_text)
        if not sub_words:
            continue

        if srt_ptr >= total_words:
            log.append(f"[SKIP] [{sub_idx:>3}] SRT ended: {sub_text[:55]}")
            continue

        start_ptr, match_type = full_match(srt_norm, sub_words, srt_ptr, total_words)

        if start_ptr is None:
            anchor = srt_ptr
            end_ptr = min(anchor + len(sub_words) - 1, total_words - 1)
            log.append(f"[MISSING] [{sub_idx:>3}] {all_words[anchor]['start']} — not found: {sub_text[:55]}")
            result.append({
                "text": sub_text,
                "start": all_words[anchor]["start"],
                "end": all_words[end_ptr]["end"],
            })
            continue

        srt_ptr = start_ptr + len(sub_words)
        end_ptr = min(srt_ptr - 1, total_words - 1)

        if match_type == "partial":
            log.append(f"[APPROX] [{sub_idx:>3}] {all_words[start_ptr]['start']} — first-word match only: {sub_text[:45]}")
        elif start_ptr in imprecise_start or end_ptr in imprecise_end:
            reasons = []
            if start_ptr in imprecise_start:
                reasons.append("start")
            if end_ptr in imprecise_end:
                reasons.append("end")
            log.append(f"[APPROX] [{sub_idx:>3}] {all_words[start_ptr]['start']} — boundary estimated ({', '.join(reasons)}): {sub_text[:40]}")

        result.append({
            "text": sub_text,
            "start": all_words[start_ptr]["start"],
            "end": all_words[end_ptr]["end"],
        })

    if not result:
        return None, "Could not build any subtitles"

    result = fix_overlaps(result)

    lines = []
    for i, r in enumerate(result, 1):
        lines.append(f"{i}\n{r['start']} --> {r['end']}\n{r['text']}\n")

    output = "\n".join(lines)
    return output, "\n".join(log) if log else f"OK — {len(result)} subtitles, no issues"


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/format", methods=["POST"])
def api_format():
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "No text provided"}), 400
    result = format_text(data["text"])
    return jsonify({"result": result})


@app.route("/api/merge", methods=["POST"])
def api_merge():
    srt_file = request.files.get("srt")
    txt_file = request.files.get("txt")
    txt_text = request.form.get("txt_text", "").strip()

    if not srt_file:
        return jsonify({"error": "No SRT file provided"}), 400
    if not txt_file and not txt_text:
        return jsonify({"error": "No text provided"}), 400

    srt_content = srt_file.read().decode("utf-8-sig")

    if txt_file:
        text_content = txt_file.read().decode("utf-8-sig")
    else:
        text_content = txt_text

    output, log = merge_srt(srt_content, text_content)

    if output is None:
        return jsonify({"error": log}), 400

    buf = io.BytesIO(output.encode("utf-8"))
    buf.seek(0)

    stem = os.path.splitext(srt_file.filename)[0]
    filename = f"{stem}_merged.srt"

    response = make_response(send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name=filename,
    ))
    response.headers["X-Log"] = log.replace("\n", " | ")
    return response


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
