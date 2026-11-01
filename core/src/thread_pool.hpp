#pragma once

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <functional>
#include <future>
#include <list>
#include <mutex>
#include <thread>
#include <vector>

namespace dafree::detail {

/// Shared analysis workers; lazy initialization keeps scanning-only clients unchanged.
class ThreadPool {
  public:
    /// The process-wide pool has one native worker per logical CPU.
    static ThreadPool &analysis() {
        static ThreadPool pool;
        active().store(&pool, std::memory_order_release);
        return pool;
    }
    /// Stop an initialized pool before an extension's DLL teardown holds the loader lock.
    static void shutdown_analysis() {
        if (auto *pool = active().load(std::memory_order_acquire))
            pool->shutdown();
    }
    /// Number of available workers, always at least one.
    std::size_t size() const { return workers_.size(); }
    /// Run independent jobs and join all of them before propagating any exception.
    void run(std::size_t count, const std::function<void()> &function) {
        std::list<std::packaged_task<void()>> batch;
        std::vector<std::future<void>> results;
        results.reserve(count);
        for (std::size_t i = 0; i < count; ++i) {
            batch.emplace_back(function);
            results.push_back(batch.back().get_future());
        }
        {
            std::lock_guard lock(mutex_);
            jobs_.splice(jobs_.end(), batch); // Publication cannot allocate or partially fail.
        }
        ready_.notify_all();
        std::exception_ptr failure;
        for (auto &result : results) {
            try {
                result.get();
            } catch (...) {
                if (!failure)
                    failure = std::current_exception();
            }
        }
        if (failure)
            std::rethrow_exception(failure);
    }
    ~ThreadPool() { shutdown(); }
    ThreadPool(const ThreadPool &) = delete;
    ThreadPool &operator=(const ThreadPool &) = delete;

  private:
    static std::atomic<ThreadPool *> &active() {
        static std::atomic<ThreadPool *> pool{nullptr};
        return pool;
    }
    void shutdown() {
        std::vector<std::thread> workers;
        {
            std::lock_guard lock(mutex_);
            if (stopping_)
                return;
            stopping_ = true;
            workers.swap(workers_);
        }
        ready_.notify_all();
        for (auto &worker : workers)
            worker.join();
    }
    ThreadPool() {
        try {
            const auto count = std::max(1u, std::thread::hardware_concurrency());
            workers_.reserve(count);
            for (unsigned i = 0; i < count; ++i)
                workers_.emplace_back([this] {
                    for (;;) {
                        std::packaged_task<void()> job;
                        {
                            std::unique_lock lock(mutex_);
                            ready_.wait(lock, [&] { return stopping_ || !jobs_.empty(); });
                            if (stopping_ && jobs_.empty())
                                return;
                            job = std::move(jobs_.front());
                            jobs_.pop_front();
                        }
                        job();
                    }
                });
        } catch (...) {
            {
                std::lock_guard lock(mutex_);
                stopping_ = true;
            }
            ready_.notify_all();
            for (auto &worker : workers_)
                worker.join();
            throw;
        }
    }
    std::mutex mutex_;
    std::condition_variable ready_;
    std::list<std::packaged_task<void()>> jobs_;
    std::vector<std::thread> workers_;
    bool stopping_ = false;
};

} // namespace dafree::detail
