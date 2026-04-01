import re
from database import Database
from models import ReferenceValue, Proposal

# Italian stop words to skip during keyword extraction
STOP_WORDS = {
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una",
    "e", "o", "ma", "che", "del", "dello", "della", "dei", "degli", "delle",
    "al", "allo", "alla", "ai", "agli", "alle", "dal", "dallo", "dalla",
    "nel", "nello", "nella", "sul", "sullo", "sulla",
}

# Map common Italian words to social_matrix categories
KEYWORD_TO_CATEGORY = {
    "pulizia": "cleanup",
    "pulire": "cleanup",
    "spiaggia": "cleanup",
    "volontario": "volunteer",
    "volontariato": "volunteer",
    "laboratorio": "workshop",
    "workshop": "workshop",
    "corso": "teaching",
    "insegnamento": "teaching",
    "tutoring": "teaching",
    "lezione": "teaching",
    "riunione": "meeting",
    "assemblea": "meeting",
    "incontro": "meeting",
    "trasporto": "transport",
    "cucina": "cooking",
    "cibo": "cooking",
    "pranzo": "cooking",
    "cena": "cooking",
    "riparazione": "repair",
    "manutenzione": "repair",
    "aggiustare": "repair",
}


def extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from event name text."""
    words = re.findall(r"[a-zA-ZàèéìòùÀÈÉÌÒÙ]+", text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 2]


def find_matching_categories(keywords: list[str]) -> list[str]:
    """Map extracted keywords to social_matrix categories."""
    categories = set()
    for kw in keywords:
        if kw in KEYWORD_TO_CATEGORY:
            categories.add(KEYWORD_TO_CATEGORY[kw])
    return list(categories)


def get_references(db: Database, event_name: str) -> tuple[list[ReferenceValue], list[Proposal]]:
    """Search social matrix and past proposals for references matching an event description."""
    keywords = extract_keywords(event_name)
    categories = find_matching_categories(keywords)

    # Search by both categories and raw keywords
    search_terms = list(set(categories + keywords))
    ref_values = db.search_reference_values(search_terms)
    past_proposals = db.search_approved_proposals(keywords)

    return ref_values, past_proposals


def format_references(ref_values: list[ReferenceValue], past_proposals: list[Proposal]) -> str:
    """Format reference values and past proposals into a guidance message."""
    if not ref_values and not past_proposals:
        return ""

    lines = ["Riferimenti dalla matrice sociale:"]

    for rv in ref_values[:5]:
        unit_label = {"hour": "ora", "event": "evento", "participant": "partecipante"}.get(
            rv.unit, rv.unit
        )
        lines.append(f'- "{rv.description}": {rv.pal_per_unit} PAL/{unit_label}')

    for p in past_proposals[:3]:
        lines.append(
            f'- Proposta #{p.id} "{p.event_name}" (approvata): '
            f"{p.num_participants} partecipanti, {p.pal_per_participant} PAL ciascuno, "
            f"{p.pal_for_organiser} PAL organizzatore"
        )

    lines.append("\nQuesti valori sono indicativi per aiutarti a calibrare la richiesta.")
    return "\n".join(lines)


def learn_from_proposal(db: Database, proposal: Proposal):
    """Extract learned values from an approved proposal and add to social matrix."""
    keywords = extract_keywords(proposal.event_name)
    if not keywords:
        return

    category = keywords[0]
    categories = find_matching_categories(keywords)
    if categories:
        category = categories[0]

    db.add_learned_value(
        category=category,
        description=f"{proposal.event_name} ({proposal.num_participants} partecipanti)",
        pal_per_unit=proposal.pal_per_participant,
        unit="participant",
        proposal_id=proposal.id,
    )
