"""Lightweight generation-time checks for a LinkedIn Social Post (not the full Evaluate phase).

Hard errors — the draft is regenerated with the reasons fed back:
  missing fields, too few distinct alternative hooks, over the platform character limit,
  unresolved placeholders or leaked JSON, figures that appear nowhere in the approved context,
  guarantee / certain-outcome promises the approved context does not make, another product's name (cross-product
  leakage), a competitor's name, text copied from competitor evidence, and a post that never names the product.
Soft findings — kept on the draft for review and for the later Evaluate phase:
  hook longer than the "see more" fold, extra hashtags trimmed, product claims without evidence,
  weak alignment with the selected content pillar (app/ai/pillar_alignment.py: the pillar's name, or —
  given the pillar and profile — its substance, so a grounded paraphrase passes).
"""

import re
from typing import Dict, List

from .competitor_grounding import has_unsupported_numbers
from .pillar_alignment import lead, pillar_alignment
from .platform_policy import PlatformPolicy

_PLACEHOLDER = re.compile(
    r"\[(?:insert|your|product|company|name|link|audience)[^\]]*\]|\{\{|\}\}|lorem ipsum|\bTODO\b|\bTBD\b|<[a-z_ -]+>|\bXX+\b",
    re.I,
)
# Promises of guaranteed or certain outcomes (especially financial ones). No approved profile, strategy or source can
# back these up unless it says so itself, and they are the kind of wording that gets a post removed or a company sued.
_ABSOLUTE = re.compile(
    r"\b(?:guarantee[ds]?|risk[- ]free|zero[- ]risk|"
    r"(?:will|guaranteed to|certain to|sure to)\s+(?:definitely\s+|certainly\s+)?(?:save|earn|make|double|triple|boost|grow|cut|slash|increase)\b"
    r"[^.!?\n]{0,40}\b(?:money|revenue|income|profit|savings|costs?|sales|returns?))\b",
    re.I,
)
_JSON_LEAK = re.compile(r'^\s*[\[{]|"\w+"\s*:\s*["\[{]', re.M)
_STOP = {"with", "from", "that", "this", "your", "their", "into", "about", "have", "will", "they", "them", "what",
         "when", "which", "where", "more", "than", "also", "only", "just", "make", "makes", "does"}


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s#]", " ", (text or "").lower()).split())


def keywords(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z][a-z-]{3,}", (text or "").lower()) if w not in _STOP]


def assemble(post: Dict) -> str:
    parts = [post.get("hook", "").strip(), post.get("body", "").strip(), post.get("cta", "").strip()]
    tags = " ".join(post.get("hashtags") or [])
    return "\n\n".join(p for p in parts + [tags] if p)


def _clean_hashtag(tag: str) -> str:
    tag = re.sub(r"[^\w]", "", str(tag or ""))
    return f"#{tag}" if tag else ""


def absolute_claims(text: str, corpus: str) -> List[str]:
    """Guarantee / certain-outcome phrases in the post that the approved context does not itself contain."""
    corpus_norm = norm(corpus)
    found = []
    for match in _ABSOLUTE.finditer(text or ""):
        phrase = match.group(0).strip()
        if norm(phrase) not in corpus_norm and phrase.lower() not in (c.lower() for c in found):
            found.append(phrase)
    return found


def _copied_from(post_text: str, sources: List[str], window: int = 8) -> bool:
    words = norm(post_text).split()
    corpus = [norm(s) for s in sources if s]
    for i in range(0, max(0, len(words) - window + 1)):
        chunk = " ".join(words[i:i + window])
        if any(chunk in c for c in corpus):
            return True
    return False


# Problems a human edit cannot be saved with. Everything else is reported, not blocked, for an edit:
# the user is the authority on their own product, but the post must still fit the platform.
EDIT_BLOCKING = frozenset({"missing", "over_limit", "placeholder", "json"})


def validate_post(post: Dict, allowed_refs: List[str], corpus: str, meta: Dict, policy: PlatformPolicy) -> Dict:
    """Return {post, errors, issues, warnings, unsupported_claims, character_count, ...}. Never raises.

    `issues` are the errors with a code ({code, message}) so callers can decide what blocks.
    """
    issues: List[Dict[str, str]] = []
    warnings: List[str] = []

    def error(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})
    allowed = set(allowed_refs)
    p = {k: (v.strip() if isinstance(v, str) else v) for k, v in post.items()}

    for field in ("hook", "body", "cta", "pillar"):
        if not p.get(field):
            error("missing", f"'{field}' is missing.")

    hook_key = norm(p.get("hook", ""))
    alternatives, seen = [], {hook_key}
    for h in p.get("alternative_hooks") or []:
        key = norm(h)
        if key and key not in seen:
            seen.add(key)
            alternatives.append(h.strip())
    if len(alternatives) < policy.alternative_hooks:
        error("alternatives", f"Need {policy.alternative_hooks} distinct alternative hooks that differ from the selected hook "
                      f"(got {len(alternatives)}).")
    p["alternative_hooks"] = alternatives[:policy.alternative_hooks]

    tags = [t for t in dict.fromkeys(_clean_hashtag(t) for t in p.get("hashtags") or []) if t]
    if len(tags) > policy.max_hashtags:
        warnings.append(f"Kept the first {policy.max_hashtags} of {len(tags)} hashtags.")
    p["hashtags"] = tags[:policy.max_hashtags]

    text = assemble(p)
    count = len(text)
    if count > policy.max_chars:
        error("over_limit", f"The post is {count} characters; the {policy.name} limit is {policy.max_chars}.")
    if len(p.get("hook", "")) > policy.hook_max_chars:
        warnings.append(f"The hook is {len(p['hook'])} characters; only about {policy.hook_max_chars} show before "
                        f"'…see more' on {policy.name}.")
    if _PLACEHOLDER.search(text):
        error("placeholder", "The post contains an unresolved placeholder (e.g. [insert …], TODO, {{…}}).")
    if _JSON_LEAK.search(p.get("body", "")) or _JSON_LEAK.search(p.get("hook", "")):
        error("json", "The post contains leaked JSON or field names.")
    if has_unsupported_numbers(text, corpus):
        error("unsupported_number", "The post contains a figure that does not appear in the approved profile, strategy, or sources "
                      "(no invented statistics, prices, or results).")

    for phrase in absolute_claims(text, corpus):
        error("absolute_claim", f"The post promises a guaranteed or certain outcome (\"{phrase}\") that nothing in the approved "
                                "profile, strategy or sources supports. Describe what the product does, not what it guarantees.")

    lowered = text.lower()
    for name in meta.get("forbidden_names") or []:
        if name and re.search(rf"\b{re.escape(name.lower())}\b", lowered):
            # The name is not repeated: this message is fed back into the next prompt.
            error("cross_product", "The post mentions another of the user's products (cross-product leakage). "
                                   "Write only about the product in this context.")
    for name in meta.get("competitor_names") or []:
        if name and re.search(rf"\b{re.escape(name.lower())}\b", lowered):
            error("competitor_named", f"The post names the competitor '{name}'. Use competitor insights for positioning only.")
    if _copied_from(text, meta.get("competitor_texts") or []):
        error("competitor_copy", "The post copies wording from competitor evidence. Use competitors only to inform positioning.")
    product = (meta.get("product_name") or "").strip()
    if product and product.lower() not in lowered:
        error("product_missing", f"The post never names the product '{product}'.")

    aligned, _ = pillar_alignment(text, lead(p.get("hook", ""), p.get("body", "")), meta.get("pillar") or "",
                                  meta.get("pillar_detail"), meta.get("profile_core"))
    if not aligned:
        warnings.append(f"The post does not clearly reflect the selected pillar '{meta.get('pillar')}'.")

    claims, unsupported = [], []
    for c in p.get("claims") or []:
        refs = [r for r in dict.fromkeys(c.get("refs") or []) if r in allowed]
        claim = {"text": (c.get("text") or "").strip(), "kind": c.get("kind") or "creative", "refs": refs}
        if not claim["text"]:
            continue
        if claim["kind"] == "product_fact" and not any(r.startswith(("S", "P:")) for r in refs):
            unsupported.append(claim["text"])
        claims.append(claim)
    p["claims"] = claims
    if unsupported:
        warnings.append(f"{len(unsupported)} product claim(s) have no supporting evidence; check them before publishing.")

    return {
        "post": p,
        "errors": [i["message"] for i in issues],
        "issues": issues,
        "warnings": warnings,
        "unsupported_claims": unsupported,
        "character_count": count,
        "platform_limit": policy.max_chars,
        "within_limit": count <= policy.max_chars,
    }
