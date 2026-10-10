"""The NaoSim status service on a running nao-sim stack, on each NAOqi version: how a client
learns the target is nao-sim, its versions and device sources, and the Docker healthcheck."""


def test_the_target_identifies_as_nao_sim(nao):
    naosim = nao.service("NaoSim")
    memory = nao.service("ALMemory")
    built_with = nao.container.image_env()["NAO_SIM_VERSION"]

    assert "NaoSim" in {s["name"] for s in nao.session.services()}
    assert naosim.getVersion() == built_with
    assert naosim.getNaoqiVersion() == nao.version.naoqi_version
    assert memory.getData("NaoSim/Version") == built_with
    assert memory.getData("NaoSim/NaoqiVersion") == nao.version.naoqi_version
    assert (
        memory.getData("NaoSim/Camera/Source") == "render"
    )  # the live tier's render camera
    assert memory.getData("NaoSim/Audio/Source") == "none"
    # Perception runs in the clients: nao-sim publishes no perception source.
    assert "NaoSim/Perception/Source" not in memory.getDataListName()


def test_ready_means_the_replacements_answer(nao):
    assert nao.service("NaoSim").isReady() is True
    assert nao.service("ALMemory").getData("NaoSim/Ready") == 1
    assert nao.version.implementation in nao.service("ALTextToSpeech").whoami()


def test_the_container_turns_healthy(nao):
    assert nao.container.wait_healthy(timeout=30) == "healthy"
