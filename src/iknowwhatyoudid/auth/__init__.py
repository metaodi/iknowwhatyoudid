"""OAuth, and the tokens it produces.

Separated from `mail/` because a token is the one thing in this feature that must never
reach a log, an argument list, or the store. Keeping it behind one package makes that
reviewable rather than a claim about several modules.
"""
