#include "dafree/backend.hpp"

namespace dafree {

namespace {

class LocalBackend final : public FsBackend {
  public:
    [[nodiscard]] auto kind() const -> BackendKind override { return BackendKind::Local; }
#ifdef _WIN32
    bool supports_local_mft() const noexcept override { return true; }
    bool can_resolve_owner_by_path() const noexcept override { return true; }
#endif
    auto stat_root(std::string_view path) -> RawEntry override {
        return platform::stat_nofollow(path);
    }
    auto stat_follow(std::string_view path) -> RawEntry override {
        return platform::stat_follow(path);
    }
    auto read_dir(std::string_view path, const DirHint &hint) -> DirListing override {
        return hint.follow_symlinks ? platform::read_dir_follow(path) : platform::read_dir(path);
    }
    auto volume_info(std::string_view path) -> std::optional<VolumeInfo> override {
        return platform::volume_info(path);
    }
    auto resolve_owner(std::string_view path, const OwnerKey *hint)
        -> std::optional<std::pair<OwnerKey, std::string>> override {
#ifdef _WIN32
        (void)hint;
        return platform::owner_of(path);
#else
        try {
            if (hint != nullptr && hint->kind == OwnerKey::Kind::PosixUid)
                return std::pair{
                    *hint, platform::name_for_uid(hint->uid).value_or(std::to_string(hint->uid))};
            return platform::owner_of(path);
        } catch (const IoError &) {
            return std::nullopt;
        }
#endif
    }
};

} // namespace

auto make_local_backend() -> std::shared_ptr<FsBackend> { return std::make_shared<LocalBackend>(); }

} // namespace dafree
