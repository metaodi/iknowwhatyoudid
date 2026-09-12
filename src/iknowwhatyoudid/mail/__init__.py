"""Reading mail, and normalising it to the one shape the store already holds.

Nothing above `reader.py` knows which provider produced a record. The provider modules
here are the only place that difference exists.
"""
