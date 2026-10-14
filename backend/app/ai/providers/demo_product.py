"""Deterministic Demo Mode for Product Understanding.

Extracts a Product Profile only from what the current project's source text states:
- labels with the value on the same line ("Features: a, b, c") or as a heading with the value on the
  following lines or as bullets ("Features:" then "- a" / "* b");
- the description sentence ("X is a <category> for <audience>");
- plain prose with explicit cues ("It includes a, b and c", "Unlike ...", "... instead of ...").
Anything not stated stays empty, so the workflow asks the owner instead of inventing it.
"""

import re
from typing import Dict, List, Optional

from ..generation_context import get_generation_context
from ..product_schemas import LIST_FIELDS, MAX_QUESTIONS
from .demo_provider import _LABEL_PATTERN, _cap, _clean, _parse_source_from_prompt, _sentences, _shorten, _split_items

# label keywords → profile field (a label matches if it contains the keyword)
_LABEL_MAP = [
    ("key_features", ("feature", "capabilit")),
    ("key_benefits", ("benefit",)),
    ("differentiators", ("differentiator", "unique", "usp", "why us")),
    ("use_cases", ("use case",)),
    ("value_proposition", ("value proposition", "tagline", "promise")),
    ("positioning", ("positioning",)),
    ("business_model", ("pricing", "price", "business model", "plans", "revenue model")),
    ("known_competitors", ("competitor", "alternative")),
    ("constraints", ("constraint", "limitation", "requirement", "compliance")),
    ("market_geography", ("market", "geograph", "region", "countr")),
    ("primary_users", ("primary user", "used by")),
    ("target_audience", ("target user", "target audience", "audience", "ideal customer", "customer")),
    ("problem_solved", ("problem", "pain", "challenge")),
    ("category", ("category", "industry")),
    ("description", ("description", "overview", "about")),
    ("name", ("product", "name", "brand")),
]
_BULLET = re.compile(r"^\s*(?:[-*•–▪]|\d{1,2}[.)])\s+(.*)$")
_LINE_LABEL = re.compile(r"^\s*(?:#{1,6}\s*)?[*_]{0,2}([A-Za-z][A-Za-z /&()'-]{1,40}?)[*_]{0,2}\s*:[*_]{0,2}\s*(.*)$")
_FEATURE_CUE = re.compile(r"\b(?:offers|includes|provides|features|comes with|supports|you get)\s+(.+)$", re.I)
_DIFFERENTIATOR_CUE = re.compile(
    r"^unlike\b|\bthe only\b|\bsets? (?:it|us|\w+) apart\b|\bwhat makes (?:it|us|\w+) different\b|\bdifferentiat", re.I)
_VALUE_CUE = re.compile(
    r"\b(?:so (?:that )?\w+(?: \w+)? can|helps|lets|allows|enables|instead of|rather than)\b|, not \w+ing\b", re.I)
_PROBLEM_CUES = re.compile(r"\b(hate|struggl\w*|wast\w*|overlook\w*|manual\w*|frustrat\w*|difficult|hard to|pain\w*|tedious|error-prone|miss\w*)\b", re.I)
_URL = re.compile(r"(https?://[^\s,)]+|www\.[^\s,)]+)", re.I)
_CLAUSE_MARKER = re.compile(r"\b(?:which|that|when|where|because|if|while|whose)\b", re.I)
_ANAPHORIC_START = re.compile(r"^\s*(?:this|these|that|those|such|so|and|but|also|however)\b", re.I)
_MONEY_TOPIC = re.compile(r"\b(?:revenue|funded|funding|investors?|profitable|pricing|price|subscriptions?|per (?:month|year)|freemium|free plan)\b", re.I)


def _product_is_subject(prefix: str, name: Optional[str]) -> bool:
    """True when the words before a cue ("... includes a, b") are about the PRODUCT (its name, "it", "we", "our plan"),
    not about something else in the text ("Every HTTP request includes IP address and User-Agent")."""
    prefix = prefix.strip().strip(",")
    if not prefix:
        return True
    if _CLAUSE_MARKER.search(prefix) or len(prefix.split()) > 5:
        return False
    first = prefix.split()[0].lower()
    if first in ("it", "we", "our", "the") or (name and name.split()[0].lower() in prefix.lower()):
        return True
    return bool(re.search(r"\b(?:plans?|app|tool|platform|product|service|software|dashboard|tier)\s*$", prefix, re.I))


def _field_for(label: str) -> Optional[str]:
    label = label.strip().lower()
    for field, keywords in _LABEL_MAP:
        if field == "name" and label in ("project name", "project title", "project", "campaign name", "campaign"):
            continue
        if any(k in label for k in keywords):
            return field
    return None


def _label_blocks(source: str) -> Dict[str, dict]:
    """Labels whose value sits on the following lines: a heading ("Features:") followed by prose or bullets
    (blank lines allowed) up to the next label, or an inline label followed directly by bullet lines.

    Returns {field: {"label", "lines", "bullets"}} for the first block of each field.
    """
    blocks: List[dict] = []
    current: Optional[dict] = None
    for raw in (source or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        bullet = _BULLET.match(line)
        label = None if bullet else _LINE_LABEL.match(line)
        if label:
            rest = label.group(2).strip()
            current = {"label": label.group(1), "lines": [rest] if rest else [], "bullets": [], "heading": not rest}
            blocks.append(current)
        elif not line:
            if current and not current["heading"]:
                current = None  # an inline label only continues with bullets directly below it
        elif current is not None:
            if bullet:
                current["bullets"].append(_clean(bullet.group(1)))
            elif current["heading"]:
                current["lines"].append(_clean(line))
            else:
                current = None
    found: Dict[str, dict] = {}
    for block in blocks:
        if not block["heading"] and not block["bullets"]:
            continue  # plain "Label: value" lines are handled sentence by sentence (see _labelled)
        field = _field_for(block["label"])
        if field and field not in found and (block["lines"] or block["bullets"]):
            found[field] = block
    return found


def _list_items(text: str) -> List[str]:
    """A prose value for a list field: separate sentences are separate items; a short comma list is split."""
    sentences = [x for x in _sentences(text) if x]
    if len(sentences) > 1:
        return [_cap(x) for x in sentences]
    parts = _split_items(text)
    return parts if all(len(x.split()) <= 6 for x in parts) else [_cap(_clean(text).rstrip("."))]


def _block_value(field: str, block: dict):
    text = " ".join(block["lines"])
    if field in LIST_FIELDS:
        items = (_list_items(text) if text else []) + [_cap(b.rstrip(".")) for b in block["bullets"]]
        return [i for i in dict.fromkeys(items) if i]
    return _shorten("; ".join([x for x in [text] if x] + block["bullets"]), 300)


def _labelled(source: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for sentence in _sentences(source):
        match = _LABEL_PATTERN.match(sentence)
        if not match:
            continue
        field = _field_for(match.group(1))
        if field and field not in found:
            found[field] = match.group(2).strip()
    return found


_NON_NAMES = {
    "it", "this", "our", "we", "the", "that", "a", "an", "here", "there",
    "what", "which", "how", "who", "when", "where", "why",
    "all", "each", "every", "some", "any", "no", "not",
    "create", "build", "launch", "make", "start", "run",
    "project", "campaign", "idea", "document", "source", "test",
    "product", "service", "tool", "app", "application", "platform", "software",
    "in", "on", "at", "by", "with", "from", "to", "for", "about",
    "features", "feature", "benefits", "benefit", "pricing", "price",
    "overview", "description", "details", "summary", "notes", "goals", "goal",
    "audience", "users", "competitors", "alternatives",
}


def _clean_name(cand: str) -> str:
    name = cand.strip().rstrip(".!?:;,")
    words = name.split()
    half = len(words) // 2
    # Web pages often repeat the title right before the first sentence ("Plausible Analytics Plausible Analytics is ...").
    if len(words) % 2 == 0 and half and words[:half] == words[half:]:
        name = " ".join(words[:half])
    return name


def _is_valid_name(cand: str) -> bool:
    cleaned = _clean_name(cand)
    if not cleaned or not cleaned[0].isupper():
        return False
    words = cleaned.split()
    if not (1 <= len(words) <= 4):
        return False
    if words[0].lower() in _NON_NAMES or cleaned.lower() in _NON_NAMES:
        return False
    return True


def _opening_sentence(sentence: str) -> tuple[Optional[str], str, str]:
    # A page title in front of the first sentence ("About | Plausible Analytics ...") is not part of the sentence.
    if "|" in sentence:
        head, tail = sentence.split("|", 1)
        if len(head.split()) <= 4 and tail.strip():
            sentence = tail.strip()
    label = _LABEL_PATTERN.match(sentence)
    if label:
        lbl_head = label.group(1).strip().lower()
        if lbl_head in ("project name", "project title", "project", "campaign name", "campaign"):
            return None, "", ""
        if lbl_head in ("product", "name", "brand", "product name"):
            sentence = label.group(2).strip()

    # 1. Preamble with for/about/introducing/launching/called/named + Candidate + separator/comma/is + rest
    # e.g. "Create a test project for FocusFlow, a lightweight scheduling tool for independent music tutors"
    m = re.search(
        r"\b(?:for|about|introducing|launching|called|named)\s+([A-Z][\w.&'-]*(?: [A-Z][\w.&'-]*){0,3})"
        r"(?:,\s*|\s*[-—–:]\s+|\s+is\s+)((?:an?|the)\s+.+)$",
        sentence,
        re.I,
    )
    if m and _is_valid_name(m.group(1)):
        cand, rest = _clean_name(m.group(1)), m.group(2).strip()
        return cand, f"{cand} is {rest}.", rest

    # 2. Appositive at start: "FocusFlow, a lightweight scheduling tool for independent music tutors"
    m = re.match(
        r"^([A-Z][\w.&'-]*(?: [A-Z][\w.&'-]*){0,3}),\s+((?:an?|the)\s+.+)$",
        sentence,
    )
    if m and _is_valid_name(m.group(1)):
        cand, rest = _clean_name(m.group(1)), m.group(2).strip()
        return cand, f"{cand} is {rest}.", rest

    # 3. Direct "StudioDesk is a booking app for …" — a capitalised name of 1-4 words, then "is a/an/the".
    m = re.match(r"^([A-Z][\w.&'-]*(?: [A-Z][\w.&'-]*){0,3}) is ((?:an?|the) .+)$", sentence)
    if m and _is_valid_name(m.group(1)):
        cand = _clean_name(m.group(1))
        return cand, f"{sentence}.", m.group(2).strip()

    # 4. Separator in (" - ", " — ", " – ", ": ")
    for separator in (" - ", " — ", " – ", ": "):
        if separator in sentence:
            head, rest = sentence.split(separator, 1)
            head, rest = head.strip(), rest.strip()
            pre_m = re.search(
                r"\b(?:for|about|introducing|launching|called|named)\s+([A-Z][\w.&'-]*(?: [A-Z][\w.&'-]*){0,3})$",
                head,
                re.I,
            )
            if pre_m and _is_valid_name(pre_m.group(1)):
                cand = _clean_name(pre_m.group(1))
                return cand, f"{cand} is {rest}.", rest
            elif _is_valid_name(head):
                cand = _clean_name(head)
                return cand, f"{cand} is {rest}.", rest

    # 5. Preamble ending with product name only (e.g. "Create a test project for FocusFlow.")
    m = re.search(
        r"\b(?:for|about|introducing|launching|called|named)\s+([A-Z][\w.&'-]*(?: [A-Z][\w.&'-]*){0,3})\.?$",
        sentence,
        re.I,
    )
    if m and _is_valid_name(m.group(1)):
        cand = _clean_name(m.group(1))
        return cand, f"{sentence}.", sentence

    return None, f"{sentence}.", sentence


def _opening(source: str) -> tuple[Optional[str], str, str]:
    """(name, description, descriptor) from the first sentence or opening sentences."""
    sentences = _sentences(source)
    if not sentences:
        return None, "", ""
    for s in sentences[:5]:
        cand, desc, descriptor = _opening_sentence(s)
        if cand:
            return cand, desc, descriptor
    return _opening_sentence(sentences[0])


def _descriptor(description: str, name: Optional[str]) -> str:
    """"StudioDesk is a booking app for ..." -> "a booking app for ..."."""
    subject = rf"(?:{re.escape(name)}|it|this|our product)" if name else r"(?:it|this|our product)"
    m = re.match(rf"^{subject}\s+is\s+(.+?)\.?$", _clean(description), re.I)
    return m.group(1) if m else ""


def _prose_fields(source: str, profile: Dict[str, object], name: Optional[str]) -> None:
    """Fill still-empty fields from plain sentences with explicit cues. Never from anything weaker."""
    used = set()
    sentences = [x for x in _sentences(source) if not _LABEL_PATTERN.match(x)]
    if not profile.get("description") and name:
        for x in sentences:
            if re.match(rf"^{re.escape(name)}\s+(?:is|helps|lets)\b", x):
                profile["description"] = _shorten(x + ".", 300)
                used.add(x)
                break
    if not profile.get("key_features"):
        for x in sentences:
            m = _FEATURE_CUE.search(x)
            if m and _product_is_subject(x[:m.start()], name):
                items = [_cap(_clean(i)) for i in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1)) if _clean(i)]
                if len(items) >= 2:
                    profile["key_features"] = items
                    used.add(x)
                    break
    if not profile.get("differentiators"):
        for x in sentences:
            if x not in used and _DIFFERENTIATOR_CUE.search(x) and not _MONEY_TOPIC.search(x):
                profile["differentiators"] = [_shorten(x, 200)]
                used.add(x)
                break
    if not profile.get("business_model"):
        for x in sentences:
            if x not in used and re.search(r"\bsubscription\b|\bfreemium\b|\bone-time (?:purchase|payment)\b", x, re.I) \
                    and re.search(r"\b(?:revenue|plans?|pricing|pay|paid|billed|charge[sd]?)\b", x, re.I) and not _CLAUSE_MARKER.search(x):
                profile["business_model"] = _shorten(x, 200)
                used.add(x)
                break
    if not profile.get("value_proposition"):
        description = str(profile.get("description") or "").rstrip(".")
        for x in sentences:
            if x not in used and x != description and _VALUE_CUE.search(x) and not _ANAPHORIC_START.match(x):
                profile["value_proposition"] = _shorten(x, 300)
                break


def build_demo_profile(prompt: str) -> dict:
    ctx = get_generation_context() or {}
    source = (ctx.get("input_text") or "").strip() or _parse_source_from_prompt(prompt)
    labelled = _labelled(source)
    blocks = _label_blocks(source)
    name, description, descriptor = _opening(source)

    profile: Dict[str, object] = {}
    for field, block in blocks.items():
        profile[field] = _block_value(field, block)
    for field, body in labelled.items():
        if field not in profile:
            profile[field] = _split_items(body) if field in LIST_FIELDS else _shorten(body, 300)
    # "Target users: ..." names the people who use the product as well as the audience.
    if not profile.get("primary_users") and profile.get("target_audience") and re.search(r"\btarget users?\s*:", source, re.I):
        profile["primary_users"] = [str(profile["target_audience"]).rstrip(".")]

    if name and not profile.get("name"):
        profile["name"] = name
    if isinstance(profile.get("name"), str):
        profile["name"] = re.split(r" - | — | – ", profile["name"])[0].strip()
    product_name = profile.get("name") if isinstance(profile.get("name"), str) else name
    _prose_fields(source, profile, product_name)
    # The opening line is only a description when it says more than the product's name.
    if description and not profile.get("description") and _clean(description).rstrip(".") != product_name:
        profile["description"] = _shorten(description, 300)
    if profile.get("description") and (not descriptor or descriptor == product_name):
        descriptor = _descriptor(str(profile["description"]), product_name) or descriptor
    if not profile.get("category") and descriptor:
        m = re.match(r"^(?:an?|the)\s+(.+?)\s+(?:for|that|which|to|built|designed|helping)\b", descriptor, re.I)
        if m:
            profile["category"] = _clean(m.group(1))
    if not profile.get("target_audience") and descriptor:
        m = re.search(r"\bfor ([^.,;]{3,100}?)(?=\s+(?:that|which|to|with|by|so)\b|[.,;]|$)", descriptor)
        if m:
            profile["target_audience"] = _clean(m.group(1))
    if not profile.get("market_geography") and descriptor:
        m = re.search(r"\bin ((?:[A-Z][a-zA-Z]+)(?: [A-Z][a-zA-Z]+)*)\s*\.?$", descriptor)
        if m:
            profile["market_geography"] = m.group(1)
    if not profile.get("problem_solved"):
        for sentence in _sentences(source)[1:]:
            if _PROBLEM_CUES.search(sentence) and not _LABEL_PATTERN.match(sentence):
                profile["problem_solved"] = _shorten(sentence, 300)
                break
    url = _URL.search(source)
    if url and not profile.get("website_url"):
        profile["website_url"] = url.group(1).rstrip(".")

    # The owner's answers are authoritative for the fields they target.
    for item in ctx.get("clarifications") or []:
        answer = _clean(item.get("answer") or "")
        if not answer:
            continue
        for field in item.get("fields") or []:
            profile[field] = _split_items(answer) if field in LIST_FIELDS else answer
    return profile


_QUESTION_TEMPLATES = {
    "name": ("What is the product called?", "Every later stage refers to the product by name."),
    "target_audience": (
        "Who is the primary customer for {name} — which role, business type, or segment buys it?",
        "Strategy, channels, and competitor research all depend on knowing exactly who buys the product.",
    ),
    "problem_solved": (
        "What specific problem does {name} solve for its users, in their own words?",
        "Content and positioning lead with the problem the audience already feels.",
    ),
    "key_features": (
        "What are the 3–5 core features of {name}?",
        "Features are what content demonstrates and what competitors are compared on.",
    ),
    "value_proposition": (
        "In one sentence, why should a customer choose {name} over how they handle this today?",
        "The value proposition becomes the core message of the promotion strategy.",
    ),
    "category": (
        "Which product category would customers search for when looking for {name}?",
        "The category defines which competitors and channels to analyse.",
    ),
    "description": ("How would you describe {name} in one or two sentences?", "A clear description anchors every later stage."),
    "business_model": (
        "How is {name} sold — free, subscription, one-time purchase, or something else?",
        "Pricing model shapes the call to action and which competitors are comparable.",
    ),
    "differentiators": (
        "What makes {name} different from the alternatives your customers use today?",
        "Differentiators decide which angles the strategy can credibly own.",
    ),
}


def build_demo_questions(prompt: str) -> dict:
    ctx = get_generation_context() or {}
    profile = ctx.get("profile") or {}
    name = profile.get("name") or "the product"
    questions: List[dict] = []
    for field in (ctx.get("askable_fields") or [])[:MAX_QUESTIONS]:
        template = _QUESTION_TEMPLATES.get(field)
        if template:
            questions.append({"question": template[0].format(name=name), "why_it_matters": template[1], "fields": [field]})
    return {"questions": questions}
