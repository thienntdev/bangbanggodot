"""Optional, match-frozen virtual bot equipment from the native templates.

No player inventory, Guild membership, or crystal board is read or modified.
Catalog construction happens in the lobby; combat only reads the frozen build.
"""
from copy import deepcopy
from functools import lru_cache

import storage

# These two tanks have no native level-five recommendation row. Reuse the
# corresponding native archetype's recommendation, explicitly recorded below.
RECOMMEND_FALLBACKS = {10000002: 10000032, 10000098: 10000086}
SLOTS = ('1', '5', '6', '7', '8')
BUILD_KEYS = ('bot_loadout_version', 'bot_loadout_tank', 'bot_loadout_role',
              'guild', 'guild_owned', 'crystals', 'crystal_board', 'crystal_recommendation',
              'military', 'military_star', 'bot_rank_full')


def eligible(ident, info):
    """Never inherit a bot build onto NPCs, clones, summons or map objects."""
    return (not info.get('npc_template') and
            (info.get('human',ident == 1) or (2 <= ident <= 10 and info.get('object_id') == ident
             and info.get('bot_loadout_version') == 1)))


@lru_cache(maxsize=8)
def _catalog(database):
    import crystals
    import guilds
    from combat_data import tank_stats
    _, gems, positions, _, attrs, _ = crystals.catalog()
    base = {int(r['nTankId']): r for r in storage.template_rows('TankBaseTemplate_table.xml')}
    recommendations = {int(r['nTankId']): [int(v) for v in r['szRmdCrystal'].split('|')]
                       for r in storage.template_rows('CrystalTankRmdTemplate_table.xml')
                       if int(r['nCrystalLevel']) == 5}
    max_guild = {}
    for (group, level), row in guilds.config()[0].items():
        if level > max_guild.get(group, {}).get('level', 0):
            max_guild[group] = dict(group=group, level=level, skill=int(row['nSkillTpltPvpId']))

    def level_five(ident):
        row = gems[ident]
        if int(row['iReuseD']) == 5:
            return ident
        signature = [(a, k) for a, k, _ in attrs[int(row['iReuseC'])]]
        matches = [i for i, r in gems.items() if int(r['iReuseD']) == 5
                   and r['iReuseA'] == row['iReuseA']
                   and [(a, k) for a, k, _ in attrs[int(r['iReuseC'])]] == signature]
        # Old combined armor has separate physical/energy versions at level 5.
        # The physical branch is the native same-family upgrade (5650205).
        if not matches and signature == [(2, 1)]:
            return 5650205
        if len(matches) != 1:
            raise ValueError('Ambiguous level-five recommendation: '+str(ident))
        return matches[0]

    builds = {}
    for tank, row in base.items():
        source = RECOMMEND_FALLBACKS.get(tank, tank)
        if source not in recommendations:
            continue
        selected = [level_five(i) for i in recommendations[source]]
        by_color = {int(gems[i]['iReuseA']): i for i in selected}
        if len(by_color) != 3 or set(positions) != set(range(1, 31)):
            raise ValueError('Native bot crystal board has invalid colors/slots')
        board = [by_color[positions[p]] for p in range(1, 31)]
        stats = tank_stats(tank, 6)
        from combat_math import D
        energy = D(stats['iEgAtk']) > D(stats['iAttack'])
        if D(stats['iEgAtk']) == D(stats['iAttack']):
            energy = any(a == 5 for i in selected for a, _, _ in attrs[int(gems[i]['iReuseC'])])
        attack, penetration = (1700, 2200) if energy else (1600, 2100)
        kind, desc = int(row['nClassification']), row.get('szDescription', '')
        if kind == 2:
            role, groups = 'tank', (1500, 1200, 1300, 1400, 2800)
        elif kind == 3:
            role, groups = 'support', (1100, 1200, 1300, 1400, attack)
        elif '射手' in desc or 'Xạ thủ' in desc or tank == 10000101:
            role, groups = 'marksman', (1800, attack, penetration, 2500, 2800)
        elif '刺客' in desc or 'Sát thủ' in desc:
            role, groups = 'assassin', (3100, attack, penetration, 1200, 2800)
        elif '法师' in desc or 'Pháp sư' in desc:
            role, groups = 'caster', (3300, attack, penetration, 1200, 2800)
        else:
            role, groups = 'fighter', (2600, attack, penetration, 1200, 2800)
        builds[tank] = dict(role=role, guild={s: max_guild[g] for s, g in zip(SLOTS, groups)},
            board=board, crystals=[list(a) for i in board for a in attrs[int(gems[i]['iReuseC'])]],
            recommendation=dict(tank=source, native=source == tank, sourceItems=recommendations[source],
                                levelFiveItems=selected))
    return builds, {str(g): v['level'] for g, v in max_guild.items()}


def catalog():
    return _catalog(str(storage.database_path()))


def apply(bot, setup):
    """Freeze optional gear; a ranked bot's own Gold+ rating enables all three.

    Rank is authoritative at selection / new battle entry. No combat tick,
    respawn or checkpoint restore calls this function to re-evaluate gear.
    """
    for key in BUILD_KEYS:
        bot.pop(key, None)
    from ranked_matches import section
    ranked_full = bool(setup.get('ranked') and section(bot.get('elo', 1000))['type'] >= 3)
    guild_on = ranked_full or setup.get('bot_guild', False)
    crystals_on = ranked_full or setup.get('bot_crystals', False)
    military_on = ranked_full or setup.get('bot_military', False)
    if not (guild_on or crystals_on or military_on):
        return
    builds, owned = catalog()
    build = builds[bot['tank_id']]
    bot.update(bot_loadout_version=1, bot_loadout_tank=bot['tank_id'], bot_loadout_role=build['role'])
    if ranked_full:
        bot['bot_rank_full'] = True
    if military_on:
        from military_rank import maximum_build
        military = maximum_build()
        bot.update(military=military, military_star=military['stars'])
    if guild_on:
        bot.update(guild=deepcopy(build['guild']), guild_owned=dict(owned))
    if crystals_on:
        bot.update(crystal_board=list(build['board']), crystals=deepcopy(build['crystals']),
                   crystal_recommendation=deepcopy(build['recommendation']))
