// SPDX-License-Identifier: GPL-3.0-or-later
// Called from GuestAlloc with m_heap_mutex held.
if (!base) {
    auto cacheSpan = [&](uint32_t start, uint32_t length) {
        if (!length) return;
        if (length >= (1u << kMinClassShift) && length <= kMaxClassSize && PowerOfTwo(length)) {
            int cls = 0;
            while ((1u << (cls + kMinClassShift)) < length) ++cls;
            m_free_small[cls].push_back(start);
        } else {
            m_free_huge[length].push_back(start);
        }
    };

    if (capacity > kMaxClassSize || uint64_t(m_heap_current) + capacity > kHeapLimit) {
        auto best = m_free_huge.end();
        for (auto entry = m_free_huge.begin(); entry != m_free_huge.end(); ++entry) {
            if (!entry->second.empty() && entry->first >= capacity &&
                (best == m_free_huge.end() || entry->first < best->first)) {
                best = entry;
            }
        }
        if (best != m_free_huge.end()) {
            const uint32_t length = best->first;
            base = best->second.back();
            best->second.pop_back();
            if (best->second.empty()) m_free_huge.erase(best);
            cacheSpan(base + capacity, length - capacity);
        }
    }

    if (!base && uint64_t(m_heap_current) + capacity > kHeapLimit) {
        // Reclaim contiguous blocks across size classes before exhausting the arena.
        using Span = std::pair<uint32_t, uint32_t>;
        std::vector<Span> spans;
        for (int cls = 0; cls < kNumSizeClasses; ++cls)
            for (auto start : m_free_small[cls])
                spans.emplace_back(start, 1u << (cls + kMinClassShift));
        for (const auto& [length, blocks] : m_free_huge)
            for (auto start : blocks)
                spans.emplace_back(start, length);
        std::sort(spans.begin(), spans.end());
        size_t merged = 0;
        for (const auto [start, length] : spans) {
            if (merged && spans[merged - 1].first + spans[merged - 1].second == start)
                spans[merged - 1].second += length;
            else
                spans[merged++] = {start, length};
        }
        spans.resize(merged);

        auto best = spans.end();
        uint64_t bestSize = UINT64_MAX;
        for (auto entry = spans.begin(); entry != spans.end(); ++entry) {
            const auto [start, length] = *entry;
            const uint64_t available = start + length == m_heap_current ? kHeapLimit - start : length;
            if (available >= capacity && available < bestSize) {
                best = entry;
                bestSize = available;
            }
        }
        if (best != spans.end()) {
            base = best->first;
            if (capacity < best->second)
                *best = {base + capacity, best->second - capacity};
            else
                best->second = 0;
            m_heap_current = std::max(m_heap_current, base + capacity);
        }
        for (auto& blocks : m_free_small) blocks.clear();
        m_free_huge.clear();
        for (const auto [start, length] : spans) cacheSpan(start, length);
    }
}
