// ALAudioPlayer's C++ front (specs/services/audio-player.md, "Architecture: a C++ front and a
// Python core"; specs/container/service-replacement.md, "Task ids, wait and stop(id): a C++ front").
//
// Only a C++ ALModule serves post/pCall, wait(id), stop(id) and isRunning(id) as a NAO's built-in
// does: the Play Sound box starts a sound with post (2.1) or pCall (2.8), waits with wait(id) and
// stops it with stop(id) from a second proxy. This front holds no logic: every method forwards to
// the Python core, the hidden _NaoqiSimAudioPlayer (naoqi_sim_audio_player_core.py). A play method
// takes its task id with getMethodID(), starts the sound in the core (a kind and its parameters
// as JSON), and is polled until done, its stop passed on when isStopRequired(id) turns true.
// One source for 2.1 (C++98) and 2.8 (NAOQISIM_NAOQI_28).
#include <sstream>
#include <string>
#include <vector>

#include <alcommon/albroker.h>
#include <alcommon/albrokermanager.h>
#include <alcommon/almodule.h>
#include <alerror/alerror.h>
#include <boost/shared_ptr.hpp>

#include "naoqi_sim_front_core.h"

#ifndef ALCALL
#define ALCALL __attribute__((visibility("default")))
#endif

namespace {
const char* const kCore = "_NaoqiSimAudioPlayer";
using naoqi_sim::Core;
using naoqi_sim::kPollMs;

// A call's parameters for the core, as a JSON object.
class Params {
 public:
  Params& add(const std::string& key, const std::string& value) {
    std::string escaped;
    for (std::string::size_type i = 0; i < value.size(); ++i) {
      const char c = value[i];
      if (c == '"' || c == '\\') escaped += '\\';
      escaped += c;
    }
    return raw(key, "\"" + escaped + "\"");
  }
  Params& add(const std::string& key, double value) {
    std::ostringstream s;
    s.precision(17);
    s << value;
    return raw(key, s.str());
  }
  Params& flag(const std::string& key, bool value) { return raw(key, value ? "true" : "false"); }
  std::string str() const { return "{" + body_ + "}"; }

 private:
  Params& raw(const std::string& key, const std::string& value) {
    if (!body_.empty()) body_ += ", ";
    body_ += "\"" + key + "\": " + value;
    return *this;
  }
  std::string body_;
};
}  // namespace

class NaoqiSimAudioPlayer : public AL::ALModule {
 public:
  NaoqiSimAudioPlayer(boost::shared_ptr<AL::ALBroker> broker, const std::string& name)
      : AL::ALModule(broker, name), core_(this, kCore) {
    setModuleDescription("naoqi-sim: ALAudioPlayer, a C++ front over the _NaoqiSimAudioPlayer core");

    functionName("playFile", getName(), "Plays a file, blocking until it ends or is stopped");
    addParam("fileName", "an absolute path");
    BIND_METHOD(NaoqiSimAudioPlayer::playFile);
    functionName("playFile", getName(), "Plays a file at a volume and pan");
    addParam("fileName", "an absolute path");
    addParam("volume", "[0, 1]");
    addParam("pan", "[-1 left, 1 right]");
    BIND_METHOD(NaoqiSimAudioPlayer::playFileAt);
    functionName("playFileFromPosition", getName(), "Plays a file from a position (seconds)");
    addParam("fileName", "an absolute path");
    addParam("position", "seconds");
    BIND_METHOD(NaoqiSimAudioPlayer::playFileFromPosition);
    functionName("playFileFromPosition", getName(), "Plays a file from a position, volume, pan");
    addParam("fileName", "an absolute path");
    addParam("position", "seconds");
    addParam("volume", "[0, 1]");
    addParam("pan", "[-1 left, 1 right]");
    BIND_METHOD(NaoqiSimAudioPlayer::playFileFromPositionAt);
    functionName("playFileInLoop", getName(), "Plays a file in a loop until stopped");
    addParam("fileName", "an absolute path");
    BIND_METHOD(NaoqiSimAudioPlayer::playFileInLoop);
    functionName("playFileInLoop", getName(), "Plays a file in a loop at a volume and pan");
    addParam("fileName", "an absolute path");
    addParam("volume", "[0, 1]");
    addParam("pan", "[-1 left, 1 right]");
    BIND_METHOD(NaoqiSimAudioPlayer::playFileInLoopAt);
    functionName("play", getName(), "Plays a loaded file (or goes on with a paused one)");
    addParam("id", "the id loadFile returned");
    BIND_METHOD(NaoqiSimAudioPlayer::play);
    functionName("play", getName(), "Plays a loaded file at a volume and pan");
    addParam("id", "the id loadFile returned");
    addParam("volume", "[0, 1]");
    addParam("pan", "[-1 left, 1 right]");
    BIND_METHOD(NaoqiSimAudioPlayer::playAt);
    functionName("playInLoop", getName(), "Plays a loaded file in a loop until stopped");
    addParam("id", "the id loadFile returned");
    BIND_METHOD(NaoqiSimAudioPlayer::playInLoop);
    functionName("playInLoop", getName(), "Plays a loaded file in a loop at a volume and pan");
    addParam("id", "the id loadFile returned");
    addParam("volume", "[0, 1]");
    addParam("pan", "[-1 left, 1 right]");
    BIND_METHOD(NaoqiSimAudioPlayer::playInLoopAt);
    functionName("playSine", getName(), "Plays a sine");
    addParam("frequence", "Hz");
    addParam("gain", "percent");
    addParam("pan", "-1 left, 0 center, 1 right");
    addParam("duration", "seconds");
    BIND_METHOD(NaoqiSimAudioPlayer::playSine);
    functionName("playSoundSetFile", getName(), "Plays a sound of the loaded sound sets");
    addParam("fileName", "the sound's name");
    BIND_METHOD(NaoqiSimAudioPlayer::playSoundSetFile);
    functionName("playSoundSetFile", getName(), "Plays a sound of a sound set");
    addParam("soundSetName", "the set");
    addParam("fileName", "the sound's name");
    BIND_METHOD(NaoqiSimAudioPlayer::playSoundSetFileOf);
    functionName("playSoundSetFile", getName(), "Plays a sound of a set: position, volume, pan, loop");
    addParam("soundSetName", "the set");
    addParam("fileName", "the sound's name");
    addParam("position", "seconds");
    addParam("volume", "[0, 1]");
    addParam("pan", "[-1 left, 1 right]");
    addParam("loop", "whether it loops");
    BIND_METHOD(NaoqiSimAudioPlayer::playSoundSetFileWith);
    functionName("playWebStream", getName(), "Not supported on naoqi-sim");
    addParam("streamName", "a URL");
    addParam("volume", "[0, 1]");
    addParam("pan", "[-1 left, 1 right]");
    BIND_METHOD(NaoqiSimAudioPlayer::playWebStream);

    functionName("stopAll", getName(), "Stops every sound");
    BIND_METHOD(NaoqiSimAudioPlayer::stopAll);
    functionName("pause", getName(), "Pauses a sound");
    addParam("id", "a task id or a loaded file's id");
    BIND_METHOD(NaoqiSimAudioPlayer::pause);
    functionName("goTo", getName(), "Jumps to a position (seconds)");
    addParam("id", "a task id or a loaded file's id");
    addParam("position", "seconds");
    BIND_METHOD(NaoqiSimAudioPlayer::goTo);
    functionName("getCurrentPosition", getName(), "The position, in seconds");
    addParam("id", "a task id or a loaded file's id");
    BIND_METHOD(NaoqiSimAudioPlayer::getCurrentPosition);
    functionName("getFileLength", getName(), "The length, in seconds");
    addParam("id", "a task id or a loaded file's id");
    BIND_METHOD(NaoqiSimAudioPlayer::getFileLength);
    functionName("setVolume", getName(), "A sound's own volume");
    addParam("id", "a task id or a loaded file's id");
    addParam("volume", "[0, 1]");
    BIND_METHOD(NaoqiSimAudioPlayer::setVolume);
    functionName("getVolume", getName(), "A sound's own volume");
    addParam("id", "a task id or a loaded file's id");
    BIND_METHOD(NaoqiSimAudioPlayer::getVolume);
    functionName("setMasterVolume", getName(), "The player's volume");
    addParam("volume", "[0, 1]");
    BIND_METHOD(NaoqiSimAudioPlayer::setMasterVolume);
    functionName("getMasterVolume", getName(), "The player's volume");
    BIND_METHOD(NaoqiSimAudioPlayer::getMasterVolume);
    functionName("setPanorama", getName(), "The pan of every sound");
    addParam("pan", "[-1 left, 1 right]");
    BIND_METHOD(NaoqiSimAudioPlayer::setPanorama);
    functionName("loadFile", getName(), "Loads a file; returns its id");
    addParam("fileName", "an absolute path");
    BIND_METHOD(NaoqiSimAudioPlayer::loadFile);
    functionName("unloadFile", getName(), "Unloads a file");
    addParam("id", "the id loadFile returned");
    BIND_METHOD(NaoqiSimAudioPlayer::unloadFile);
    functionName("unloadAllFiles", getName(), "Unloads every file");
    BIND_METHOD(NaoqiSimAudioPlayer::unloadAllFiles);
    functionName("getLoadedFilesIds", getName(), "The loaded files' ids");
    BIND_METHOD(NaoqiSimAudioPlayer::getLoadedFilesIds);
    functionName("getLoadedFilesNames", getName(), "The loaded files' paths");
    BIND_METHOD(NaoqiSimAudioPlayer::getLoadedFilesNames);
    functionName("getInstalledSoundSetsList", getName(), "The installed sound sets");
    BIND_METHOD(NaoqiSimAudioPlayer::getInstalledSoundSetsList);
    functionName("getLoadedSoundSetsList", getName(), "The loaded sound sets");
    BIND_METHOD(NaoqiSimAudioPlayer::getLoadedSoundSetsList);
    functionName("getSoundSetFileNames", getName(), "The sounds of a set");
    addParam("setName", "the set");
    BIND_METHOD(NaoqiSimAudioPlayer::getSoundSetFileNames);
    functionName("isSoundSetInstalled", getName(), "Whether a set is installed");
    addParam("soundSet", "the set");
    BIND_METHOD(NaoqiSimAudioPlayer::isSoundSetInstalled);
    functionName("isSoundSetLoaded", getName(), "Whether a set is loaded");
    addParam("soundSet", "the set");
    BIND_METHOD(NaoqiSimAudioPlayer::isSoundSetLoaded);
    functionName("isSoundSetFileInstalled", getName(), "Whether a set has a sound");
    addParam("soundSet", "the set");
    addParam("soundSetFile", "the sound's name");
    BIND_METHOD(NaoqiSimAudioPlayer::isSoundSetFileInstalled);
    functionName("loadSoundSet", getName(), "Loads a sound set");
    addParam("setName", "the set");
    BIND_METHOD(NaoqiSimAudioPlayer::loadSoundSet);
    functionName("unloadSoundSet", getName(), "Unloads a sound set");
    addParam("setName", "the set");
    BIND_METHOD(NaoqiSimAudioPlayer::unloadSoundSet);
    functionName("whoami", getName(), "Identifies this implementation");
    BIND_METHOD(NaoqiSimAudioPlayer::whoami);
  }

  // -- long calls --------------------------------------------------------------------------
  void playFile(const std::string& path) { playFileAt(path, 1.0f, 0.0f); }
  void playFileAt(const std::string& path, const float& volume, const float& pan) {
    run("file", Params().add("path", path).add("volume", volume).add("pan", pan));
  }
  void playFileFromPosition(const std::string& path, const float& position) {
    playFileFromPositionAt(path, position, 1.0f, 0.0f);
  }
  void playFileFromPositionAt(const std::string& path, const float& position,
                              const float& volume, const float& pan) {
    run("file", Params().add("path", path).add("position", position).add("volume", volume)
                    .add("pan", pan));
  }
  void playFileInLoop(const std::string& path) { playFileInLoopAt(path, 1.0f, 0.0f); }
  void playFileInLoopAt(const std::string& path, const float& volume, const float& pan) {
    run("file",
        Params().add("path", path).add("volume", volume).add("pan", pan).flag("loop", true));
  }
  void play(const int& id) { playAt(id, 1.0f, 0.0f); }
  void playAt(const int& id, const float& volume, const float& pan) {
    run("loaded", Params().add("id", id).add("volume", volume).add("pan", pan));
  }
  void playInLoop(const int& id) { playInLoopAt(id, 1.0f, 0.0f); }
  void playInLoopAt(const int& id, const float& volume, const float& pan) {
    run("loaded", Params().add("id", id).add("volume", volume).add("pan", pan).flag("loop", true));
  }
  void playSine(const int& frequency, const int& gain, const int& pan, const float& duration) {
    run("sine", Params().add("frequency", frequency).add("gain", gain).add("pan", pan)
                    .add("duration", duration));
  }
  void playSoundSetFile(const std::string& file) { run("soundset", Params().add("file", file)); }
  void playSoundSetFileOf(const std::string& set, const std::string& file) {
    run("soundset", Params().add("set", set).add("file", file));
  }
  void playSoundSetFileWith(const std::string& set, const std::string& file,
                            const float& position, const float& volume, const float& pan,
                            const bool& loop) {
    run("soundset", Params().add("set", set).add("file", file).add("position", position)
                        .add("volume", volume).add("pan", pan).flag("loop", loop));
  }
  void playWebStream(const std::string& /*stream*/, const float& /*volume*/,
                     const float& /*pan*/) {
    throw AL::ALError(getName(), "playWebStream", "web streams are not supported on naoqi-sim");
  }

  // -- forwarded --------------------------------------------------------------------------------
  void stopAll() { core_.callVoid("stopAll"); }
  void pause(const int& id) { core_.callVoid("pause", id); }
  void goTo(const int& id, const float& position) { core_.callVoid("goTo", id, position); }
  float getCurrentPosition(const int& id) { return core_.call<float>("getCurrentPosition", id); }
  float getFileLength(const int& id) { return core_.call<float>("getFileLength", id); }
  void setVolume(const int& id, const float& volume) { core_.callVoid("setVolume", id, volume); }
  float getVolume(const int& id) { return core_.call<float>("getVolume", id); }
  void setMasterVolume(const float& volume) { core_.callVoid("setMasterVolume", volume); }
  float getMasterVolume() { return core_.call<float>("getMasterVolume"); }
  void setPanorama(const float& pan) { core_.callVoid("setPanorama", pan); }
  int loadFile(const std::string& path) { return core_.call<int>("loadFile", path); }
  void unloadFile(const int& id) { core_.callVoid("unloadFile", id); }
  void unloadAllFiles() { core_.callVoid("unloadAllFiles"); }
  std::vector<std::string> getLoadedFilesIds() {
    return core_.call<std::vector<std::string> >("getLoadedFilesIds");
  }
  std::vector<std::string> getLoadedFilesNames() {
    return core_.call<std::vector<std::string> >("getLoadedFilesNames");
  }
  std::vector<std::string> getInstalledSoundSetsList() {
    return core_.call<std::vector<std::string> >("getInstalledSoundSetsList");
  }
  std::vector<std::string> getLoadedSoundSetsList() {
    return core_.call<std::vector<std::string> >("getLoadedSoundSetsList");
  }
  std::vector<std::string> getSoundSetFileNames(const std::string& set) {
    return core_.call<std::vector<std::string> >("getSoundSetFileNames", set);
  }
  bool isSoundSetInstalled(const std::string& set) {
    return core_.call<bool>("isSoundSetInstalled", set);
  }
  bool isSoundSetLoaded(const std::string& set) { return core_.call<bool>("isSoundSetLoaded", set); }
  bool isSoundSetFileInstalled(const std::string& set, const std::string& file) {
    return core_.call<bool>("isSoundSetFileInstalled", set, file);
  }
  void loadSoundSet(const std::string& set) { core_.callVoid("loadSoundSet", set); }
  void unloadSoundSet(const std::string& set) { core_.callVoid("unloadSoundSet", set); }
  std::string whoami() { return "naoqi-sim C++ front over " + core_.call<std::string>("whoami"); }

 private:
  // A play: the task id post/pCall gave this call (a core id when called blocking), started in
  // the core, polled until done; a stop(id) on it is passed on once.
  void run(const std::string& kind, const Params& params) {
    const int task = getMethodID();
    const bool posted = task >= 0;
    const int id = posted ? task : core_.call<int>("newId");
    core_.callVoid("start", id, kind, params.str());
    bool stopped = false;
    while (!core_.call<bool>("waitDone", id, kPollMs)) {
      if (posted && !stopped && isStopRequired(id)) {
        core_.callVoid("stopCall", id);
        stopped = true;
      }
    }
  }

  Core core_;
};

extern "C" {
ALCALL int _createModule(boost::shared_ptr<AL::ALBroker> broker) {
  AL::ALBrokerManager::setInstance(broker->fBrokerManager.lock());
  AL::ALBrokerManager::getInstance()->addBroker(broker);
  AL::ALModule::createModule<NaoqiSimAudioPlayer>(broker, "ALAudioPlayer");
  return 0;
}
ALCALL int _closeModule() { return 0; }
}
