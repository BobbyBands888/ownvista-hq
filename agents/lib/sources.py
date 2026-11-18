"""Which public-domain federal (DVIDS) videos fit Ten-Four Tapes.

The channel is police / law-enforcement footage. DVIDS also carries military operations, including the
U.S. Southern Command strikes on "narco-terrorist" vessels: not bodycam, often lethal, and politically charged.
Those never become leads or content. Law-enforcement units (CBP, Border Patrol, Coast Guard, military police)
stay in.
"""
import re

MILITARY_UNITS = re.compile(r"southern command|southcom|northern command|central command|indo-?pacific command|"
                            r"africa command|european command|joint task force|department of war|"
                            r"department of defense|secretary of (war|defense)|\bnavy\b|air force|\barmy\b(?! corps)|"
                            r"marine corps|special operations", re.I)
STRIKE_WORDS = re.compile(r"narco-?terroris|\bstrike[sd]?\b|kinetic|lethal|airstrike|designated terrorist|"
                          r"cartel vessel|vessel (was )?(destroyed|sunk)", re.I)
LAW_ENFORCEMENT = re.compile(r"customs and border|border patrol|\bcbp\b|coast guard|military police|"
                             r"security forces|\bpolice\b", re.I)


def is_military_op(lead):
    """True for DVIDS military operations / strikes, which the channel doesn't cover."""
    if (lead.get("source_type") or "") != "dvids_public_domain":
        return False
    unit = lead.get("agency_name") or ""
    text = f"{lead.get('title') or ''} {lead.get('summary') or ''}"
    if STRIKE_WORDS.search(text):
        return True
    return bool(MILITARY_UNITS.search(unit)) and not LAW_ENFORCEMENT.search(unit + " " + text)
