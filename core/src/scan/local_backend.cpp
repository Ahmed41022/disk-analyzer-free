#include "dafree/backend.hpp"

namespace dafree {

namespace {

class LocalBackend final : public FsBackend {
  public:
    [[nodiscard]] BackendKind kind() const override { return BackendKind::Local; }
    RawEntry stat_root(std::string_view path) override { return platform::stat_nofollow(path); }
    DirListing read_dir(std::string_view path, const DirHint &) override {
        return platform::read_dir(path);
    }
    std::optional<VolumeInfo> volume_info(std::string_view path) override {
        return platform::volume_info(path);
    }
    std::optional<std::pair<OwnerKey, std::string>> resolve_owner(std::string_view path,
                                                                  const OwnerKey *hint) override {
#ifdef _WIN32
        // SID resolution is introduced by T3.6.
        (void)path;
        (void)hint;
        return std::nullopt;
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

std::shared_ptr<FsBackend> make_local_backend() { return std::make_shared<LocalBackend>(); }

} // namespace dafree
