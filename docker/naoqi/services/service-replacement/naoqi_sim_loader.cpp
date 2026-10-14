// _NaoqiSimLoader: loads naoqi-sim's Python modules from NAOqi's autoload.
//
// The desktop loaders ignore autoload.ini's [python] section, and a Python module cannot load
// itself earlier (sitecustomize runs before the bridge has a broker). This module is an autoload
// entry right after pythonbridge, in the copy where the built-ins we replace are left out: its
// init() loads our Python modules there, synchronously, so they are registered before the next
// entry (our C++ fronts, then every module that calls them) loads. Nothing is exited or restarted.
//
//   NAOQI_SIM_PYTHON_MODULES  our modules, in load order (`from <module> import *` each)
//   NAOQI_SIM_MODULES_DIR     their folder, added to the embedded interpreter's sys.path (2.8's
//                             naoqi-service does not inherit PYTHONPATH)
//
// One source for NAOqi 2.1 and 2.8, compiled in the image build (Dockerfile stage `native`).
// specs/container/service-replacement.md, "Replacing a built-in".
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <sstream>
#include <string>

#include <alcommon/albroker.h>
#include <alcommon/albrokermanager.h>
#include <alcommon/almodule.h>
#include <alcommon/alproxy.h>
#include <boost/shared_ptr.hpp>

// The module entry points' export macro comes from qibuild, not from the SDK's headers.
#ifndef ALCALL
#define ALCALL __attribute__((visibility("default")))
#endif

namespace {
std::string env(const char* name) {
  const char* value = std::getenv(name);
  return value ? value : "";
}
}  // namespace

class NaoqiSimLoader : public AL::ALModule {
 public:
  NaoqiSimLoader(boost::shared_ptr<AL::ALBroker> broker, const std::string& name)
      : AL::ALModule(broker, name) {
    setModuleDescription("naoqi-sim: loads naoqi-sim's Python modules from NAOqi's autoload");
  }

  // Failures are logged, not thrown: the entrypoint checks that every name our modules register
  // answers, and fails the boot otherwise (launchPythonModule does not report an import error).
  void init() {
    const std::string folder = env("NAOQI_SIM_MODULES_DIR");
    try {
      AL::ALProxy bridge(getParentBroker(), "ALPythonBridge");
      if (!folder.empty()) {
        bridge.call<std::string>("eval", "import sys; sys.path.insert(0, '" + folder + "')");
      }
      AL::ALProxy launcher(getParentBroker(), "ALLauncher");
      std::istringstream modules(env("NAOQI_SIM_PYTHON_MODULES"));
      std::string module;
      while (modules >> module) {
        std::fprintf(stderr, "[naoqi_sim_loader] loading %s\n", module.c_str());
        launcher.callVoid("launchPythonModule", module);
      }
    } catch (const std::exception& e) {
      std::fprintf(stderr, "[naoqi_sim_loader] failed: %s\n", e.what());
    }
  }
};

extern "C" {
ALCALL int _createModule(boost::shared_ptr<AL::ALBroker> broker) {
  AL::ALBrokerManager::setInstance(broker->fBrokerManager.lock());
  AL::ALBrokerManager::getInstance()->addBroker(broker);
  AL::ALModule::createModule<NaoqiSimLoader>(broker, "_NaoqiSimLoader");
  return 0;
}
ALCALL int _closeModule() { return 0; }
}
