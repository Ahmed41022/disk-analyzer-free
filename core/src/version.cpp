namespace dafree {

/// Return the version injected from the Python package metadata at configure time.
auto version() noexcept -> const char * { return DAFREE_VERSION; }

} // namespace dafree
