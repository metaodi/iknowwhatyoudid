"""The only place an HTTP request is made.

`http.py` holds a host allow-list, so "no destination other than a configured account"
is a property one test can assert about the whole codebase — the technique `0003` used
to make `git/binary.py` the only door to git.
"""
