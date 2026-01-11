examples = [
    'Star Wars - Episode I - The Phantom Menace',
    'Documentary - Part 1',
    'NoSeparatorFilename',
    'Artist - Track - Remix',
]
for s in examples:
    print(repr(s) + ' -> ' + repr(s.replace(' - ', ': ', 1)))
