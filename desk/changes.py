"""What changed in the settings, in words, for the journal's event log.

The video's point: a rule changed until the past looks good proves nothing,
and nobody can judge a change that was never written down. So every change
made on the dashboard is logged with the old and the new value.
"""

# Values that may hold a name, an email or an account id are logged as "changed" only.
PRIVATE = ("sec_user_agent", "ntfy_topic")
# Changed through their own switch with its own check, never through the settings form.
RESERVED = ("mode",)


def _show(v):
    if isinstance(v, list):
        return " ".join(str(x) for x in v) or "(none)"
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, float):
        return "%g" % v
    return str(v)


def _list_change(old, new):
    added = [x for x in new if x not in old]
    removed = [x for x in old if x not in new]
    parts = []
    if added:
        parts.append("added %s" % " ".join(added))
    if removed:
        parts.append("removed %s" % " ".join(removed))
    return ", ".join(parts) or "reordered"


def diff(old, new):
    """[(key, sentence)] for every setting whose value differs."""
    out = []
    for k in sorted(new):
        a, b = old.get(k), new[k]
        if a == b:
            continue
        if k in PRIVATE:
            out.append((k, "Setting changed: %s (value not logged)." % k))
        elif isinstance(a, list) and isinstance(b, list):
            out.append((k, "Setting changed: %s, %s." % (k, _list_change(a, b))))
        else:
            out.append((k, "Setting changed: %s from %s to %s." % (k, _show(a), _show(b))))
    return out
