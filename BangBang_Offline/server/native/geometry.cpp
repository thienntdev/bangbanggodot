// Bang Bang gameplay geometry accelerator, ABI 1.
//
// This module owns immutable copies of map rectangles, not combat state.
// It computes only the same inclusive slab-contact fraction as
// combat_geometry.rect_contact. Python retains movement rounding, the native
// nine-cell walking rule, water-wall lifetime, damage, AI and event ordering.
// Compile without fast-math or contraction (GCC/Clang: -ffp-contract=off;
// MSVC: /fp:strict). Rebuild handles whenever the Python map changes.
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <new>
#include <shared_mutex>
#include <unordered_map>
#include <vector>

#ifndef BB_GEOMETRY_SOURCE_SHA256
#define BB_GEOMETRY_SOURCE_SHA256 "unversioned"
#endif

#if defined(_WIN32)
#define BB_EXPORT extern "C" __declspec(dllexport)
#else
#define BB_EXPORT extern "C" __attribute__((visibility("default")))
#endif

namespace {

constexpr std::uint32_t kAbiVersion = 1;
constexpr double kCoordinateLimit = 1.0e9;
constexpr double kBinSize = 192.0;
constexpr std::size_t kMaximumRectangles = 1000000;
constexpr std::uint64_t kMaximumBinEntries = 2000000;

struct Rectangle {
    double left;
    double top;
    double right;
    double bottom;
};

struct RectangleIndex {
    std::vector<Rectangle> rectangles;
    std::unordered_map<std::uint64_t, std::vector<std::uint32_t>> bins;
    // Very large rectangles would make a spatial index wasteful. Linear
    // traversal has the same answer for finite, ordered rectangles and
    // nonnegative padding; it also bounds the index's auxiliary storage.
    bool linear = false;
    std::int32_t min_x = std::numeric_limits<std::int32_t>::max();
    std::int32_t min_y = std::numeric_limits<std::int32_t>::max();
    std::int32_t max_x = std::numeric_limits<std::int32_t>::min();
    std::int32_t max_y = std::numeric_limits<std::int32_t>::min();
};

std::shared_mutex registry_mutex;
std::unordered_map<std::uint64_t, std::shared_ptr<const RectangleIndex>> registry;
std::uint64_t next_handle = 1;
thread_local char error_text[256] = {};

void clear_error() noexcept {
    error_text[0] = '\0';
}

void set_error(const char* message) noexcept {
    const std::size_t length = std::min(std::strlen(message), sizeof(error_text) - 1);
    std::memcpy(error_text, message, length);
    error_text[length] = '\0';
}

double error_result(const char* message) noexcept {
    set_error(message);
    return std::numeric_limits<double>::quiet_NaN();
}

bool valid_coordinate(double value) noexcept {
    return std::isfinite(value) && std::abs(value) <= kCoordinateLimit;
}

std::int32_t bin_coordinate(double value) noexcept {
    // All callers first constrain values to at most +/-2e9, so conversion
    // after floor is representable by int32. Do not truncate toward zero.
    return static_cast<std::int32_t>(std::floor(value / kBinSize));
}

std::uint64_t bin_key(std::int32_t x, std::int32_t y) noexcept {
    return (static_cast<std::uint64_t>(static_cast<std::uint32_t>(x)) << 32)
        | static_cast<std::uint32_t>(y);
}

std::uint64_t rectangle_bin_count(std::int32_t left, std::int32_t top,
                                  std::int32_t right, std::int32_t bottom) noexcept {
    return static_cast<std::uint64_t>(static_cast<std::int64_t>(right) - left + 1)
        * static_cast<std::uint64_t>(static_cast<std::int64_t>(bottom) - top + 1);
}

// Keep these operations and comparisons in the Python implementation's
// order. In particular, do not replace this with a reciprocal multiply or
// fuse subtraction/multiplication. Endpoints and padded edges are inclusive.
double rectangle_contact(double x, double y, double dx, double dy,
                         const Rectangle& rectangle, double padding) noexcept {
    double low = 0.0;
    double high = 1.0;
    if (dx == 0.0) {
        if (!(rectangle.left - padding <= x && x <= rectangle.right + padding)) {
            return -1.0;
        }
    } else {
        double t1 = (rectangle.left - padding - x) / dx;
        double t2 = (rectangle.right + padding - x) / dx;
        if (t1 > t2) std::swap(t1, t2);
        if (t1 > low) low = t1;
        if (t2 < high) high = t2;
        if (low > high) return -1.0;
    }
    if (dy == 0.0) {
        if (!(rectangle.top - padding <= y && y <= rectangle.bottom + padding)) {
            return -1.0;
        }
    } else {
        double t1 = (rectangle.top - padding - y) / dy;
        double t2 = (rectangle.bottom + padding - y) / dy;
        if (t1 > t2) std::swap(t1, t2);
        if (t1 > low) low = t1;
        if (t2 < high) high = t2;
        if (low > high) return -1.0;
    }
    return low;
}

double linear_contact(const RectangleIndex& index, double x, double y,
                      double dx, double dy, double padding) noexcept {
    double first = -1.0;
    for (const Rectangle& rectangle : index.rectangles) {
        const double contact = rectangle_contact(x, y, dx, dy, rectangle, padding);
        if (contact >= 0.0 && (first < 0.0 || contact < first)) first = contact;
        if (first == 0.0) return first;
    }
    return first;
}

double indexed_contact(const RectangleIndex& index, double sx, double sy,
                       double ex, double ey, double padding) {
    if (index.rectangles.empty()) return -1.0;
    const double dx = ex - sx;
    const double dy = ey - sy;
    if (index.linear) return linear_contact(index, sx, sy, dx, dy, padding);

    // Exactly the 192px broad-phase bins used by BattleMap._wall_contact.
    // Clipping to occupied bounds only skips bins that cannot contain walls.
    const std::int32_t left = std::max(index.min_x,
        bin_coordinate(std::min(sx, ex) - padding));
    const std::int32_t top = std::max(index.min_y,
        bin_coordinate(std::min(sy, ey) - padding));
    const std::int32_t right = std::min(index.max_x,
        bin_coordinate(std::max(sx, ex) + padding));
    const std::int32_t bottom = std::min(index.max_y,
        bin_coordinate(std::max(sy, ey) + padding));
    if (left > right || top > bottom) return -1.0;

    const std::uint64_t cells = rectangle_bin_count(left, top, right, bottom);
    if (cells > static_cast<std::uint64_t>(index.bins.size()) * 4 + 64) {
        return linear_contact(index, sx, sy, dx, dy, padding);
    }

    double first = -1.0;
    for (std::int32_t x = left; x <= right; ++x) {
        for (std::int32_t y = top; y <= bottom; ++y) {
            const auto bucket = index.bins.find(bin_key(x, y));
            if (bucket == index.bins.end()) continue;
            // A rectangle can occur in several bins. Rechecking its same
            // fraction is harmless, avoids allocating a query-time set, and
            // never changes a tie: this API returns no rectangle identity.
            for (const std::uint32_t id : bucket->second) {
                const double contact = rectangle_contact(
                    sx, sy, dx, dy, index.rectangles[id], padding);
                if (contact >= 0.0 && (first < 0.0 || contact < first)) first = contact;
                if (first == 0.0) return first;
            }
        }
    }
    return first;
}

}  // namespace

BB_EXPORT std::uint32_t bb_geometry_abi_version() noexcept {
    return kAbiVersion;
}

BB_EXPORT const char* bb_geometry_source_sha256() noexcept {
    return BB_GEOMETRY_SOURCE_SHA256;
}

BB_EXPORT const char* bb_geometry_last_error() noexcept {
    return error_text;
}

BB_EXPORT std::uint64_t bb_geometry_create(const double* coordinates,
                                          std::size_t count) noexcept {
    clear_error();
    if (count > kMaximumRectangles || (count != 0 && coordinates == nullptr)) {
        set_error("Invalid rectangle buffer or count (maximum 1000000)");
        return 0;
    }
    try {
        auto index = std::make_shared<RectangleIndex>();
        index->rectangles.reserve(count);
        std::uint64_t entries = 0;
        for (std::size_t i = 0; i < count; ++i) {
            const double* row = coordinates + i * 4;
            for (std::size_t j = 0; j < 4; ++j) {
                if (!valid_coordinate(row[j])) {
                    set_error("Rectangle coordinates must be finite and bounded by 1e9");
                    return 0;
                }
            }
            if (row[0] > row[2] || row[1] > row[3]) {
                set_error("Rectangle edges are inverted; use the Python fallback");
                return 0;
            }
            index->rectangles.push_back({row[0], row[1], row[2], row[3]});
            const std::int32_t left = bin_coordinate(row[0]);
            const std::int32_t top = bin_coordinate(row[1]);
            const std::int32_t right = bin_coordinate(row[2]);
            const std::int32_t bottom = bin_coordinate(row[3]);
            index->min_x = std::min(index->min_x, left);
            index->min_y = std::min(index->min_y, top);
            index->max_x = std::max(index->max_x, right);
            index->max_y = std::max(index->max_y, bottom);
            // Stop accumulating as soon as we choose the bounded linear
            // representation, avoiding overflow even with many huge walls.
            if (!index->linear) {
                entries += rectangle_bin_count(left, top, right, bottom);
                if (entries > kMaximumBinEntries) index->linear = true;
            }
        }
        if (!index->linear) {
            for (std::size_t i = 0; i < index->rectangles.size(); ++i) {
                const Rectangle& rectangle = index->rectangles[i];
                const std::int32_t left = bin_coordinate(rectangle.left);
                const std::int32_t top = bin_coordinate(rectangle.top);
                const std::int32_t right = bin_coordinate(rectangle.right);
                const std::int32_t bottom = bin_coordinate(rectangle.bottom);
                for (std::int32_t x = left; x <= right; ++x) {
                    for (std::int32_t y = top; y <= bottom; ++y) {
                        index->bins[bin_key(x, y)].push_back(static_cast<std::uint32_t>(i));
                    }
                }
            }
        }
        std::unique_lock<std::shared_mutex> lock(registry_mutex);
        if (next_handle == 0) {
            set_error("Native geometry handle space exhausted");
            return 0;
        }
        const std::uint64_t handle = next_handle++;
        registry.emplace(handle, std::move(index));
        return handle;
    } catch (const std::bad_alloc&) {
        set_error("Native geometry allocation failed");
    } catch (...) {
        set_error("Native geometry index creation failed");
    }
    return 0;
}

BB_EXPORT int bb_geometry_destroy(std::uint64_t handle) noexcept {
    clear_error();
    try {
        std::unique_lock<std::shared_mutex> lock(registry_mutex);
        if (handle != 0 && registry.erase(handle) != 0) return 1;
        set_error("Invalid or already destroyed native geometry handle");
    } catch (...) {
        set_error("Native geometry handle destruction failed");
    }
    return 0;
}

BB_EXPORT double bb_geometry_contact(std::uint64_t handle,
                                    double sx, double sy, double ex, double ey,
                                    double padding) noexcept {
    clear_error();
    if (!valid_coordinate(sx) || !valid_coordinate(sy)
        || !valid_coordinate(ex) || !valid_coordinate(ey)
        || !valid_coordinate(padding) || padding < 0.0) {
        return error_result("Query coordinates must be finite/bounded; padding must be nonnegative");
    }
    try {
        std::shared_ptr<const RectangleIndex> index;
        {
            std::shared_lock<std::shared_mutex> lock(registry_mutex);
            const auto found = registry.find(handle);
            if (found == registry.end()) {
                return error_result("Invalid or destroyed native geometry handle");
            }
            index = found->second;
        }
        // The immutable copy remains alive if another thread destroys its
        // registry handle while this call is in progress. No Python objects
        // or global query scratch buffers are accessed here.
        return indexed_contact(*index, sx, sy, ex, ey, padding);
    } catch (...) {
        return error_result("Native geometry query failed");
    }
}

BB_EXPORT std::uint64_t bb_geometry_live_handles() noexcept {
    clear_error();
    try {
        std::shared_lock<std::shared_mutex> lock(registry_mutex);
        return static_cast<std::uint64_t>(registry.size());
    } catch (...) {
        set_error("Native geometry handle count failed");
        return std::numeric_limits<std::uint64_t>::max();
    }
}
