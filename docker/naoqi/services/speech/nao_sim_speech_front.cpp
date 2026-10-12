// ALTextToSpeech's C++ front (specs/services/speech.md, "Architecture: a C++ front over the Python
// core"; specs/container/service-replacement.md, "Task ids, wait and stop(id): a C++ front").
//
// Only a C++ ALModule serves post/pCall, wait(id), stop(id) and isRunning(id) as a NAO's built-in
// does: the Say and Animated Say boxes and ALAnimatedSpeech start, wait for and stop a sentence by
// task id. This front holds no logic. Every method forwards to the Python core, the hidden
// _NaoSimTextToSpeech (docker/services/speech/nao_sim_speech_*); a sentence takes its task id with
// getMethodID(), starts in the core, and is polled until done, its stop passed on when
// isStopRequired(id) turns true.
//
// One source for 2.1 (C++98) and 2.8 (NAOSIM_NAOQI_28): on 2.8 the front also carries the hidden
// _sayWithLocale ALAnimatedSpeech calls and the built-in's hidden signals, fired as member signals
// when the core asks through _fire (never through asObject().post: that crashed naoqi-service).
#include <string>
#include <vector>

#include <alcommon/albroker.h>
#include <alcommon/albrokermanager.h>
#include <alcommon/almodule.h>
#include <alcommon/alproxy.h>
#include <alvalue/alvalue.h>
#include <boost/shared_ptr.hpp>
#include <boost/thread/mutex.hpp>
#include <boost/thread/thread.hpp>
#include "nao_sim_front_core.h"
#ifdef NAOSIM_NAOQI_28
#include <qi/anyobject.hpp>
#include <qi/anyvalue.hpp>
#include <qi/future.hpp>
#include <qi/session.hpp>
#include <qi/signal.hpp>
#endif

#ifndef ALCALL
#define ALCALL __attribute__((visibility("default")))
#endif

namespace {
const char* const kCore = "_NaoSimTextToSpeech";
using nao_sim::Core;
using nao_sim::kPollMs;

}  // namespace

class NaoSimTextToSpeech : public AL::ALModule {
 public:
  NaoSimTextToSpeech(boost::shared_ptr<AL::ALBroker> broker, const std::string& name)
      : AL::ALModule(broker, name), core_(this, kCore) {
    setModuleDescription("nao-sim: ALTextToSpeech, a C++ front over the _NaoSimTextToSpeech core");

    functionName("say", getName(), "Says the text, blocking until it is spoken or stopped");
    addParam("stringToSay", "the text, with NAOqi's tags");
    BIND_METHOD(NaoSimTextToSpeech::say);
    functionName("say", getName(), "Says the text in the given language, for this call only");
    addParam("stringToSay", "the text, with NAOqi's tags");
    addParam("language", "a language name");
    BIND_METHOD(NaoSimTextToSpeech::sayIn);

    functionName("sayToFile", getName(), "Not supported on nao-sim");
    addParam("stringToSay", "the text");
    addParam("fileName", "the file");
    BIND_METHOD(NaoSimTextToSpeech::sayToFile);
    functionName("stopAll", getName(), "Stops all current speech");
    BIND_METHOD(NaoSimTextToSpeech::stopAll);
    functionName("setLanguage", getName(), "Sets the language");
    addParam("language", "a language name");
    BIND_METHOD(NaoSimTextToSpeech::setLanguage);
    functionName("getLanguage", getName(), "Returns the current language");
    BIND_METHOD(NaoSimTextToSpeech::getLanguage);
    functionName("getAvailableLanguages", getName(), "Returns the installed languages");
    BIND_METHOD(NaoSimTextToSpeech::getAvailableLanguages);
    functionName("getSupportedLanguages", getName(), "Returns the supported languages");
    BIND_METHOD(NaoSimTextToSpeech::getSupportedLanguages);
    functionName("resetSpeed", getName(), "Resets the speed");
    BIND_METHOD(NaoSimTextToSpeech::resetSpeed);
    functionName("setParameter", getName(), "Sets a parameter (speed, pitchShift...)");
    addParam("parameter", "its name");
    addParam("value", "its value");
    BIND_METHOD(NaoSimTextToSpeech::setParameter);
    functionName("getParameter", getName(), "Gets a parameter");
    addParam("parameter", "its name");
    BIND_METHOD(NaoSimTextToSpeech::getParameter);
    functionName("setVoice", getName(), "Sets the voice (ignored)");
    addParam("voiceID", "a voice");
    BIND_METHOD(NaoSimTextToSpeech::setVoice);
    functionName("getVoice", getName(), "Returns the voice");
    BIND_METHOD(NaoSimTextToSpeech::getVoice);
    functionName("getAvailableVoices", getName(), "Returns the voices");
    BIND_METHOD(NaoSimTextToSpeech::getAvailableVoices);
    functionName("setVolume", getName(), "Sets the volume");
    addParam("volume", "[0, 1]");
    BIND_METHOD(NaoSimTextToSpeech::setVolume);
    functionName("getVolume", getName(), "Returns the volume");
    BIND_METHOD(NaoSimTextToSpeech::getVolume);
    functionName("locale", getName(), "Returns the locale");
    BIND_METHOD(NaoSimTextToSpeech::locale);
    functionName("loadVoicePreference", getName(), "Loads a voice preference (ignored)");
    addParam("preferenceName", "a preference");
    BIND_METHOD(NaoSimTextToSpeech::loadVoicePreference);
    functionName("setLanguageDefaultVoice", getName(), "Sets a language's default voice (ignored)");
    addParam("language", "a language name");
    addParam("voice", "a voice");
    BIND_METHOD(NaoSimTextToSpeech::setLanguageDefaultVoice);
    functionName("enableNotifications", getName(), "Deprecated no-op");
    BIND_METHOD(NaoSimTextToSpeech::enableNotifications);
    functionName("disableNotifications", getName(), "Deprecated no-op");
    BIND_METHOD(NaoSimTextToSpeech::disableNotifications);
    functionName("whoami", getName(), "Identifies this implementation");
    BIND_METHOD(NaoSimTextToSpeech::whoami);

#ifdef NAOSIM_NAOQI_28
    getBuilder().advertiseSignal("_started", &started_);
    getBuilder().advertiseSignal("synchroTTS", &synchro_);  // declared, never fired, as before
    getBuilder().advertiseSignal("languageTTS", &language_);
    functionName("_sayWithLocale", getName(), "ALAnimatedSpeech's say: text, locale, call uuid");
    addParam("stringToSay", "the text, with NAOqi's tags");
    addParam("locale", "{language, region}");
    addParam("uuid", "the caller's id for this call");
    BIND_METHOD(NaoSimTextToSpeech::_sayWithLocale);
    functionName("_pause", getName(), "Pauses (ignored)");
    BIND_METHOD(NaoSimTextToSpeech::_pause);
    functionName("_resume", getName(), "Resumes (ignored)");
    BIND_METHOD(NaoSimTextToSpeech::_resume);
    functionName("reset", getName(), "Resets (ignored)");
    BIND_METHOD(NaoSimTextToSpeech::reset);
    functionName("_fire", getName(), "Fires a hidden signal for the core: _started or languageTTS");
    addParam("signal", "its name");
    addParam("text", "its argument");
    BIND_METHOD(NaoSimTextToSpeech::_fire);
#endif
  }

  void say(const std::string& text) { speak(text, ""); }
  void sayIn(const std::string& text, const std::string& language) { speak(text, language); }

  void sayToFile(const std::string& text, const std::string& path) {
    core_.callVoid("sayToFile", text, path);
  }
  void stopAll() { core_.callVoid("stopAll"); }
  void setLanguage(const std::string& language) {
    core_.callVoid("setLanguage", language);
  }
  std::string getLanguage() { return core_.call<std::string>("getLanguage"); }
  std::vector<std::string> getAvailableLanguages() {
    return core_.call<std::vector<std::string> >("getAvailableLanguages");
  }
  std::vector<std::string> getSupportedLanguages() {
    return core_.call<std::vector<std::string> >("getSupportedLanguages");
  }
  void resetSpeed() { core_.callVoid("resetSpeed"); }
  void setParameter(const std::string& name, const float& value) {
    core_.callVoid("setParameter", name, value);
  }
  float getParameter(const std::string& name) {
    return core_.call<float>("getParameter", name);
  }
  void setVoice(const std::string& voice) {
    core_.callVoid("setVoice", voice);
  }
  std::string getVoice() { return core_.call<std::string>("getVoice"); }
  std::vector<std::string> getAvailableVoices() {
    return core_.call<std::vector<std::string> >("getAvailableVoices");
  }
  void setVolume(const float& volume) { core_.callVoid("setVolume", volume); }
  float getVolume() { return core_.call<float>("getVolume"); }
  std::string locale() { return core_.call<std::string>("locale"); }
  void loadVoicePreference(const std::string& name) {
    core_.callVoid("loadVoicePreference", name);
  }
  void setLanguageDefaultVoice(const std::string& language, const std::string& voice) {
    core_.callVoid("setLanguageDefaultVoice", language, voice);
  }
  void enableNotifications() { core_.callVoid("enableNotifications"); }
  void disableNotifications() { core_.callVoid("disableNotifications"); }
  std::string whoami() {
    return "nao-sim C++ front over " + core_.call<std::string>("whoami");
  }

#ifdef NAOSIM_NAOQI_28
  // ALAnimatedSpeech 2.8 calls this as a qi call and stops it by cancelling the call's future,
  // never with stop(id) (measured with `qicli trace`): so the call answers with a future whose
  // cancel stops the sentence in the core, completed by a thread that follows the sentence.
  qi::Future<void> _sayWithLocale(const std::string& text, const qi::AnyValue& /*locale*/,
                                  const std::string& /*uuid*/) {
    const int id = core_.call<int>("newId");
    core_.callVoid("start", id, text, std::string());
    Core* core = &core_;
    qi::Promise<void> promise([core, id](qi::Promise<void>&) { core->callVoid("stopCall", id); });
    boost::thread([core, id, promise]() mutable {
      while (!core->call<bool>("waitDone", id, kPollMs)) {
      }
      if (promise.isCancelRequested()) {
        promise.setCanceled();
      } else {
        promise.setValue(0);
      }
    }).detach();
    return promise.future();
  }
  void _pause() { core_.callVoid("pause"); }
  void _resume() { core_.callVoid("resume"); }
  void reset() { core_.callVoid("reset"); }
  void _fire(const std::string& signal, const std::string& text) {
    if (signal == "_started") {
      started_(text);
    } else if (signal == "languageTTS") {
      language_(text);
    }
  }
#endif

 private:
  // A sentence: the task id post/pCall gave this call (a core id when called blocking), started
  // in the core, polled until done; a stop(id) on it is passed on once.
  void speak(const std::string& text, const std::string& language) {
    const int task = getMethodID();
    const bool posted = task >= 0;
    const int id = posted ? task : core_.call<int>("newId");
    core_.callVoid("start", id, text, language);
    bool stopped = false;
    while (!core_.call<bool>("waitDone", id, kPollMs)) {
      if (posted && !stopped && isStopRequired(id)) {
        core_.callVoid("stopCall", id);
        stopped = true;
      }
    }
  }

  Core core_;
#ifdef NAOSIM_NAOQI_28
  qi::Signal<std::string> started_;
  qi::Signal<qi::uint64_t> synchro_;
  qi::Signal<std::string> language_;
#endif
};

extern "C" {
ALCALL int _createModule(boost::shared_ptr<AL::ALBroker> broker) {
  AL::ALBrokerManager::setInstance(broker->fBrokerManager.lock());
  AL::ALBrokerManager::getInstance()->addBroker(broker);
  AL::ALModule::createModule<NaoSimTextToSpeech>(broker, "ALTextToSpeech");
  return 0;
}
ALCALL int _closeModule() { return 0; }
}
