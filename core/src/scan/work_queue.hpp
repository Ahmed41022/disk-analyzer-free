#pragma once

#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <deque>
#include <mutex>
#include <optional>
#include <utility>

namespace dafree::detail {

template <class T> class WorkQueue {
  public:
    explicit WorkQueue(std::size_t capacity = 0) : capacity_(capacity) {}
    bool push(T value) {
        std::unique_lock lock(mutex_);
        space_.wait(lock, [&] { return closed_ || capacity_ == 0 || values_.size() < capacity_; });
        if (closed_)
            return false;
        values_.push_back(std::move(value));
        lock.unlock();
        ready_.notify_one();
        return true;
    }
    std::optional<T> pop() {
        std::unique_lock lock(mutex_);
        ready_.wait(lock, [&] { return closed_ || !values_.empty(); });
        return remove(lock);
    }
    std::optional<T> pop_for(std::chrono::milliseconds timeout) {
        std::unique_lock lock(mutex_);
        ready_.wait_for(lock, timeout, [&] { return closed_ || !values_.empty(); });
        return remove(lock);
    }
    void close(bool discard = false) {
        {
            std::lock_guard lock(mutex_);
            closed_ = true;
            if (discard)
                values_.clear();
        }
        ready_.notify_all();
        space_.notify_all();
    }
    [[nodiscard]] bool drained() const {
        std::lock_guard lock(mutex_);
        return closed_ && values_.empty();
    }

  private:
    std::optional<T> remove(std::unique_lock<std::mutex> &lock) {
        if (values_.empty())
            return std::nullopt;
        T value = std::move(values_.front());
        values_.pop_front();
        lock.unlock();
        space_.notify_one();
        return value;
    }
    mutable std::mutex mutex_;
    std::condition_variable ready_, space_;
    std::deque<T> values_;
    std::size_t capacity_;
    bool closed_ = false;
};

} // namespace dafree::detail
