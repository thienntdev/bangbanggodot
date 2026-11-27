"""Canonical solo layouts and the source CityTemplate hard-mode aliases.

Hard offline runs deliberately reuse the reviewed normal layout/controller.
The native request keeps its original hero-map ID; saved rooms keep a canonical
layout ID plus a separate difficulty. This is not a claim of hard-script parity.
"""
CHAPTER2 = (211, 212, 213, 401, 402, 403)
CHAPTER3 = (404, 405, 406, 301, 302, 303)
CHAPTER4 = (701, 702, 703, 304, 305, 306)
CHAPTER5 = (501, 502, 503, 504, 505, 506)
CHAPTER6 = (601, 602, 603, 30101, 30102, 30103)
CHAPTER7 = (31201, 31202, 31203, 31301, 31302, 31303)
CHAPTER8 = (31401,31402,31403,31501,31502,31503)
CHAPTER9 = (31601,31602)
MAPS = (201, 204, 205, 203, 206) + CHAPTER2 + CHAPTER3 + CHAPTER4 + CHAPTER5 + CHAPTER6 + CHAPTER7 + CHAPTER8 + CHAPTER9
# Literal nHeroMapId -> nMapId pairs, not arithmetic guesses. Chapter one has
# no hero-map IDs in CityTemplate; its five maps remain normal-only.
HARD_TO_NORMAL = {
    5211: 211, 5212: 212, 5213: 213, 5401: 401, 5402: 402, 5403: 403,
    5404: 404, 5405: 405, 5406: 406, 5301: 301, 5302: 302, 5303: 303,
    5701: 701, 5702: 702, 5703: 703, 5304: 304, 5305: 305, 5306: 306,
    5501: 501, 5502: 502, 5503: 503, 5504: 504, 5505: 505, 5506: 506,
    5601: 601, 5602: 602, 5603: 603, 31101: 30101, 31102: 30102, 31103: 30103,
    32201: 31201, 32202: 31202, 32203: 31203, 32301: 31301, 32302: 31302, 32303: 31303,
    32401: 31401, 32402: 31402, 32403: 31403, 32501: 31501, 32502: 31502, 32503: 31503,
    32601: 31601, 32602: 31602,
}
NORMAL_TO_HARD = {normal: hard for hard, normal in HARD_TO_NORMAL.items()}
REQUEST_MAPS = MAPS + tuple(HARD_TO_NORMAL)


def resolve_request(map_id):
    """Return (canonical layout, difficulty), rejecting unknown/special maps."""
    if type(map_id) is not int:
        raise ValueError('Mã màn PvE không hợp lệ.')
    if map_id in MAPS:
        return map_id, 0
    if map_id in HARD_TO_NORMAL:
        return HARD_TO_NORMAL[map_id], 1
    raise ValueError('Màn PvE chưa được hỗ trợ; chỉ mở 49 màn thường và 44 màn khó đơn.')


def solo_room(requested_map_id, room_id=1001):
    map_id, difficulty = resolve_request(requested_map_id)
    return dict(room_id=room_id,
                name='PvE — ' + NAMES[map_id] + (' (Khó offline)' if difficulty else ''),
                map_id=map_id, pve_requested_map_id=requested_map_id,
                pve_difficulty=difficulty, mode=1, room_type=4, state=0, camp=1,
                ready=1, max_num=1, min_num=1, ob_num=0)
CITIES = {201:10100, 204:10200, 205:10300, 203:10400, 206:10500,
          211:20100,212:20200,213:20300,401:20400,402:20500,403:20600,
          404:30100,405:30200,406:30300,301:30400,302:30500,303:30600,
          701:40100,702:40200,703:40300,304:40400,305:40500,306:40600,
          501:50100,502:50200,503:50300,504:50400,505:50500,506:50600,
          601:60100,602:60200,603:60300,30101:60400,30102:60500,30103:60600,
          31201:70100,31202:70200,31203:70300,31301:70400,31302:70500,31303:70600,31401:80100,31402:80200,31403:80300,31501:80400,31502:80500,31503:80600,31601:90100,31602:90200}
NAMES = {201:'Lính đánh thuê gian ác', 204:'Đột kích sấm sét',
         205:'Trận chiến quyết liệt', 203:'Mỏ vàng', 206:'Anh hùng cứu mỹ nhân',
         211:'Thoát khỏi trại giam',212:'Nhảy vực cầu sinh',213:'Thoát khỏi miệng hổ',
         401:'Tàu ngầm đáng sợ',402:'Con đường dũng sĩ',403:'Nhện đấu Tank Siêu Cấp',
         404:'Truy kích cường địch',405:'Bảo vệ cầu',406:'Xe lửa cuồng bạo',
         301:'Cuộc chiến bờ biển',302:'Phá hủy đạn đạo',303:'Chiến hạm trọng yếu',
         701:'Sân bay gặp nạn',702:'Nhà ga phục kích',703:'Chiến hạm cuồng phong',
         304:'Rừng dã chiến',305:'Công xưởng tank',306:'Tank cuồng bạo',
         501:'Người ngoài hành tinh xâm lược',502:'Giải cứu sinh tử',503:'Thu hồi trạm không gian',
         504:'Phản công tuyệt địa',505:'Đại chiến người ngoài hành tinh',506:'Trận chiến thủ lĩnh',
         601:'Giải cứu nữ vương',602:'Thu hồi động cơ',603:'Chiến binh Sith',
         30101:'Người phán quyết',30102:'Behemoth Tinh Không',30103:'Bá Tước Dooku',
         31201:'Resident Evil',31202:'Tìm kiếm bệnh dịch',31203:'Lính sinh hóa',
         31301:'Thành phố chết',31302:'Red Bee',31303:'Sống hay chết',31401:'Hoang mạc chết chóc',31402:'Căn cứ hoang mạc',31403:'Bình minh đẫm máu',31501:'Trở lại thành phố',31502:'Bóng ma căn cứ',31503:'Nguồn gốc tận thế',31601:'Mê cung kinh hoàng',31602:'Nữ thần báo thù'}
