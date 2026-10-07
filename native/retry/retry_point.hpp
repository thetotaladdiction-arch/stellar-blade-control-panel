#pragma once

namespace sbretrypoint
{
    bool install();
    void on_update();
    void shutdown();
}

#if defined(SBRETRYPOINT_TESTING)
// Offline harness entry points (tests/). Never compiled into the staged DLL.
#include "sbcore/gate.hpp"
#include "sbcore/paths.hpp"

namespace sbretrypoint::testing
{
    // install() with the given module paths and gate result in place of the
    // running module's location and the running process's gate. A passed
    // gate's image must be a (fake) image with the TaskGraph at the certified
    // RVAs: the production sbcore::dispatch::bind() is used unchanged.
    bool install_with(const sbcore::paths::ModulePaths& paths, sbcore::paths::Error path_error,
                      const sbcore::gate::Result& gate);
}
#endif
