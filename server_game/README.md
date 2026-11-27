# BangBang Game Server (Go)

Backend cho game Tank Ghost / BangBang, implement Sixcube binary protocol kết nối cơ sở dữ liệu PostgreSQL (hỗ trợ kiến trúc 1 Account -> Nhiều Characters, quản lý kho đồ, xe tank, bang hội, thư tín, xếp hạng, boss thế giới).

## Cấu trúc thư mục

```
server_game/
├── main.go                     # Entry point, HTTP + WebSocket server, DB wiring
├── schema.sql                  # Toàn bộ SQL schema (Users, Characters, Tanks, Items, Guilds, Mails, Ranks...)
├── go.mod / go.sum             # Go dependencies (bao gồm github.com/lib/pq, gorilla/websocket...)
├── protocol/
│   ├── codec.go                # Binary encoder/decoder (Sixcube Little-Endian framing)
│   ├── message_ids.go          # Message ID constants (Tank, Item, Auth, Gate, Battle...)
│   ├── messages.go             # Server→Client message encoders (BulkDataType TankInstance & ItemInstance chuẩn 22 & 13 fields)
│   └── decoders.go             # Client→Server message decoders (RequestContainerItem, LevelUpTank, StrengthenTank...)
├── handler/
│   ├── auth_handler.go         # POST /api/auth (HTTP login/auto-create user & character)
│   ├── register_handler.go     # POST /api/register (Đăng ký tài khoản kèm Captcha)
│   └── ws_handler.go           # WebSocket login/gate handler (xử lý tank level, cường hóa, rương đồ, cleanup)
└── game/
    └── store.go                # In-memory & PostgreSQL store (Auto-migrate, User -> Character, Tanks, Inventory)
```

## Cơ sở dữ liệu (PostgreSQL - Render Free 30 ngày)

Server đã được cấu hình mặc định kết nối đến PostgreSQL trên Render:
- **Default Database URL**: `postgresql://bangbang_wy6y_user:0ANTGQ2sbtBOMn5e0HGcwjRhWyfxXp4I@dpg-dc43nrt9el5s73a4tl70-a.singapore-postgres.render.com/bangbang_wy6y`
- **Auto-Migrate**: Khi server khởi động, `store.go` tự động kiểm tra và thực thi migration script tạo toàn bộ các bảng nếu chưa có, đồng thời tự migrate dữ liệu cũ từ bảng `players` sang `users` & `characters`.
- **Lưu ý 30 ngày Render Free**: Render cung cấp instance PostgreSQL miễn phí trong 30 ngày kể từ lúc tạo. Khi hết 30 ngày hoặc khi muốn chuyển database:
  - Truyền URL mới qua tham số CLI: `.\bangbang-server.exe -db="postgresql://user:pass@host:5432/dbname"`
  - Hoặc đặt biến môi trường: `$env:DATABASE_URL="postgresql://user:pass@host:5432/dbname"`
  - Nếu kết nối DB lỗi/mất mạng, server sẽ tự động fallback sang in-memory store để không làm gián đoạn việc chạy thử.

### Kiến trúc Database & So sánh thiết kế lưu trữ

#### 1. Mô hình 1 User -> Nhiều Characters
- `users`: Đại diện cho tài khoản đăng nhập (`id`, `username`, `password_hash`, `email`, `status`).
- `characters`: Nhân vật thuộc tài khoản (`id`, `user_id`, `name`, `level`, `exp`, `coin`, `silver`, `gold`, `thew`, `is_active`). Hiện tại khi user đăng ký hoặc lần đầu login, hệ thống tự tạo 1 character mặc định (sẵn sàng cho UI chọn nhân vật ở client sau này).

#### 2. Thiết kế Hybrid (Relational + JSONB) cho Tank và Item
So sánh với bản `BangBang_Offline` (lưu nguyên JSON string vào `garage.data` và `settings.inventory`):
- **Bản Offline (Pure JSON Blob)**: Khó truy vấn SQL, không thể indexing, không ràng buộc unique/foreign key, khi sửa 1 item phải đọc parse toàn bộ mảng JSON rồi ghi đè lại.
- **Bản Hiện tại (Relational + JSONB)**:
  - Các trường cốt lõi, thường xuyên lọc và tính toán được tách thành cột chuẩn (`tank_level`, `stth_level`, `cont_type`, `slot_no`, `template_id`, `count`, `rank`...).
  - Cột `data JSONB DEFAULT '{}'` lưu kèm các thuộc tính động hoặc mở rộng không cố định.
  - Hỗ trợ đánh index, truy vấn SQL trực tiếp, an toàn dữ liệu và tối ưu hiệu năng cao.

### Danh sách các bảng trong `schema.sql`:
1. `users`: Tài khoản người chơi.
2. `characters`: Nhân vật trong game (khóa ngoại `user_id -> users.id`).
3. `character_tanks`: Xe tank sở hữu (22 thuộc tính Sixcube TankInstance: cấp tank, cấp cường hóa, exp, skill, skin, ext_flag...).
4. `character_items`: Rương đồ người chơi (13 thuộc tính Sixcube ItemInstance: container 2-Vật phẩm, 3-Nguyên liệu, 4-Thời trang, 6-Skin, 7-Decor).
5. `guilds`: Bang hội (tên bang, cấp, điểm tài sản, chủ bang...).
6. `guild_members`: Thành viên bang hội và chức vụ.
7. `offline_mails`: Hòm thư offline kèm vật phẩm/tiền đính kèm.
8. `rank_seasons` & `rank_entries`: Mùa giải và bảng xếp hạng PvP.
9. `match_history`: Lịch sử các trận đấu (PvP, AI, Boss).
10. `world_boss_rounds` & `world_boss_scores`: Boss thế giới và xếp hạng sát thương người chơi.

---

## Chạy server

```bash
cd server_game
go build -o bangbang-server.exe .
.\bangbang-server.exe
```

Hoặc chỉ định DB tùy chọn:
```bash
.\bangbang-server.exe -db="<connection_string>"
```

Server chạy trên `http://127.0.0.1:8080` (mặc định).

## Endpoints

| Endpoint | Protocol | Chức năng |
|---|---|---|
| `POST /api/auth` | HTTP JSON | Đăng nhập / tự đăng ký tài khoản & nhân vật |
| `POST /api/register` | HTTP JSON | Đăng ký tài khoản (kèm captcha) |
| `/ws/login` | WebSocket Binary | Login protocol handshake (Sixcube LE) |
| `/ws/gate` | WebSocket Binary | Gate → vào thế giới game, nạp tank & rương đồ |
| `/godot/*` | HTTP Static | Serve game assets |

## Tính năng đã hoàn thành

- ✅ **Database PostgreSQL**: Kết nối Render Free tier, auto-migration bảng biểu, lưu trữ bền vững.
- ✅ **Kiến trúc Users -> Characters**: 1 tài khoản quản lý nhiều nhân vật (mặc định active char 1).
- ✅ **Hệ thống Tanks**:
  - Tự cấp 5 xe tank khởi đầu.
  - Cấu trúc 22 trường đầy đủ Sixcube `TankInstance` (UUID, TankID, Level, StthLevel, Exp, ExtFlag...).
  - Nâng cấp xe tank (Msg 203: `RequestLevelUpTank` -> Msg 1151: `UpdateTankInstance`).
  - Cường hóa xe tank (Msg 204: `RequestStrengthenTank` -> Msg 1151).
- ✅ **Hệ thống Túi đồ / Rương (Inventory)**:
  - Đầy đủ 5 container (Cont 2: Vật phẩm, Cont 3: Nguyên liệu, Cont 4: Thời trang, Cont 6: Skin, Cont 7: Trang trí).
  - Khởi tạo quà tân thủ (thẻ exp, đá cường hóa, rương bạc...).
  - Xem túi đồ (Msg 165: `RequestContainerItem` -> Msg 1100: `NotifyContainerItem`).
  - Sử dụng vật phẩm (Msg 153: `RequestUseItem`).
  - Sắp xếp / Dọn dẹp túi đồ (Msg 152: `RequestCleanUpCont`).
- ✅ **Mở rộng sẵn sàng**: Đã tạo bảng Guilds, Offline Mails, Rank Seasons, World Boss, Match History.
- ✅ **Flow kết nối mượt mà**: HTTP auth → WS login → WS gate → Lobby.

## Cách test với Godot client

1. Chạy server: `.\bangbang-server.exe`
2. Mở Godot project `client_godot/`
3. Đảm bảo cấu hình trỏ về `127.0.0.1:8080`
4. Nhấn F5 → Nhập username/password bất kỳ → Bấm Đăng nhập hoặc Đăng ký → Vào Lobby và kiểm tra Gara / Túi đồ.
