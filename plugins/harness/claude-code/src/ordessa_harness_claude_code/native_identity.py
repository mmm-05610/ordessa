"""Single pure Claude native session identity check; selectors are not identities."""

def _native_identity(value):
    # 'default' is an SDK input selector, never observed native identity.
    if (not isinstance(value, str) or not value or value.strip() != value
            or value == "default" or any(ord(character) < 32 for character in value)):
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True
