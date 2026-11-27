"""M35 reviewed cosmetics: code-only catalog overlay, never a DB migration.

The 18 November source supplies new geometry/icons and completes three held
appearances. Native combat stays on its original IDs, stats and timing; the
explicit maps below are used only by the final presentation serializer.
Razor and every source skin without full closure are deliberately excluded.

New item metadata is cloned from the pinned same-tank native cosmetic template,
not the donor's economy/gameplay tables. Existing Fire Dance's conflicting
10701 identity is resolved logically to the exact source split 3007415;
Pumpkin10701 and all saved inventory/garage rows remain untouched.
"""
from __future__ import annotations

from copy import deepcopy

LEGACY_UNAVAILABLE = 'Skin đang thiếu hoặc chưa xác minh đủ tài nguyên, chưa thể mặc.'
APPROVED_ITEMS = {
    (10000038,10380): frozenset((2903813,)),
    (10000040,10400): frozenset((2904014,)),
    (10000067,10718): frozenset((2906714,)),
    (10000067,10719): frozenset((2906715,)),
    (10000047,10716): frozenset((2904714,)),
    (10000048,10720): frozenset((2904813,)),
    (10000075,10723): frozenset((2907515,)),
    (10000051,10636): frozenset((2905122,)),
    (10000107,866): frozenset((2970212,)),
    (10000074,3007415): frozenset((2907415,)),
}
ITEM_IDENTITIES = {item: pair for pair, items in APPROVED_ITEMS.items() for item in items}

# Explicit reviewed pairs, NOT a numeric offset/prefix operation.
GHOST_EFFECTS = {
    'tank':10000038,
    'skill':{'312100':923100,'312101':923101,'312201':923201,
             '312301':923301,'312401':923401},
    'buff':{'312101':923101,'312111':923111,'312114':923114,
            '312115':923115,'312116':923116,'312117':923117,
            '312118':923118,'312121':923121,'312122':923122,
            '312124':923124,'312151':923151,'312152':923152,
            '312153':923153,'312154':923154,'312155':923155,
            '312156':923156,'312157':923157,'312158':923158,
            '312159':923159,'312161':923161,'312212':923212,
            '312311':923311,'312321':923321,'312331':923331,
            '312341':923341,'312403':923403},
    'scene':{'312411':923411},'npc':{},
}
WOLF_EFFECTS = {
    'tank':10000040,
    'skill':{'314100':914100,'314101':914101,'314201':914201,
             '314211':914211,'314301':914301,'314401':914401},
    'buff':{'314101':914101,'314102':914102,'314103':914103,
            '314104':914104,'314112':914112,'314121':914121,
            '314122':914122,'314202':914202,'314212':914212,
            '314213':914213,'314303':914303,'314304':914304,
            '314305':914305},
    'scene':{},'npc':{},
}
DRUID_EFFECTS = {
    'tank':10000051,
    'skill':{'326100':462100,'326101':462101,'326201':462201,
             '326301':462301,'326331':462331,'326371':462371,
             '326401':462401},
    'buff':{'326101':462101,'326112':462112,'326201':462201,
            '326202':462202,'326203':462203,'326204':462204,
            '326205':462205,'326211':462211,'326301':462301,
            '326304':462304,'326305':462305,'326306':462306,
            '326307':462307,'326308':462308,'326309':462309,
            '326310':462310,'326312':462312,'326316':462316,
            '326321':462321,'326322':462322,'326332':462332,
            '326341':462341,'326343':462343,'326344':462344,
            '326402':462402,'326403':462403,'326404':462404,
            '326411':462411,'326422':462422},
    'scene':{'326309':462309,'326313':462313,'326351':462351,
             '326401':462401},'npc':{},
}
FIRE_EFFECTS = {
    'tank':10000074,
    'skill':{'348100':648100,'348101':648101,'348201':648201,
             '348211':648211,'348301':648301,'348311':648311,
             '348401':648401},
    'buff':{'348101':648101,'348102':648102,'348111':648111,
            '348112':648112,'348113':648113,'348114':648114,
            '348122':648122,'348123':648123,'348321':648321,
            '348202':648202,'348203':648203,'348204':648204,
            '348205':648205,'348211':648211,'348313':648313,
            '348402':648402,'348403':648403,'348404':648404},
    'scene':{},'npc':{},
}
EFFECTS = {10380:GHOST_EFFECTS,10400:WOLF_EFFECTS,
           10636:DRUID_EFFECTS,3007415:FIRE_EFFECTS}

# Source-exterior aliases are review metadata only; native saved appearance IDs
# remain the five pre-existing canonical geometries. No global alias is added.
SOURCE_EXTERIORS = {10792:10718,10793:10719,10794:10716,10795:10720,10791:10723}
# item -> native metadata template, name, exact inventory icon key
NEW_ITEM_SPECS = {
    2903813:(2903801,'Ghost Rider - Lục Hỏa U Linh','eling_sss01_icon'),
    2904014:(2904013,'Wolverine - Kim Lang','jinganglang_sss01_icon'),
    2906714:(2906713,'Triệu Vân Lam Phong','zhaoyun_pf03_skin_v1'),
    2906715:(2906713,'Triệu Vân Tử Ảnh','zhaoyun_pf05_skin_v1'),
    2904714:(2904713,'Pikachu Tử Lôi','bika_pf03_skin_v1'),
    2904813:(2904821,'Sát Thủ Ám Dạ','cike_pf01_skin_v1'),
    2907515:(2907514,'Cơ Giáp Lữ Bố','lvbu_mech_lock'),
}
# Exact supplied UI tiers for the seven NEW identities only; never gameplay.
NEW_ITEM_QUALITIES = {2903813:5,2904014:5,2906714:4,2906715:4,
                      2904714:4,2904813:4,2907515:4}
TEMPLATE_IDENTITIES = {
    2903801:(10000038,10181),2904013:(10000040,10685),
    2906713:(10000067,10619),
    2904713:(10000047,10697),2904821:(10000048,10632),
    2907514:(10000075,10638),
}
ALIAS_COMPONENTS = {10718:(9814,9815),10719:(9816,9817),10716:(9810,9811),
                    10720:(9818,9819),10723:(9836,9837)}
NEW_EXTERIORS = (10380,10400,3007415)
_MISSING = object()


def item_matches(template_id, tank, exterior):
    """Constrain both reviewed items and reviewed exteriors to exact identities."""
    item, pair = int(template_id), (int(tank), int(exterior))
    if item in ITEM_IDENTITIES:
        return ITEM_IDENTITIES[item] == pair
    allowed = APPROVED_ITEMS.get(pair)
    return allowed is None or item in allowed


def _matches_map(value, expected):
    return (isinstance(value,dict)
            and not set(value)-{'tank','skill','buff','scene','npc'}
            and value.get('tank') == expected['tank']
            and all(value.get(kind,{}) == expected.get(kind,{})
                    for kind in ('skill','buff','scene','npc')))


def effective_settings(support, effects):
    """Private effective copies; custom status/map preimages fail closed."""
    if not isinstance(support,dict) or not isinstance(effects,dict):
        raise ValueError('M35: danh mục skin tĩnh không đúng cấu trúc.')
    result,maps=deepcopy(support),deepcopy(effects)
    for tank,exterior in APPROVED_ITEMS:
        group=result.setdefault(str(tank),{})
        if not isinstance(group,dict):
            raise ValueError(f'M35: danh mục skin tank {tank} khác nguồn đã kiểm.')
        allowed=('ready',LEGACY_UNAVAILABLE) if exterior in (10636,866) else ('ready',)
        before=group.get(str(exterior),_MISSING)
        if before is not _MISSING and before not in allowed:
            raise ValueError(f'M35: trạng thái skin {tank}/{exterior} khác nguồn đã kiểm.')
        expected=EFFECTS.get(exterior,{'tank':tank})
        before_map=maps.get(str(exterior),_MISSING)
        if before_map is not _MISSING and not _matches_map(before_map,expected):
            raise ValueError(f'M35: ánh xạ skin {tank}/{exterior} khác nguồn đã kiểm.')
        group[str(exterior)]='ready'
        if exterior in EFFECTS:
            maps.setdefault(str(exterior),deepcopy(expected))
    return result,maps


def _read_item(db, ident):
    cursor=db.execute('SELECT * FROM client_ItemTemplate_table WHERE nItemId=? '
                      'ORDER BY _ordinal DESC LIMIT 1',(str(ident),))
    row=cursor.fetchone()
    return dict(zip((d[0] for d in cursor.description),row)) if row is not None else None


def _identity(row, tank, exterior):
    return (row is not None and tuple(str(row.get(k)) for k in
            ('nType','nContType','iReuseA','iReuseB')) ==
            ('29','6',str(tank),str(exterior)))


def _validated_overrides(db):
    """Validate latest SQL rows, then construct private cosmetic-only rows."""
    result={}
    for exterior in NEW_EXTERIORS:
        for table,key in (('client_TankExternalTemplate_table','nId'),
                          ('client_TankSkinAttrTemplate_table','nID')):
            if db.execute(f'SELECT 1 FROM {table} WHERE {key}=? LIMIT 1',(str(exterior),)).fetchone():
                raise ValueError(f'M35: mã ngoại hình {exterior} đã có dữ liệu ngoài bản đã kiểm.')
    for exterior,parts in ALIAS_COMPONENTS.items():
        row=db.execute('SELECT nCrenelId,nBodyId FROM client_TankExternalTemplate_table '
                       'WHERE nId=? ORDER BY _ordinal DESC LIMIT 1',(str(exterior),)).fetchone()
        if row is None or tuple(str(v) for v in row) != tuple(str(v) for v in parts):
            raise ValueError(f'M35: hình học skin {exterior} khác nguồn đã kiểm.')
        if db.execute('SELECT 1 FROM client_TankSkinAttrTemplate_table WHERE nID=? LIMIT 1',
                      (str(exterior),)).fetchone():
            raise ValueError(f'M35: thuộc tính skin {exterior} khác nguồn đã kiểm.')
    templates={}
    for ident,(tank,exterior) in TEMPLATE_IDENTITIES.items():
        row=_read_item(db,ident)
        if (not _identity(row,tank,exterior)
                or str(row.get('iStackMax')) != '1'
                or str(row.get('iSalePrice')) != '-1'
                or str(row.get('nSaleCoinType')) != '2'
                or str(row.get('iReuseC')) != '2'
                or row.get('nAutoUse') not in (None,'','0',0)):
            raise ValueError(f'M35: mẫu vật phẩm skin {ident} khác nguồn đã kiểm.')
        templates[ident]=row
    for ident,(template,name,icon) in NEW_ITEM_SPECS.items():
        tank,exterior=ITEM_IDENTITIES[ident]
        row=deepcopy(templates[template]);row.pop('_ordinal',None)
        row.update(nItemId=str(ident),iReuseA=str(tank),iReuseB=str(exterior),
                   szName=name,szIconPath1=icon+'.png',
                   szDesc='Trang phục '+name+'. Giữ nguyên cơ chế và chỉ số chiến đấu của tank gốc.')
        row['iQuality']=str(NEW_ITEM_QUALITIES[ident])
        current=_read_item(db,ident)
        if current is not None and {k:v for k,v in current.items() if k!='_ordinal'} != row:
            raise ValueError(f'M35: mã vật phẩm skin {ident} đã có dữ liệu ngoài bản đã kiểm.')
        result[ident]=deepcopy(current) if current is not None else row
    for item,tank,exterior in ((2905122,10000051,10636),(2970212,10000107,866)):
        if not _identity(_read_item(db,item),tank,exterior):
            raise ValueError(f'M35: vật phẩm skin {item} khác nguồn đã kiểm.')
    fire=_read_item(db,2907415)
    if not (_identity(fire,10000074,10701) or _identity(fire,10000074,3007415)):
        raise ValueError('M35: vật phẩm Fire Dance 2907415 khác nguồn đã kiểm.')
    fire=deepcopy(fire);fire['iReuseB']='3007415';result[2907415]=fire
    return result


def validate_source_rows(db):
    """Read only the caller's transaction; no migration, grant or DB writes."""
    _validated_overrides(db)


def item_template(db, template_id):
    """Effective item for owned-item validation; ownership stays in C207."""
    ident=int(template_id)
    if ident in NEW_ITEM_SPECS or ident == 2907415:
        return _validated_overrides(db)[ident]
    return _read_item(db,ident)


def effective_items(db, items):
    """Overlay private catalog copies only; callers still gate by ready status."""
    result=deepcopy(items)
    result.update(_validated_overrides(db))
    return result
