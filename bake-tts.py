#!/usr/bin/env python3
"""Bake Azure Speech TTS mp3s for all readable segments.

Walks HTML pages, groups text by <h2> (per model), generates audio/<lang>/<hash>.mp3
via the Azure Cognitive Services TTS REST API, and writes data-tts-{lang}=<hash>
back to the anchor element (h1 for cover, h2 for each model).

Idempotent: skips audio files that already exist; only rewrites HTML when
attributes actually change.

Env vars:
    AZURE_SPEECH_KEY        required  Azure Speech resource key
    AZURE_SPEECH_REGION     required  e.g. "eastus", "eastus2"
    AZURE_VOICE_ID          optional  Chinese voice (default: zh-CN-XiaoxiaoNeural)
    AZURE_VOICE_ID_EN       optional  English voice; if absent, EN baking skipped

    R2_ACCOUNT_ID           optional  set all three to upload MP3s to R2 instead
    R2_ACCESS_KEY_ID        optional  of writing audio/ (see make_store below);
    R2_SECRET_ACCESS_KEY    optional  needs `pip install boto3`
    R2_BUCKET               optional  default "bigcat-audio"
    R2_PREFIX               optional  default = this repo's directory name

Usage:
    pip install beautifulsoup4 requests
    python3 bake-tts.py                              # all *-dayNN.html
    python3 bake-tts.py decision-making-day01.html   # one page
    python3 bake-tts.py --lang zh                    # only Chinese
    python3 bake-tts.py --dry-run                    # plan, no API calls
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Comment, NavigableString

# Azure endpoint template — region is filled in at request time
ENDPOINT_TEMPLATE = "https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
DEFAULT_VOICE_ZH = "zh-CN-XiaoxiaoNeural"
DEFAULT_VOICE_EN = "en-US-JennyNeural"
# Elements whose data-zh/data-en text becomes part of a model's narration.
NARRATION_TAGS = ("h1", "h2", "h3", "h4", "p", "div", "li", "summary")
REPO_DIR = Path(__file__).parent.resolve()
AUDIO_DIR = REPO_DIR / "audio"
# Azure tolerates much larger bodies than Volcano. 3000 chars gives plenty of
# headroom under their ~10-min audio-per-request limit; most model sections fit
# in one call so ffmpeg concat isn't usually needed.
MAX_CHARS_PER_CALL = 3000


# ---------------------------------------------------------------------------
# Where baked MP3s go.
#
# Historically: audio/<lang>/<hash>.mp3, committed to the repo. That put ~8GB
# of binaries across the fleet into git and pushed the biggest sites toward the
# 1GB GitHub Pages limit. Migrated repos upload to R2 instead (bucket key
# <repo>/<lang>/<hash>.mp3, served by the bigcat-audio Worker) and stop
# tracking audio/ entirely.
#
# R2 mode switches on when the three R2_* env vars are present, so a local run
# without credentials still bakes to disk and behaves exactly as before.
# ---------------------------------------------------------------------------


class LocalStore:
    """Baked MP3s as files under audio/<lang>/."""

    label = "local audio/"

    def __init__(self, root: Path):
        self.root = root

    def has(self, lang: str, digest: str) -> bool:
        return (self.root / lang / f"{digest}.mp3").exists()

    def put(self, lang: str, digest: str, data: bytes) -> None:
        p = self.root / lang / f"{digest}.mp3"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


class R2Store:
    """Baked MP3s as R2 objects under <prefix>/<lang>/<hash>.mp3.

    The existing keys are listed once up front: the bake is idempotent by
    "does this object already exist", and one paginated LIST is far cheaper
    than a HEAD per segment.
    """

    def __init__(self, account_id: str, access_key: str, secret_key: str,
                 bucket: str, prefix: str):
        import boto3  # imported lazily so local runs need no extra dep
        from botocore.config import Config

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.label = f"r2://{bucket}/{self.prefix}"
        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 5}),
        )
        self.existing = self._list_existing()
        print(f"  {self.label}: {len(self.existing)} objects already baked")

    def _list_existing(self) -> set:
        keys = set()
        token = None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": self.prefix + "/"}
            if token:
                kw["ContinuationToken"] = token
            resp = self.client.list_objects_v2(**kw)
            for o in resp.get("Contents", []):
                keys.add(o["Key"])
            if not resp.get("IsTruncated"):
                return keys
            token = resp["NextContinuationToken"]

    def _key(self, lang: str, digest: str) -> str:
        return f"{self.prefix}/{lang}/{digest}.mp3"

    def has(self, lang: str, digest: str) -> bool:
        return self._key(lang, digest) in self.existing

    def put(self, lang: str, digest: str, data: bytes) -> None:
        key = self._key(lang, digest)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType="audio/mpeg",
            # Content-addressed keys, so the bytes behind one never change.
            CacheControl="public, max-age=31536000, immutable",
        )
        self.existing.add(key)


def make_store() -> LocalStore | R2Store:
    env = {k: os.environ.get(k) for k in
           ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")}
    if not all(env.values()):
        if any(env.values()):
            missing = [k for k, v in env.items() if not v]
            print(f"WARNING: partial R2 config, baking to disk instead. "
                  f"Missing: {', '.join(missing)}", file=sys.stderr)
        return LocalStore(AUDIO_DIR)
    return R2Store(
        env["R2_ACCOUNT_ID"], env["R2_ACCESS_KEY_ID"], env["R2_SECRET_ACCESS_KEY"],
        os.environ.get("R2_BUCKET", "bigcat-audio"),
        os.environ.get("R2_PREFIX", REPO_DIR.name),
    )


def hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def plain_text(attr_value: str) -> str:
    """Strip inline HTML from a data-* attribute so the hash matches what the
    browser sees as element.textContent."""
    return BeautifulSoup(attr_value, "html.parser").get_text().strip()


def normalize_for_tts(text: str) -> str:
    """Light normalization. Fix nbsp + spell out ✓/✗/⚠ marks
    (Azure otherwise drops them, losing good/bad semantic). NOTE: × is
    NOT replaced — commonly used as multiplication ("Care × Challenge")."""
    text = text.replace(" ", " ")
    text = text.replace("✓ ", "正例，").replace("✓ ", "正例，").replace("✓", "正例，")
    text = text.replace("✔ ", "正例，").replace("✔ ", "正例，").replace("✔", "正例，")
    text = text.replace("✗ ", "反例，").replace("✗ ", "反例，").replace("✗", "反例，")
    text = text.replace("✘ ", "反例，").replace("✘ ", "反例，").replace("✘", "反例，")
    text = text.replace("❌ ", "反例，").replace("❌ ", "反例，").replace("❌", "反例，")
    text = text.replace("⚠️ ", "注意，").replace("⚠ ", "注意，").replace("⚠", "注意，")
    # Math / comparison symbols that Azure otherwise renders as awkward
    # single-character reads or silence. Pad with commas so surrounding
    # phrasing doesn't collide.
    import re as _re
    text = _re.sub(r"\s*≥\s*", " 大于等于 ", text)
    text = _re.sub(r"\s*≤\s*", " 小于等于 ", text)
    text = _re.sub(r"\s*>\s*", " 大于 ", text)
    text = _re.sub(r"\s*<\s*", " 小于 ", text)
    text = _re.sub(r"\s*×\s*", " 乘以 ", text)
    text = _re.sub(r"\s*÷\s*", " 除以 ", text)
    text = _re.sub(r"\s*±\s*", " 正负 ", text)
    # `=` gets spoken as "等于" only when surrounded by spaces or between
    # obviously numeric/short-word contexts; leave "A=B" style alone since
    # it's often used as inline labelling in Chinese copy.
    text = _re.sub(r"\s+=\s+", " 等于 ", text)
    # Strip decorative icons. Azure narrates them by name (🌀 → "龙卷风"),
    # which derails a heading like "🌀 越界 · 跨学科的联想". Runs AFTER the
    # ✓/✗/⚠ replacements above, which need those glyphs intact.
    text = _re.sub(
        r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]",
        "", text,
    )
    return text


def ssml_escape(text: str) -> str:
    """XML-escape user text before embedding in SSML."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def synth(key: str, region: str, voice_name: str, text: str) -> bytes:
    """Single Azure TTS call. Voice name like 'zh-CN-XiaoxiaoNeural'."""
    lang = "-".join(voice_name.split("-")[:2])  # e.g. zh-CN-XiaoxiaoNeural → zh-CN
    body = (
        f'<speak version="1.0" xml:lang="{lang}">'
        f'<voice name="{voice_name}">{ssml_escape(normalize_for_tts(text))}</voice>'
        f'</speak>'
    ).encode("utf-8")

    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
        "User-Agent": "mental-models-daily-bake",
    }
    url = ENDPOINT_TEMPLATE.format(region=region)
    r = requests.post(url, data=body, headers=headers, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Azure TTS HTTP {r.status_code}: {r.text[:500]}")
    return r.content


def synth_with_retry(key, region, voice_name, text, max_retries=3):
    """Retry transient 5xx / 429 with exponential backoff."""
    import time
    last_err = None
    for attempt in range(max_retries):
        try:
            return synth(key, region, voice_name, text)
        except RuntimeError as e:
            msg = str(e)
            if "HTTP 5" in msg or "HTTP 429" in msg:
                last_err = e
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_err


def synth_long(key: str, region: str, voice_name: str, text: str) -> bytes:
    """TTS arbitrary-length text by chunking + ffmpeg concat. Each Azure call
    returns mp3 with proper headers, but concat still benefits from ffmpeg
    rewriting the header for the joined file (so audio.duration is finite)."""
    import time
    import subprocess
    import tempfile
    chunks = chunk_text(text)
    if len(chunks) == 1:
        return synth_with_retry(key, region, voice_name, chunks[0])

    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for i, c in enumerate(chunks):
            try:
                mp3 = synth_with_retry(key, region, voice_name, c)
            except Exception:
                print(f"        chunk {i}/{len(chunks)} ({len(c)} chars) failed: {c[:60]!r}", file=sys.stderr)
                raise
            f = Path(tmp) / f"part{i:03d}.mp3"
            f.write_bytes(mp3)
            files.append(f)
            time.sleep(0.1)

        manifest = Path(tmp) / "list.txt"
        manifest.write_text("".join(f"file '{f}'\n" for f in files))
        out = Path(tmp) / "out.mp3"
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(manifest), "-c", "copy", str(out)],
            capture_output=True,
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "-f", "concat", "-safe", "0",
                 "-i", str(manifest), "-c:a", "libmp3lame", "-b:a", "128k",
                 str(out)],
                capture_output=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg concat failed: {result.stderr.decode()[:500]}")
        return out.read_bytes()


def detect_page_mode(soup) -> str:
    """Return 'split', 'full', or 'legacy' based on document markup.

    - 'split': new pattern — one file per language; element text is the language;
      no data-zh / data-en attrs. Identified by <html lang="..."> + no data-zh.
    - 'full': legacy embedded — <html data-i18n-mode="full"> + data-zh/data-en
      pairs on translatable elements.
    - 'legacy': oldest pages — bilingual sections labeled by class/text.
    """
    html = soup.find("html")
    if html and html.get("data-i18n-mode") == "full":
        return "full"
    if soup.find(attrs={"data-zh": True}) or soup.find(attrs={"data-en": True}):
        return "full"
    return "split"


def page_lang(soup) -> str:
    """Pull the page's primary language from <html lang>. Defaults to zh."""
    html = soup.find("html")
    lang_attr = (html.get("lang") if html else "") or "zh"
    return "en" if lang_attr.lower().startswith("en") else "zh"


def collect_groups(soup) -> list[tuple]:
    """Return [(anchor_element, {'zh': text, 'en': text}), ...] grouped by model.

    A 'model' is bounded by h2 elements. The very first group (before the first
    h2) is the cover (h1 + intro).

    SPLIT mode: extracts element.textContent for every readable element, attributes
    it to the page's lang (zh OR en). Returns text in one language bucket only.

    FULL mode (legacy): concatenates data-zh / data-en from elements with those
    attributes, plus content-detected .prompt-item / .prompt-block paragraphs.
    Returns both language buckets.
    """
    mode = detect_page_mode(soup)
    body = soup.body or soup
    # Section boundaries: h2 elements + <div class="card"> (philosophy pages
    # use per-thinker cards, sometimes alongside a trailing h2 like 深入思考).
    # Collect both, then sort by DOM order.
    candidates = list(body.find_all(["h2", "h3", "h4"]))
    candidates += list(body.find_all("div", class_=lambda c: c and ("card" in c or c == "deep-head")))
    candidates = [el for el in candidates if not el.find_parent(class_="mmd-controls")]
    # DOM order: use sourceline+sourcepos if available, else find_all() order
    candidate_ids = set(id(c) for c in candidates)
    seen = set()
    h2s = []
    for el in body.find_all(True):
        if id(el) in candidate_ids and id(el) not in seen:
            # De-duplicate nested boundaries: if ANY ancestor is a
            # candidate, keep only the outer. Prevents inner h3 titles
            # inside cards (buddhism .sutra-card > .section > h3, or
            # philosophy card > h2) from over-splitting the audio.
            outer = el.find_parent(lambda p: id(p) in candidate_ids)
            if outer is not None:
                continue
            seen.add(id(el))
            h2s.append(el)
    if not h2s:
        return []  # no model boundaries — page isn't a content page

    h1 = body.find("h1")
    anchors_and_bounds = []
    anchors_and_bounds.append((h1 or h2s[0], None, h2s[0]))  # cover
    for i, h2 in enumerate(h2s):
        end = h2s[i + 1] if i + 1 < len(h2s) else None
        anchors_and_bounds.append((h2, h2, end))

    # ---- SPLIT mode: one language per file, read textContent directly ----
    if mode == "split":
        lang = page_lang(soup)
        n_groups = len(anchors_and_bounds)
        bins_split: list[list[str]] = [[] for _ in range(n_groups)]
        h2_set = set(id(h) for h in h2s)
        h2_seen = 0
        # If we capture an outer container div (because it carries bare text
        # mixed with block children), skip everything inside it so the same
        # text isn't narrated twice.
        skip_descendants_of: set[int] = set()
        # Readable text-bearing tags. Skip nav/controls and obviously decorative bits.
        for node in body.descendants:
            if id(node) in h2_set:
                h2_seen += 1
            if not hasattr(node, "name") or node.name not in NARRATION_TAGS:
                continue
            if skip_descendants_of and any(
                id(anc) in skip_descendants_of for anc in node.parents
            ):
                continue
            if node.find_parent("nav") or node.find_parent(class_="mmd-controls"):
                continue
            # Skip elements inside a diagram/SVG, footers, anything purely decorative
            if node.find_parent("svg") or node.find_parent("style") or node.find_parent("script"):
                continue
            # Only direct visible text — skip divs that WRAP block-level children
            # (their text is captured via those inner elements). Include divs whose
            # direct children are inline only (bare text, <strong>, <em>, <span>) —
            # these are "leaf" divs holding real content.
            classes = node.get("class") or []
            _BLOCK_TAGS = ("div", "p", "h1", "h2", "h3", "h4", "h5", "h6",
                           "ul", "ol", "li", "section", "article", "table",
                           "tr", "td", "th", "pre", "blockquote")
            if node.name == "div":
                has_block_children = any(
                    getattr(child, "name", None) in _BLOCK_TAGS
                    for child in node.children
                )
                # If the div has block children but ALSO carries direct text
                # nodes with content (e.g. <div class="tryit"><div class="label">
                # THIS WEEK</div>bare instruction text<br/>思考：...</div>), keep
                # it — that bare text is not covered by any child element.
                has_direct_text = any(
                    isinstance(child, NavigableString)
                    and not isinstance(child, Comment)
                    and str(child).strip()
                    for child in node.children
                )
                if has_block_children and not has_direct_text:
                    continue
                if has_block_children and has_direct_text:
                    # Captured this outer container; suppress its children so
                    # inner leaf divs (e.g. <div class="label">THIS WEEK</div>)
                    # aren't re-narrated.
                    skip_descendants_of.add(id(node))
            # Skip elements explicitly tagged as the opposite language
            if lang == "zh" and "en" in classes:
                continue
            if lang == "en" and "zh" in classes:
                continue
            text = node.get_text().strip()
            if not text:
                continue
            # Skip prompt-box etc. whose text is clearly the wrong language
            # (e.g. "English Prompt" boxes inside a zh page with no `en` class)
            if "prompt-box" in classes or "prompt-block" in classes or "prompt-item" in classes:
                cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
                ascii_letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
                if lang == "zh" and ascii_letters > cjk * 3:
                    continue
                if lang == "en" and cjk > ascii_letters:
                    continue
            bins_split[h2_seen].append(text)
        out = []
        for (anchor, _, _), parts in zip(anchors_and_bounds, bins_split):
            joined = "  ".join(parts).strip()
            if joined:
                # Same shape as FULL mode but with text only in the page's lang
                texts = {"zh": "", "en": ""}
                texts[lang] = joined
                out.append((anchor, texts))
        return out

    # ---- FULL mode (legacy): use data-zh / data-en attributes ----
    # Decorative elements whose data-zh/data-en contain OPPOSITE-language text.
    SKIP_CLASSES = {"en", "zh", "date", "category"}

    def is_decorative(el) -> bool:
        cls = el.get("class") or []
        return any(c in SKIP_CLASSES for c in cls)

    all_tagged = []
    for tag in NARRATION_TAGS:
        for el in body.find_all(tag):
            if el.find_parent("nav") or el.find_parent(class_="mmd-controls"):
                continue
            if is_decorative(el):
                continue
            if not (el.has_attr("data-zh") or el.has_attr("data-en")):
                continue
            all_tagged.append(el)

    n_groups = len(anchors_and_bounds)
    bins: list[dict] = [{"zh": [], "en": []} for _ in range(n_groups)]

    # Pick up <p> inside .prompt-item which lacks data-zh/data-en (different
    # content per language, not translations).
    def detect_lang(text: str) -> str:
        return "zh" if re.search(r"[一-鿿]", text) else "en"

    prompt_ps = []
    for pi in body.find_all(class_="prompt-item"):
        for p in pi.find_all("p"):
            if p.find_parent("nav") or p.find_parent(class_="mmd-controls"):
                continue
            if p.has_attr("data-zh") or p.has_attr("data-en"):
                continue
            txt = p.get_text().strip()
            if txt:
                prompt_ps.append((p, detect_lang(txt), txt))

    doc_order = list(body.descendants)
    h2_seen = 0
    h2_set = set(id(h) for h in h2s)
    tagged_set = set(id(e) for e in all_tagged)
    prompt_p_map = {id(p): (lang, txt) for p, lang, txt in prompt_ps}
    for node in doc_order:
        if id(node) in h2_set:
            h2_seen += 1
        if id(node) in tagged_set:
            g = h2_seen
            for lang in ("zh", "en"):
                if node.has_attr(f"data-{lang}"):
                    t = plain_text(node[f"data-{lang}"])
                    if t:
                        bins[g][lang].append(t)
        elif id(node) in prompt_p_map:
            g = h2_seen
            lang, txt = prompt_p_map[id(node)]
            bins[g][lang].append(txt)

    out = []
    for (anchor, _, _), texts in zip(anchors_and_bounds, bins):
        joined = {lang: "  ".join(texts[lang]).strip() for lang in ("zh", "en")}
        if joined["zh"] or joined["en"]:
            out.append((anchor, joined))
    return out


def chunk_text(text: str, max_chars: int = MAX_CHARS_PER_CALL) -> list[str]:
    """Split text into chunks ≤ max_chars at sentence boundaries (。！？.!?)."""
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"(?<=[。！？.!?])\s*", text)
    chunks: list[str] = []
    cur = ""
    for p in parts:
        if not p:
            continue
        if len(cur) + len(p) > max_chars and cur:
            chunks.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        chunks.append(cur)
    final = []
    for c in chunks:
        while len(c) > max_chars:
            final.append(c[:max_chars])
            c = c[max_chars:]
        if c:
            final.append(c)
    return final


def process_page(
    path: Path,
    key: str,
    region: str,
    voice_zh: str,
    voice_en: str | None,
    langs: set,
    dry_run: bool,
    store,
) -> None:
    print(f"\n=== {path.name} ===")
    html_src = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html_src, "html.parser")
    mode = detect_page_mode(soup)
    groups = collect_groups(soup)
    print(f"  {len(groups)} model groups (cover + N models)  [mode={mode}]")

    changed = False
    generated = skipped_existing = skipped_lang = errors = 0

    # SPLIT mode uses `data-tts` (single attr); FULL uses `data-tts-zh/-en`.
    # Clean up any stale hash attrs on non-anchors.
    anchor_ids = {id(a) for a, _ in groups}
    stale_attrs = ("data-tts", "data-tts-zh", "data-tts-en")
    for attr in stale_attrs:
        for el in soup.find_all(attrs={attr: True}):
            if id(el) not in anchor_ids:
                del el[attr]
                changed = True

    for anchor, lang_texts in groups:
        for lang in ("zh", "en"):
            if lang not in langs:
                skipped_lang += 1
                continue
            text = lang_texts.get(lang, "")
            if not text:
                continue
            voice = voice_zh if lang == "zh" else voice_en
            if not voice and not dry_run:
                skipped_lang += 1
                # No voice for this lang, so nothing gets baked. But an anchor can
                # still carry a hash no bake ever produced (copied from TEMPLATE,
                # or written by hand), and the player would fetch a guaranteed-404
                # URL. Drop it -- only when R2 is the store (authoritative), and
                # only if the object it names is missing, so audio baked earlier
                # keeps playing.
                attr_name = "data-tts" if mode == "split" else f"data-tts-{lang}"
                old = anchor.get(attr_name)
                if old and isinstance(store, R2Store) and not store.has(lang, old):
                    del anchor[attr_name]
                    changed = True
                    print(f"  [{lang}] dropped dead {attr_name}={old} (no voice, not in R2)")
                continue

            # Hash the RAW text on purpose: normalisation rules keep evolving
            # (icons, ✓/✗, math symbols) and hashing their output would silently
            # invalidate — and re-bake — every existing segment on the next push.
            # Old audio therefore stays as baked; new pages get current rules.
            digest = hash_text(text)
            # SPLIT mode: each file is single-language, JS reads `data-tts`.
            # FULL mode: file holds both, JS reads `data-tts-{lang}`.
            attr_name = "data-tts" if mode == "split" else f"data-tts-{lang}"
            if anchor.get(attr_name) != digest:
                anchor[attr_name] = digest
                changed = True

            label = (anchor.get_text() or "(cover)")[:20]
            if store.has(lang, digest):
                skipped_existing += 1
                continue
            if dry_run:
                print(f"  [{lang}] would bake {digest}.mp3 ← {label} ({len(text)} chars)")
                continue
            try:
                audio = synth_long(key, region, voice, text)
                store.put(lang, digest, audio)
                generated += 1
                n_chunks = len(chunk_text(text))
                print(f"  [{lang}] {digest}.mp3 ({len(audio):,} B, {n_chunks} chunks) ← {label}")
            except Exception as e:
                errors += 1
                print(f"  [{lang}] FAILED {digest} ← {label}\n         {e}", file=sys.stderr)

    if changed and not dry_run:
        path.write_text(str(soup), encoding="utf-8")
        print(f"  wrote {path.name} (updated data-tts-* attributes)")

    print(
        f"  generated={generated} skipped_existing={skipped_existing} "
        f"skipped_lang={skipped_lang} errors={errors}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", help="HTML files (default: all *-dayNN.html)")
    parser.add_argument("--lang", choices=["zh", "en", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")
    voice_zh = os.environ.get("AZURE_VOICE_ID") or DEFAULT_VOICE_ZH
    voice_en = os.environ.get("AZURE_VOICE_ID_EN")  # None = skip EN

    if not args.dry_run:
        missing = [
            k for k, v in {
                "AZURE_SPEECH_KEY": key,
                "AZURE_SPEECH_REGION": region,
            }.items() if not v
        ]
        if missing:
            print(f"ERROR: missing env vars: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
    if args.lang in ("en", "all") and not voice_en:
        print("Note: AZURE_VOICE_ID_EN not set — English segments will be skipped.")

    langs = {"zh", "en"} if args.lang == "all" else {args.lang}

    if args.files:
        files = [Path(f) if Path(f).is_absolute() else REPO_DIR / f for f in args.files]
    else:
        # Discover by exclusion, not by a name pattern: a positive pattern
        # silently matches zero files when a page adopts a new naming scheme,
        # and the workflow still goes green. *.en.html is included: with an EN
        # voice it gets baked, without one its dead data-tts get dropped.
        files = sorted(
            p for p in REPO_DIR.iterdir()
            if p.suffix == ".html"
            and not p.name.startswith("index.")
            and not p.name.endswith("-index.html")
        )

    store = make_store()
    print(f"Audio store: {store.label}")

    for path in files:
        try:
            process_page(path, key, region, voice_zh, voice_en, langs, args.dry_run, store)
        except Exception as e:
            print(f"  PAGE FAILED: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
# 2026-06-01: re-trigger bake for June quota reset
