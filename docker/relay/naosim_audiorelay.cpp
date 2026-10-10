// _NaoSimAudioRelay: hands a PCM buffer to an ALAudioDevice subscriber as a binary.
//
// NAOqi's Python 2.7 cannot send a binary value: py2 qi sends str and bytearray as a qi string,
// ALProxy turns a bytearray into None. A NAO's C++ ALAudioDevice calls processRemote with an
// ALValue binary, which a libqi 3 client receives as a bytearray. This module takes the PCM as a
// string from the Python ALAudioDevice replacement and makes that call as the C++ module does.
// It holds no logic: what is sent, to whom and when is the Python module's.
//
// One source for NAOqi 2.1 and 2.8, compiled in the image build (Dockerfile stage `relay`) against
// the version's C++ SDK headers and linked against the suite's libraries.
// specs/container/service-replacement.md, "Binary arguments: the native relay".
#include <map>
#include <string>

#include <alcommon/albroker.h>
#include <alcommon/albrokermanager.h>
#include <alcommon/almodule.h>
#include <alcommon/alproxy.h>
#include <alvalue/alvalue.h>
#include <boost/shared_ptr.hpp>
#include <boost/thread/mutex.hpp>

// The module entry points' export macro comes from qibuild, not from the SDK's headers.
#ifndef ALCALL
#define ALCALL __attribute__((visibility("default")))
#endif

class NaoSimAudioRelay : public AL::ALModule {
 public:
  NaoSimAudioRelay(boost::shared_ptr<AL::ALBroker> broker, const std::string& name)
      : AL::ALModule(broker, name) {
    setModuleDescription("nao-sim: delivers PCM to an ALAudioDevice subscriber as a binary");

    functionName("deliver", getName(), "Calls subscriber.processRemote with the PCM as a binary");
    addParam("subscriber", "the subscriber's module or service name");
    addParam("nbOfChannels", "channels in the buffer");
    addParam("nbOfSamplesByChannel", "samples per channel");
    addParam("timeStamp", "[seconds, microseconds]");
    addParam("buffer", "s16le PCM, as a string");
    BIND_METHOD(NaoSimAudioRelay::deliver);

    functionName("forget", getName(), "Drops the cached proxy to a subscriber");
    addParam("subscriber", "the subscriber's module or service name");
    BIND_METHOD(NaoSimAudioRelay::forget);
  }

  void deliver(const std::string& subscriber, const int& nbOfChannels,
               const int& nbOfSamplesByChannel, const AL::ALValue& timeStamp,
               const std::string& buffer) {
    AL::ALValue binary;
    binary.SetBinary(buffer.data(), buffer.size());
    proxy(subscriber)->callVoid("processRemote", nbOfChannels, nbOfSamplesByChannel, timeStamp,
                                binary);
  }

  void forget(const std::string& subscriber) {
    boost::mutex::scoped_lock lock(mutex_);
    proxies_.erase(subscriber);
  }

 private:
  typedef std::map<std::string, boost::shared_ptr<AL::ALProxy> > Proxies;

  boost::shared_ptr<AL::ALProxy> proxy(const std::string& subscriber) {
    boost::mutex::scoped_lock lock(mutex_);
    Proxies::iterator it = proxies_.find(subscriber);
    if (it != proxies_.end()) return it->second;
    boost::shared_ptr<AL::ALProxy> p(new AL::ALProxy(getParentBroker(), subscriber));
    proxies_[subscriber] = p;
    return p;
  }

  boost::mutex mutex_;
  Proxies proxies_;
};

extern "C" {
ALCALL int _createModule(boost::shared_ptr<AL::ALBroker> broker) {
  AL::ALBrokerManager::setInstance(broker->fBrokerManager.lock());
  AL::ALBrokerManager::getInstance()->addBroker(broker);
  AL::ALModule::createModule<NaoSimAudioRelay>(broker, "_NaoSimAudioRelay");
  return 0;
}
ALCALL int _closeModule() { return 0; }
}
