// Our C++ fronts' way to their Python core (specs/container/service-replacement.md, "Task ids, wait
// and stop(id): a C++ front"): typed calls, through ALProxy on 2.1 and a qi::AnyObject from the
// broker's session on 2.8 (NAOSIM_NAOQI_28), each version's own API. Typed calls are safe because
// each image compiles against its suite's own SDK (specs/container/container.md, "Build files").
#ifndef NAO_SIM_FRONT_CORE_H
#define NAO_SIM_FRONT_CORE_H

#include <string>

#include <alcommon/albroker.h>
#include <alcommon/almodule.h>
#include <alcommon/alproxy.h>
#include <boost/shared_ptr.hpp>
#include <boost/thread/mutex.hpp>
#ifdef NAOSIM_NAOQI_28
#include <qi/anyobject.hpp>
#include <qi/session.hpp>
#endif

namespace nao_sim {

const int kPollMs = 20;  // how long each waitDone may block in a core

class Core {
 public:
  Core(AL::ALModule* module, const char* name) : module_(module), name_(name) {}

#ifdef NAOSIM_NAOQI_28
  template <typename R> R call(const std::string& m) { return object().call<R>(m); }
  template <typename R, typename A> R call(const std::string& m, const A& a) {
    return object().call<R>(m, a);
  }
  template <typename R, typename A, typename B>
  R call(const std::string& m, const A& a, const B& b) {
    return object().call<R>(m, a, b);
  }
  template <typename R, typename A, typename B, typename C>
  R call(const std::string& m, const A& a, const B& b, const C& c) {
    return object().call<R>(m, a, b, c);
  }
  void callVoid(const std::string& m) { object().call<void>(m); }
  template <typename A> void callVoid(const std::string& m, const A& a) {
    object().call<void>(m, a);
  }
  template <typename A, typename B> void callVoid(const std::string& m, const A& a, const B& b) {
    object().call<void>(m, a, b);
  }
  template <typename A, typename B, typename C>
  void callVoid(const std::string& m, const A& a, const B& b, const C& c) {
    object().call<void>(m, a, b, c);
  }
#else
  template <typename R> R call(const std::string& m) { return proxy()->call<R>(m); }
  template <typename R, typename A> R call(const std::string& m, const A& a) {
    return proxy()->call<R>(m, a);
  }
  template <typename R, typename A, typename B>
  R call(const std::string& m, const A& a, const B& b) {
    return proxy()->call<R>(m, a, b);
  }
  template <typename R, typename A, typename B, typename C>
  R call(const std::string& m, const A& a, const B& b, const C& c) {
    return proxy()->call<R>(m, a, b, c);
  }
  void callVoid(const std::string& m) { proxy()->callVoid(m); }
  template <typename A> void callVoid(const std::string& m, const A& a) { proxy()->callVoid(m, a); }
  template <typename A, typename B> void callVoid(const std::string& m, const A& a, const B& b) {
    proxy()->callVoid(m, a, b);
  }
  template <typename A, typename B, typename C>
  void callVoid(const std::string& m, const A& a, const B& b, const C& c) {
    proxy()->callVoid(m, a, b, c);
  }
#endif

 private:
#ifdef NAOSIM_NAOQI_28
  qi::AnyObject object() {
    boost::mutex::scoped_lock lock(mutex_);
    if (!object_) object_ = module_->getParentBroker()->session()->service(name_).value();
    return object_;
  }
  qi::AnyObject object_;
#else
  boost::shared_ptr<AL::ALProxy> proxy() {
    boost::mutex::scoped_lock lock(mutex_);
    if (!proxy_) proxy_.reset(new AL::ALProxy(module_->getParentBroker(), name_));
    return proxy_;
  }
  boost::shared_ptr<AL::ALProxy> proxy_;
#endif
  AL::ALModule* module_;
  std::string name_;
  boost::mutex mutex_;
};
}  // namespace nao_sim

#endif  // NAO_SIM_FRONT_CORE_H
