package game

import "math"

// ----- Combat Constants -----

const (
	// ArmorConstant K: determines how effective armor is.
	// K=200: 200 armor => 50% damage reduction.
	// Community formula uses 200; Python reference uses 300.
	ArmorConstant float64 = 200

	// DefaultCritMultiplier is the damage multiplier when a critical hit lands.
	DefaultCritMultiplier float64 = 2.0
)

// ----- Combat Stats -----

// CombatStats holds the base combat stats for a battle actor (tank/NPC).
// These are the base values AFTER quân hàm + tinh thể flat buffs are applied.
// Mirrors Python: iAttack, iEgAtk, iArmor, iEgArmor, iCentesis, iEgCtsis
type CombatStats struct {
	Attack    float64 // Physical attack (iAttack)
	EnergyAtk float64 // Energy attack (iEgAtk)
	Armor     float64 // Physical defense (iArmor)
	EnergyDef float64 // Energy defense (iEgArmor)
	Pierce    float64 // Physical penetration (iCentesis)
	EnergyPen float64 // Energy penetration (iEgCtsis)
}

// ----- Stat Calculation -----

// StatValue computes a combat stat with percentage and flat bonuses.
//
// Formula: base * (1 + bonusPct) + bonusFlat
//
// bonusPct comes from attr_bonus() — skill buffs, tinh thể (crystal kind=2).
// bonusFlat comes from additional runtime flat modifiers (rare, most flat
// is baked into base from quân hàm / tinh thể kind=1 before battle).
func StatValue(base, bonusPct, bonusFlat float64) float64 {
	return base*(1+bonusPct) + bonusFlat
}

// ----- Effective Armor -----

// EffectiveArmor calculates armor after buffs, reductions, and penetration.
//
// Formula (community):
//   [Defense] = (DEF_base * (1 + Σ DEF_%) + Σ DEF_flat) * (1 - DEF_Reduction%)
//   [Pierce]  = Pierce (already computed via StatValue by caller)
//   effective = [Defense] - [Pierce], floored at 0
//
// Parameters:
//   - armor:        target's base armor for this school
//   - defBonusPct:  target's DEF % buff (from attr_bonus, skills)
//   - defBonusFlat: target's DEF flat buff (runtime additions)
//   - reductionPct: debuff % that reduces target's armor (0.0-1.0)
//   - pierce:       attacker's total pierce stat (already computed with StatValue)
func EffectiveArmor(armor, defBonusPct, defBonusFlat, reductionPct, pierce float64) float64 {
	// Step 1: compute [Defense] = (base * (1 + DEF_%) + DEF_flat) * (1 - reduction%)
	def := StatValue(armor, defBonusPct, defBonusFlat) * (1 - reductionPct)

	// Step 2: subtract pierce
	ea := def - pierce

	// Step 3: floor at 0 (no negative armor)
	if ea < 0 {
		ea = 0
	}
	return ea
}

// ArmorMultiplier returns the damage multiplier from armor.
// Formula: K / (K + effectiveArmor)
// When effectiveArmor = 0: returns 1.0 (full damage)
// When effectiveArmor = K: returns 0.5 (half damage)
func ArmorMultiplier(effectiveArmor float64) float64 {
	if effectiveArmor <= 0 {
		return 1.0
	}
	return ArmorConstant / (ArmorConstant + effectiveArmor)
}

// ----- Damage Calculation -----

// DamageParams holds all inputs for a damage calculation.
type DamageParams struct {
	// Raw damage = [ATK] * [DMG%]
	// Where [ATK] = StatValue(base_atk, atk_bonus_pct, atk_bonus_flat)
	// and [DMG%] = skill damage ratio (e.g. 1.0 = 100% ATK)
	// Caller computes this before calling CalculateDamage.
	Raw float64

	// School: "physical", "energy", or "true"
	School string

	// Attacker's pierce stat (already computed with StatValue if needed)
	Pierce float64

	// Target's armor
	TargetArmor    float64 // Target's base armor for this school
	DefBonusPct    float64 // Target's DEF % buff (from skills/attr_bonus)
	DefBonusFlat   float64 // Target's DEF flat buff (runtime)
	ArmorReduction float64 // Debuff % reducing target's armor (0.0-1.0)

	// Multipliers
	DMGBonus       float64 // Outgoing damage bonus (attacker side, 0.0 = no bonus)
	IncomingBonus  float64 // Incoming damage bonus on target (debuffs, 0.0 = no bonus)
	Critical       bool    // Whether this hit is a critical strike
	CritMultiplier float64 // Crit multiplier (0 or <1 defaults to 2.0)

	// Damage reductions (each 0.0-1.0, applied multiplicatively like Python)
	Reductions []float64
}

// CalculateDamage computes final damage based on BB formula (matches Python).
//
// DMG = Raw * [CRIT] * [OutFactor] * [ArmorFactor] * [InFactor] * Π(1-reduction_i)
//
// Where:
//   - Raw              = [ATK]*[DMG%] (computed by caller)
//   - [CRIT]           = CritMultiplier if critical, else 1
//   - [OutFactor]      = max(0, 1 + DMGBonus)
//   - [ArmorFactor]    = K / (K + EffectiveArmor)
//   - [InFactor]       = max(0, 1 + IncomingBonus)
//   - Π(1-reduction_i) = multiplicative reductions
//
// True damage bypasses armor, crit, and reductions.
func CalculateDamage(p DamageParams) float64 {
	if p.Raw <= 0 {
		return 0
	}

	value := p.Raw

	// True damage: bypass everything
	if p.School == "true" {
		return math.Round(value)
	}

	// [CRIT]
	if p.Critical {
		cm := p.CritMultiplier
		if cm < 1 {
			cm = DefaultCritMultiplier
		}
		value *= cm
	}

	// Armor factor: K / (K + effective_armor)
	ea := EffectiveArmor(p.TargetArmor, p.DefBonusPct, p.DefBonusFlat, p.ArmorReduction, p.Pierce)

	// [OutFactor] * [ArmorFactor] * [InFactor]  (same order as Python line 162)
	outFactor := 1.0 + p.DMGBonus
	if outFactor < 0 {
		outFactor = 0
	}
	inFactor := 1.0 + p.IncomingBonus
	if inFactor < 0 {
		inFactor = 0
	}
	value *= outFactor * ArmorMultiplier(ea) * inFactor

	// Reductions: multiplicative Π(1-r)  (Python line 163-164)
	for _, r := range p.Reductions {
		if r > 0 && r <= 1 {
			value *= (1 - r)
		}
	}

	// Floor at 0, round
	if value < 0 {
		value = 0
	}
	return math.Round(value)
}

// ----- Convenience helpers -----

// PhysicalDamage calculates physical damage with base stats only (no runtime buffs).
func PhysicalDamage(raw float64, attacker, target *CombatStats) float64 {
	return CalculateDamage(DamageParams{
		Raw:         raw,
		School:      "physical",
		Pierce:      attacker.Pierce,
		TargetArmor: target.Armor,
	})
}

// EnergyDamage calculates energy damage with base stats only (no runtime buffs).
func EnergyDamage(raw float64, attacker, target *CombatStats) float64 {
	return CalculateDamage(DamageParams{
		Raw:         raw,
		School:      "energy",
		Pierce:      attacker.EnergyPen,
		TargetArmor: target.EnergyDef,
	})
}
