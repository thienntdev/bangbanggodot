"""M45 explicitly reviewed boxes; no native Drop table is inferred.

The user authorized 10% main prize / 90% common materials. Each conditional
pool is uniform. Planning every outcome before the draw prevents bag capacity
or an already-owned permanent tank from becoming a free rare-prize reroll.
Only normal_shop calls this module inside its authenticated transaction.
"""
from __future__ import annotations

from copy import deepcopy
import secrets

import economy_actions
import mail_rewards
import storage
from mail_rewards import RewardError


def require_usable_main(box, containers, garage, available):
    """Do not sell an egg whose permanent main prize is already owned.

    Purchase needs space for the egg only. Reward space is checked separately
    when opening; this guard concerns an irreversible ownership conflict.
    """
    if box['mode'] != 'random':
        return
    for reward in mail_rewards.normalize(box['main_rewards'], available):
        if not reward['unique']:
            continue
        if reward['kind'] == 'tank':
            owned = any(row['tank_id'] == reward['id'] and int(row.get('cont_type', 0)) == 0 for row in garage)
        elif reward['kind'] == 'item':
            owned = any(row['template_id'] == reward['id'] and row['count'] > 0 and not row.get('life_time')
                        for row in containers.get(str(reward['container']), []))
        else:
            owned = False
        if owned:
            raise RewardError('already_owned',
                              'Bạn đã sở hữu phần thưởng vĩnh viễn trong hộp. Không thể mua thêm hộp này; '
                              'chưa trừ tiền. Không quay lại hoặc đổi phần thưởng trùng.', {'key': reward['key']})


def outcomes(box):
    """Return all possible rewards, without choosing or consuming randomness."""
    if box['mode'] == 'fixed':
        return [('fixed', deepcopy(box['fixed_rewards']))]
    if box['mode'] != 'random' or box.get('main_percent') != 10 or box.get('material_percent') != 90:
        raise RewardError('box_config', 'Hộp chưa có cấu hình phần thưởng đã kiểm tra.')
    return ([('main', [deepcopy(row)]) for row in box['main_rewards']]
            + [('material', [deepcopy(row)]) for row in box['material_rewards']])


def plans(db, box, ref, available):
    """Read-only plans for every allowed branch; preserve the box on any error.

    Current reviewed eggs award tanks/helpers/materials and the sole fixed
    present awards Bạc. None awards a grocery item, so planning the grant before
    removing the grocery box has exactly the same capacity as consume-first.
    Refuse any future catalog expansion that invalidates that invariant.
    """
    values = []
    for outcome, rewards in outcomes(box):
        for row in rewards:
            descriptor = available.get(row['kind'] + ':' + str(row['id']), {})
            if row['kind'] == 'item' and descriptor.get('container') == ref['container']:
                raise RewardError('box_config', 'Hộp có phần thưởng cùng ngăn chưa được kiểm tra; chưa mở hộp.')
        try:
            value = mail_rewards.plan(db, storage.profile_id(), rewards, available)
        except RewardError as exc:
            if exc.code == 'already_owned':
                raise RewardError('already_owned',
                                  'Bạn đã sở hữu phần thưởng vĩnh viễn trong hộp. Hộp được giữ nguyên; '
                                  'không quay lại hoặc đổi thành vật phẩm khác.', exc.details) from exc
            if exc.code == 'bag_full':
                raise RewardError('bag_full',
                                  'Cần đủ chỗ cho mọi phần thưởng có thể nhận. Dọn túi rồi mở lại; '
                                  'hộp được giữ nguyên.', exc.details) from exc
            if exc.code == 'wallet_overflow':
                raise RewardError('wallet_overflow', 'Ví sẽ vượt giới hạn; hộp được giữ nguyên.') from exc
            raise
        item = economy_actions._lookup(value['containers'], ref)
        economy_actions._protection(item)
        item['count'] -= 1
        if item['count'] == 0:
            value['containers'][str(ref['container'])].remove(item)
        values.append(dict(outcome=outcome, value=value))
    if not values:
        raise RewardError('box_config', 'Hộp chưa có phần thưởng hợp lệ.')
    return values


def select(values):
    """Only call after proof and all branch preflights, immediately before save."""
    if len(values) == 1 and values[0]['outcome'] == 'fixed':
        return values[0]
    outcome = 'main' if secrets.randbelow(100) < 10 else 'material'
    pool = [value for value in values if value['outcome'] == outcome]
    if not pool:
        raise RewardError('box_config', 'Nhánh phần thưởng chưa có cấu hình hợp lệ.')
    return pool[0] if len(pool) == 1 else pool[secrets.randbelow(len(pool))]
