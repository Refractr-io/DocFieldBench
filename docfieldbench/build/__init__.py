"""Dataset build: one module per source. Turns source documents and their structured data into tasks.

Nothing here converts documents for systems: the text layer read below is a build-time check (is a gold value
printed? is an absent field really absent?) and never ships as an input.
"""
