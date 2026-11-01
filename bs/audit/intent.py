"""Deletion-intent classifier.

Ordered rules (first match wins). Deletion is the default because verification-style requests
("confirm my profile is gone") carry no deletion verb, while non-deletion requests (access,
correction, opt-out, login help) state their purpose explicitly.
"""
import re

STRONG_DELETE = re.compile("|".join([
    r"delet", r"eras", r"remov", r"clos(e|ing) (my|the|this) account", r"close this account", r"\bwipe\b", r"purge",
    r"permanent", r"get rid of", r"forgotten", r"deactivat",
    r"elimin", r"borr(a|e)", r"cancel(ar|e)", r"apag", r"exclu", r"cancella", r"suppr", r"effac", r"l(ö|o)sch", r"entfern",
    r"verwijder", r"rimuov", r"削除", r"消去", r"退会", r"삭제", r"탈퇴", r"删除", r"注销", r"刪除", r"註銷",
]), re.I)
EXPLICIT_NEG = re.compile("|".join([
    r"not asking for (deletion|removal)", r"\bdo not (close|delete|remove|erase)\b", r"\bdon'?t (close|delete|remove|erase)\b",
    r"\b(leave|keep) (my|the|this) (account|profile)\b", r"still need the account", r"\bwithout (deleting|closing|removing|erasing)\b", r"not a request (to|for) (erase|delet|remov|clos)", r"information request",
    r"leave the account active", r"not (want|wish) (to )?(delete|close)", r"\bkeep the account\b",
]), re.I)
MARKETING = re.compile(r"(marketing|promotional|newsletter|promo)", re.I)
ACCESS = re.compile(r"(tell me what|what personal information|copy of|download|portable format|information (you )?hold|data you hold|access to my)", re.I)
CORRECT = re.compile(r"(misspell|correct|replace|update|change|out of date|reset)", re.I)
CORRECT_OBJ = re.compile(r"(name|surname|email|e-mail|address|number|phone|login|password)", re.I)
DELETE_VERB = re.compile(r"(delete|erase|erasure|remove (my|the|all|any)|close (my|this|the) account|permanently)", re.I)


def deletion_intent(text):
    t = text or ""
    if EXPLICIT_NEG.search(t):
        return False
    if MARKETING.search(t) and re.search(r"(only|stop|unsubscribe|opt)", t, re.I) and not DELETE_VERB.search(t.replace("marketing lists", "")):
        return False
    if MARKETING.search(t) and re.search(r"lists? only", t, re.I):
        return False
    if ACCESS.search(t) and not DELETE_VERB.search(t):
        return False
    if CORRECT.search(t) and CORRECT_OBJ.search(t) and not STRONG_DELETE.search(t):
        return False
    return True
