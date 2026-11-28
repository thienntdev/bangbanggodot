package game

// Quest/Sign-in related store methods — AddCurrency, SwapItem, SellItem.

// AddCurrency adds currency to a character's wallet.
func (s *Store) AddCurrency(charID uint32, cash, golden, silver int32) {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return
	}
	c.Cash += cash
	c.Golden += golden
	c.Silver += silver

	// Persist to DB if available
	if s.db != nil {
		_, _ = s.db.Exec(`UPDATE characters SET data = jsonb_set(jsonb_set(jsonb_set(
			COALESCE(data, '{}'),
			'{cash}', to_jsonb($2::int)),
			'{golden}', to_jsonb($3::int)),
			'{silver}', to_jsonb($4::int))
			WHERE char_id = $1`, charID, c.Cash, c.Golden, c.Silver)
	}
}

// SwapItem swaps two item positions in a bag container.
func (s *Store) SwapItem(charID uint32, contType uint8, originSlot, destSlot int16) {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return
	}

	var originIdx, destIdx int = -1, -1
	for i := range c.Items {
		if c.Items[i].ContType == contType {
			if c.Items[i].SlotNo == originSlot {
				originIdx = i
			}
			if c.Items[i].SlotNo == destSlot {
				destIdx = i
			}
		}
	}

	if originIdx >= 0 && destIdx >= 0 {
		// Swap slots
		c.Items[originIdx].SlotNo, c.Items[destIdx].SlotNo = c.Items[destIdx].SlotNo, c.Items[originIdx].SlotNo
	} else if originIdx >= 0 {
		// Move to empty slot
		c.Items[originIdx].SlotNo = destSlot
	}
}

// SellItem removes an item from inventory and returns a sell price.
func (s *Store) SellItem(charID uint32, contType uint8, slot int16) int32 {
	s.mu.Lock()
	defer s.mu.Unlock()

	c := s.characters[charID]
	if c == nil {
		return 0
	}

	for i := range c.Items {
		if c.Items[i].ContType == contType && c.Items[i].SlotNo == slot {
			// Calculate sell price (simple: 10 xu per item)
			sellPrice := int32(10) * c.Items[i].Count
			// Remove item
			c.Items = append(c.Items[:i], c.Items[i+1:]...)
			return sellPrice
		}
	}
	return 0
}


// SetTankTalentPage sets the talent page UUID for a specific tank.
func (s *Store) SetTankTalentPage(charID uint32, tankUUID, pageUUID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := s.characters[charID]
	if c == nil {
		return
	}
	for i := range c.Tanks {
		if c.Tanks[i].TankUuid == tankUUID {
			c.Tanks[i].TalPageUuid = pageUUID
			return
		}
	}
}

// SetTankCrystalScheme sets the crystal scheme ID for a specific tank.
func (s *Store) SetTankCrystalScheme(charID uint32, tankUUID string, schemeID uint8) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := s.characters[charID]
	if c == nil {
		return
	}
	for i := range c.Tanks {
		if c.Tanks[i].TankUuid == tankUUID {
			c.Tanks[i].CrystalSchemeID = schemeID
			return
		}
	}
}

// GetTankByUUID returns a pointer to a tank by its UUID.
func (s *Store) GetTankByUUID(charID uint32, tankUUID string) *PlayerTank {
	s.mu.RLock()
	defer s.mu.RUnlock()
	c := s.characters[charID]
	if c == nil {
		return nil
	}
	for i := range c.Tanks {
		if c.Tanks[i].TankUuid == tankUUID {
			return &c.Tanks[i]
		}
	}
	return nil
}

// FindItemBySlot returns a pointer to an item at a specific slot in a container.
func (s *Store) FindItemBySlot(charID uint32, contType uint8, slotNo int16) *PlayerItem {
	s.mu.RLock()
	defer s.mu.RUnlock()
	c := s.characters[charID]
	if c == nil {
		return nil
	}
	for i := range c.Items {
		if c.Items[i].ContType == contType && c.Items[i].SlotNo == slotNo {
			return &c.Items[i]
		}
	}
	return nil
}

// SetAvatar sets the avatar template ID for a character.
func (s *Store) SetAvatar(charID uint32, templateID uint32) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := s.characters[charID]
	if c == nil {
		return
	}
	c.AvatarID = templateID
}

// SetDecorate sets the decorate (background) template ID for a character.
func (s *Store) SetDecorate(charID uint32, templateID uint32) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := s.characters[charID]
	if c == nil {
		return
	}
	c.DecorateID = templateID
}

// SetExtFlagCurUse sets ext_flag CUR_USE (32) on the item at slotNo, clears on others.
func (s *Store) SetExtFlagCurUse(charID uint32, contType uint8, slotNo int16) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := s.characters[charID]
	if c == nil {
		return
	}
	const curUse = uint32(32)
	for i := range c.Items {
		if c.Items[i].ContType == contType {
			if c.Items[i].SlotNo == slotNo {
				c.Items[i].ExtFlag |= curUse
			} else {
				c.Items[i].ExtFlag &^= curUse
			}
		}
	}
}

// GetUsedItemTemplate returns the template ID of an item at a slot (for award display).
// Returns 0 if not found.
func (s *Store) GetUsedItemTemplate(charID uint32, contType uint8, slotNo int16) uint32 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	c := s.characters[charID]
	if c == nil {
		return 0
	}
	for _, it := range c.Items {
		if it.ContType == contType && it.SlotNo == slotNo {
			return it.TemplateID
		}
	}
	return 0
}
