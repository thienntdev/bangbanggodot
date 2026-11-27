"""Per-match virtual-bot looks. Never reads/writes a player's inventory."""
import json
import random
from tank_halos import SUPPORTED as HALOS
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    value=json.loads(Path(__file__).with_name('bot_cosmetic_catalog.json').read_text(encoding='utf8'))
    if value.get('schemaVersion')!=1:raise ValueError('Unsupported bot cosmetic catalog')
    return value


def valid_avatar(value):
    """Saved virtual bots may contain the old icon-only pool; repair without RNG."""
    return value if value in catalog()['avatars'] else 2801001


def _look_rng(rng):
    cloned=random.Random()
    try:
        cloned.setstate(rng.getstate())
    except NotImplementedError:
        cloned=random.SystemRandom()
    return cloned


def roll(bot,rng=None,*,skin_only=False):
    rng=rng or random.SystemRandom()
    pool=catalog()
    choices=pool['skins'].get(str(bot['tank_id']))
    if not choices:raise ValueError('Bot tank has no verified cosmetic pool')
    bot['tank_ext']=rng.choice(choices)
    bot['cosmetics_tank_id']=bot['tank_id']
    if not skin_only:
        avatar_rng=_look_rng(rng)
        # Preserve the old stream position so a narrower fashion pool cannot
        # change subsequent tank/skin/background draws in the seeded roster.
        rng.randrange(pool['avatarRollCount'])
        bot['avatar']=avatar_rng.choice(pool['avatars'])
        bot['decorate_id']=rng.choice(pool['backgrounds'])
        # Cosmetic-only stream: adding a halo must not advance the existing
        # seeded roster/tank/skin choices, nor the arena's gameplay RNG.
        halo_rng = _look_rng(rng)
        bot['halo_id']=halo_rng.choice([0, *sorted(HALOS)])


def prepare_selection(state,*,resuming=False,rng=None):
    # A repeated C212 and reconnect must retain exactly the same choices.
    if resuming or state.get('battle') or (state.get('room') or {}).get('tank_test'):return
    bots=[b for b in state.get('bots',[]) if b.get('in_room',True)]
    if state.pop('bot_cosmetics_prepared',False) and all(b.get('cosmetics_tank_id')==b['tank_id'] for b in bots):return
    for bot in bots:roll(bot,rng)
