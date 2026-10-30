#include "dafree/model.hpp"

namespace dafree {

// Keep an explicit native instantiation for the small integer model fields.
template class SegVector<std::uint32_t>;

} // namespace dafree
