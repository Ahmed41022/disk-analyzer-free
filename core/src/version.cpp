namespace dafree {

/// Return the version injected from the Python package metadata at configure time.
const char *version() noexcept { return DAFREE_VERSION; }

} // namespace dafree
