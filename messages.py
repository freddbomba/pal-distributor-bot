"""Italian message templates for the PAL distribution bot."""

from models import Proposal
from utils import format_pal_amount, format_status


def welcome():
    return (
        "Benvenuto nel bot di distribuzione PAL della Rete Palanche di Genova!\n"
        "Usa /help per vedere i comandi disponibili."
    )


def help_text():
    return (
        "Comandi disponibili:\n\n"
        "/register <indirizzo_TON> - Registra il tuo wallet TON\n"
        "/propose - Avvia una proposta di distribuzione PAL (guidata)\n"
        "/propose_incentive - Proponi un nuovo incentivo per la rete\n"
        "/incentives - Elenca gli incentivi attivi\n"
        "/endorse <id> - Appoggia una proposta in attesa\n"
        "/object <id> <motivo> - Obietta a una proposta (motivo obbligatorio)\n"
        "/reinstate <id> - [Admin] Ripristina una proposta in sospeso\n"
        "/reject <id> - [Admin] Rifiuta una proposta in sospeso\n"
        "/expire_incentive <id> - [Admin] Contrassegna un incentivo come scaduto\n"
        "/history [n] - Mostra le ultime n proposte (default 10)\n"
        "/myproposals - Mostra le tue proposte\n"
        "/balance - Mostra il saldo PAL della tesoreria\n"
        "/status <id> - Mostra i dettagli di una proposta\n"
        "/matrix - Mostra i valori di riferimento della matrice sociale\n"
    )


def registration_success(ton_address: str):
    return f"Wallet registrato con successo: {ton_address}"


def registration_updated(ton_address: str):
    return f"Wallet aggiornato: {ton_address}"


def not_registered():
    return "Non sei ancora registrato. Usa /register <indirizzo_TON> per registrarti."


def invalid_ton_address():
    return "Indirizzo TON non valido. Deve iniziare con EQ o UQ (48 caratteri) o essere in formato raw."


# --- Proposal conversation ---

def propose_ask_event():
    return "Qual e' l'evento? Descrivi brevemente l'attivita' per cui richiedi PAL."


def propose_ask_participants():
    return "Quanti partecipanti?"


def propose_ask_pal_per_participant():
    return "Quante PAL per partecipante?"


def propose_ask_pal_organiser():
    return "Quante PAL per l'organizzatore?"


def propose_summary(proposal: Proposal, proposer_name: str):
    return (
        f"Proposta #{proposal.id}\n"
        f"Evento: {proposal.event_name}\n"
        f"Partecipanti: {proposal.num_participants}\n"
        f"PAL per partecipante: {format_pal_amount(proposal.pal_per_participant)}\n"
        f"PAL per organizzatore: {format_pal_amount(proposal.pal_for_organiser)}\n"
        f"Totale: {format_pal_amount(proposal.total_amount)} PAL\n"
        f"Proposta da: {proposer_name}\n\n"
        f"In attesa di appoggio da un altro membro."
    )


def propose_confirm_summary(
    event_name: str,
    num_participants: int,
    pal_per_participant: float,
    pal_for_organiser: float,
    total: float,
) -> str:
    return (
        f"Riepilogo proposta:\n\n"
        f"Evento: {event_name}\n"
        f"Partecipanti: {num_participants}\n"
        f"PAL per partecipante: {format_pal_amount(pal_per_participant)}\n"
        f"PAL per organizzatore: {format_pal_amount(pal_for_organiser)}\n"
        f"Totale: {format_pal_amount(total)} PAL\n\n"
        f"Confermi la proposta?"
    )


def incentive_confirm_summary(offered_by: str, description: str, conditions: str) -> str:
    return (
        f"Riepilogo incentivo:\n\n"
        f"Offerto da: {offered_by}\n"
        f"Incentivo: {description}\n"
        f"Condizioni: {conditions}\n\n"
        f"Confermi la proposta?"
    )


def propose_amount_exceeds_max(max_amount: float):
    return f"Il totale supera il massimo consentito di {format_pal_amount(max_amount)} PAL. Riprova."


def propose_invalid_number():
    return "Per favore inserisci un numero valido."


def propose_timeout():
    return "Tempo scaduto per la proposta. Usa /propose per ricominciare."


def propose_cooldown(remaining_seconds: int):
    minutes = remaining_seconds // 60
    if minutes > 0:
        return f"Devi aspettare ancora {minutes} minuti prima di proporre di nuovo."
    return f"Devi aspettare ancora {remaining_seconds} secondi prima di proporre di nuovo."



# --- Endorsement ---

def endorsed(proposal: Proposal, endorser_name: str):
    return (
        f"Proposta #{proposal.id} appoggiata da {endorser_name}!\n"
        f"Inizia il countdown di 24 ore. Se nessuno obietta, i PAL verranno distribuiti."
    )


def proposal_endorsed_update(proposal: Proposal, proposer_name: str, endorser_name: str):
    return (
        f"Proposta #{proposal.id}\n"
        f"Evento: {proposal.event_name}\n"
        f"Partecipanti: {proposal.num_participants}\n"
        f"PAL per partecipante: {format_pal_amount(proposal.pal_per_participant)}\n"
        f"PAL per organizzatore: {format_pal_amount(proposal.pal_for_organiser)}\n"
        f"Totale: {format_pal_amount(proposal.total_amount)} PAL\n"
        f"Proposta da: {proposer_name}\n"
        f"Appoggiata da: {endorser_name}\n\n"
        f"In attesa — countdown 24h attivo. Scade: {proposal.expires_at}"
    )


def cannot_endorse_own():
    return "Non puoi appoggiare la tua stessa proposta."


def already_endorsed():
    return "Questa proposta e' gia' stata appoggiata."


# --- Objection ---

def objection_reason_required():
    return "Devi fornire un motivo per l'obiezione.\nUso: /object <id> <motivo>"


def objection_recorded(proposal: Proposal, objector_name: str):
    return (
        f"Proposta #{proposal.id} — IN SOSPESO\n\n"
        f"Obiezione di {objector_name}:\n"
        f'"{proposal.objection_reason}"\n\n'
        f"In attesa di decisione degli amministratori."
    )


def proposal_on_hold_update(proposal: Proposal, proposer_name: str, objector_name: str):
    return (
        f"Proposta #{proposal.id} — IN SOSPESO\n"
        f"Evento: {proposal.event_name}\n"
        f"Partecipanti: {proposal.num_participants}\n"
        f"PAL per partecipante: {format_pal_amount(proposal.pal_per_participant)}\n"
        f"PAL per organizzatore: {format_pal_amount(proposal.pal_for_organiser)}\n"
        f"Totale: {format_pal_amount(proposal.total_amount)} PAL\n"
        f"Proposta da: {proposer_name}\n\n"
        f"Obiezione di {objector_name}:\n"
        f'"{proposal.objection_reason}"\n\n'
        f"In attesa di decisione degli amministratori."
    )


def cannot_object_own():
    return "Non puoi obiettare alla tua stessa proposta."


def object_prompt_reason():
    return "Per quale motivo obietti? Rispondi a questo messaggio con il motivo."


# --- Admin actions ---

def reinstated(proposal_id: int):
    return (
        f"Proposta #{proposal_id} ripristinata. Nuovo countdown di 24 ore attivato."
    )


def rejected(proposal_id: int):
    return f"Proposta #{proposal_id} rifiutata."


def admin_only():
    return "Solo gli amministratori possono usare questo comando."


# --- Auto-approval ---

def auto_approved(proposal: Proposal, tx_hash: str):
    return (
        f"Proposta #{proposal.id} APPROVATA!\n"
        f"Evento: {proposal.event_name}\n"
        f"Totale: {format_pal_amount(proposal.total_amount)} PAL distribuiti.\n"
        f"TX: {tx_hash}"
    )


def auto_approval_failed(proposal: Proposal, error: str):
    return (
        f"Proposta #{proposal.id}: trasferimento fallito.\n"
        f"Errore: {error}\n"
        f"Gli amministratori verificheranno."
    )


def endorsement_expired(proposal_id: int):
    return (
        f"Proposta #{proposal_id} scaduta — nessun appoggio ricevuto entro il termine."
    )


# --- Status & History ---

def proposal_status(proposal: Proposal):
    lines = [
        f"Proposta #{proposal.id} — {format_status(proposal.status)}",
        f"Evento: {proposal.event_name}",
        f"Partecipanti: {proposal.num_participants}",
        f"PAL/partecipante: {format_pal_amount(proposal.pal_per_participant)}",
        f"PAL organizzatore: {format_pal_amount(proposal.pal_for_organiser)}",
        f"Totale: {format_pal_amount(proposal.total_amount)} PAL",
        f"Creata: {proposal.created_at}",
    ]
    if proposal.endorsed_at:
        lines.append(f"Appoggiata: {proposal.endorsed_at}")
    if proposal.expires_at:
        lines.append(f"Scadenza: {proposal.expires_at}")
    if proposal.objection_reason:
        lines.append(f"Obiezione: {proposal.objection_reason}")
    if proposal.tx_hash:
        lines.append(f"TX: {proposal.tx_hash}")
    return "\n".join(lines)


def history_header(count: int):
    return f"Ultime {count} proposte:\n"


def history_row(proposal: Proposal):
    return (
        f"#{proposal.id} | {format_status(proposal.status)} | "
        f"{format_pal_amount(proposal.total_amount)} PAL | {proposal.event_name}"
    )


def no_proposals():
    return "Nessuna proposta trovata."


# --- Balance ---

def treasury_balance(pal_balance: float, ton_balance: float):
    return (
        f"Saldo tesoreria:\n"
        f"PAL: {format_pal_amount(pal_balance)}\n"
        f"TON (per gas): {ton_balance:.4f}"
    )


# --- Matrix ---

def matrix_header():
    return "Matrice sociale — Valori di riferimento:\n"


def matrix_row(ref):
    unit_label = {"hour": "ora", "event": "evento", "participant": "partecipante"}.get(
        ref.unit, ref.unit
    )
    source_label = "base" if ref.source == "seed" else "appreso"
    return f"- {ref.description}: {ref.pal_per_unit} PAL/{unit_label} [{source_label}]"


# --- Errors ---

def proposal_not_found(proposal_id: int):
    return f"Proposta #{proposal_id} non trovata."


def wrong_status(proposal_id: int, expected: str, actual: str):
    return (
        f"Proposta #{proposal_id} non e' nello stato corretto.\n"
        f"Stato attuale: {format_status(actual)}, richiesto: {format_status(expected)}"
    )


# --- Incentive conversation ---

def propose_incentive_ask_offered_by():
    return "Chi offre questo incentivo? (es. 'Bottega del Pane Boccadasse')"


def propose_incentive_ask_description():
    return "Descrivi l'incentivo. (es. '5% di sconto pagando in PAL')"


def propose_incentive_ask_conditions():
    return "Quali sono le condizioni per ottenerlo? (es. 'Acquisti superiori a 10 PAL')"


def propose_incentive_summary(proposal: Proposal, proposer_name: str) -> str:
    return (
        f"Proposta Incentivo #{proposal.id}\n"
        f"Offerto da: {proposal.incentive_offered_by}\n"
        f"Incentivo: {proposal.incentive_description}\n"
        f"Condizioni: {proposal.incentive_conditions}\n"
        f"Proposta da: {proposer_name}\n\n"
        f"In attesa di appoggio da un altro membro."
    )


def auto_approved_incentive(proposal: Proposal, incentive) -> str:
    return (
        f"Incentivo #{incentive.id} ATTIVATO!\n"
        f"Offerto da: {incentive.offered_by}\n"
        f"Incentivo: {incentive.description}\n"
        f"Condizioni: {incentive.conditions}\n"
        f"(Proposta #{proposal.id} approvata per consenso)"
    )


def incentives_list(incentives: list) -> str:
    if not incentives:
        return "Nessun incentivo attivo al momento."
    lines = ["Incentivi attivi:\n"]
    for inc in incentives:
        lines.append(f"#{inc.id} — {inc.offered_by}: {inc.description}")
        lines.append(f"   Condizioni: {inc.conditions}\n")
    return "\n".join(lines)


def incentive_expired_msg(incentive_id: int) -> str:
    return f"Incentivo #{incentive_id} contrassegnato come scaduto."


def incentive_not_found(incentive_id: int) -> str:
    return f"Incentivo #{incentive_id} non trovato."
