"""Shared combat arithmetic, provisionally using the balance team's V1 rules.

Ported from BangBang_BanGiao_CongThuc_V1/reference/core_math.py (2026-09-26).
This is NOT recovered original-server code. Verified original behavior takes
precedence; conflicting or unresolved gameplay rules require a user decision.
No damage handler is activated merely by importing this module.

Python 3.10+; standard library only. Numeric inputs are int, str, Decimal.
Float/None/non-finite values fail rather than silently choosing a coefficient.
See tai_lieu/01_LUAT_TOAN_HIEU_LUC.md for scope, ordering and authored design choices.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from decimal import Decimal, Context, ROUND_HALF_UP, localcontext
from functools import wraps
from typing import Callable, Iterable, Mapping, TypeAlias, TypeVar

Number: TypeAlias = int | str | Decimal
CTX = Context(prec=60, rounding=ROUND_HALF_UP)
ZERO = Decimal('0')
ONE = Decimal('1')
Q = Decimal('0.001')
K = Decimal('300')
F = TypeVar('F', bound=Callable)
RULESET_SOURCE = 'balance_v1_provisional'

class UnresolvedFormula(ValueError):
    """A semantic decision is missing. Do not run the associated skill branch."""


def deterministic(fn: F) -> F:
    @wraps(fn)
    def call(*args, **kwargs):
        with localcontext(CTX):
            return fn(*args, **kwargs)
    return call  # type: ignore[return-value]


def D(value: Number) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise TypeError('Use int/str/Decimal; floats, bool and missing values are not accepted.')
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError('Non-finite numeric input.')
    return result


def positive(value: Number, *, allow_zero: bool = True) -> Decimal:
    n = D(value)
    if n < 0 or (not allow_zero and n == 0):
        raise ValueError('Expected a nonnegative number.' if allow_zero else 'Expected a positive number.')
    return n


def fraction(value: Number) -> Decimal:
    n = D(value)
    if not ZERO <= n <= ONE:
        raise ValueError('Expected a fraction in [0, 1], e.g. "0.25" for 25%.')
    return n


def int_ms(n: int, *, positive_only: bool = False) -> int:
    if isinstance(n, bool) or not isinstance(n, int) or n < (1 if positive_only else 0):
        raise ValueError('Time is integer milliseconds with a valid nonnegative range.')
    return n


@deterministic
def quantize(value: Number) -> Decimal:
    return D(value).quantize(Q, rounding=ROUND_HALF_UP)


@deterministic
def stat(base: Number, *, flat_pre: Iterable[Number] = (),
         percent_add: Iterable[Number] = (), independent_multipliers: Iterable[Number] = (),
         flat_post: Iterable[Number] = (), lower_bound: Number | None = 0) -> Decimal:
    """One stat. Generic and specific modifiers enter the same additive pool.
    Use lower_bound=None for armor debuffs that are allowed to make armor negative.
    The caller must resolve modifier stacking/deduplication before this function.
    """
    value = (D(base) + sum((D(x) for x in flat_pre), ZERO))
    value *= max(ZERO, ONE + sum((D(x) for x in percent_add), ZERO))
    for factor in independent_multipliers:
        value *= positive(factor)
    value += sum((D(x) for x in flat_post), ZERO)
    if lower_bound is not None:
        value = max(D(lower_bound), value)
    return value  # Do not quantize intermediate stats.


@deterministic
def effective_armor(armor: Number, *, reduction_pct: Number = 0,
                    reduction_flat: Number = 0, penetration_pct: Number = 0,
                    penetration_flat: Number = 0) -> Decimal:
    a = D(armor) * (ONE - fraction(reduction_pct)) - positive(reduction_flat)
    pp, pf = fraction(penetration_pct), positive(penetration_flat)
    # Penetration cannot create negative armor or strengthen an existing negative debuff.
    return a if a < 0 else max(ZERO, a * (ONE - pp) - pf)


@deterministic
def armor_multiplier(effective: Number, *, armor_constant: Number = K) -> Decimal:
    """Armor factor; callers must explicitly opt in to a non-V1 constant.

    M81323 uses a frozen native NPC iK only for newly profiled PvE targets as
    an offline calibration. The default remains V1 K300 for players, PvP,
    old unprofiled battles, and every existing arithmetic caller.
    """
    a = D(effective)
    k = positive(armor_constant, allow_zero=False)
    return k / (k + a) if a >= 0 else 2 - k / (k - a)


@deterministic
def damage_amount(raw: Number, *, school: str, armor: Number = 0,
                  reduction_pct: Number = 0, reduction_flat: Number = 0,
                  penetration_pct: Number = 0, penetration_flat: Number = 0,
                  source_condition_multiplier: Number = 1,
                  target_class_multiplier: Number = 1,
                  outgoing_bonus: Number = 0, incoming_bonus: Number = 0,
                  reductions: Iterable[Number] = (), critical: bool = False,
                  can_critical: bool = False, critical_multiplier: Number = 2,
                  immune: bool = False, inverse_armor: bool = False,
                  armor_constant: Number = K) -> Decimal:
    """Returns potential damage BEFORE shields and HP, rounded at event commit.

    For true damage V1 bypasses armor/critical/general amps/reductions, but retains
    explicit source-condition/target-class formula factors and immunity. A skill
    requiring different true-damage semantics must declare an explicit override.
    armor_constant is a target-side, explicitly opted-in PvE calibration;
    default V1 K300 and all existing school/order rules stay unchanged.
    """
    if school not in {'physical', 'energy', 'true'}:
        raise ValueError('School must be physical, energy, or true.')
    raw = positive(raw)
    # Validate even for true damage/immunity so bad frozen profiles cannot hide
    # behind branches that do not happen to use the armor stage on this hit.
    armor_k = positive(armor_constant, allow_zero=False)
    cm = positive(critical_multiplier)
    if cm < 1:
        raise ValueError('Critical multiplier must be >=1.')
    if critical and (not can_critical or school == 'true'):
        raise ValueError('This packet is not eligible to critical strike.')
    # Validate even in immune branches, so bad data cannot hide behind immunity.
    armor_value = effective_armor(armor, reduction_pct=reduction_pct,
                                  reduction_flat=reduction_flat,
                                  penetration_pct=penetration_pct,
                                  penetration_flat=penetration_flat)
    rs = [fraction(x) for x in reductions]
    value = raw * positive(source_condition_multiplier) * positive(target_class_multiplier)
    out_factor, in_factor = max(ZERO, ONE + D(outgoing_bonus)), max(ZERO, ONE + D(incoming_bonus))
    if immune:
        return quantize(0)
    if school != 'true':
        value *= cm if critical else ONE
        if inverse_armor:
            # Q69: use reduced armor before penetration; replace this stage.
            a = max(ZERO,effective_armor(armor,reduction_pct=reduction_pct,reduction_flat=reduction_flat))
            armor_factor = ONE+a/(armor_k+a)
        else:
            armor_factor = armor_multiplier(armor_value, armor_constant=armor_k)
        value *= out_factor * armor_factor * in_factor
        for reduction in rs:
            value *= ONE - reduction
    return quantize(value)


@dataclass(frozen=True)
class Shield:
    shield_id: str
    remaining: Number
    school: str = 'all'
    expires_ms: int = 2**63 - 1


@dataclass(frozen=True)
class HitResult:
    potential_damage: Decimal
    shield_absorbed: Decimal
    hp_loss: Decimal
    hp_after: Decimal
    overkill: Decimal
    killed: bool
    shields: tuple[Shield, ...]
    broken_shield_ids: tuple[str, ...]


@deterministic
def apply_damage(amount: Number, hp: Number, shields: Iterable[Shield] = (), *,
                 school: str, now_ms: int = 0, hp_floor: Number = 0) -> HitResult:
    """Specialized shields -> all shields; each group earlier expiry -> stable id.
    This pure reducer emits break/kill facts. It does not dispatch combat triggers.
    Expired shields are removed without a break event. Dead targets stay dead.
    """
    if school not in {'physical', 'energy', 'true'}:
        raise ValueError('Unknown damage school.')
    int_ms(now_ms)
    potential, health = quantize(positive(amount)), quantize(positive(hp))
    floor = quantize(positive(hp_floor))
    if health > 0 and floor > health:
        raise ValueError('HP floor must not increase current HP.')
    remaining: dict[str, Shield] = {}
    seen = set()
    for s in shields:
        if s.shield_id in seen or not s.shield_id:
            raise ValueError('Shield IDs must be unique and nonempty.')
        seen.add(s.shield_id)
        if s.school not in {'all', 'physical', 'energy', 'true'}:
            raise ValueError('Unknown shield school.')
        int_ms(s.expires_ms)
        value = quantize(positive(s.remaining))
        if s.expires_ms > now_ms and value > 0:
            remaining[s.shield_id] = replace(s, remaining=value)
    if health == 0:
        return HitResult(potential, quantize(0), quantize(0), health, quantize(0), False,
                         tuple(remaining.values()), ())
    matching = sorted((s for s in remaining.values() if s.school in {'all', school}),
                      key=lambda s: (s.school == 'all', s.expires_ms, s.shield_id))
    left, absorbed, broken = potential, ZERO, []
    for s in matching:
        used = min(D(s.remaining), left)
        left -= used
        absorbed += used
        new_amount = D(s.remaining) - used
        if new_amount == 0 and used > 0:
            broken.append(s.shield_id)
            del remaining[s.shield_id]
        else:
            remaining[s.shield_id] = replace(s, remaining=new_amount)
        if left == 0:
            break
    lost = min(left, max(ZERO, health - floor))
    after = health - lost
    return HitResult(potential, absorbed, lost, after, left - lost, after == 0 and health > 0,
                     tuple(remaining.values()), tuple(broken))


@dataclass(frozen=True)
class HealResult:
    potential_heal: Decimal
    effective_heal: Decimal
    hp_after: Decimal
    overheal: Decimal


@deterministic
def heal(raw: Number, hp: Number, max_hp: Number, *, outgoing_bonus: Number = 0,
         incoming_bonus: Number = 0, wound_reductions: Iterable[Number] = ()) -> HealResult:
    """No revival, critical strikes, armor, or automatic overheal-to-shield conversion."""
    amount, current, maximum = positive(raw), quantize(positive(hp)), quantize(positive(max_hp, allow_zero=False))
    if maximum <= 0 or current > maximum:
        raise ValueError('Invalid HP state.')
    amount *= max(ZERO, ONE + D(outgoing_bonus)) * max(ZERO, ONE + D(incoming_bonus))
    for r in wound_reductions:
        amount *= ONE - fraction(r)
    amount = quantize(amount)
    effective = min(amount, maximum - current) if current > 0 else quantize(0)
    return HealResult(amount, effective, current + effective, amount - effective)


@deterministic
def heal_conversion(actual_enemy_hp_loss: Number, ratio: Number) -> Decimal:
    """No arbitrary 100% upper cap: a described 125% vamp remains possible.
    Caller must exclude overkill, shields, ally/self HP changes, and duplicate procs.
    Pass this raw healing result into heal() once.
    """
    return positive(actual_enemy_hp_loss) * positive(ratio)


@deterministic
def hp_after_max_change(hp: Number, old_max: Number, new_max: Number) -> Decimal:
    current, old, new = positive(hp), positive(old_max, allow_zero=False), positive(new_max, allow_zero=False)
    if current > old:
        raise ValueError('HP exceeds old maximum.')
    # Arithmetic only; does not emit a heal/loss event.
    return min(quantize(new), quantize(current / old * new))


@deterministic
def atomic_ratio_swap(hp_a: Number, max_a: Number, hp_b: Number, max_b: Number) -> tuple[Decimal, Decimal]:
    """Abstract ally-ratio primitive; Dracula's enemy branch is in mechanics.py.
    Input states must be captured simultaneously by the skill executor.
    """
    a, am = positive(hp_a, allow_zero=False), positive(max_a, allow_zero=False)
    b, bm = positive(hp_b, allow_zero=False), positive(max_b, allow_zero=False)
    if a > am or b > bm:
        raise ValueError('HP exceeds maximum.')
    na, nb = quantize(b / bm * am), quantize(a / am * bm)
    return min(quantize(am), max(min(ONE, am), na)), min(quantize(bm), max(min(ONE, bm), nb))


@deterministic
def split_total(total: Number, count: int) -> tuple[Decimal, ...]:
    """Allocate rounded total into count milli-HP packets, preserving exact sum.
    Earliest packets get one extra 0.001 until remainder is exhausted.
    This is allocation only; it does NOT decide an unknown skill's tick count.
    """
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100000:
        raise ValueError('Count must be an integer in [1, 100000].')
    units = int(quantize(positive(total)) / Q)
    q, r = divmod(units, count)
    return tuple(Decimal(q + (i < r)) * Q for i in range(count))


def tick_offsets(duration_ms: int, interval_ms: int, *, immediate: bool = False) -> tuple[int, ...]:
    int_ms(duration_ms)
    int_ms(interval_ms, positive_only=True)
    if duration_ms // interval_ms > 100000:
        raise ValueError('Unreasonable tick count.')
    return ((0,) if immediate else ()) + tuple(range(interval_ms, duration_ms + 1, interval_ms))


@deterministic
def cooldown_ms(base_ms: int, cdr_add: Iterable[Number] = ()) -> int:
    int_ms(base_ms)
    cdr = min(D('0.50'), max(ZERO, sum((D(x) for x in cdr_add), ZERO)))
    result = D(base_ms) * (ONE - cdr)
    return int(result.to_integral_value(rounding='ROUND_CEILING')) if base_ms else 0


@deterministic
def fire_interval_ms(base_ms: int, speed_bonus_add: Iterable[Number] = ()) -> int:
    int_ms(base_ms, positive_only=True)
    factor = min(D('3'), max(D('0.25'), ONE + sum((D(x) for x in speed_bonus_add), ZERO)))
    return max(1, int((D(base_ms) / factor).to_integral_value(rounding='ROUND_CEILING')))


def reduce_cooldown_flat(remaining_ms: int, amount_ms: int) -> int:
    return max(0, int_ms(remaining_ms) - int_ms(amount_ms))


@deterministic
def reduce_cooldown_percent(remaining_ms: int, ratio: Number, *, basis: str, base_ms: int | None = None) -> int:
    int_ms(remaining_ms)
    r = fraction(ratio)
    if basis == 'remaining':
        b = remaining_ms
    elif basis == 'base' and base_ms is not None:
        b = int_ms(base_ms)
    else:
        raise UnresolvedFormula('A percent cooldown reduction requires explicit base/remaining basis.')
    value = max(ZERO, D(remaining_ms) - D(b) * r)
    return int(value.to_integral_value(rounding='ROUND_CEILING'))


@dataclass(frozen=True)
class Charges:
    maximum: int
    available: int
    recharge_ms: int
    remaining_ms: int | None = None
    gap_remaining_ms: int = 0

    def __post_init__(self):
        if any(isinstance(x, bool) or not isinstance(x, int) for x in [self.maximum, self.available]):
            raise ValueError('Charges must be integers.')
        if not self.maximum >= self.available >= 0 or self.maximum < 1:
            raise ValueError('Invalid charge count.')
        int_ms(self.recharge_ms, positive_only=True)
        int_ms(self.gap_remaining_ms)
        if self.available == self.maximum:
            if self.remaining_ms is not None:
                raise ValueError('A full charge pool has no running recharge timer.')
        elif self.remaining_ms is None:
            raise ValueError('A non-full charge pool requires a running timer.')
        else:
            int_ms(self.remaining_ms, positive_only=True)

    def spend(self, use_gap_ms: int) -> Charges:
        int_ms(use_gap_ms)
        if self.available == 0 or self.gap_remaining_ms > 0:
            raise ValueError('Skill is not ready.')
        return replace(self, available=self.available - 1,
                       remaining_ms=self.recharge_ms if self.available == self.maximum else self.remaining_ms,
                       gap_remaining_ms=use_gap_ms)

    def advance(self, elapsed_ms: int) -> Charges:
        dt = int_ms(elapsed_ms)
        gap = max(0, self.gap_remaining_ms - dt)
        available, timer = self.available, self.remaining_ms
        while available < self.maximum and timer is not None and dt >= timer:
            dt -= timer
            available += 1
            timer = self.recharge_ms if available < self.maximum else None
        if timer is not None:
            timer -= dt
        return replace(self, available=available, remaining_ms=timer, gap_remaining_ms=gap)

    def reset(self, *, clear_gap: bool) -> Charges:
        return replace(self, available=self.maximum, remaining_ms=None,
                       gap_remaining_ms=0 if clear_gap else self.gap_remaining_ms)


@dataclass(frozen=True)
class OwnedSkin:
    tank_id: str
    quality: int
    owned: bool
    activity_valid: bool  # Already resolved by the client's eligibility adapter.


def active_skin_types(tank_id: str, skins: Iterable[OwnedSkin]) -> frozenset[int]:
    """Exact per-tank rank/collection condition from supplied hasSkinAttrActive.
    Ownership/time validity are external inputs, not guessed from item lifetime.
    The equipped skin is deliberately absent from this API.
    """
    qualities = {s.quality for s in skins if s.tank_id == tank_id and s.owned and s.activity_valid and s.quality in {2,3,4,5}}
    active = {q - 1 for q in qualities}
    if len(qualities) >= 1: active.add(11)
    if len(qualities) >= 2: active.add(12)
    if len(qualities) >= 3 and 5 in qualities: active.add(13)
    if len(qualities) == 4: active.add(14)
    return frozenset(active)


@deterministic
def skin_bonuses(tank_id: str, active_types: Iterable[int], typed_rows: Iterable[Mapping]) -> dict:
    """Sum active bonus ROWS once, not once per inventory item or equipped skin."""
    active = set(active_types)
    pct: dict[int, Decimal] = {}
    flat: dict[int, Decimal] = {}
    buffs: set[str] = set()
    seen: set[int] = set()
    for row in typed_rows:
        if row['tank_id'] != tank_id or row['active_type'] not in active:
            continue
        ident = row['row_1based']
        if ident in seen:
            raise ValueError('Duplicate bonus row supplied; do not double-count source rows.')
        seen.add(ident)
        if row['kind'] == 'born_buff_reference':
            buffs.add(str(row['buff_id']))
        elif row['kind'] == 'stat_modifier':
            vt = row['value_type']
            if vt not in {1, 2}:
                raise UnresolvedFormula('Unknown source value-type semantics.')
            bucket = flat if vt == 1 else pct
            attr = row['attribute_id']
            bucket[attr] = bucket.get(attr, ZERO) + D(row['amount'])
        else:
            raise UnresolvedFormula('Triggered skin row has no reviewed adapter.')
    return {'percent_add':pct, 'flat_pre':flat, 'born_buff_ids':sorted(buffs)}

