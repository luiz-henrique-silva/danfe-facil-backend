from typing import Final

# Domínios de email temporário/descartável (lista enxuta de alto uso)
DISPOSABLE_DOMAINS: Final[set[str]] = {
    "mailinator.com",
    "mailinator.net",
    "guerrillamail.com",
    "guerrillamail.net",
    "guerrillamail.org",
    "grr.la",
    "sharklasers.com",
    "10minutemail.com",
    "10minutemail.net",
    "10minutemail.org",
    "yopmail.com",
    "yopmail.net",
    "yopmail.fr",
    "mohmal.com",
    "temp-mail.org",
    "temp-mail.io",
    "tempmail.com",
    "tempmail.io",
    "tmpmail.org",
    "throwawaymail.com",
    "maildrop.cc",
    "mailnesia.com",
    "inboxkitten.com",
    "getnada.com",
    "nada.email",
    "trashmail.com",
    "trashmail.de",
    "mailnesia.com",
    "dispostable.com",
    "mailcatch.com",
    "mytemp.email",
    "fakemail.net",
    "fakeinbox.com",
    "emailondeck.com",
    "spamgourmet.com",
    "spam4.me",
    "emlpro.com",
    "fammail.net",
    "emailto.de",
    "mintemail.com",
    "timzap.com",
    "maileater.com",
    "cesmail.com",
    "mailfreeonline.com",
    "jetable.org",
    "incognitomail.org",
    "spambox.us",
    "spamfree24.org",
    "discard.email",
    "neverbox.com",
    "mailnull.com",
    "sendanonymous.net",
    "zzz.com",
    "kochamtrans.pl",
    "tmail.ws",
    "zoaxe.com",
    "thunked.com",
    "brefmail.com",
    "drdrb.com",
    "moneymotortion.com",
    "mt2009.com",
    "mytrashmail.com",
    "pepbot.com",
    "glutenfreemail.com",
    "hotcookie.net",
    "webfreeemail.com",
    "bundes-li.org",
    "irish2me.com",
}

# Domínios com múltiplos subdomínios por usuário (prefixo aleatório antes do @)
DISPOSABLE_PREFIX_DOMAINS: Final[set[str]] = {
    "maildrop.cc",
    "temp-mail.org",
}


def is_disposable_email(email: str) -> bool:
    """Retorna True se o email usa um domínio temporário/descartável."""
    try:
        domain = email.rsplit("@", 1)[1].lower()
    except IndexError:
        return False

    base = domain
    if domain.count(".") >= 2:
        base = domain.rsplit(".", 2)[-2] + "." + domain.rsplit(".", 1)[-1]

    if domain in DISPOSABLE_DOMAINS:
        return True

    # pega os dois últimos níveis do domínio
    parts = domain.split(".")
    last_two = ".".join(parts[-2:]) if len(parts) >= 2 else domain
    last_three = ".".join(parts[-3:]) if len(parts) >= 3 else domain

    if last_two in DISPOSABLE_DOMAINS or last_three in DISPOSABLE_DOMAINS:
        return True
    if base in DISPOSABLE_DOMAINS:
        return True

    return False