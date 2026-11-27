"""Opt-in contract for the reviewed M42 offline PvE mechanics.

New battles freeze the version with their balance profile. Checkpoints made
before M42 deliberately retain their previous controllers and objective rules.
The source identity is the immutable native-map SHA carried by the geometry;
an arena may add its own local overlay without changing that source identity.
This does not claim that the missing Flash server scripts were recovered.
"""

VERSION = 1
SOURCE_SHA256 = {
    501: '2e41f780d42a25b9cc67a1ae79409b22cf17e1e3363da9d12fe2403663c54e03',
    502: 'aa6b91f33527390a1234cce77c6717ec50ef4f90befda411ce902ded8308f5f2',
    503: '77594140837da09ca9e6e9967a86f26485c25ca6f7ef963e70c1850045d1c5fe',
    505: 'bbcb32edbce556d51be581b16a8466afbfd638364e29dde70a5fa62573bb829a',
    603: '184f690f3dc68e7f595adf6a82ae948154d8f1391b74986a196473c3ace67d3f',
    30102: 'df5f5fe3bc4d9961d61e0ad0e82777574e1119ecc846b859a3bf9ae29c6d9466',
    30103: '91da59ec5b5f9112f3d8274ddcb9d42be82b1d8e83895c608b6f458702fdf7fc',
    31202: '7484fd5b48227166ede79f372c5957c9c19382892cb6bc07c3271bec98b711d5',
    31403: 'a68071b4d629b15155aea717bbc7eb0120bf015b08808f9c0f743cd23c9cd441',
    31601: '2828c13b9b2b445b3f886fbec6909b8e32ed72ec4653207ef32c44fe8a70d0d7',
}


def enabled(arena):
    """Enable only frozen new-run rules on the exact reviewed native layout."""
    profile = arena.state.get('battle', {}).get('pve_balance') or {}
    version = profile.get('local_mechanics_version')
    expected = SOURCE_SHA256.get(arena.geometry.id)
    return (type(version) is int and version == VERSION
            and profile.get('map_id') == arena.geometry.id
            and expected is not None
            and arena.geometry.data.get('source', {}).get('sha256') == expected)
