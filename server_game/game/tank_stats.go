package game

// TankBaseStats holds base combat stats at level 1 from TankUpTemplate_table.xml.
// Fields map to XML: iHp, iArmor, iAttack, iCentesis, iEgArmor, iEgAtk, iEgCtsis, iFireInterv, iSpeed, iMp, nFireRange.
type TankBaseStats struct {
	HP        int32
	Armor     int32
	Attack    int32
	Pierce    int32
	EnergyDef int32
	EnergyAtk int32
	EnergyPen int32
	FireRateMS int32
	MoveSpeed int32
	MP        int32
	Range     int32
}

// tankBaseStatsTable maps tankID → base stats at level 1 from TankUpTemplate_table.xml.
// Auto-generated from BangBang_Offline/data/xmlpack/TankUpTemplate_table.xml.
var tankBaseStatsTable = map[uint32]TankBaseStats{
	10000001: {HP: 2325, Armor: 150, Attack: 238, Pierce: 30, EnergyDef: 150, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 170, MP: 100, Range: 480},
	10000002: {HP: 4510, Armor: 254, Attack: 118, Pierce: 18, EnergyDef: 327, EnergyAtk: 230, EnergyPen: 28, FireRateMS: 900, MoveSpeed: 155, MP: 100, Range: 336},
	10000003: {HP: 4300, Armor: 258, Attack: 246, Pierce: 27, EnergyDef: 335, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 150, MP: 100, Range: 336},
	10000008: {HP: 2350, Armor: 128, Attack: 107, Pierce: 18, EnergyDef: 155, EnergyAtk: 271, EnergyPen: 55, FireRateMS: 950, MoveSpeed: 165, MP: 100, Range: 408},
	10000019: {HP: 2200, Armor: 128, Attack: 107, Pierce: 18, EnergyDef: 141, EnergyAtk: 268, EnergyPen: 32, FireRateMS: 450, MoveSpeed: 170, MP: 100, Range: 552},
	10000029: {HP: 2450, Armor: 144, Attack: 107, Pierce: 18, EnergyDef: 156, EnergyAtk: 225, EnergyPen: 30, FireRateMS: 950, MoveSpeed: 165, MP: 100, Range: 480},
	10000030: {HP: 2225, Armor: 158, Attack: 254, Pierce: 32, EnergyDef: 131, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 500, MoveSpeed: 170, MP: 100, Range: 552},
	10000031: {HP: 3025, Armor: 198, Attack: 221, Pierce: 30, EnergyDef: 188, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 1000, MoveSpeed: 170, MP: 100, Range: 336},
	10000032: {HP: 4250, Armor: 251, Attack: 87, Pierce: 30, EnergyDef: 333, EnergyAtk: 190, EnergyPen: 31, FireRateMS: 950, MoveSpeed: 155, MP: 100, Range: 336},
	10000033: {HP: 2425, Armor: 144, Attack: 107, Pierce: 18, EnergyDef: 153, EnergyAtk: 266, EnergyPen: 30, FireRateMS: 500, MoveSpeed: 165, MP: 200, Range: 552},
	10000034: {HP: 4475, Armor: 333, Attack: 209, Pierce: 26, EnergyDef: 249, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 950, MoveSpeed: 150, MP: 100, Range: 336},
	10000035: {HP: 2300, Armor: 131, Attack: 107, Pierce: 18, EnergyDef: 138, EnergyAtk: 263, EnergyPen: 50, FireRateMS: 900, MoveSpeed: 165, MP: 100, Range: 408},
	10000036: {HP: 3100, Armor: 230, Attack: 249, Pierce: 35, EnergyDef: 197, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 1050, MoveSpeed: 155, MP: 100, Range: 336},
	10000037: {HP: 2525, Armor: 150, Attack: 107, Pierce: 18, EnergyDef: 149, EnergyAtk: 227, EnergyPen: 31, FireRateMS: 950, MoveSpeed: 160, MP: 100, Range: 480},
	10000038: {HP: 2800, Armor: 171, Attack: 107, Pierce: 18, EnergyDef: 171, EnergyAtk: 254, EnergyPen: 34, FireRateMS: 950, MoveSpeed: 160, MP: 100, Range: 480},
	10000039: {HP: 2375, Armor: 153, Attack: 107, Pierce: 18, EnergyDef: 176, EnergyAtk: 241, EnergyPen: 34, FireRateMS: 1000, MoveSpeed: 170, MP: 100, Range: 480},
	10000040: {HP: 4275, Armor: 320, Attack: 204, Pierce: 26, EnergyDef: 269, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 950, MoveSpeed: 160, MP: 100, Range: 336},
	10000041: {HP: 2275, Armor: 132, Attack: 266, Pierce: 27, EnergyDef: 108, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 500, MoveSpeed: 175, MP: 100, Range: 552},
	10000042: {HP: 3203, Armor: 194, Attack: 107, Pierce: 18, EnergyDef: 194, EnergyAtk: 247, EnergyPen: 38, FireRateMS: 900, MoveSpeed: 165, MP: 100, Range: 336},
	10000043: {HP: 2425, Armor: 147, Attack: 261, Pierce: 32, EnergyDef: 140, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 500, MoveSpeed: 155, MP: 100, Range: 552},
	10000044: {HP: 2575, Armor: 165, Attack: 239, Pierce: 47, EnergyDef: 135, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 850, MoveSpeed: 160, MP: 100, Range: 480},
	10000045: {HP: 4250, Armor: 275, Attack: 107, Pierce: 28, EnergyDef: 310, EnergyAtk: 201, EnergyPen: 34, FireRateMS: 1000, MoveSpeed: 155, MP: 100, Range: 336},
	10000046: {HP: 3328, Armor: 194, Attack: 274, Pierce: 29, EnergyDef: 165, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 165, MP: 100, Range: 408},
	10000047: {HP: 2950, Armor: 174, Attack: 107, Pierce: 18, EnergyDef: 174, EnergyAtk: 268, EnergyPen: 28, FireRateMS: 1000, MoveSpeed: 165, MP: 100, Range: 480},
	10000048: {HP: 2175, Armor: 161, Attack: 273, Pierce: 49, EnergyDef: 161, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 1000, MoveSpeed: 170, MP: 100, Range: 408},
	10000049: {HP: 2600, Armor: 159, Attack: 107, Pierce: 18, EnergyDef: 159, EnergyAtk: 264, EnergyPen: 29, FireRateMS: 1000, MoveSpeed: 170, MP: 100, Range: 480},
	10000050: {HP: 2800, Armor: 162, Attack: 107, Pierce: 18, EnergyDef: 162, EnergyAtk: 250, EnergyPen: 29, FireRateMS: 1050, MoveSpeed: 160, MP: 100, Range: 480},
	10000051: {HP: 2575, Armor: 144, Attack: 257, Pierce: 30, EnergyDef: 159, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 600, MoveSpeed: 155, MP: 100, Range: 552},
	10000052: {HP: 2400, Armor: 155, Attack: 107, Pierce: 18, EnergyDef: 180, EnergyAtk: 263, EnergyPen: 29, FireRateMS: 950, MoveSpeed: 160, MP: 100, Range: 480},
	10000053: {HP: 4436, Armor: 281, Attack: 224, Pierce: 29, EnergyDef: 281, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 155, MP: 100, Range: 336},
	10000054: {HP: 2575, Armor: 143, Attack: 107, Pierce: 18, EnergyDef: 153, EnergyAtk: 238, EnergyPen: 29, FireRateMS: 1000, MoveSpeed: 160, MP: 100, Range: 480},
	10000055: {HP: 2225, Armor: 147, Attack: 252, Pierce: 49, EnergyDef: 165, EnergyAtk: 252, EnergyPen: 49, FireRateMS: 1000, MoveSpeed: 170, MP: 150, Range: 408},
	10000056: {HP: 3325, Armor: 260, Attack: 250, Pierce: 33, EnergyDef: 230, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 1000, MoveSpeed: 155, MP: 100, Range: 336},
	10000057: {HP: 2425, Armor: 155, Attack: 238, Pierce: 24, EnergyDef: 182, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 850, MoveSpeed: 165, MP: 100, Range: 408},
	10000058: {HP: 2475, Armor: 147, Attack: 107, Pierce: 18, EnergyDef: 171, EnergyAtk: 268, EnergyPen: 27, FireRateMS: 1000, MoveSpeed: 175, MP: 150, Range: 480},
	10000059: {HP: 2450, Armor: 161, Attack: 107, Pierce: 18, EnergyDef: 173, EnergyAtk: 259, EnergyPen: 26, FireRateMS: 1000, MoveSpeed: 175, MP: 100, Range: 480},
	10000060: {HP: 2250, Armor: 180, Attack: 234, Pierce: 30, EnergyDef: 153, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 1000, MoveSpeed: 165, MP: 100, Range: 480},
	10000061: {HP: 2950, Armor: 197, Attack: 225, Pierce: 27, EnergyDef: 197, EnergyAtk: 225, EnergyPen: 27, FireRateMS: 900, MoveSpeed: 155, MP: 100, Range: 336},
	10000062: {HP: 3264, Armor: 206, Attack: 211, Pierce: 28, EnergyDef: 206, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 950, MoveSpeed: 155, MP: 200, Range: 336},
	10000063: {HP: 2336, Armor: 114, Attack: 293, Pierce: 45, EnergyDef: 135, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 500, MoveSpeed: 160, MP: 100, Range: 552},
	10000064: {HP: 2450, Armor: 185, Attack: 259, Pierce: 55, EnergyDef: 164, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 175, MP: 150, Range: 408},
	10000065: {HP: 2350, Armor: 165, Attack: 107, Pierce: 18, EnergyDef: 138, EnergyAtk: 256, EnergyPen: 28, FireRateMS: 900, MoveSpeed: 170, MP: 100, Range: 480},
	10000066: {HP: 4175, Armor: 255, Attack: 107, Pierce: 18, EnergyDef: 327, EnergyAtk: 214, EnergyPen: 27, FireRateMS: 950, MoveSpeed: 160, MP: 100, Range: 336},
	10000067: {HP: 3175, Armor: 243, Attack: 255, Pierce: 31, EnergyDef: 204, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 700, MoveSpeed: 175, MP: 100, Range: 336},
	10000068: {HP: 4325, Armor: 338, Attack: 107, Pierce: 18, EnergyDef: 272, EnergyAtk: 200, EnergyPen: 29, FireRateMS: 900, MoveSpeed: 155, MP: 200, Range: 336},
	10000069: {HP: 2650, Armor: 164, Attack: 107, Pierce: 18, EnergyDef: 140, EnergyAtk: 256, EnergyPen: 29, FireRateMS: 1000, MoveSpeed: 165, MP: 100, Range: 480},
	10000070: {HP: 3250, Armor: 212, Attack: 234, Pierce: 35, EnergyDef: 207, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 850, MoveSpeed: 170, MP: 100, Range: 336},
	10000071: {HP: 2700, Armor: 176, Attack: 264, Pierce: 26, EnergyDef: 168, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 850, MoveSpeed: 155, MP: 100, Range: 480},
	10000072: {HP: 2375, Armor: 125, Attack: 252, Pierce: 27, EnergyDef: 132, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 450, MoveSpeed: 170, MP: 100, Range: 552},
	10000073: {HP: 3075, Armor: 192, Attack: 220, Pierce: 30, EnergyDef: 203, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 1000, MoveSpeed: 160, MP: 100, Range: 336},
	10000074: {HP: 3125, Armor: 162, Attack: 107, Pierce: 18, EnergyDef: 179, EnergyAtk: 282, EnergyPen: 30, FireRateMS: 900, MoveSpeed: 165, MP: 100, Range: 480},
	10000075: {HP: 3325, Armor: 227, Attack: 243, Pierce: 33, EnergyDef: 206, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 160, MP: 100, Range: 336},
	10000076: {HP: 4200, Armor: 266, Attack: 207, Pierce: 26, EnergyDef: 344, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 155, MP: 100, Range: 336},
	10000077: {HP: 3125, Armor: 191, Attack: 206, Pierce: 26, EnergyDef: 165, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 850, MoveSpeed: 175, MP: 100, Range: 336},
	10000078: {HP: 2850, Armor: 167, Attack: 186, Pierce: 23, EnergyDef: 146, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 165, MP: 150, Range: 408},
	10000079: {HP: 2639, Armor: 156, Attack: 107, Pierce: 18, EnergyDef: 158, EnergyAtk: 249, EnergyPen: 30, FireRateMS: 800, MoveSpeed: 160, MP: 100, Range: 480},
	10000080: {HP: 2500, Armor: 126, Attack: 107, Pierce: 18, EnergyDef: 146, EnergyAtk: 241, EnergyPen: 27, FireRateMS: 950, MoveSpeed: 160, MP: 100, Range: 480},
	10000081: {HP: 2425, Armor: 167, Attack: 245, Pierce: 31, EnergyDef: 138, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 165, MP: 100, Range: 480},
	10000082: {HP: 3050, Armor: 216, Attack: 243, Pierce: 32, EnergyDef: 189, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 850, MoveSpeed: 175, MP: 100, Range: 480},
	10000083: {HP: 2950, Armor: 152, Attack: 132, Pierce: 18, EnergyDef: 179, EnergyAtk: 254, EnergyPen: 30, FireRateMS: 1000, MoveSpeed: 160, MP: 100, Range: 480},
	10000084: {HP: 2500, Armor: 153, Attack: 107, Pierce: 18, EnergyDef: 185, EnergyAtk: 282, EnergyPen: 34, FireRateMS: 1000, MoveSpeed: 160, MP: 100, Range: 480},
	10000085: {HP: 2625, Armor: 143, Attack: 107, Pierce: 18, EnergyDef: 162, EnergyAtk: 229, EnergyPen: 30, FireRateMS: 1000, MoveSpeed: 160, MP: 150, Range: 480},
	10000086: {HP: 3225, Armor: 149, Attack: 107, Pierce: 18, EnergyDef: 179, EnergyAtk: 306, EnergyPen: 53, FireRateMS: 1000, MoveSpeed: 160, MP: 100, Range: 480},
	10000087: {HP: 3300, Armor: 230, Attack: 214, Pierce: 33, EnergyDef: 200, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 850, MoveSpeed: 160, MP: 100, Range: 336},
	10000088: {HP: 2525, Armor: 158, Attack: 107, Pierce: 18, EnergyDef: 185, EnergyAtk: 236, EnergyPen: 28, FireRateMS: 1000, MoveSpeed: 160, MP: 100, Range: 480},
	10000089: {HP: 2275, Armor: 126, Attack: 127, Pierce: 18, EnergyDef: 134, EnergyAtk: 238, EnergyPen: 30, FireRateMS: 500, MoveSpeed: 165, MP: 100, Range: 552},
	10000090: {HP: 3225, Armor: 210, Attack: 107, Pierce: 18, EnergyDef: 231, EnergyAtk: 232, EnergyPen: 33, FireRateMS: 1000, MoveSpeed: 165, MP: 100, Range: 336},
	10000091: {HP: 4050, Armor: 318, Attack: 213, Pierce: 30, EnergyDef: 258, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 950, MoveSpeed: 165, MP: 100, Range: 336},
	10000092: {HP: 3200, Armor: 209, Attack: 107, Pierce: 18, EnergyDef: 218, EnergyAtk: 229, EnergyPen: 30, FireRateMS: 1000, MoveSpeed: 175, MP: 100, Range: 336},
	10000093: {HP: 2599, Armor: 149, Attack: 107, Pierce: 30, EnergyDef: 159, EnergyAtk: 288, EnergyPen: 52, FireRateMS: 950, MoveSpeed: 170, MP: 100, Range: 408},
	10000094: {HP: 3439, Armor: 219, Attack: 236, Pierce: 31, EnergyDef: 195, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 850, MoveSpeed: 170, MP: 100, Range: 336},
	10000095: {HP: 2310, Armor: 164, Attack: 263, Pierce: 34, EnergyDef: 137, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 500, MoveSpeed: 170, MP: 100, Range: 552},
	10000096: {HP: 2651, Armor: 164, Attack: 258, Pierce: 34, EnergyDef: 137, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 1357, MoveSpeed: 175, MP: 100, Range: 336},
	10000097: {HP: 2809, Armor: 171, Attack: 107, Pierce: 18, EnergyDef: 137, EnergyAtk: 270, EnergyPen: 30, FireRateMS: 1000, MoveSpeed: 160, MP: 100, Range: 480},
	10000098: {HP: 2756, Armor: 168, Attack: 107, Pierce: 18, EnergyDef: 183, EnergyAtk: 293, EnergyPen: 34, FireRateMS: 1000, MoveSpeed: 160, MP: 100, Range: 480},
	10000099: {HP: 3176, Armor: 218, Attack: 235, Pierce: 31, EnergyDef: 191, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 800, MoveSpeed: 165, MP: 100, Range: 336},
	10000100: {HP: 3124, Armor: 209, Attack: 251, Pierce: 45, EnergyDef: 189, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 800, MoveSpeed: 160, MP: 100, Range: 336},
	10000101: {HP: 2389, Armor: 152, Attack: 300, Pierce: 60, EnergyDef: 123, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 800, MoveSpeed: 185, MP: 100, Range: 480},
	10000102: {HP: 3229, Armor: 228, Attack: 205, Pierce: 36, EnergyDef: 200, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 160, MP: 100, Range: 336},
	10000103: {HP: 4358, Armor: 260, Attack: 222, Pierce: 29, EnergyDef: 329, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 155, MP: 100, Range: 336},
	10000104: {HP: 2520, Armor: 146, Attack: 107, Pierce: 18, EnergyDef: 129, EnergyAtk: 210, EnergyPen: 30, FireRateMS: 500, MoveSpeed: 170, MP: 100, Range: 552},
	10000105: {HP: 3004, Armor: 159, Attack: 107, Pierce: 18, EnergyDef: 164, EnergyAtk: 255, EnergyPen: 32, FireRateMS: 1000, MoveSpeed: 170, MP: 100, Range: 480},
	10000106: {HP: 2520, Armor: 147, Attack: 107, Pierce: 18, EnergyDef: 152, EnergyAtk: 264, EnergyPen: 33, FireRateMS: 1000, MoveSpeed: 170, MP: 100, Range: 480},
	10000107: {HP: 2600, Armor: 173, Attack: 107, Pierce: 18, EnergyDef: 161, EnergyAtk: 234, EnergyPen: 31, FireRateMS: 950, MoveSpeed: 170, MP: 100, Range: 480},
	10000108: {HP: 2494, Armor: 132, Attack: 107, Pierce: 18, EnergyDef: 143, EnergyAtk: 277, EnergyPen: 59, FireRateMS: 900, MoveSpeed: 180, MP: 100, Range: 408},
	10000109: {HP: 4383, Armor: 312, Attack: 227, Pierce: 30, EnergyDef: 240, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 900, MoveSpeed: 160, MP: 100, Range: 336},
	10000110: {HP: 3308, Armor: 224, Attack: 232, Pierce: 33, EnergyDef: 203, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 1000, MoveSpeed: 165, MP: 100, Range: 336},
	10000111: {HP: 2284, Armor: 149, Attack: 274, Pierce: 30, EnergyDef: 144, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 550, MoveSpeed: 175, MP: 150, Range: 552},
	10000112: {HP: 2678, Armor: 167, Attack: 107, Pierce: 18, EnergyDef: 177, EnergyAtk: 289, EnergyPen: 34, FireRateMS: 1000, MoveSpeed: 170, MP: 100, Range: 480},
	10000113: {HP: 2599, Armor: 158, Attack: 107, Pierce: 18, EnergyDef: 147, EnergyAtk: 243, EnergyPen: 30, FireRateMS: 1000, MoveSpeed: 165, MP: 100, Range: 480},
	10000114: {HP: 2258, Armor: 153, Attack: 245, Pierce: 47, EnergyDef: 158, EnergyAtk: 112, EnergyPen: 18, FireRateMS: 800, MoveSpeed: 170, MP: 100, Range: 408},
	10000115: {HP: 3071, Armor: 207, Attack: 240, Pierce: 40, EnergyDef: 192, EnergyAtk: 107, EnergyPen: 18, FireRateMS: 1000, MoveSpeed: 170, MP: 100, Range: 336},
	10000116: {HP: 1852, Armor: 153, Attack: 200, Pierce: 32, EnergyDef: 138, EnergyAtk: 81, EnergyPen: 18, FireRateMS: 750, MoveSpeed: 165, MP: 150, Range: 480},
}

// GetTankBaseStats returns base stats for a tankID from TankUpTemplate_table.xml.
// Returns nil if tankID not found.
func GetTankBaseStats(tankID uint32) *TankBaseStats {
	if s, ok := tankBaseStatsTable[tankID]; ok {
		return &s
	}
	return nil
}
